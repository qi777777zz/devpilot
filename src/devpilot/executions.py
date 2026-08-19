from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from devpilot.db import StepExecutionRecord
from devpilot.domain import RunStep, StepExecutionStatus


class StepExecutions:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, task_id: UUID, step: RunStep) -> StepExecutionRecord | None:
        return self.session.scalar(
            select(StepExecutionRecord).where(
                StepExecutionRecord.task_id == str(task_id),
                StepExecutionRecord.step == step.value,
            )
        )

    def begin(self, task_id: UUID, step: RunStep) -> StepExecutionRecord:
        record = self.get(task_id, step)
        if record is None:
            record = StepExecutionRecord(
                task_id=str(task_id),
                step=step.value,
                idempotency_key=f"{task_id}:{step.value}",
                status=StepExecutionStatus.RUNNING.value,
                attempt=1,
                started_at=datetime.now(UTC),
            )
            self.session.add(record)
        else:
            record.status = StepExecutionStatus.RUNNING.value
            record.attempt += 1
            record.error_message = None
            record.started_at = datetime.now(UTC)
            record.completed_at = None
        self.session.flush()
        return record

    def complete(self, record: StepExecutionRecord, result: dict[str, Any]) -> None:
        record.status = StepExecutionStatus.COMPLETED.value
        record.result = result
        record.error_message = None
        record.completed_at = datetime.now(UTC)
        self.session.flush()

    def fail(self, record: StepExecutionRecord, error: str) -> None:
        record.status = StepExecutionStatus.FAILED.value
        record.error_message = error
        self.session.flush()
