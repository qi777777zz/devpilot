# DevPilot

DevPilot is a recoverable agent runtime for repository-level software engineering tasks. It turns
an engineering requirement into a durable sequence of repository inspection, planning, change
proposal, testing, review, and reporting steps.

The current milestone is intentionally **offline and non-mutating**. It demonstrates runtime
recovery and traceability without an API key, and it will not edit repository files before tool
permissions, idempotency, sandboxing, and rollback are implemented.

## What works now

- Task API and browser-based run console
- Step-level status transitions and wall-clock/step budgets
- Durable queue with compare-and-swap worker leases and heartbeat renewal
- Idempotent step records with classified retry behavior
- Append-only run trace, durable artifacts, and checkpoints
- Resume from the latest successful checkpoint after a failure
- Repository boundary validation and deterministic metadata snapshots
- Tree-sitter module/class/function indexing with stable content-aware cache keys
- Explainable BM25, symbol, path, and reference retrieval under a context budget
- Offline provider for repeatable planning, proposals, and reviews
- Opt-in, shell-free test execution
- SQLite local persistence behind a repository boundary
- Automated API, recovery, safety, and tool tests
- Docker image and read-only workspace mount

## Run locally

Requires Python 3.12 or newer.

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -e ".[dev]"
devpilot --reload
```

Open <http://127.0.0.1:8000>. API documentation is available at
<http://127.0.0.1:8000/docs>.

On macOS or Linux, activate the environment with `source .venv/bin/activate`.

## Run with Docker

```bash
docker compose up --build
```

The repository is mounted read-only at `/workspace`, local execution remains disabled, and task
state is stored in the `devpilot-data` volume.

## Verify

```bash
ruff check .
pytest --cov=devpilot --cov-report=term-missing
```

## Architecture

```text
HTTP / Run console
        |
        v
Task service -----> tasks + events + checkpoints + artifacts
        |
        v
Agent runtime ----> provider contract
        |
        +----------> repository inspector
        +----------> opt-in test runner
```

Read [the runtime design](docs/architecture/runtime.md) and the
[architecture decisions](docs/decisions/) for boundaries and trade-offs.

## Roadmap

1. Redis Streams transport adapter for the existing lease contract
2. Embedding and pgvector candidate retrieval with measured ablation
3. Patch policy, isolated execution, validation, and rollback
4. Measured single-agent versus multi-agent comparison
5. RepoTaskBench evaluation and expanded failure-injection experiments

Metrics will be published only after they can be reproduced from the evaluation harness.
