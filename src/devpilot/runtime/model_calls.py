"""Durable accounting around external model calls."""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic
from typing import Any
from uuid import UUID

from devpilot.domain import EventKind, RunStep
from devpilot.errors import BudgetExceededError
from devpilot.modeling import ModelProvider
from devpilot.repository import TaskRepository


class ModelCallController:
    """Charge budgets and persist sanitized telemetry at the call boundary."""

    SAFE_METADATA = ("request_id", "input_tokens", "output_tokens", "total_tokens")

    def __init__(
        self,
        tasks: TaskRepository,
        provider: ModelProvider,
        heartbeat: Callable[[], None] | None,
    ) -> None:
        self.tasks = tasks
        self.provider = provider
        self.heartbeat = heartbeat

    def count(self, task_id: UUID) -> int:
        return self.tasks.count_events(task_id, EventKind.MODEL_CALL_STARTED)

    def invoke(
        self,
        task_id: UUID,
        step: RunStep,
        role: str,
        call: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        if not self.provider.uses_model:
            return call()

        task = self.tasks.get(task_id)
        used = self.count(task_id)
        if used >= task.budget.max_model_calls:
            raise BudgetExceededError(
                f"Model call budget exhausted before {role}: {used}/{task.budget.max_model_calls}"
            )

        metadata = {
            "role": role,
            "provider": self.provider.name,
            "model": self.provider.model,
            "call_number": used + 1,
            "budget": task.budget.max_model_calls,
        }
        self.tasks.append_event(
            task_id,
            EventKind.MODEL_CALL_STARTED,
            f"Started structured {role} model call.",
            step=step,
            payload=metadata,
        )
        # Commit before I/O so a crash or process kill still consumes the attempt budget.
        self.tasks.commit()
        self._heartbeat()

        call_started = monotonic()
        try:
            result = call()
        except Exception as exc:
            duration_ms = round((monotonic() - call_started) * 1000, 3)
            self.tasks.append_event(
                task_id,
                EventKind.MODEL_CALL_FAILED,
                f"Structured {role} model call failed.",
                step=step,
                payload={
                    **metadata,
                    "duration_ms": duration_ms,
                    "error_type": type(exc).__name__,
                },
            )
            self.tasks.commit()
            raise

        duration_ms = round((monotonic() - call_started) * 1000, 3)
        call_metadata = self.provider.call_metadata()
        safe_metadata = {
            key: call_metadata[key] for key in self.SAFE_METADATA if key in call_metadata
        }
        self.tasks.append_event(
            task_id,
            EventKind.MODEL_CALL_COMPLETED,
            f"Structured {role} model call completed.",
            step=step,
            payload={**metadata, "duration_ms": duration_ms, **safe_metadata},
        )
        self.tasks.commit()
        self._heartbeat()
        return result

    def _heartbeat(self) -> None:
        if self.heartbeat is not None:
            self.heartbeat()
