from __future__ import annotations

from devpilot.indexing import CodeChunk, PythonTreeSitterParser, RepositoryIndexer
from devpilot.retrieval import HybridCodeRetriever


def test_tree_sitter_extracts_qualified_symbols_and_references() -> None:
    source = b"""
class OrderService:
    def submit_order(self, order):
        return validate_order(order)

def validate_order(order):
    return bool(order)
"""
    symbols = PythonTreeSitterParser().parse("orders/service.py", source)
    by_name = {symbol.qualified_name: symbol for symbol in symbols}
    assert "OrderService" in by_name
    assert "OrderService.submit_order" in by_name
    assert "validate_order" in by_name
    assert by_name["OrderService.submit_order"].references == ["validate_order"]


def test_repository_index_is_reused_for_same_tree(database, settings) -> None:
    from devpilot.tools import RepositoryInspector

    snapshot = RepositoryInspector(settings).inspect(".")
    with database.session_factory() as session:
        indexer = RepositoryIndexer(session)
        first = indexer.index(snapshot)
        session.commit()
        second = indexer.index(snapshot)
        assert [chunk.id for chunk in first] == [chunk.id for chunk in second]


def test_hybrid_retrieval_prioritizes_symbol_and_respects_budget() -> None:
    chunks = [
        make_chunk(
            "submit_order",
            "OrderService.submit_order",
            "orders/service.py",
            "def submit_order(order):\n    return validate_order(order)\n",
            ["validate_order"],
        ),
        make_chunk(
            "render_order",
            "OrderPage.render_order",
            "web/page.py",
            "def render_order(order):\n    return template(order)\n",
            ["template"],
        ),
    ]
    retriever = HybridCodeRetriever(chunks)
    results = retriever.search("change OrderService submit order validation")
    assert results[0].chunk.qualified_name == "OrderService.submit_order"

    context = retriever.build_context("order", token_budget=8)
    assert context["estimated_tokens"] == 8
    assert context["selected_count"] == 1
    assert context["results"][0]["truncated"] is True


def test_named_implementation_symbol_outranks_keyword_heavy_test() -> None:
    implementation = make_chunk(
        "claim",
        "JobQueue.claim",
        "src/devpilot/queue.py",
        "def claim(self, owner):\n    return lease(owner)\n",
        ["lease"],
    )
    test = make_chunk(
        "test_worker_lease_claim_recovery",
        "test_worker_lease_claim_recovery",
        "tests/test_queue.py",
        "worker lease claim recovery job queue worker lease claim",
        ["JobQueue.claim"],
    )
    results = HybridCodeRetriever([test, implementation]).search(
        "Improve JobQueue claim lease recovery"
    )
    assert results[0].chunk.qualified_name == "JobQueue.claim"


def make_chunk(
    name: str,
    qualified_name: str,
    path: str,
    content: str,
    references: list[str],
) -> CodeChunk:
    from devpilot.indexing import tokenize

    return CodeChunk(
        id=qualified_name,
        path=path,
        language="Python",
        name=name,
        qualified_name=qualified_name,
        kind="function",
        start_line=1,
        end_line=2,
        signature=content.splitlines()[0],
        content=content,
        tokens=tokenize(f"{path} {qualified_name} {content}"),
        references=references,
    )
