# Failure experiment: stale patch context left a staging directory

## Symptom

A unified diff passed path policy checks but `git apply --check` rejected it because the expected
source line was no longer present. The first implementation had already copied the repository and
left that staging directory behind when validation raised an exception.

## Root cause

Cleanup was attached to successful finalization. Patch preflight was correctly ordered before
application, but failure cleanup did not cover exceptions raised between repository copy and the
final runtime node.

## Correction

Workspace creation and both Git operations now share one exception boundary. Any validation or
application error removes the task workspace before propagating the failure. Runtime cancellation
and non-retryable failures also invoke idempotent cleanup.

## Verification

`test_failed_patch_application_removes_workspace` supplies a diff with stale context, asserts that
preflight fails, verifies that the task workspace is gone, and confirms that the source file still
contains its original value.

## Generalization

Temporary state needs failure semantics at the narrowest operation that creates it. Relying only on
workflow-level finalizers leaks resources when a step fails before the workflow can advance.
