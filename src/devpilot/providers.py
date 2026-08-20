"""Compatibility imports for the pre-package provider API.

New code should import from :mod:`devpilot.modeling`. This shim keeps existing integrations and
tests working while the internal directory structure evolves.
"""

from devpilot.modeling import (
    AgentContext,
    ChangeOutput,
    DeterministicProvider,
    ModelProvider,
    OpenAIResponsesClient,
    OpenAIStructuredProvider,
    PlanOutput,
    ReviewFinding,
    ReviewOutput,
    StructuredResponseClient,
    build_provider,
)

__all__ = [
    "AgentContext",
    "ChangeOutput",
    "DeterministicProvider",
    "ModelProvider",
    "OpenAIResponsesClient",
    "OpenAIStructuredProvider",
    "PlanOutput",
    "ReviewFinding",
    "ReviewOutput",
    "StructuredResponseClient",
    "build_provider",
]
