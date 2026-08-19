# ADR 001: Own the execution boundary, reuse infrastructure

**Status:** accepted for the first milestone

## Context

Long-running coding tasks need budgets, explicit tool permissions, checkpoint recovery, and an
audit trail. A framework can accelerate graph construction, but the project also needs to expose
the failure behavior that is being evaluated.

## Decision

DevPilot owns a small execution kernel: step transitions, budgets, checkpoints, events, and tool
contracts. It reuses FastAPI, SQLAlchemy, databases, queues, parsers, and model SDKs.

## Alternatives

- **LangGraph only:** faster graph delivery and mature checkpoint integrations, but the failure
  semantics central to this project would sit behind framework abstractions.
- **Fully custom stack:** offers little learning value in databases, HTTP, or parsing and creates
  avoidable maintenance work.

## Consequences

The runtime requires more tests and careful concurrency design. A small LangGraph comparison will
be implemented later and measured on recovery behavior, integration effort, and trace fidelity.

