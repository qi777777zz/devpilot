from __future__ import annotations

import os
import socket
from collections.abc import Callable
from dataclasses import dataclass
from time import sleep
from uuid import UUID

from sqlalchemy.orm import Session

from devpilot.config import Settings
from devpilot.domain import EventKind, TaskStatus
from devpilot.errors import InvalidTaskStateError, LeaseLostError, RetryableStepError
from devpilot.indexing import RepositoryIndexer
from devpilot.patching import WorkspaceManager
from devpilot.providers import build_provider
from devpilot.queue import JobQueue
from devpilot.repository import TaskRepository
from devpilot.runtime import AgentRuntime
from devpilot.tools import LocalTestRunner, RepositoryInspector


def build_runtime(
    session: Session,
    settings: Settings,
    heartbeat: Callable[[], None] | None = None,
) -> AgentRuntime:
    return AgentRuntime(
        session=session,
        provider=build_provider(settings),
        inspector=RepositoryInspector(settings),
        test_runner=LocalTestRunner(settings),
        indexer=RepositoryIndexer(session),
        workspace_manager=WorkspaceManager(settings),
        context_token_budget=settings.context_token_budget,
        heartbeat=heartbeat,
    )


def cancel_task(session: Session, task_id: UUID) -> None:
    tasks = TaskRepository(session)
    task = tasks.get(task_id)
    if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
        raise InvalidTaskStateError(f"Task cannot be cancelled from state {task.status.value}")
    tasks.set_status(task_id, TaskStatus.CANCELLED)
    tasks.append_event(task_id, EventKind.TASK_CANCELLED, "Task was cancelled by the user.")
    JobQueue(session).cancel_for_task(task_id)
    tasks.commit()


def enqueue_task(session: Session, settings: Settings, task_id: UUID) -> None:
    tasks = TaskRepository(session)
    task = tasks.get(task_id)
    if task.status not in {TaskStatus.PENDING, TaskStatus.FAILED, TaskStatus.PAUSED}:
        raise InvalidTaskStateError(f"Task cannot be queued from state {task.status.value}")
    job = JobQueue(session).enqueue(task_id, settings.worker_max_attempts)
    tasks.append_event(
        task_id,
        EventKind.TASK_QUEUED,
        "Task entered the durable execution queue.",
        payload={"job_id": job.id, "max_attempts": job.max_attempts},
    )
    tasks.commit()


@dataclass
class Worker:
    session: Session
    settings: Settings
    worker_id: str

    @classmethod
    def create(cls, session: Session, settings: Settings, worker_id: str | None = None) -> Worker:
        identity = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        return cls(session=session, settings=settings, worker_id=identity)

    def run_once(self) -> bool:
        queue = JobQueue(self.session)
        lease = queue.claim(self.worker_id, self.settings.worker_lease_seconds)
        if lease is None:
            return False
        tasks = TaskRepository(self.session)
        tasks.append_event(
            lease.task_id,
            EventKind.TASK_LEASED,
            "A worker leased the task for execution.",
            payload={
                "worker_id": self.worker_id,
                "job_id": str(lease.id),
                "attempt": lease.attempt,
            },
        )
        tasks.commit()
        lease_holder = [lease]

        def renew_lease() -> None:
            lease_holder[0] = queue.heartbeat(lease_holder[0], self.settings.worker_lease_seconds)

        try:
            runtime = build_runtime(self.session, self.settings, heartbeat=renew_lease)
            runtime.run(lease.task_id)
        except Exception as exc:
            self.session.expire_all()
            current = tasks.get(lease.task_id)
            if current.status not in {TaskStatus.FAILED, TaskStatus.CANCELLED}:
                tasks.set_status(
                    lease.task_id,
                    TaskStatus.FAILED,
                    error_message=f"{type(exc).__name__}: {exc}",
                )
                tasks.append_event(
                    lease.task_id,
                    EventKind.TASK_FAILED,
                    "Worker could not initialize or complete the runtime.",
                    payload={"error_type": type(exc).__name__, "error": str(exc)},
                )
                tasks.commit()
            try:
                queue.fail(
                    lease,
                    f"{type(exc).__name__}: {exc}",
                    retryable=isinstance(exc, RetryableStepError),
                )
            except LeaseLostError:
                pass
            return True
        try:
            queue.complete(lease)
        except LeaseLostError:
            # Cancellation can revoke a lease while a cooperative step is exiting.
            pass
        return True

    def run_forever(self) -> None:
        while True:
            if not self.run_once():
                sleep(self.settings.worker_poll_seconds)
