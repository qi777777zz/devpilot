from __future__ import annotations

from devpilot.config import Settings
from devpilot.tools import LocalTestRunner, RepositoryInspector


def test_repository_snapshot_is_stable(settings: Settings) -> None:
    inspector = RepositoryInspector(settings)
    first = inspector.inspect(".")
    second = inspector.inspect(".")
    assert first["tree_digest"] == second["tree_digest"]
    assert first["languages"] == {"Python": 1}


def test_repository_digest_changes_with_file_content(settings: Settings) -> None:
    inspector = RepositoryInspector(settings)
    before = inspector.inspect(".")
    sample = settings.allowed_repository_root / "src" / "sample.py"
    sample.write_text("def answer():\n    return 43\n", encoding="utf-8")
    after = inspector.inspect(".")
    assert before["tree_digest"] != after["tree_digest"]


def test_local_test_execution_is_opt_in(settings: Settings) -> None:
    report = LocalTestRunner(settings).run(str(settings.allowed_repository_root))
    assert report["status"] == "skipped"
    assert report["command"] is None
