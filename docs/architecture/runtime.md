# Runtime architecture

DevPilot treats a repository task as a durable sequence of control points rather than a single
model call. The first release deliberately uses a deterministic offline provider so runtime
behavior can be tested without network access or repository mutation.

## Durable records

- **Task** stores user intent, budgets, and lifecycle status.
- **Run event** is an append-only explanation of what happened.
- **Checkpoint** stores the minimum state required to resume after the last successful step.
- **Artifact** stores evidence such as repository snapshots, plans, test reports, and reviews.
- **Job** stores durable queue state, attempts, ownership, and lease expiry.
- **Step execution** stores one idempotency key and attempt history boundary per task node.

These records are separate because they have different retention and query needs. A task is
mutable lifecycle state; events are an audit trail; checkpoints are recovery data; artifacts are
user-facing evidence.

## Initial workflow

```text
validate -> inspect repository -> build plan -> propose change
         -> run tests -> review -> finalize
```

Every successful step atomically persists its execution result, checkpoint, artifacts, and event
before the next step starts. A failed run can resume at the step following its newest checkpoint.
Workers claim jobs using compare-and-swap leases, renew ownership after every node, and allow an
expired lease to be reclaimed. A stale worker cannot acknowledge a job after ownership changes.
Side-effecting patch tools are intentionally absent from this milestone; they will be added only
with file policies and rollback.

## Current boundaries

- SQLite is for local development; repository interfaces keep PostgreSQL migration isolated.
- The database queue is the deterministic reference transport; Redis Streams will implement the
  same lease contract for distributed deployments.
- The deterministic provider never edits files.
- Local test commands are opt-in and run without a shell.
