from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import monotonic
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from devpilot.domain import ArtifactKind, EventKind, RunStep, TaskStatus
from devpilot.errors import (
    BudgetExceededError,
    InvalidTaskStateError,
    RetryableStepError,
    RuntimeErrorBase,
)
from devpilot.executions import StepExecutions
from devpilot.indexing import RepositoryIndexer
from devpilot.providers import AgentContext, ModelProvider
from devpilot.repository import TaskRepository
from devpilot.retrieval import HybridCodeRetriever
from devpilot.tools import LocalTestRunner, RepositoryInspector


@dataclass
class RunState:
    task_id: UUID
    requirement: str
    repository_path: str
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    repository: dict[str, Any] | None = None
    code_context: dict[str, Any] | None = None
    plan: dict[str, Any] | None = None
    proposal: dict[str, Any] | None = None
    test_report: dict[str, Any] | None = None
    review: dict[str, Any] | None = None

    def checkpoint(self) -> dict[str, Any]:
        return {
            "task_id": str(self.task_id),
            "requirement": self.requirement,
            "repository_path": self.repository_path,
            "started_at": self.started_at.isoformat(),
            "repository": self.repository,
            "code_context": self.code_context,
            "plan": self.plan,
            "proposal": self.proposal,
            "test_report": self.test_report,
            "review": self.review,
        }

    @classmethod
    def restore(cls, payload: dict[str, Any]) -> RunState:
        return cls(
            task_id=UUID(str(payload["task_id"])),
            requirement=str(payload["requirement"]),
            repository_path=str(payload["repository_path"]),
            started_at=datetime.fromisoformat(str(payload["started_at"])),
            repository=payload.get("repository"),
            code_context=payload.get("code_context"),
            plan=payload.get("plan"),
            proposal=payload.get("proposal"),
            test_report=payload.get("test_report"),
            review=payload.get("review"),
        )


