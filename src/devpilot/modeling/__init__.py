"""Public model-provider API.

Import from this module unless an adapter-specific type is required.
"""

from devpilot.modeling.contracts import (
    AgentContext,
    ChangeOutput,
    ModelProvider,
    PlanOutput,
    ReviewFinding,
    ReviewOutput,
    StructuredResponseClient,
)
from devpilot.modeling.factory import build_provider
from devpilot.modeling.offline import DeterministicProvider
from devpilot.modeling.openai_provider import OpenAIResponsesClient, OpenAIStructuredProvider

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
