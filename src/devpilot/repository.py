from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from devpilot.db import ArtifactRecord, CheckpointRecord, RunEventRecord, TaskRecord
from devpilot.domain import (
    ArtifactKind,
    ArtifactView,
    EventKind,
    RunEventView,
    RunStep,
    TaskBudget,
    TaskCreate,
    TaskDetail,
    TaskStatus,
    TaskView,
)


class TaskNotFoundError(LookupError):
    pass


class TaskRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, data: TaskCreate) -> TaskView:
        record = TaskRecord(
            title=data.title,
            requirement=data.requirement,
            repository_path=data.repository_path,
            status=TaskStatus.PENDING.value,
            budget=data.budget.model_dump(),
        )
        self.session.add(record)
        self.session.flush()
        self.append_event(
            UUID(record.id),
            EventKind.TASK_CREATED,
            "Task accepted and waiting to run.",
            payload={"budget": data.budget.model_dump()},
        )
        self.session.commit()
        return self._to_view(record)

    def list(self, limit: int = 50) -> list[TaskView]:
        records = self.session.scalars(
            select(TaskRecord).order_by(TaskRecord.created_at.desc()).limit(limit)
        ).all()
        return [self._to_view(record) for record in records]

    def get_record(self, task_id: UUID, *, with_children: bool = False) -> TaskRecord:
        query = select(TaskRecord).where(TaskRecord.id == str(task_id))
        if with_children:
            query = query.options(
                selectinload(TaskRecord.events), selectinload(TaskRecord.artifacts)
            )
        record = self.session.scalar(query)
        if record is None:
            raise TaskNotFoundError(str(task_id))
        return record

    def get(self, task_id: UUID) -> TaskView:
        return self._to_view(self.get_record(task_id))

    def get_detail(self, task_id: UUID) -> TaskDetail:
        record = self.get_record(task_id, with_children=True)
        view = self._to_view(record)
        return TaskDetail(
            **view.model_dump(),
            events=[self._event_to_view(event) for event in record.events],
            artifacts=[self._artifact_to_view(artifact) for artifact in record.artifacts],
        )

    def set_status(
        self,
        task_id: UUID,
        status: TaskStatus,
        *,
        current_step: RunStep | None = None,
        result_summary: str | None = None,
        error_message: str | None = None,
    ) -> None:
        record = self.get_record(task_id)
        record.status = status.value
        record.current_step = current_step.value if current_step else None
        if result_summary is not None:
            record.result_summary = result_summary
        if error_message is not None:
            record.error_message = error_message
        self.session.flush()

    def append_event(
        self,
        task_id: UUID,
        kind: EventKind,
        message: str,
        *,
        step: RunStep | None = None,
        payload: dict[str, Any] | None = None,
    ) -> RunEventRecord:
        last_sequence = self.session.scalar(
            select(func.max(RunEventRecord.sequence)).where(RunEventRecord.task_id == str(task_id))
        )
        event = RunEventRecord(
            task_id=str(task_id),
            sequence=(last_sequence or 0) + 1,
            kind=kind.value,
            step=step.value if step else None,
            message=message,
            payload=payload or {},
        )
        self.session.add(event)
        self.session.flush()
        return event

    def add_artifact(
        self,
        task_id: UUID,
        kind: ArtifactKind,
        name: str,
        content: dict[str, Any],
    ) -> ArtifactRecord:
        artifact = ArtifactRecord(task_id=str(task_id), kind=kind.value, name=name, content=content)
        self.session.add(artifact)
        self.session.flush()
        return artifact

    def save_checkpoint(
        self,
        task_id: UUID,
        step_index: int,
        step: RunStep,
        state: dict[str, Any],
    ) -> CheckpointRecord:
        checkpoint = CheckpointRecord(
            task_id=str(task_id), step_index=step_index, step=step.value, state=state
        )
        self.session.add(checkpoint)
        self.session.flush()
        return checkpoint

    def latest_checkpoint(self, task_id: UUID) -> CheckpointRecord | None:
        return self.session.scalar(
            select(CheckpointRecord)
            .where(CheckpointRecord.task_id == str(task_id))
            .order_by(CheckpointRecord.step_index.desc())
            .limit(1)
        )

    def commit(self) -> None:
        self.session.commit()

    @staticmethod
    def _to_view(record: TaskRecord) -> TaskView:
        return TaskView(
            id=UUID(record.id),
            title=record.title,
            requirement=record.requirement,
            repository_path=record.repository_path,
            status=TaskStatus(record.status),
            current_step=RunStep(record.current_step) if record.current_step else None,
            budget=TaskBudget.model_validate(record.budget),
            result_summary=record.result_summary,
            error_message=record.error_message,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _event_to_view(record: RunEventRecord) -> RunEventView:
        return RunEventView(
            id=UUID(record.id),
            task_id=UUID(record.task_id),
            sequence=record.sequence,
            kind=EventKind(record.kind),
            step=RunStep(record.step) if record.step else None,
            message=record.message,
            payload=record.payload,
            created_at=record.created_at,
        )

    @staticmethod
    def _artifact_to_view(record: ArtifactRecord) -> ArtifactView:
        return ArtifactView(
            id=UUID(record.id),
            task_id=UUID(record.task_id),
            kind=ArtifactKind(record.kind),
            name=record.name,
            content=record.content,
            created_at=record.created_at,
        )
