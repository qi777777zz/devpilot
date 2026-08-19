from __future__ import annotations

from devpilot.evaluation import RetrievalCase, RetrievalEvaluator
from devpilot.indexing import CodeChunk, tokenize


def test_retrieval_metrics_report_hit_rate_and_mrr() -> None:
    chunks = [
        chunk("runtime.py", "AgentRuntime.run", "run task checkpoint runtime"),
        chunk("queue.py", "JobQueue.claim", "claim worker lease queue"),
    ]
    metrics = RetrievalEvaluator(chunks).evaluate(
        [
            RetrievalCase("recover runtime checkpoint", "runtime.py", "AgentRuntime.run"),
            RetrievalCase("worker lease claim", "queue.py", "JobQueue.claim"),
            RetrievalCase("missing payment handler", "payments.py"),
        ]
    )
    assert metrics.cases == 3
    assert metrics.hit_at_1 == 2 / 3
    assert metrics.hit_at_5 == 2 / 3
    assert metrics.mean_reciprocal_rank == 2 / 3


def chunk(path: str, symbol: str, content: str) -> CodeChunk:
    return CodeChunk(
        id=symbol,
        path=path,
        language="Python",
        name=symbol.rsplit(".", 1)[-1],
        qualified_name=symbol,
        kind="function",
        start_line=1,
        end_line=2,
        signature=symbol,
        content=content,
        tokens=tokenize(f"{path} {symbol} {content}"),
        references=[],
    )
