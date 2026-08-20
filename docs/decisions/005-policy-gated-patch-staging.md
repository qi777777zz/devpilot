# ADR 005: Validate and execute patches in disposable workspaces

**Status:** accepted

## Context

An AI Coding provider can return malformed diffs, touch credentials or deployment files, escape
the repository through path traversal, or produce a valid-looking patch that does not apply to the
current revision. Applying such output directly to the working repository makes recovery and audit
claims unreliable.

## Decision

DevPilot accepts only canonical text unified diffs and applies four controls before tests run:

1. Reject protected paths, environment files, secret-key formats, binary patches, renames, path
   traversal, and file types outside an explicit allowlist.
2. Enforce configurable byte and changed-file limits.
3. Copy the repository to a task-specific workspace and require `git apply --check` to pass before
   applying the patch there.
4. Hash every touched source path before and after staging, run checks against the staged copy, and
   delete that copy after success, cancellation, or terminal failure.

Environment files, private-key formats, dependency/build directories, and symbolic links are
omitted from the copy. Patches that introduce symlinks or submodules are rejected.

The patch and its validation report remain durable artifacts, while the workspace is disposable.
Checkpoint recovery recreates the workspace deterministically when it no longer exists.

## Alternatives

- **Edit the source and reverse the patch:** simple, but interruption between write and rollback can
  leave user files dirty.
- **Create a Git branch or worktree:** preserves Git history but assumes a clean Git repository and
  introduces branch/index side effects.
- **Container per step:** stronger process isolation, but heavier and still benefits from the same
  file policy and preflight validation.

## Consequences

The original repository remains unchanged even when patch application fails. The copy has storage
and startup cost, and it is not a security boundary for arbitrary commands. A later execution
backend can place the same disposable workspace inside a restricted container without changing the
runtime or provider contracts.
