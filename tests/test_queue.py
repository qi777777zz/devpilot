from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from devpilot.db import Database, JobRecord
from devpilot.domain import JobState, TaskCreate
from devpilot.errors import LeaseLostError
from devpilot.queue import JobQueue
from devpilot.repository import TaskRepository


def create_task(database: Database):
    with database.session_factory() as session:
        return TaskRepository(session).create(
            TaskCreate(
                title="Exercise queue leasing",
                requirement="Verify that an expired worker lease can be safely reclaimed.",
                repository_path=".",
            )
        )


def test_expired_lease_is_reclaimed_without_double_completion(database: Database) -> None:
    task = create_task(database)
    with database.session_factory() as first_session:
        first_queue = JobQueue(first_session)
        first_queue.enqueue(task.id, max_attempts=3)
        started = datetime.now(UTC) + timedelta(milliseconds=1)
        first_lease = first_queue.claim("worker-a", 10, now=started)
        assert first_lease is not None

    with database.session_factory() as second_session:
        second_queue = JobQueue(second_session)
        assert second_queue.claim("worker-b", 10, now=started) is None
        second_lease = second_queue.claim("worker-b", 10, now=started + timedelta(seconds=11))
        assert second_lease is not None
        assert second_lease.attempt == 2

    with database.session_factory() as stale_session:
        with pytest.raises(LeaseLostError):
            JobQueue(stale_session).complete(first_lease)

    with database.session_factory() as owner_session:
        JobQueue(owner_session).complete(second_lease)
        job = owner_session.scalar(select(JobRecord).where(JobRecord.task_id == str(task.id)))
        assert job is not None
        assert job.state == JobState.COMPLETED.value


def test_enqueue_is_idempotent_for_an_active_task(database: Database) -> None:
    task = create_task(database)
    with database.session_factory() as session:
        queue = JobQueue(session)
        first = queue.enqueue(task.id, max_attempts=3)
        second = queue.enqueue(task.id, max_attempts=3)
        assert first.id == second.id


def test_heartbeat_extends_lease_and_retry_uses_backoff(database: Database) -> None:
    task = create_task(database)
    with database.session_factory() as session:
        queue = JobQueue(session)
        queue.enqueue(task.id, max_attempts=3)
        started = datetime.now(UTC) + timedelta(milliseconds=1)
        lease = queue.claim("worker-a", 10, now=started)
        assert lease is not None
        renewed = queue.heartbeat(lease, 10, now=started + timedelta(seconds=8))
        assert renewed.expires_at == started + timedelta(seconds=18)
        assert queue.claim("worker-b", 10, now=started + timedelta(seconds=11)) is None

        state = queue.fail(
            renewed,
            "temporary provider error",
            retryable=True,
            now=started + timedelta(seconds=12),
        )
        assert state == JobState.QUEUED
        assert queue.claim("worker-b", 10, now=started + timedelta(seconds=12)) is None
        retried = queue.claim("worker-b", 10, now=started + timedelta(seconds=13))
        assert retried is not None
        assert retried.attempt == 2
