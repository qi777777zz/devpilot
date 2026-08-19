from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TaskStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class JobState(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    COMPLETED = "completed"
    DEAD = "dead"
    CANCELLED = "cancelled"


class StepExecutionStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RunStep(StrEnum):
    VALIDATE = "validate"
    INSPECT_REPOSITORY = "inspect_repository"
    BUILD_PLAN = "build_plan"
    PROPOSE_CHANGE = "propose_change"
    RUN_TESTS = "run_tests"
    REVIEW = "review"
    FINALIZE = "finalize"


class EventKind(StrEnum):
    TASK_CREATED = "task.created"
    TASK_STARTED = "task.started"
    TASK_QUEUED = "task.queued"
    TASK_LEASED = "task.leased"
    STEP_STARTED = "step.started"
    STEP_COMPLETED = "step.completed"
    STEP_FAILED = "step.failed"
    STEP_RETRYING = "step.retrying"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"


class ArtifactKind(StrEnum):
    REPOSITORY_SNAPSHOT = "repository_snapshot"
    IMPLEMENTATION_PLAN = "implementation_plan"
    CHANGE_PROPOSAL = "change_proposal"
    TEST_REPORT = "test_report"
    REVIEW_REPORT = "review_report"
    FINAL_REPORT = "final_report"


class TaskBudget(BaseModel):
    max_steps: int = Field(default=20, ge=1, le=200)
    max_model_calls: int = Field(default=10, ge=0, le=100)
    max_tool_calls: int = Field(default=20, ge=0, le=200)
    max_wall_seconds: int = Field(default=900, ge=10, le=86_400)
    max_retries_per_step: int = Field(default=2, ge=0, le=10)


class TaskCreate(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    requirement: str = Field(min_length=10, max_length=10_000)
    repository_path: str = Field(default=".", min_length=1, max_length=1_000)
    budget: TaskBudget = Field(default_factory=TaskBudget)


class TaskView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    requirement: str
    repository_path: str
    status: TaskStatus
    current_step: RunStep | None
    budget: TaskBudget
    result_summary: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class RunEventView(BaseModel):
    id: UUID
    task_id: UUID
    sequence: int
    kind: EventKind
    step: RunStep | None
    message: str
    payload: dict[str, Any]
    created_at: datetime


class ArtifactView(BaseModel):
    id: UUID
    task_id: UUID
    kind: ArtifactKind
    name: str
    content: dict[str, Any]
    created_at: datetime


class JobView(BaseModel):
    id: UUID
    task_id: UUID
    state: JobState
    attempts: int
    max_attempts: int
    available_at: datetime
    lease_owner: str | None
    lease_expires_at: datetime | None
    last_error: str | None
    created_at: datetime


class TaskDetail(TaskView):
    events: list[RunEventView]
    artifacts: list[ArtifactView]
    jobs: list[JobView]


class HealthView(BaseModel):
    status: str = "ok"
    service: str = "devpilot-api"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
