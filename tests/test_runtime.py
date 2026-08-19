from __future__ import annotations

from pathlib import Path

import pytest

from devpilot.config import Settings
from devpilot.db import Database
from devpilot.domain import TaskBudget, TaskCreate
from devpilot.errors import BudgetExceededError, RetryableStepError
from devpilot.indexing import RepositoryIndexer
from devpilot.patching import WorkspaceManager
from devpilot.providers import AgentContext, DeterministicProvider, ModelProvider
from devpilot.repository import TaskRepository
from devpilot.runtime import AgentRuntime
from devpilot.tools import LocalTestRunner, RepositoryInspector, ToolExecutionError


class FailPlanOnceProvider(DeterministicProvider):
    def __init__(self) -> None:
        self.failed = False

    def build_plan(self, context: AgentContext) -> dict[str, object]:
        if not self.failed:
            self.failed = True
            raise RuntimeError("injected planner failure")
        return super().build_plan(context)


class TransientPlanProvider(DeterministicProvider):
    name = "transient-test-provider"
    model = "test-model"
    uses_model = True

    def __init__(self) -> None:
        self.calls = 0

    def build_plan(self, context: AgentContext) -> dict[str, object]:
        self.calls += 1
        if self.calls == 1:
            raise RetryableStepError("temporary model capacity error")
        return super().build_plan(context)


class BudgetedModelProvider(DeterministicProvider):
    name = "budgeted-test-provider"
    model = "test-model"
    uses_model = True


def build_runtime(
    database: Database, settings: Settings, provider: ModelProvider
) -> tuple[AgentRuntime, TaskRepository]:
    session = database.session_factory()
    repository = TaskRepository(session)
    runtime = AgentRuntime(
        session,
        provider,
        RepositoryInspector(settings),
        LocalTestRunner(settings),
        RepositoryIndexer(session),
        WorkspaceManager(settings),
        settings.context_token_budget,
    )
    return runtime, repository


def test_runtime_resumes_after_last_checkpoint(database: Database, settings: Settings) -> None:
    provider = FailPlanOnceProvider()
    runtime, tasks = build_runtime(database, settings, provider)
    task = tasks.create(
        TaskCreate(
            title="Exercise checkpoint recovery",
            requirement="Inspect the repository and recover after an injected planner failure.",
            repository_path=".",
        )
    )

    with pytest.raises(RuntimeError, match="injected planner failure"):
        runtime.run(task.id)

    failed = tasks.get_detail(task.id)
    assert failed.status.value == "failed"
    assert [artifact.kind.value for artifact in failed.artifacts] == [
        "repository_snapshot",
        "code_context",
    ]

    runtime.run(task.id)
    recovered = tasks.get_detail(task.id)
    assert recovered.status.value == "completed"
    assert (
        len([item for item in recovered.artifacts if item.kind.value == "repository_snapshot"]) == 1
    )
    resumed_events = [event for event in recovered.events if event.kind.value == "task.started"]
    assert resumed_events[-1].payload["resume_from"] == 3


def test_inspector_rejects_path_outside_workspace(settings: Settings, tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-repository"
    outside.mkdir(exist_ok=True)
    inspector = RepositoryInspector(settings)
    with pytest.raises(ToolExecutionError, match="must stay inside"):
        inspector.inspect(str(outside))


def test_transient_step_failure_retries_inside_same_run(
    database: Database, settings: Settings
) -> None:
    provider = TransientPlanProvider()
    runtime, tasks = build_runtime(database, settings, provider)
    task = tasks.create(
        TaskCreate(
            title="Retry a transient planner failure",
            requirement=(
                "Retry the planning node when the model reports a temporary capacity error."
            ),
            repository_path=".",
        )
    )

    runtime.run(task.id)

    completed = tasks.get_detail(task.id)
    assert completed.status.value == "completed"
    assert provider.calls == 2
    retry_events = [event for event in completed.events if event.kind.value == "step.retrying"]
    assert len(retry_events) == 1
    assert retry_events[0].payload["attempt"] == 2
    model_starts = [event for event in completed.events if event.kind.value == "model.call.started"]
    model_failures = [
        event for event in completed.events if event.kind.value == "model.call.failed"
    ]
    assert len(model_starts) == 4
    assert len(model_failures) == 1


def test_model_call_budget_stops_before_third_role(database: Database, settings: Settings) -> None:
    runtime, tasks = build_runtime(database, settings, BudgetedModelProvider())
    task = tasks.create(
        TaskCreate(
            title="Enforce model call budget",
            requirement="Allow planner and implementer calls but stop before reviewer execution.",
            repository_path=".",
            budget=TaskBudget(max_model_calls=2),
        )
    )

    with pytest.raises(BudgetExceededError, match="2/2"):
        runtime.run(task.id)

    detail = tasks.get_detail(task.id)
    started = [event for event in detail.events if event.kind.value == "model.call.started"]
    completed = [event for event in detail.events if event.kind.value == "model.call.completed"]
    assert detail.status.value == "failed"
    assert [event.payload["role"] for event in started] == ["planner", "implementer"]
    assert len(completed) == 2
    assert all("duration_ms" in event.payload for event in completed)


def test_offline_provider_does_not_consume_model_budget(
    database: Database, settings: Settings
) -> None:
    runtime, tasks = build_runtime(database, settings, DeterministicProvider())
    task = tasks.create(
        TaskCreate(
            title="Run offline without model budget",
            requirement="Complete the deterministic workflow without making any external calls.",
            repository_path=".",
            budget=TaskBudget(max_model_calls=0),
        )
    )

    runtime.run(task.id)

    detail = tasks.get_detail(task.id)
    assert detail.status.value == "completed"
    assert not [event for event in detail.events if event.kind.value.startswith("model.call")]
    assert detail.artifacts[-1].content["model_calls"] == 0
