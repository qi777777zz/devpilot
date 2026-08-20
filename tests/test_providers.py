from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from devpilot.config import Settings
from devpilot.errors import ModelProviderError, RetryableStepError
from devpilot.modeling import (
    AgentContext,
    ChangeOutput,
    OpenAIResponsesClient,
    OpenAIStructuredProvider,
    PlanOutput,
    ReviewOutput,
    build_provider,
)


class RecordingStructuredClient:
    model = "test-model"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def parse(
        self,
        *,
        role: str,
        instructions: str,
        payload: dict[str, Any],
        response_model: type[Any],
    ) -> Any:
        self.calls.append(
            {
                "role": role,
                "instructions": instructions,
                "payload": payload,
                "response_model": response_model,
            }
        )
        outputs = {
            PlanOutput: {
                "goal": "Make a safe change",
                "steps": ["Inspect", "Patch", "Verify"],
                "acceptance_criteria": ["Tests pass"],
                "risks": ["Regression"],
            },
            ChangeOutput: {
                "summary": "No patch needed for this protocol test.",
                "patch": None,
                "files_considered": ["src/sample.py"],
                "risks": [],
            },
            ReviewOutput: {
                "decision": "accept",
                "requirement_covered": True,
                "findings": [],
                "notes": ["Evidence is consistent."],
            },
        }
        return response_model.model_validate(outputs[response_model])

    def call_metadata(self) -> dict[str, Any]:
        return {"request_id": f"test-{self.calls[-1]['role']}"}


class FakeResponsesAPI:
    def __init__(self, output: object = None, error: Exception | None = None) -> None:
        self.output = output
        self.error = error
        self.kwargs: dict[str, Any] | None = None

    def parse(self, **kwargs: Any) -> object:
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            id="resp_test",
            output_parsed=self.output,
            usage=SimpleNamespace(input_tokens=10, output_tokens=4, total_tokens=14),
        )


class StatusError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def context() -> AgentContext:
    return AgentContext(
        requirement="Safely update the sample behavior.",
        repository={
            "root": "C:/secret/repository",
            "tree_digest": "abc123",
            "file_count": 2,
            "languages": {"Python": 1},
            "sample_files": ["src/sample.py"],
            "files": ["src/sample.py", ".env"],
        },
        code_context={"chunks": [{"path": "src/sample.py", "content": "return 42"}]},
        plan={"steps": ["Change the return value"]},
        proposal={"patch": None},
        patch_validation={"status": "skipped"},
        test_report={"status": "passed"},
    )


def test_structured_provider_separates_roles_and_limits_context() -> None:
    client = RecordingStructuredClient()
    provider = OpenAIStructuredProvider(client)

    plan = provider.build_plan(context())
    change = provider.propose_change(context())
    review = provider.review(context())

    assert [call["role"] for call in client.calls] == ["planner", "implementer", "reviewer"]
    assert plan["role"] == "planner"
    assert change["mode"] == "no_change"
    assert review["decision"] == "accept"
    assert "root" not in client.calls[0]["payload"]["repository"]
    assert "files" not in client.calls[0]["payload"]["repository"]
    assert client.calls[2]["payload"]["patch_validation"] == {"status": "skipped"}
    assert client.calls[2]["response_model"] is ReviewOutput
    assert provider.call_metadata() == {"request_id": "test-reviewer"}


def test_responses_client_uses_official_structured_parse_shape(settings: Settings) -> None:
    api = FakeResponsesAPI(
        output={
            "goal": "Inspect first",
            "steps": ["Inspect"],
            "acceptance_criteria": ["Evidence recorded"],
            "risks": [],
        }
    )
    sdk = SimpleNamespace(responses=api)
    configured = settings.model_copy(update={"openai_model": "test-model"})
    client = OpenAIResponsesClient(configured, client=sdk)

    parsed = client.parse(
        role="planner",
        instructions="Plan safely.",
        payload={"requirement": "Inspect"},
        response_model=PlanOutput,
    )

    assert parsed.goal == "Inspect first"
    assert api.kwargs is not None
    assert api.kwargs["model"] == "test-model"
    assert api.kwargs["text_format"] is PlanOutput
    assert api.kwargs["input"][0] == {"role": "system", "content": "Plan safely."}
    assert json.loads(api.kwargs["input"][1]["content"]) == {"requirement": "Inspect"}
    assert client.call_metadata() == {
        "request_id": "resp_test",
        "input_tokens": 10,
        "output_tokens": 4,
        "total_tokens": 14,
    }


@pytest.mark.parametrize("status_code", [429, 500, 503])
def test_responses_client_classifies_transient_http_errors(
    settings: Settings, status_code: int
) -> None:
    api = FakeResponsesAPI(error=StatusError(status_code))
    client = OpenAIResponsesClient(settings, client=SimpleNamespace(responses=api))

    with pytest.raises(RetryableStepError, match="transiently"):
        client.parse(
            role="planner",
            instructions="Plan.",
            payload={},
            response_model=PlanOutput,
        )


def test_responses_client_rejects_invalid_output_and_nonretryable_error(
    settings: Settings,
) -> None:
    invalid = OpenAIResponsesClient(
        settings,
        client=SimpleNamespace(responses=FakeResponsesAPI(output={"goal": "missing lists"})),
    )
    with pytest.raises(ModelProviderError, match="violated its schema"):
        invalid.parse(
            role="planner",
            instructions="Plan.",
            payload={},
            response_model=PlanOutput,
        )

    failed = OpenAIResponsesClient(
        settings,
        client=SimpleNamespace(responses=FakeResponsesAPI(error=StatusError(400))),
    )
    with pytest.raises(ModelProviderError, match="StatusError"):
        failed.parse(
            role="planner",
            instructions="Plan.",
            payload={},
            response_model=PlanOutput,
        )

    empty = OpenAIResponsesClient(
        settings,
        client=SimpleNamespace(responses=FakeResponsesAPI(output=None)),
    )
    with pytest.raises(ModelProviderError, match="no structured output"):
        empty.parse(
            role="planner",
            instructions="Plan.",
            payload={},
            response_model=PlanOutput,
        )


def test_openai_provider_requires_api_key(settings: Settings) -> None:
    configured = settings.model_copy(update={"model_provider": "openai", "openai_api_key": None})
    with pytest.raises(ModelProviderError, match="OPENAI_API_KEY"):
        build_provider(configured)


def test_openai_provider_can_be_configured_without_network(settings: Settings) -> None:
    configured = settings.model_copy(
        update={"model_provider": "openai", "openai_api_key": SecretStr("sk-test")}
    )
    provider = build_provider(configured)
    assert isinstance(provider, OpenAIStructuredProvider)
    assert provider.model == "gpt-5.6"


def test_settings_normalizes_blank_api_key() -> None:
    assert Settings(openai_api_key="   ").openai_api_key is None


def test_openai_provider_requires_lease_longer_than_request_timeout() -> None:
    with pytest.raises(ValidationError, match="worker_lease_seconds must exceed"):
        Settings(
            model_provider="openai",
            openai_api_key="sk-test",
            worker_lease_seconds=30,
            model_request_timeout_seconds=120,
        )
