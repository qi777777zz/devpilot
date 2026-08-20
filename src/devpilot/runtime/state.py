"""Serializable state carried between durable runtime checkpoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID


@dataclass
class RunState:
    """Mutable workflow state; every field must remain JSON-serializable."""

    task_id: UUID
    requirement: str
    repository_path: str
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    repository: dict[str, Any] | None = None
    code_context: dict[str, Any] | None = None
    plan: dict[str, Any] | None = None
    proposal: dict[str, Any] | None = None
    patch_validation: dict[str, Any] | None = None
    workspace_root: str | None = None
    test_report: dict[str, Any] | None = None
    review: dict[str, Any] | None = None

    def checkpoint(self) -> dict[str, Any]:
        """Return the complete resume payload persisted after a successful node."""

        return {
            "task_id": str(self.task_id),
            "requirement": self.requirement,
            "repository_path": self.repository_path,
            "started_at": self.started_at.isoformat(),
            "repository": self.repository,
            "code_context": self.code_context,
            "plan": self.plan,
            "proposal": self.proposal,
            "patch_validation": self.patch_validation,
            "workspace_root": self.workspace_root,
            "test_report": self.test_report,
            "review": self.review,
        }

    @classmethod
    def restore(cls, payload: dict[str, Any]) -> RunState:
        """Rehydrate a checkpoint without depending on ORM records."""

        return cls(
            task_id=UUID(str(payload["task_id"])),
            requirement=str(payload["requirement"]),
            repository_path=str(payload["repository_path"]),
            started_at=datetime.fromisoformat(str(payload["started_at"])),
            repository=payload.get("repository"),
            code_context=payload.get("code_context"),
            plan=payload.get("plan"),
            proposal=payload.get("proposal"),
            patch_validation=payload.get("patch_validation"),
            workspace_root=payload.get("workspace_root"),
            test_report=payload.get("test_report"),
            review=payload.get("review"),
        )
