"""Explainable hybrid code retrieval under a hard context budget."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from devpilot.indexing import CodeChunk, tokenize


@dataclass(frozen=True)
class ScoredChunk:
    chunk: CodeChunk
    score: float
    matched_terms: list[str]


class HybridCodeRetriever:
    def __init__(self, chunks: list[CodeChunk]) -> None:
        self.chunks = chunks
        self.document_frequency = self._document_frequency(chunks)
        self.average_length = (
            sum(len(chunk.tokens) for chunk in chunks) / len(chunks) if chunks else 0.0
        )

    def search(self, query: str, limit: int = 20) -> list[ScoredChunk]:
        query_terms = list(dict.fromkeys(tokenize(query)))
        query_compact = re.sub(r"[^a-z0-9]", "", query.lower())
        asks_for_tests = bool({"test", "tests", "pytest"}.intersection(query_terms))
        scored: list[ScoredChunk] = []
        for chunk in self.chunks:
            counts = Counter(chunk.tokens)
            matched = [term for term in query_terms if counts[term] > 0]
            if not matched:
                continue
            score = sum(self._bm25(term, counts[term], len(chunk.tokens)) for term in matched)
            name_tokens = set(tokenize(chunk.name) + tokenize(chunk.qualified_name))
            score += 1.6 * len(name_tokens.intersection(query_terms))
            path_tokens = set(tokenize(chunk.path))
            score += 0.6 * len(path_tokens.intersection(query_terms))
            reference_tokens = set(tokenize(" ".join(chunk.references)))
            score += 0.35 * len(reference_tokens.intersection(query_terms))
            symbol_parts = re.split(r"[._]", chunk.qualified_name)
            direct_mentions = sum(
                1
                for part in symbol_parts
                if len(re.sub(r"[^a-z0-9]", "", part.lower())) >= 3
                and re.sub(r"[^a-z0-9]", "", part.lower()) in query_compact
            )
            score += 3.0 * direct_mentions
            if not asks_for_tests and chunk.path.startswith(("tests/", "test/")):
                score *= 0.72
            scored.append(ScoredChunk(chunk=chunk, score=score, matched_terms=matched))
        return sorted(scored, key=lambda item: (-item.score, item.chunk.path))[:limit]

    def build_context(
        self,
        query: str,
        *,
        token_budget: int = 3000,
        result_limit: int = 20,
    ) -> dict[str, object]:
        selected: list[dict[str, object]] = []
        used_tokens = 0
        for result in self.search(query, result_limit):
            estimated = max(len(result.chunk.content) // 4, 1)
            remaining = token_budget - used_tokens
            if remaining <= 0:
                break
            content = result.chunk.content
            truncated = estimated > remaining
            if truncated:
                content = content[: remaining * 4]
                estimated = remaining
            selected.append(
                {
                    "path": result.chunk.path,
                    "symbol": result.chunk.qualified_name,
                    "kind": result.chunk.kind,
                    "lines": [result.chunk.start_line, result.chunk.end_line],
                    "score": round(result.score, 4),
                    "matched_terms": result.matched_terms,
                    "references": result.chunk.references[:20],
                    "estimated_tokens": estimated,
                    "truncated": truncated,
                    "content": content,
                }
            )
            used_tokens += estimated
        return {
            "query": query,
            "strategy": "bm25+symbol+path+reference",
            "candidate_count": len(self.chunks),
            "selected_count": len(selected),
            "token_budget": token_budget,
            "estimated_tokens": used_tokens,
            "results": selected,
        }

    def _bm25(self, term: str, frequency: int, document_length: int) -> float:
        documents = len(self.chunks)
        document_frequency = self.document_frequency.get(term, 0)
        inverse_frequency = math.log(
            1 + (documents - document_frequency + 0.5) / (document_frequency + 0.5)
        )
        k1 = 1.5
        b = 0.75
        normalization = 1 - b
        if self.average_length:
            normalization += b * document_length / self.average_length
        return inverse_frequency * (frequency * (k1 + 1)) / (frequency + k1 * normalization)

    @staticmethod
    def _document_frequency(chunks: list[CodeChunk]) -> dict[str, int]:
        frequency: Counter[str] = Counter()
        for chunk in chunks:
            frequency.update(set(chunk.tokens))
        return dict(frequency)
