"""Typed contracts shared by model providers and the runtime.

Keeping schemas here prevents an API-specific adapter from leaking into workflow code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class AgentContext:
    """Evidence passed between role-specific provider calls."""

    requirement: str
    repository: dict[str, Any]
    code_context: dict[str, Any] | None = None
    plan: dict[str, Any] | None = None
    proposal: dict[str, Any] | None = None
    patch_validation: dict[str, Any] | None = None
    test_report: dict[str, Any] | None = None


class ModelProvider(Protocol):
    """Provider boundary consumed by :class:`AgentRuntime`."""

    name: str
    model: str
    uses_model: bool

    def build_plan(self, context: AgentContext) -> dict[str, Any]: ...

    def propose_change(self, context: AgentContext) -> dict[str, Any]: ...

    def review(self, context: AgentContext) -> dict[str, Any]: ...

    def call_metadata(self) -> dict[str, Any]: ...


class PlanOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1, max_length=2000)
    steps: list[str] = Field(min_length=1, max_length=12)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=12)
    risks: list[str] = Field(default_factory=list, max_length=12)


class ChangeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=4000)
    patch: str | None = Field(default=None, max_length=500_000)
    files_considered: list[str] = Field(default_factory=list, max_length=100)
    risks: list[str] = Field(default_factory=list, max_length=20)


class ReviewFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Literal["low", "medium", "high", "critical"]
    message: str = Field(min_length=1, max_length=2000)
    path: str | None = Field(default=None, max_length=1000)


class ReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accept", "needs_revision", "reject"]
    requirement_covered: bool
    findings: list[ReviewFinding] = Field(default_factory=list, max_length=30)
    notes: list[str] = Field(default_factory=list, max_length=20)


OutputModel = TypeVar("OutputModel", bound=BaseModel)


class StructuredResponseClient(Protocol):
    """Transport-neutral structured response client used by role providers."""

    model: str

    def parse(
        self,
        *,
        role: str,
        instructions: str,
        payload: dict[str, Any],
        response_model: type[OutputModel],
    ) -> OutputModel: ...

    def call_metadata(self) -> dict[str, Any]: ...
