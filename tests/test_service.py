from __future__ import annotations

from devpilot.config import Settings
from devpilot.db import Database
from devpilot.domain import TaskCreate
from devpilot.repository import TaskRepository
from devpilot.service import Worker, enqueue_task


def test_worker_marks_task_failed_when_provider_configuration_is_invalid(
    database: Database, settings: Settings
) -> None:
    configured = settings.model_copy(update={"model_provider": "openai", "openai_api_key": None})
    session = database.session_factory()
    tasks = TaskRepository(session)
    task = tasks.create(
        TaskCreate(
            title="Reject invalid provider configuration",
            requirement="Fail safely when an external provider is enabled without credentials.",
            repository_path=".",
        )
    )
    enqueue_task(session, configured, task.id)

    processed = Worker.create(session, configured, worker_id="test-worker").run_once()

    detail = tasks.get_detail(task.id)
    assert processed is True
    assert detail.status.value == "failed"
    assert detail.jobs[-1].state.value == "dead"
    assert "OPENAI_API_KEY" in (detail.error_message or "")
    assert any(event.kind.value == "task.failed" for event in detail.events)
