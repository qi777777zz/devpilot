from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import monotonic
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from devpilot.domain import ArtifactKind, EventKind, RunStep, TaskStatus
from devpilot.providers import AgentContext, ModelProvider
from devpilot.repository import TaskRepository
from devpilot.tools import LocalTestRunner, RepositoryInspector


class RuntimeErrorBase(RuntimeError):
    pass


class InvalidTaskStateError(RuntimeErrorBase):
    pass


class BudgetExceededError(RuntimeErrorBase):
    pass


@dataclass
class RunState:
    task_id: UUID
    requirement: str
    repository_path: str
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    repository: dict[str, Any] | None = None
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
    ) -> None:
        self.tasks = TaskRepository(session)
        self.provider = provider
        self.inspector = inspector
        self.test_runner = test_runner
        self.handlers: dict[RunStep, Callable[[RunState], str]] = {
            RunStep.VALIDATE: self._validate,
            RunStep.INSPECT_REPOSITORY: self._inspect_repository,
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
                current = self.tasks.get(task_id)
                if current.status == TaskStatus.CANCELLED:
                    return
                if monotonic() - started > task.budget.max_wall_seconds:
                    raise BudgetExceededError("Task wall-clock budget exceeded")
                self._run_step(index, step, state)
        except Exception as exc:
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

    def _run_step(self, index: int, step: RunStep, state: RunState) -> None:
        self.tasks.set_status(state.task_id, TaskStatus.RUNNING, current_step=step)
        self.tasks.append_event(
            state.task_id,
            EventKind.STEP_STARTED,
            f"Started {step.value}.",
            step=step,
        )
        self.tasks.commit()
        try:
            summary = self.handlers[step](state)
        except Exception as exc:
            self.tasks.append_event(
                state.task_id,
                EventKind.STEP_FAILED,
                f"{step.value} failed.",
                step=step,
                payload={"error_type": type(exc).__name__, "error": str(exc)},
            )
            self.tasks.commit()
            raise
        self.tasks.save_checkpoint(state.task_id, index, step, state.checkpoint())
        self.tasks.append_event(
            state.task_id,
            EventKind.STEP_COMPLETED,
            summary,
            step=step,
        )
        self.tasks.commit()

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
            plan=state.plan,
            proposal=state.proposal,
            test_report=state.test_report,
        )
