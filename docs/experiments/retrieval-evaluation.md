# Retrieval evaluation protocol

## Metrics

- **Hit@1:** expected symbol is the first result.
- **Hit@5:** expected symbol appears in the first five results.
- **MRR:** mean reciprocal rank of the expected symbol.
- **Context tokens:** estimated prompt budget consumed by selected chunks.

## Candidate strategies

1. lexical terms only
2. BM25
3. BM25 + symbol and path evidence
4. BM25 + symbol, path, reference, and task-specific priors
5. the preceding strategy plus embedding candidates (planned)

## Data split

Repository tasks will be divided into development and holdout cases. A retrieval change is kept
only when it improves the development set without reducing holdout Hit@5. The expected path and
symbol must be recorded before running the candidate strategy.

## Current status

The evaluator and deterministic fixture cases are implemented. Live smoke testing over DevPilot
correctly ranks `JobQueue.claim` first for a lease-recovery requirement and selects context under a
3,000-token budget. These smoke observations are not presented as benchmark metrics; the larger
holdout set is still pending.
