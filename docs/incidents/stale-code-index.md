# Failure experiment: stale code index

## Scenario

A file changes without being renamed. If the repository digest only contains file paths, the
index cache key remains unchanged and retrieval serves symbols from the previous file contents.

## Root cause

The first repository snapshot hashed the sorted path list. That detects additions and deletions,
but not content-only edits.

## Correction

The snapshot now hashes every indexed path together with its SHA-256 content digest. Index reuse
requires both the repository root and the full tree digest to match.

## Verification

`test_repository_digest_changes_with_file_content` edits a function body without renaming the
file and asserts that the tree digest changes. `test_repository_index_is_reused_for_same_tree`
proves that an unchanged tree still reuses stable symbol identifiers.

## Generalization

Cache keys must represent the data that affects the cached result. The same principle applies to
build caches, prompt caches, derived datasets, and model-evaluation artifacts.
