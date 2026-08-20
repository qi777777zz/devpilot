"""Deterministic provider for local development and reproducible tests."""

from __future__ import annotations

from typing import Any

from devpilot.modeling.contracts import AgentContext


class DeterministicProvider:
    """Exercise every runtime control point without making a network call."""

    name = "deterministic-offline"
    model = "none"
    uses_model = False

    def build_plan(self, context: AgentContext) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": self.model,
            "role": "planner",
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
            "risks": ["Offline mode cannot synthesize a repository patch."],
        }

    def propose_change(self, context: AgentContext) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": self.model,
            "role": "implementer",
            "mode": "dry_run",
            "summary": "Offline mode records a proposal boundary without mutating files.",
            "patch": None,
            "reason": "Configure a model provider before enabling repository writes.",
            "files_considered": context.repository.get("sample_files", []),
            "risks": [],
        }

    def review(self, context: AgentContext) -> dict[str, Any]:
        test_status = (context.test_report or {}).get("status", "unknown")
        return {
            "provider": self.name,
            "model": self.model,
            "role": "reviewer",
            "decision": "accepted_for_dry_run",
            "requirement_covered": True,
            "test_status": test_status,
            "findings": [],
            "notes": [
                "The runtime completed every planned control point.",
                "No repository mutation was attempted in offline mode.",
            ],
        }

    def call_metadata(self) -> dict[str, Any]:
        return {}
