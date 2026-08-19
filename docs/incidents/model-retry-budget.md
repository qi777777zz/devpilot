# Failure experiment: retries bypassed model-call budgets

## Symptom

The runtime already exposed `max_model_calls`, but provider calls were ordinary method invocations.
A transient failure could therefore retry a planning node without any durable count, and a process
restart could forget calls made after the previous checkpoint.

## Root cause

The budget existed only in the task schema. Model attempts were not represented as durable runtime
events, and successful checkpoints were too coarse to account for failed or interrupted requests.
The SDK's own retry default could also create multiple HTTP attempts behind one Runtime call, while
the original 30-second worker lease was shorter than the model timeout.

## Correction

The runtime now writes and commits `model.call.started` before invoking a real provider. The durable
event count is checked against the task budget before every Planner, Implementer, or Reviewer call.
Completion and failure events record sanitized diagnostics; the offline provider bypasses this path
because it performs no external model call.

SDK retries are set to zero so Runtime retry policy remains authoritative. The default worker lease
is 180 seconds, and OpenAI configuration is rejected unless its lease exceeds the request timeout.
Non-retryable provider initialization errors mark the task failed and move its queue job directly
to the dead-letter state instead of leaving a lease active or retrying invalid configuration.

## Verification

`test_model_call_budget_stops_before_third_role` gives a task a budget of two calls. Planner and
Implementer complete, Reviewer is never invoked, and exactly two start/completion pairs remain in
the trace. `test_offline_provider_does_not_consume_model_budget` verifies that an offline run can
complete with a zero-call budget.

## Generalization

Budgets must be charged at the external side-effect boundary, before the attempt begins, and stored
independently of successful workflow checkpoints.
