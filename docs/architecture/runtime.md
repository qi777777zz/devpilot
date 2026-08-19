# Runtime architecture

DevPilot treats a repository task as a durable sequence of control points rather than a single
model call. The first release deliberately uses a deterministic offline provider so runtime
behavior can be tested without network access or repository mutation.

## Durable records

- **Task** stores user intent, budgets, and lifecycle status.
- **Run event** is an append-only explanation of what happened.
- **Checkpoint** stores the minimum state required to resume after the last successful step.
- **Artifact** stores evidence such as repository snapshots, plans, test reports, and reviews.

These records are separate because they have different retention and query needs. A task is
mutable lifecycle state; events are an audit trail; checkpoints are recovery data; artifacts are
user-facing evidence.

## Initial workflow

```text
validate -> inspect repository -> build plan -> propose change
         -> run tests -> review -> finalize
```

Every successful step persists a checkpoint before the next step starts. A failed run can resume
at the step following its newest checkpoint. Side-effecting patch tools are intentionally absent
from this milestone; they will be added only with idempotency keys, file policies, and rollback.

## Current boundaries

- SQLite is for local development; repository interfaces keep PostgreSQL migration isolated.
- Work is executed by an in-process background task; Redis Streams arrives with worker leasing.
- The deterministic provider never edits files.
- Local test commands are opt-in and run without a shell.

