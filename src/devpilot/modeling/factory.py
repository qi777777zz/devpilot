"""Configuration-driven provider construction."""

from devpilot.config import Settings
from devpilot.modeling.contracts import ModelProvider
from devpilot.modeling.offline import DeterministicProvider
from devpilot.modeling.openai_provider import OpenAIResponsesClient, OpenAIStructuredProvider


def build_provider(settings: Settings) -> ModelProvider:
    """Build the explicitly configured provider; offline remains the safe default."""

    if settings.model_provider == "deterministic":
        return DeterministicProvider()
    return OpenAIStructuredProvider(OpenAIResponsesClient(settings))
