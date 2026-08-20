# Code map

This page is the shortest path into the DevPilot codebase. Public package entry points re-export
the types most callers need; implementation modules are grouped by why they change.

## Start here

1. `api.py` accepts HTTP commands and returns task views.
2. `service.py` enqueues work and manages worker leases.
3. `runtime/engine.py` executes the durable workflow one checkpointed node at a time.
4. `modeling/` produces structured plans, patches, and reviews.
5. `patching.py` is the authority boundary for any proposed file change.

## Package layout

```text
src/devpilot/
├── api.py / cli.py / web/       # delivery surfaces
├── service.py                   # API-to-worker application services
├── runtime/
│   ├── engine.py                # workflow transitions and artifacts
│   ├── state.py                 # JSON checkpoint contract
│   └── model_calls.py           # budgets, retries, sanitized telemetry
├── modeling/
│   ├── contracts.py             # provider protocols and output schemas
│   ├── offline.py               # deterministic no-network provider
│   ├── openai_provider.py       # Responses API adapter and role prompts
│   └── factory.py               # configuration-driven selection
├── indexing.py / retrieval.py  # repository intelligence
├── patching.py / tools.py       # bounded side effects
├── db.py / repository.py       # durable records and persistence facade
├── queue.py / executions.py    # leasing and node idempotency
└── domain.py / errors.py        # shared application vocabulary
```

## Stable imports

Use these imports from application code and tests:

```python
from devpilot.modeling import ModelProvider, build_provider
from devpilot.runtime import AgentRuntime, RunState
```

`devpilot.providers` remains a compatibility shim for code written before the `modeling/` package
was introduced. New internal code should use `devpilot.modeling`.

## Dependency direction

```text
delivery -> service -> runtime -> domain/persistence
                         |-----> modeling contracts
                         |-----> indexing/retrieval
                         `-----> patching/tools
```

- Model adapters never receive direct filesystem or process authority.
- Patch policy does not import model code; every provider follows the same local safety path.
- Checkpoint state contains JSON values rather than ORM objects, so recovery is process-independent.
- External model attempts are committed before network I/O, separately from step checkpoints.

## Where to add common features

- New model vendor: implement `StructuredResponseClient`, then extend `modeling/factory.py`.
- New language parser: register it behind the indexer's language boundary.
- New patch rule: add it to `PatchPolicy` with a focused test in `test_patching.py`.
- New workflow node: extend `RunStep`, add a handler in `AgentRuntime`, and test resume behavior.
- New transport: preserve `JobQueue` lease semantics even if delivery moves to Redis Streams.

Comments in the source explain non-obvious transaction, recovery, and security decisions. Names,
types, and small functions carry routine implementation detail so comments do not drift from code.
