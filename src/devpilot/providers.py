from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class AgentContext:
    requirement: str
    repository: dict[str, Any]
    code_context: dict[str, Any] | None = None
    plan: dict[str, Any] | None = None
    proposal: dict[str, Any] | None = None
    test_report: dict[str, Any] | None = None


class ModelProvider(Protocol):
    name: str

    def build_plan(self, context: AgentContext) -> dict[str, Any]: ...

    def propose_change(self, context: AgentContext) -> dict[str, Any]: ...

    def review(self, context: AgentContext) -> dict[str, Any]: ...


class DeterministicProvider:
    """Offline provider used to exercise the runtime without an API key.

    It deliberately proposes no file mutation. Real providers will implement the
    same interface and must return a validated patch proposal.
    """

    name = "deterministic-offline"

    def build_plan(self, context: AgentContext) -> dict[str, Any]:
        return {
            "provider": self.name,
            "goal": context.requirement,
            "steps": [
                "Inspect repository evidence",
                "Identify the smallest safe change surface",
                "Produce a reviewable patch proposal",
                "Run repository checks",
                "Review evidence against the requirement",
            ],
            "acceptance_criteria": [
                "The requested behavior is explicit",
                "Existing behavior remains verifiable",
                "Every claimed result has a recorded artifact",
            ],
        }

    def propose_change(self, context: AgentContext) -> dict[str, Any]:
        return {
            "provider": self.name,
            "mode": "dry_run",
            "summary": "Offline mode records a proposal boundary without mutating files.",
            "patch": None,
            "reason": "Configure a model provider before enabling repository writes.",
            "files_considered": context.repository.get("sample_files", []),
        }

    def review(self, context: AgentContext) -> dict[str, Any]:
        test_status = (context.test_report or {}).get("status", "unknown")
        return {
            "provider": self.name,
            "decision": "accepted_for_dry_run",
            "requirement_covered": True,
            "test_status": test_status,
            "notes": [
                "The runtime completed every planned control point.",
                "No repository mutation was attempted in offline mode.",
            ],
        }
