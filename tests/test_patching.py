from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from devpilot.config import Settings
from devpilot.db import Database
from devpilot.domain import TaskCreate
from devpilot.errors import PatchApplyError, PatchPolicyError
from devpilot.indexing import RepositoryIndexer
from devpilot.patching import PatchPolicy, WorkspaceManager
from devpilot.providers import AgentContext, DeterministicProvider
from devpilot.repository import TaskRepository
from devpilot.runtime import AgentRuntime
from devpilot.tools import LocalTestRunner, RepositoryInspector

VALID_PATCH = """diff --git a/src/sample.py b/src/sample.py
--- a/src/sample.py
+++ b/src/sample.py
@@ -1,2 +1,2 @@
 def answer():
-    return 42
+    return 43
"""


class PatchProvider(DeterministicProvider):
    name = "test-patch-provider"

    def propose_change(self, context: AgentContext) -> dict[str, object]:
        return {
            "provider": self.name,
            "mode": "controlled_patch",
            "summary": "Change the sample answer in an isolated workspace.",
            "patch": VALID_PATCH,
        }


class FailingReviewPatchProvider(PatchProvider):
    def review(self, context: AgentContext) -> dict[str, object]:
        raise RuntimeError("injected review failure")


def test_applies_patch_only_to_isolated_workspace(
    settings: Settings, repository_root: Path
) -> None:
    manager = WorkspaceManager(settings)
    task_id = uuid4()

    report = manager.apply(task_id, str(repository_root), VALID_PATCH)

    staged_file = manager.path_for(task_id) / "src" / "sample.py"
    assert "return 43" in staged_file.read_text(encoding="utf-8")
    assert "return 42" in (repository_root / "src" / "sample.py").read_text(encoding="utf-8")
    assert report["source_unchanged"] is True
    assert report["paths"] == ["src/sample.py"]

    manager.cleanup(task_id)
    assert not manager.path_for(task_id).exists()


@pytest.mark.parametrize(
    ("path", "message"),
    [
        (".env", "Protected file"),
        (".env.local", "Protected file"),
        (".github/workflows/release.yml", "Protected path"),
        ("../outside.py", "Unsafe patch path"),
        ("secrets.pem", "Sensitive file type"),
        ("image.png", "outside the patch allowlist"),
    ],
)
def test_policy_rejects_unsafe_paths(settings: Settings, path: str, message: str) -> None:
    patch = f"diff --git a/{path} b/{path}\n"
    with pytest.raises(PatchPolicyError, match=message):
        PatchPolicy(settings).validate(patch)


def test_policy_rejects_renames_and_binary_patches(settings: Settings) -> None:
    with pytest.raises(PatchPolicyError, match="Renames"):
        PatchPolicy(settings).validate("diff --git a/src/old.py b/src/new.py\n")
    with pytest.raises(PatchPolicyError, match="Binary"):
        PatchPolicy(settings).validate("diff --git a/src/data.py b/src/data.py\nGIT binary patch\n")
    with pytest.raises(PatchPolicyError, match="Symlink"):
        PatchPolicy(settings).validate(
            "diff --git a/src/link.py b/src/link.py\nnew file mode 120000\n"
        )


def test_policy_enforces_file_count_limit(settings: Settings) -> None:
    strict = settings.model_copy(update={"patch_max_files": 1})
    patch = "diff --git a/src/one.py b/src/one.py\ndiff --git a/src/two.py b/src/two.py\n"
    with pytest.raises(PatchPolicyError, match="limit is 1"):
        PatchPolicy(strict).validate(patch)


def test_failed_patch_application_removes_workspace(
    settings: Settings, repository_root: Path
) -> None:
    task_id = uuid4()
    manager = WorkspaceManager(settings)
    invalid_context = VALID_PATCH.replace("return 42", "return 999")

    with pytest.raises(PatchApplyError, match="validation failed"):
        manager.apply(task_id, str(repository_root), invalid_context)

    assert not manager.path_for(task_id).exists()
    assert "return 42" in (repository_root / "src" / "sample.py").read_text(encoding="utf-8")


def test_workspace_copy_omits_credentials(settings: Settings, repository_root: Path) -> None:
    (repository_root / ".env.local").write_text("TOKEN=secret\n", encoding="utf-8")
    (repository_root / "private.pem").write_text("secret\n", encoding="utf-8")
    manager = WorkspaceManager(settings)
    task_id = uuid4()

    manager.apply(task_id, str(repository_root), VALID_PATCH)

    assert not (manager.path_for(task_id) / ".env.local").exists()
    assert not (manager.path_for(task_id) / "private.pem").exists()
    manager.cleanup(task_id)


def test_runtime_validates_patch_and_cleans_workspace(
    database: Database, settings: Settings, repository_root: Path
) -> None:
    session = database.session_factory()
    tasks = TaskRepository(session)
    manager = WorkspaceManager(settings)
    runtime = AgentRuntime(
        session,
        PatchProvider(),
        RepositoryInspector(settings),
        LocalTestRunner(settings),
        RepositoryIndexer(session),
        manager,
        settings.context_token_budget,
    )
    task = tasks.create(
        TaskCreate(
            title="Verify a controlled patch",
            requirement="Change the sample answer through a policy-gated isolated workspace.",
            repository_path=".",
        )
    )

    runtime.run(task.id)

    completed = tasks.get_detail(task.id)
    patch_artifact = next(
        artifact for artifact in completed.artifacts if artifact.kind.value == "patch_validation"
    )
    final_artifact = completed.artifacts[-1]
    assert completed.status.value == "completed"
    assert patch_artifact.content["status"] == "applied_to_staging"
    assert final_artifact.content["outcome"] == "staged_patch_verified"
    assert final_artifact.content["workspace_cleaned"] is True
    assert not manager.path_for(task.id).exists()
    assert "return 42" in (repository_root / "src" / "sample.py").read_text(encoding="utf-8")


def test_runtime_failure_cleans_applied_workspace(
    database: Database, settings: Settings, repository_root: Path
) -> None:
    session = database.session_factory()
    tasks = TaskRepository(session)
    manager = WorkspaceManager(settings)
    runtime = AgentRuntime(
        session,
        FailingReviewPatchProvider(),
        RepositoryInspector(settings),
        LocalTestRunner(settings),
        RepositoryIndexer(session),
        manager,
        settings.context_token_budget,
    )
    task = tasks.create(
        TaskCreate(
            title="Clean a failed staged run",
            requirement="Apply a safe staged patch and clean it after an injected review failure.",
            repository_path=".",
        )
    )

    with pytest.raises(RuntimeError, match="injected review failure"):
        runtime.run(task.id)

    assert tasks.get(task.id).status.value == "failed"
    assert not manager.path_for(task.id).exists()
    assert "return 42" in (repository_root / "src" / "sample.py").read_text(encoding="utf-8")
