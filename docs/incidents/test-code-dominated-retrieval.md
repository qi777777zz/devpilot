# Failure experiment: test code dominated retrieval

## Symptom

The live query `Improve JobQueue worker lease claim recovery` returned
`test_heartbeat_extends_lease_and_retry_uses_backoff` ahead of `JobQueue.claim`.

## Root cause

The test contained more repetitions of `worker`, `lease`, `claim`, and `recovery`, so BM25 term
evidence outweighed the implementation symbol. The initial symbol boost counted overlapping terms
but did not recognize that the user directly named `JobQueue`.

## Correction

- Direct mentions of qualified symbol components receive stronger evidence.
- Test paths receive a lower prior when the query does not ask for tests or pytest.
- Test chunks remain in the candidate list because they often provide behavioral evidence.

After the change, `JobQueue.claim` ranks first for the live query, followed by `Worker.run_once`.

## Verification

`test_named_implementation_symbol_outranks_keyword_heavy_test` constructs an intentionally
keyword-heavy test chunk and verifies that the explicitly named implementation symbol ranks first.

## Generalization

Retrieval relevance is task-dependent. Documentation search, test discovery, and implementation
editing need different priors even when they share the same candidate index.

