# DevPilot

DevPilot is a recoverable agent runtime for repository-level software engineering tasks. It turns
an engineering requirement into a durable sequence of repository inspection, planning, change
proposal, testing, review, and reporting steps.

The bundled provider is intentionally offline and proposes no edits, so the project runs without
an API key. Providers that return a unified diff enter a policy-gated staging workflow: DevPilot
copies the repository, applies and tests the patch there, verifies that the source repository did
not change, and removes the staging workspace after the run.

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
- Unified-diff parsing with path, file type, size, and file-count safety policies
- Isolated patch staging with preflight validation and source-integrity verification
- Automatic staging cleanup after success, cancellation, and terminal failure
- Offline provider for repeatable planning, proposals, and reviews
- Optional OpenAI Responses provider with strict Pydantic outputs
- Role-separated Planner, Implementer, and independent Reviewer prompts
- Durable model-call budgets with latency, request ID, and token telemetry
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

The default provider is deterministic and makes no network calls. To opt into the structured
OpenAI provider, set the following values in `.env`:

```dotenv
DEVPILOT_MODEL_PROVIDER=openai
DEVPILOT_OPENAI_API_KEY=your-api-key
DEVPILOT_OPENAI_MODEL=gpt-5.6
```

The key is read from the environment and is never stored in task events or artifacts. Structured
model output still passes through the local patch policy; enabling a provider does not grant direct
filesystem or command access.

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
Agent runtime ----> provider contract -> Planner / Implementer / Reviewer
        |
        +----------> repository inspector
        +----------> patch policy -> isolated workspace
        +----------> opt-in test runner
```

Read [the runtime design](docs/architecture/runtime.md) and the
[architecture decisions](docs/decisions/) for boundaries and trade-offs.

## Roadmap

1. Redis Streams transport adapter for the existing lease contract
2. Embedding and pgvector candidate retrieval with measured ablation
3. Container-level resource isolation for untrusted test commands
4. Measured one-pass versus reviewer-guided revision comparison
5. RepoTaskBench evaluation and expanded failure-injection experiments

Metrics will be published only after they can be reproduced from the evaluation harness.
