from __future__ import annotations

from uuid import uuid4

from devpilot import modeling
from devpilot.providers import DeterministicProvider as CompatibilityProvider
from devpilot.runtime import AgentRuntime, RunState
from devpilot.runtime.engine import AgentRuntime as EngineRuntime


def test_public_packages_export_stable_entry_points() -> None:
    assert AgentRuntime is EngineRuntime
    assert CompatibilityProvider is modeling.DeterministicProvider
    assert "build_provider" in modeling.__all__
    assert "OpenAIStructuredProvider" in modeling.__all__


def test_run_state_checkpoint_round_trip_is_process_neutral() -> None:
    state = RunState(
        task_id=uuid4(),
        requirement="Preserve state across a worker restart.",
        repository_path=".",
        plan={"steps": ["inspect", "verify"]},
        patch_validation={"status": "skipped"},
    )

    restored = RunState.restore(state.checkpoint())

    assert restored.task_id == state.task_id
    assert restored.plan == state.plan
    assert restored.patch_validation == state.patch_validation
