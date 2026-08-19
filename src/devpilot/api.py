from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from devpilot.config import Settings, get_settings
from devpilot.db import Database
from devpilot.domain import HealthView, TaskCreate, TaskDetail, TaskStatus, TaskView
from devpilot.repository import TaskNotFoundError, TaskRepository
from devpilot.runtime import InvalidTaskStateError
from devpilot.service import build_runtime, cancel_task


def _run_in_background(database: Database, settings: Settings, task_id: UUID) -> None:
    with database.session_factory() as session:
        runtime = build_runtime(session, settings)
        try:
            runtime.run(task_id)
        except Exception:
            # Runtime persists structured failure evidence before re-raising.
            return


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    database = Database(app_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        database.create_schema()
        yield

    app = FastAPI(
        title="DevPilot API",
        version="0.1.0",
        description="Recoverable execution for repository-level engineering tasks.",
        lifespan=lifespan,
    )
    app.state.database = database
    app.state.settings = app_settings

    def get_session() -> Generator[Session, None, None]:
        yield from database.session()

    SessionDependency = Annotated[Session, Depends(get_session)]

    @app.get("/api/v1/health", response_model=HealthView)
    def health() -> HealthView:
        return HealthView()

    @app.post("/api/v1/tasks", response_model=TaskView, status_code=status.HTTP_201_CREATED)
    def create_task(data: TaskCreate, session: SessionDependency) -> TaskView:
        return TaskRepository(session).create(data)

    @app.get("/api/v1/tasks", response_model=list[TaskView])
    def list_tasks(
        session: SessionDependency,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> list[TaskView]:
        return TaskRepository(session).list(limit)

    @app.get("/api/v1/tasks/{task_id}", response_model=TaskDetail)
    def get_task(task_id: UUID, session: SessionDependency) -> TaskDetail:
        try:
            return TaskRepository(session).get_detail(task_id)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Task not found") from exc

    @app.post("/api/v1/tasks/{task_id}/run", status_code=status.HTTP_202_ACCEPTED)
    def run_task(
        task_id: UUID,
        background_tasks: BackgroundTasks,
        session: SessionDependency,
    ) -> dict[str, str]:
        try:
            task = TaskRepository(session).get(task_id)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Task not found") from exc
        if task.status not in {TaskStatus.PENDING, TaskStatus.FAILED, TaskStatus.PAUSED}:
            raise HTTPException(
                status_code=409, detail=f"Task cannot run from state {task.status.value}"
            )
        background_tasks.add_task(_run_in_background, database, app_settings, task_id)
        return {"task_id": str(task_id), "status": "scheduled"}

    @app.post("/api/v1/tasks/{task_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
    def stop_task(task_id: UUID, session: SessionDependency) -> dict[str, str]:
        try:
            cancel_task(session, task_id)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Task not found") from exc
        except InvalidTaskStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"task_id": str(task_id), "status": "cancelled"}

    web_dir = Path(__file__).parent / "web"
    app.mount("/assets", StaticFiles(directory=web_dir), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(web_dir / "index.html")

    return app


app = create_app()
