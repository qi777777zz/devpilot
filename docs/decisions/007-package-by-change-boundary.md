# ADR 007: Organize runtime and modeling code by change boundary

**Status:** accepted

## Context

The first milestones used flat modules to keep bootstrapping simple. As recovery, patch staging,
structured providers, role prompts, and model telemetry were added, `runtime.py` and `providers.py`
accumulated unrelated reasons to change. Readers had to understand checkpoint serialization,
workflow transactions, SDK behavior, schemas, and prompts in two large files.

## Decision

Split these areas into packages organized by responsibility:

- `runtime/state.py` owns the process-neutral checkpoint payload.
- `runtime/model_calls.py` owns model budgets and external-call telemetry.
- `runtime/engine.py` owns node order, status transitions, and artifacts.
- `modeling/contracts.py` owns protocols and strict output schemas.
- `modeling/offline.py` and `modeling/openai_provider.py` own concrete adapters.
- `modeling/factory.py` owns configuration-driven selection.

Package `__init__.py` files define the stable imports. `devpilot.providers` remains a small
compatibility shim, while new code imports from `devpilot.modeling`.

Comments are reserved for transaction timing, recovery behavior, and security boundaries. Routine
control flow should remain understandable through names, types, and small modules.

## Alternatives

- **Keep flat modules:** fewer files, but unrelated changes continue to collide.
- **One directory per technical layer:** produces broad `services/` and `utils/` buckets with weak
  ownership.
- **One class per file:** maximizes file count without improving dependency direction.

## Consequences

New readers can follow the workflow without loading API-specific code. Provider adapters can change
without touching checkpoint state, and model-call accounting can evolve independently from node
handlers. The additional package files require explicit public exports and compatibility tests,
which are covered by `test_structure.py`.
