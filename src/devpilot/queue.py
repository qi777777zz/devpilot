from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from devpilot.db import JobRecord, TaskRecord
from devpilot.domain import JobState, TaskStatus
from devpilot.errors import LeaseLostError


def aware_utcnow() -> datetime:
    return datetime.now(UTC)


def affected_rows(result: Any) -> int:
    """Normalize SQLAlchemy DML row counts across supported dialects."""
    return int(result.rowcount or 0)


@dataclass(frozen=True)
class JobLease:
    id: UUID
    task_id: UUID
    owner: str
    attempt: int
    max_attempts: int
    expires_at: datetime


class JobQueue:
    """Database-backed queue with compare-and-swap leasing.

    The interface is intentionally transport-neutral. A Redis Streams adapter can
    preserve the same worker contract without changing runtime behavior.
    """

    ACTIVE_STATES = (JobState.QUEUED.value, JobState.LEASED.value)

    def __init__(self, session: Session) -> None:
        self.session = session

    def enqueue(self, task_id: UUID, max_attempts: int) -> JobRecord:
        existing = self.session.scalar(
            select(JobRecord)
            .where(
                JobRecord.task_id == str(task_id),
                JobRecord.state.in_(self.ACTIVE_STATES),
            )
            .order_by(JobRecord.created_at.desc())
            .limit(1)
        )
        if existing is not None:
            return existing
        job = JobRecord(
            task_id=str(task_id),
            state=JobState.QUEUED.value,
            max_attempts=max_attempts,
            available_at=aware_utcnow(),
        )
        self.session.add(job)
        task = self.session.get(TaskRecord, str(task_id))
        if task is not None:
            task.status = TaskStatus.QUEUED.value
            task.current_step = None
        self.session.commit()
        return job

    def claim(
        self,
        owner: str,
        lease_seconds: int,
        *,
        now: datetime | None = None,
    ) -> JobLease | None:
        claimed_at = now or aware_utcnow()
        claimable = or_(
            (JobRecord.state == JobState.QUEUED.value) & (JobRecord.available_at <= claimed_at),
            (JobRecord.state == JobState.LEASED.value) & (JobRecord.lease_expires_at <= claimed_at),
        )
        candidate_ids = self.session.scalars(
            select(JobRecord.id)
            .where(claimable)
            .order_by(JobRecord.available_at, JobRecord.created_at)
            .limit(8)
        ).all()
        expires_at = claimed_at + timedelta(seconds=lease_seconds)
        for candidate_id in candidate_ids:
            result = self.session.execute(
                update(JobRecord)
                .where(JobRecord.id == candidate_id, claimable)
                .values(
                    state=JobState.LEASED.value,
                    lease_owner=owner,
                    lease_expires_at=expires_at,
                    heartbeat_at=claimed_at,
                    attempts=JobRecord.attempts + 1,
                )
            )
            if affected_rows(result) != 1:
                self.session.rollback()
                continue
            self.session.commit()
            job = self.session.get(JobRecord, candidate_id)
            if job is None:
                return None
            return JobLease(
                id=UUID(job.id),
                task_id=UUID(job.task_id),
                owner=owner,
                attempt=job.attempts,
                max_attempts=job.max_attempts,
                expires_at=expires_at,
            )
        return None

    def heartbeat(
        self,
        lease: JobLease,
        lease_seconds: int,
        *,
        now: datetime | None = None,
    ) -> JobLease:
        heartbeat_at = now or aware_utcnow()
        expires_at = heartbeat_at + timedelta(seconds=lease_seconds)
        result = self.session.execute(
            update(JobRecord)
            .where(
                JobRecord.id == str(lease.id),
                JobRecord.state == JobState.LEASED.value,
                JobRecord.lease_owner == lease.owner,
            )
            .values(heartbeat_at=heartbeat_at, lease_expires_at=expires_at)
        )
        if affected_rows(result) != 1:
            self.session.rollback()
            raise LeaseLostError(f"Worker {lease.owner} no longer owns job {lease.id}")
        self.session.commit()
        return JobLease(
            id=lease.id,
            task_id=lease.task_id,
            owner=lease.owner,
            attempt=lease.attempt,
            max_attempts=lease.max_attempts,
            expires_at=expires_at,
        )

    def complete(self, lease: JobLease) -> None:
        self._finish_owned_job(lease, JobState.COMPLETED, None)

    def fail(
        self,
        lease: JobLease,
        error: str,
        *,
        retryable: bool,
        now: datetime | None = None,
    ) -> JobState:
        if retryable and lease.attempt < lease.max_attempts:
            available_at = (now or aware_utcnow()) + timedelta(
                seconds=min(2 ** (lease.attempt - 1), 30)
            )
            result = self.session.execute(
                update(JobRecord)
                .where(
                    JobRecord.id == str(lease.id),
                    JobRecord.state == JobState.LEASED.value,
                    JobRecord.lease_owner == lease.owner,
                )
                .values(
                    state=JobState.QUEUED.value,
                    available_at=available_at,
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error=error,
                )
            )
            if affected_rows(result) != 1:
                self.session.rollback()
                raise LeaseLostError(f"Cannot retry unowned job {lease.id}")
            task = self.session.get(TaskRecord, str(lease.task_id))
            if task is not None:
                task.status = TaskStatus.RETRYING.value
            self.session.commit()
            return JobState.QUEUED
        self._finish_owned_job(lease, JobState.DEAD, error)
        return JobState.DEAD

    def cancel_for_task(self, task_id: UUID) -> int:
        result = self.session.execute(
            update(JobRecord)
            .where(
                JobRecord.task_id == str(task_id),
                JobRecord.state.in_(self.ACTIVE_STATES),
            )
            .values(
                state=JobState.CANCELLED.value,
                lease_owner=None,
                lease_expires_at=None,
            )
        )
        self.session.commit()
        return affected_rows(result)

    def _finish_owned_job(self, lease: JobLease, state: JobState, error: str | None) -> None:
        result = self.session.execute(
            update(JobRecord)
            .where(
                JobRecord.id == str(lease.id),
                JobRecord.state == JobState.LEASED.value,
                JobRecord.lease_owner == lease.owner,
            )
            .values(
                state=state.value,
                lease_owner=None,
                lease_expires_at=None,
                last_error=error,
            )
        )
        if affected_rows(result) != 1:
            self.session.rollback()
            raise LeaseLostError(f"Cannot finish unowned job {lease.id}")
        self.session.commit()
