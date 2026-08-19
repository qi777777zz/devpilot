# ADR 003: Define queue semantics before selecting the distributed transport

**Status:** accepted

## Context

An API background callback loses queued work when the process exits. A message broker improves
delivery, but it does not define application-level ownership, duplicate side-effect behavior, or
the point at which work is safe to acknowledge.

## Decision

DevPilot first implements a database-backed reference queue with compare-and-swap leases. A job
records its owner, expiry, heartbeat, attempts, retry availability, and terminal state. A worker
renews the lease after each durable runtime node. Step executions use stable idempotency keys so a
reclaimed job resumes after the newest committed checkpoint rather than repeating completed work.

Redis Streams will be an adapter for this contract, not the source of its semantics.

## Alternatives

- **API background tasks:** minimal setup but queued work is not durable.
- **Celery immediately:** productive for standard tasks, but retry and acknowledgement defaults can
  obscure the failure model this project needs to demonstrate.
- **Redis Streams immediately:** consumer groups provide delivery primitives, but tests would need
  an external service before ownership rules are stable.

## Consequences

The reference queue works in unit tests without infrastructure and exposes lease races directly.
SQLite remains development-only; PostgreSQL will use row locking for higher concurrency. Redis
Streams deployments still retain database step idempotency because message delivery is at least
once.

