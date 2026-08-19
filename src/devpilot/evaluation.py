from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from devpilot.indexing import CodeChunk
from devpilot.retrieval import HybridCodeRetriever, ScoredChunk


@dataclass(frozen=True)
class RetrievalCase:
    query: str
    expected_path: str
    expected_symbol: str | None = None


@dataclass(frozen=True)
class RetrievalMetrics:
    cases: int
    hit_at_1: float
    hit_at_5: float
    mean_reciprocal_rank: float


class RetrievalEvaluator:
    def __init__(self, chunks: list[CodeChunk]) -> None:
        self.retriever = HybridCodeRetriever(chunks)

    def evaluate(self, cases: list[RetrievalCase]) -> RetrievalMetrics:
        ranks = [self._rank(case, self.retriever.search(case.query, limit=20)) for case in cases]
        if not ranks:
            return RetrievalMetrics(0, 0.0, 0.0, 0.0)
        return RetrievalMetrics(
            cases=len(ranks),
            hit_at_1=mean(1.0 if rank == 1 else 0.0 for rank in ranks),
            hit_at_5=mean(1.0 if 0 < rank <= 5 else 0.0 for rank in ranks),
            mean_reciprocal_rank=mean(1 / rank if rank else 0.0 for rank in ranks),
        )

    @staticmethod
    def _rank(case: RetrievalCase, results: list[ScoredChunk]) -> int:
        for rank, result in enumerate(results, start=1):
            path_matches = result.chunk.path == case.expected_path
            symbol_matches = (
                case.expected_symbol is None or result.chunk.qualified_name == case.expected_symbol
            )
            if path_matches and symbol_matches:
                return rank
        return 0
