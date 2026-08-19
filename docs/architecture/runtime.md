# Runtime architecture

DevPilot treats a repository task as a durable sequence of control points rather than a single
model call. The first release deliberately uses a deterministic offline provider so runtime
behavior can be tested without network access. A provider-supplied patch is never applied to the
source repository; it is validated and executed in a disposable staging workspace.

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
validate -> inspect repository -> retrieve context -> build plan -> propose change
         -> validate and stage patch -> run tests -> review -> finalize and clean
```

Every successful step atomically persists its execution result, checkpoint, artifacts, and event
before the next step starts. A failed run can resume at the step following its newest checkpoint.
Workers claim jobs using compare-and-swap leases, renew ownership after every node, and allow an
expired lease to be reclaimed. A stale worker cannot acknowledge a job after ownership changes.
Patch application is bounded by an allowlist policy. Canonical unified diffs are checked for
protected paths, traversal, binary content, file types, byte size, and changed-file count before a
repository copy is created. `git apply --check` runs before application. Tests target the staged
copy, the source digest is verified, and the staged copy is deleted after completion, cancellation,
or a terminal failure. A resumed run reconstructs a missing staged copy from its checkpointed patch.

## Current boundaries

- SQLite is for local development; repository interfaces keep PostgreSQL migration isolated.
- The database queue is the deterministic reference transport; Redis Streams will implement the
  same lease contract for distributed deployments.
- The deterministic provider never edits files.
- Local test commands are opt-in and run without a shell.
- The staging workspace is not a hardened process sandbox; container-level CPU, memory, network,
  and syscall isolation remains required before running untrusted commands.
