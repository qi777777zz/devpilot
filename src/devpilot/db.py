"""SQLAlchemy records and database lifecycle for durable runtime state."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

from devpilot.config import Settings


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TaskRecord(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(120))
    requirement: Mapped[str] = mapped_column(Text)
    repository_path: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(32), index=True)
    current_step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    budget: Mapped[dict[str, int]] = mapped_column(JSON)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    events: Mapped[list[RunEventRecord]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="RunEventRecord.sequence"
    )
    artifacts: Mapped[list[ArtifactRecord]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="ArtifactRecord.created_at"
    )
    checkpoints: Mapped[list[CheckpointRecord]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="CheckpointRecord.step_index"
    )
    jobs: Mapped[list[JobRecord]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="JobRecord.created_at"
    )
    step_executions: Mapped[list[StepExecutionRecord]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class RunEventRecord(Base):
    __tablename__ = "run_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    task: Mapped[TaskRecord] = relationship(back_populates="events")


class ArtifactRecord(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    content: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    task: Mapped[TaskRecord] = relationship(back_populates="artifacts")


class CheckpointRecord(Base):
    __tablename__ = "checkpoints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    step_index: Mapped[int] = mapped_column(Integer)
    step: Mapped[str] = mapped_column(String(64))
    state: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    task: Mapped[TaskRecord] = relationship(back_populates="checkpoints")


class JobRecord(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    task: Mapped[TaskRecord] = relationship(back_populates="jobs")


class StepExecutionRecord(Base):
    __tablename__ = "step_executions"
    __table_args__ = (UniqueConstraint("task_id", "step", name="uq_task_step_execution"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    step: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped[TaskRecord] = relationship(back_populates="step_executions")


class RepositoryIndexRecord(Base):
    __tablename__ = "repository_indexes"
    __table_args__ = (
        UniqueConstraint("repository_root", "tree_digest", name="uq_repository_tree_index"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    repository_root: Mapped[str] = mapped_column(String(1000), index=True)
    tree_digest: Mapped[str] = mapped_column(String(64), index=True)
    parser_version: Mapped[str] = mapped_column(String(64))
    file_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    documents: Mapped[list[CodeDocumentRecord]] = relationship(
        back_populates="index", cascade="all, delete-orphan"
    )


class CodeDocumentRecord(Base):
    __tablename__ = "code_documents"
    __table_args__ = (UniqueConstraint("index_id", "path", name="uq_index_document_path"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    index_id: Mapped[str] = mapped_column(ForeignKey("repository_indexes.id"), index=True)
    path: Mapped[str] = mapped_column(String(1000))
    language: Mapped[str] = mapped_column(String(64), index=True)
    content_digest: Mapped[str] = mapped_column(String(64))
    line_count: Mapped[int] = mapped_column(Integer)

    index: Mapped[RepositoryIndexRecord] = relationship(back_populates="documents")
    symbols: Mapped[list[CodeSymbolRecord]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class CodeSymbolRecord(Base):
    __tablename__ = "code_symbols"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id: Mapped[str] = mapped_column(ForeignKey("code_documents.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    qualified_name: Mapped[str] = mapped_column(String(1000), index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    signature: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    tokens: Mapped[list[str]] = mapped_column(JSON)
    references: Mapped[list[str]] = mapped_column(JSON)

    document: Mapped[CodeDocumentRecord] = relationship(back_populates="symbols")


class Database:
    def __init__(self, settings: Settings) -> None:
        if settings.database_url.startswith("sqlite"):
            database_path = settings.database_url.removeprefix("sqlite:///")
            if database_path and database_path != ":memory:":
                Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        connect_args = (
            {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
        )
        self.engine = create_engine(settings.database_url, connect_args=connect_args)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    def session(self) -> Generator[Session, None, None]:
        with self.session_factory() as session:
            yield session
