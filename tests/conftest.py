from __future__ import annotations

from pathlib import Path

import pytest

from devpilot.config import Settings
from devpilot.db import Database


@pytest.fixture
def repository_root(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "sample.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Sample repository\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def settings(repository_root: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{repository_root / 'devpilot-test.db'}",
        allowed_repository_root=repository_root,
        enable_local_execution=False,
    )


@pytest.fixture
def database(settings: Settings) -> Database:
    db = Database(settings)
    db.create_schema()
    return db
