# Failure experiment: expired worker lease

## Scenario

Worker A claims a task and then stops making progress before acknowledging it. After the lease
expires, Worker B reclaims the same job. Worker A later wakes up and attempts to mark the job done.

## Risk

Without an ownership check, both workers can report success or repeat external side effects.

## Strategy

1. Claim with a conditional update over the current state and lease expiry.
2. Attach the worker identity to every heartbeat and terminal update.
3. Reject completion when the stored owner differs from the caller.
4. Keep step idempotency in the database so Worker B skips committed nodes.
5. Add file mutation tools only after their own idempotency and rollback policy exists.

## Verification

`test_expired_lease_is_reclaimed_without_double_completion` advances an injected clock, lets a
second worker reclaim the job, and proves that the stale worker receives `LeaseLostError`.

## Reuse

The same fencing pattern applies to scheduled jobs, payment processors, media pipelines, and any
at-least-once queue consumer with external side effects.