class AgentRuntime:
    STEPS = list(RunStep)

    def __init__(
        self,
        session: Session,
        provider: ModelProvider,
        inspector: RepositoryInspector,
        test_runner: LocalTestRunner,
        indexer: RepositoryIndexer,
        context_token_budget: int,
        heartbeat: Callable[[], None] | None = None,
    ) -> None:
        self.tasks = TaskRepository(session)
        self.executions = StepExecutions(session)
        self.session = session
        self.provider = provider
        self.inspector = inspector
        self.test_runner = test_runner
        self.indexer = indexer
        self.context_token_budget = context_token_budget
        self.heartbeat = heartbeat
        self.handlers: dict[RunStep, Callable[[RunState], str]] = {
            RunStep.VALIDATE: self._validate,
            RunStep.INSPECT_REPOSITORY: self._inspect_repository,
            RunStep.RETRIEVE_CONTEXT: self._retrieve_context,
            RunStep.BUILD_PLAN: self._build_plan,
            RunStep.PROPOSE_CHANGE: self._propose_change,
            RunStep.RUN_TESTS: self._run_tests,
            RunStep.REVIEW: self._review,
            RunStep.FINALIZE: self._finalize,
        }

    def run(self, task_id: UUID) -> None:
        task = self.tasks.get(task_id)
        if task.status in {TaskStatus.RUNNING, TaskStatus.COMPLETED, TaskStatus.CANCELLED}:
            raise InvalidTaskStateError(f"Task cannot run from state {task.status.value}")

        checkpoint = self.tasks.latest_checkpoint(task_id)
        if checkpoint:
            state = RunState.restore(checkpoint.state)
            start_index = checkpoint.step_index + 1
        else:
            state = RunState(
                task_id=task_id,
                requirement=task.requirement,
                repository_path=task.repository_path,
            )
            start_index = 0

        if len(self.STEPS) > task.budget.max_steps:
            raise BudgetExceededError("Task step budget is smaller than the workflow")

        started = monotonic()
        self.tasks.set_status(task_id, TaskStatus.RUNNING)
        self.tasks.append_event(
            task_id,
            EventKind.TASK_STARTED,
            "Runtime started the task.",
            payload={"resume_from": start_index, "provider": self.provider.name},
        )
        self.tasks.commit()

        try:
            for index in range(start_index, len(self.STEPS)):
                step = self.STEPS[index]
                self.session.expire_all()
                current = self.tasks.get(task_id)
                if current.status == TaskStatus.CANCELLED:
                    return
                if monotonic() - started > task.budget.max_wall_seconds:
                    raise BudgetExceededError("Task wall-clock budget exceeded")
                self._run_step(index, step, state, task.budget.max_retries_per_step)
        except Exception as exc:
            self.session.expire_all()
            if self.tasks.get(task_id).status == TaskStatus.CANCELLED:
                return
            self.tasks.set_status(
                task_id,
                TaskStatus.FAILED,
                error_message=f"{type(exc).__name__}: {exc}",
            )
            self.tasks.append_event(
                task_id,
                EventKind.TASK_FAILED,
                "Runtime stopped after a failed step.",
                payload={"error_type": type(exc).__name__, "error": str(exc)},
            )
            self.tasks.commit()
            raise

    def _run_step(
        self,
        index: int,
        step: RunStep,
        state: RunState,
        max_retries: int,
    ) -> None:
        existing = self.executions.get(state.task_id, step)
        if existing is not None and existing.status == "completed" and existing.result:
            saved_state = existing.result.get("state")
            if isinstance(saved_state, dict):
                self._restore_into(state, saved_state)
            return

        self.tasks.set_status(state.task_id, TaskStatus.RUNNING, current_step=step)
        for retry_index in range(max_retries + 1):
            execution = self.executions.begin(state.task_id, step)
            event_kind = EventKind.STEP_STARTED if retry_index == 0 else EventKind.STEP_RETRYING
            self.tasks.append_event(
                state.task_id,
                event_kind,
                (
                    f"Started {step.value}."
                    if retry_index == 0
                    else f"Retrying {step.value} after a transient failure."
                ),
                step=step,
                payload={"attempt": execution.attempt},
            )
            self.tasks.commit()
            try:
                summary = self.handlers[step](state)
            except Exception as exc:
                self.session.rollback()
                failed_execution = self.executions.get(state.task_id, step)
                if failed_execution is None:
                    raise RuntimeErrorBase("Step execution record disappeared") from exc
                self.executions.fail(failed_execution, f"{type(exc).__name__}: {exc}")
                self.tasks.append_event(
                    state.task_id,
                    EventKind.STEP_FAILED,
                    f"{step.value} failed.",
                    step=step,
                    payload={
                        "attempt": failed_execution.attempt,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "retryable": isinstance(exc, RetryableStepError),
                    },
                )
                self.tasks.commit()
                if isinstance(exc, RetryableStepError) and retry_index < max_retries:
                    continue
                raise
            checkpoint_state = state.checkpoint()
            self.tasks.save_checkpoint(state.task_id, index, step, checkpoint_state)
            self.executions.complete(
                execution,
                {"summary": summary, "state": checkpoint_state},
            )
            self.tasks.append_event(
                state.task_id,
                EventKind.STEP_COMPLETED,
                summary,
                step=step,
                payload={"attempt": execution.attempt},
            )
            self.tasks.commit()
            if self.heartbeat is not None:
                self.heartbeat()
            return

    def _validate(self, state: RunState) -> str:
        if len(state.requirement.strip()) < 10:
            raise ValueError("Requirement is too short to produce an auditable plan")
        return "Requirement passed structural validation."

    def _inspect_repository(self, state: RunState) -> str:
        state.repository = self.inspector.inspect(state.repository_path)
        self.tasks.add_artifact(
            state.task_id,
            ArtifactKind.REPOSITORY_SNAPSHOT,
            "Repository snapshot",
            state.repository,
        )
        return f"Indexed repository metadata for {state.repository['file_count']} files."

    def _build_plan(self, state: RunState) -> str:
        state.plan = self.provider.build_plan(self._context(state))
        self.tasks.add_artifact(
            state.task_id,
            ArtifactKind.IMPLEMENTATION_PLAN,
            "Implementation plan",
            state.plan,
        )
        return f"Built a plan with {len(state.plan.get('steps', []))} steps."

    def _retrieve_context(self, state: RunState) -> str:
        if state.repository is None:
            raise RuntimeErrorBase("Repository evidence is missing")
        chunks = self.indexer.index(state.repository)
        retriever = HybridCodeRetriever(chunks)
        state.code_context = retriever.build_context(
            state.requirement,
            token_budget=self.context_token_budget,
        )
        self.tasks.add_artifact(
            state.task_id,
            ArtifactKind.CODE_CONTEXT,
            "Repository-aware code context",
            state.code_context,
        )
        return (
            f"Selected {state.code_context['selected_count']} code chunks "
            f"from {state.code_context['candidate_count']} candidates."
        )

    def _propose_change(self, state: RunState) -> str:
        state.proposal = self.provider.propose_change(self._context(state))
        self.tasks.add_artifact(
            state.task_id,
            ArtifactKind.CHANGE_PROPOSAL,
            "Change proposal",
            state.proposal,
        )
        return "Recorded a dry-run change proposal."

    def _run_tests(self, state: RunState) -> str:
        if state.repository is None:
            raise RuntimeErrorBase("Repository evidence is missing")
        state.test_report = self.test_runner.run(str(state.repository["root"]))
        self.tasks.add_artifact(
            state.task_id,
            ArtifactKind.TEST_REPORT,
            "Test report",
            state.test_report,
        )
        return f"Test stage finished with status {state.test_report['status']}."

    def _review(self, state: RunState) -> str:
        state.review = self.provider.review(self._context(state))
        self.tasks.add_artifact(
            state.task_id,
            ArtifactKind.REVIEW_REPORT,
            "Independent review",
            state.review,
        )
        return f"Review decision: {state.review['decision']}."

    def _finalize(self, state: RunState) -> str:
        result = {
            "outcome": "dry_run_completed",
            "provider": self.provider.name,
            "repository_digest": (state.repository or {}).get("tree_digest"),
            "test_status": (state.test_report or {}).get("status"),
            "review_decision": (state.review or {}).get("decision"),
        }
        self.tasks.add_artifact(
            state.task_id,
            ArtifactKind.FINAL_REPORT,
            "Final report",
            result,
        )
        self.tasks.set_status(
            state.task_id,
            TaskStatus.COMPLETED,
            result_summary=(
                "Dry run completed with a traceable plan, proposal, test stage, and review."
            ),
        )
        self.tasks.append_event(
            state.task_id,
            EventKind.TASK_COMPLETED,
            "Task completed successfully.",
            payload=result,
        )
        return "Final report persisted."

    @staticmethod
    def _context(state: RunState) -> AgentContext:
        return AgentContext(
            requirement=state.requirement,
            repository=state.repository or {},
            code_context=state.code_context,
            plan=state.plan,
            proposal=state.proposal,
            test_report=state.test_report,
        )

    @staticmethod
    def _restore_into(state: RunState, payload: dict[str, Any]) -> None:
        restored = RunState.restore(payload)
        state.started_at = restored.started_at
        state.repository = restored.repository
        state.code_context = restored.code_context
        state.plan = restored.plan
        state.proposal = restored.proposal
        state.test_report = restored.test_report
        state.review = restored.review
