from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from devpilot.config import Settings
from devpilot.domain import EventKind, TaskStatus
from devpilot.providers import DeterministicProvider
from devpilot.repository import TaskRepository
from devpilot.runtime import AgentRuntime, InvalidTaskStateError
from devpilot.tools import LocalTestRunner, RepositoryInspector


def build_runtime(session: Session, settings: Settings) -> AgentRuntime:
    return AgentRuntime(
        session=session,
        provider=DeterministicProvider(),
        inspector=RepositoryInspector(settings),
        test_runner=LocalTestRunner(settings),
    )


def cancel_task(session: Session, task_id: UUID) -> None:
    tasks = TaskRepository(session)
    task = tasks.get(task_id)
    if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
        raise InvalidTaskStateError(f"Task cannot be cancelled from state {task.status.value}")
    tasks.set_status(task_id, TaskStatus.CANCELLED)
    tasks.append_event(task_id, EventKind.TASK_CANCELLED, "Task was cancelled by the user.")
    tasks.commit()
