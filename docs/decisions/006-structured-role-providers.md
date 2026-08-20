# ADR 006: Use structured, role-separated model providers

**Status:** accepted

## Context

A single free-form model response mixes planning, implementation, and approval. It is difficult to
validate, encourages self-approval, and makes retries hard to audit. Giving a remote model direct
filesystem tools would also bypass DevPilot's deterministic patch policy.

The OpenAI Responses API supports parsing model output directly into a Pydantic model through
`client.responses.parse(..., text_format=Model)`. See the
[official Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs).

## Decision

DevPilot keeps one provider contract with three role-specific operations:

- **Planner** receives the requirement, repository summary, and retrieved code context.
- **Implementer** additionally receives the plan and returns a canonical unified diff or no change.
- **Reviewer** receives the proposal, patch-policy result, and test evidence, but does not inherit
  another role's instructions.

Each operation has an `extra="forbid"` Pydantic output model. The model never receives direct file
or command tools. Its diff enters the same local policy, isolated workspace, and test stages used
by any other provider.

Every external attempt is persisted as sanitized start/completion/failure events. Attempts consume
the task's `max_model_calls` budget across step retries and checkpoint recovery. Completion events
may contain latency, response ID, and token counts, but never the API key or complete prompts.
SDK-level retries are disabled so the Runtime remains the only retry authority. Configuration also
requires the worker lease to exceed a single model-request timeout.

## Alternatives

- **One agent and one JSON blob:** fewer calls, but no independent review boundary.
- **Free-form Markdown parsing:** portable, but ambiguous and harder to validate safely.
- **Model-controlled tool loop:** flexible, but expands the authority and injection surface before
  the underlying sandbox is hardened.

## Consequences

Offline execution remains the default and existing tests need no API key. Real model execution is
explicitly enabled through environment configuration. Role separation adds latency and model cost,
so budgets are enforced before each attempt and future experiments must compare the quality gain.
