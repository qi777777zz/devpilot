# ADR 002: Start with a deterministic, non-mutating provider

**Status:** accepted

## Context

Connecting a model and patch tool before defining permissions makes early demos impressive but
unsafe and difficult to test. Runtime defects become confused with model variance.

## Decision

The first provider produces deterministic plans, dry-run proposals, and reviews. Repository test
execution is disabled unless explicitly enabled. Patch mutation will be introduced after file
policies, idempotency records, sandboxing, and rollback tests exist.

## Consequences

The first milestone demonstrates reliability rather than autonomous editing. It gives subsequent
model providers a stable contract and makes CI independent of external API keys.

