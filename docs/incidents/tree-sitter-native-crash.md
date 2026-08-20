# Incident: Tree-sitter 0.26 access violation on Windows

## Symptom

The API process exited without a Python exception while indexing `runtime.py`. The last durable
event was `step.started` for `retrieve_context`; the task and lease remained active until expiry.
Running the indexer with Python faulthandler reproduced a Windows access violation while iterating
`Node.children` in the native binding.

## Investigation

Small parser tests passed, but walking the larger runtime syntax tree consistently crashed. The
environment had `tree-sitter==0.26.0` with `tree-sitter-python==0.25.0`. The official py-tree-sitter
release line documents 0.25.1, and the project issue tracker contains open native crash reports.

## Correction

The runtime binding is constrained to `>=0.25.1,<0.26` while the Python grammar remains on 0.25.
The full repository indexing smoke test is rerun after installation, not only the small fixture
test.

## Architectural consequence

Native parser failure can terminate the worker before application cleanup runs. Durable leases
and checkpoints allow another worker to reclaim the task, but repeated deterministic crashes need
a dead-letter policy. Parser execution will move behind a process boundary before untrusted
repositories are accepted.

## Generalization

Compatibility tests must exercise realistic input sizes and supported version pairs. Unit tests
over tiny syntax trees are insufficient for native extensions, database drivers, image codecs,
and other libraries that can fail outside Python's exception model.
