"""Unified-diff policy enforcement and disposable workspace management."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import UUID

from devpilot.config import Settings
from devpilot.errors import PatchApplyError, PatchPolicyError

DIFF_HEADER = re.compile(r"^diff --git a/(.+) b/(.+)$")


@dataclass(frozen=True)
class PatchManifest:
    paths: list[str]
    size_bytes: int
    additions: int
    deletions: int


class PatchPolicy:
    """Reject patch shapes that exceed DevPilot's file authority."""

    ALLOWED_SUFFIXES = {
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".java",
        ".go",
        ".rs",
        ".md",
        ".json",
        ".toml",
        ".yaml",
        ".yml",
        ".txt",
    }
    PROTECTED_PREFIXES = (
        ".git/",
        ".github/workflows/",
        "var/",
        ".venv/",
        "node_modules/",
    )
    PROTECTED_NAMES = {
        ".env",
        ".gitignore",
        "dockerfile",
        "compose.yaml",
        "compose.yml",
    }
    PROTECTED_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def validate(self, patch: str) -> PatchManifest:
        encoded = patch.encode("utf-8")
        if not patch.strip():
            raise PatchPolicyError("Patch is empty")
        if len(encoded) > self.settings.patch_max_bytes:
            raise PatchPolicyError(
                f"Patch exceeds {self.settings.patch_max_bytes} byte safety limit"
            )
        if "GIT binary patch" in patch or "Binary files " in patch:
            raise PatchPolicyError("Binary patches are not accepted")
        unsafe_mode = re.compile(
            r"^(?:new file mode|old mode|new mode|deleted file mode) (?:120000|160000)$",
            re.MULTILINE,
        )
        if unsafe_mode.search(patch):
            raise PatchPolicyError("Symlink and submodule patches are not accepted")

        paths: list[str] = []
        for line in patch.splitlines():
            match = DIFF_HEADER.match(line)
            if match is None:
                continue
            old_path, new_path = match.groups()
            if old_path != new_path:
                raise PatchPolicyError("Renames are outside the controlled patch boundary")
            for candidate in {old_path, new_path}:
                self._validate_path(candidate)
            if new_path not in paths:
                paths.append(new_path)
        if not paths:
            raise PatchPolicyError("Patch must contain canonical diff --git headers")
        if len(paths) > self.settings.patch_max_files:
            raise PatchPolicyError(
                f"Patch changes {len(paths)} files; limit is {self.settings.patch_max_files}"
            )
        additions = sum(
            1 for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++")
        )
        deletions = sum(
            1 for line in patch.splitlines() if line.startswith("-") and not line.startswith("---")
        )
        return PatchManifest(
            paths=paths,
            size_bytes=len(encoded),
            additions=additions,
            deletions=deletions,
        )

    def _validate_path(self, value: str) -> None:
        if value.startswith('"') or "\\" in value or ":" in value:
            raise PatchPolicyError("Quoted or backslash paths are not accepted")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or "." in path.parts:
            raise PatchPolicyError(f"Unsafe patch path: {value}")
        normalized = path.as_posix().lower()
        if normalized in self.PROTECTED_NAMES or normalized.startswith(".env."):
            raise PatchPolicyError(f"Protected file cannot be changed: {value}")
        if normalized.startswith(self.PROTECTED_PREFIXES):
            raise PatchPolicyError(f"Protected path cannot be changed: {value}")
        if path.suffix.lower() in self.PROTECTED_SUFFIXES:
            raise PatchPolicyError(f"Sensitive file type cannot be changed: {value}")
        if path.suffix.lower() not in self.ALLOWED_SUFFIXES:
            raise PatchPolicyError(f"File type is outside the patch allowlist: {value}")


class WorkspaceManager:
    """Apply approved text patches to task-scoped repository copies."""

    IGNORED_NAMES = {".git", ".venv", "node_modules", "var", "__pycache__", "dist"}

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.storage_root = settings.workspace_storage_root
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.policy = PatchPolicy(settings)

    def apply(self, task_id: UUID, source_root: str, patch: str) -> dict[str, object]:
        manifest = self.policy.validate(patch)
        source = Path(source_root).resolve()
        target = self.path_for(task_id)
        self.cleanup(task_id)
        self._validate_storage_location(source)
        shutil.copytree(source, target, ignore=self._ignore)
        try:
            before = self._digest_paths(source, manifest.paths)
            self._git_apply(target, patch, check_only=True)
            self._git_apply(target, patch, check_only=False)
            source_after = self._digest_paths(source, manifest.paths)
            if source_after != before:
                raise PatchApplyError("Source repository changed during staged patch application")
            staged_after = self._digest_paths(target, manifest.paths)
        except Exception:
            self.cleanup(task_id)
            raise
        return {
            "status": "applied_to_staging",
            "workspace_root": str(target),
            "paths": manifest.paths,
            "size_bytes": manifest.size_bytes,
            "additions": manifest.additions,
            "deletions": manifest.deletions,
            "source_digest": before,
            "staged_digest": staged_after,
            "source_unchanged": True,
        }

    def cleanup(self, task_id: UUID) -> None:
        target = self.path_for(task_id)
        if target.exists():
            resolved = target.resolve()
            if resolved.parent != self.storage_root.resolve():
                raise PatchApplyError(f"Refusing to clean unexpected workspace: {resolved}")
            shutil.rmtree(resolved)

    def path_for(self, task_id: UUID) -> Path:
        return self.storage_root / str(task_id)

    @classmethod
    def _ignore(cls, directory: str, names: list[str]) -> set[str]:
        ignored = set(names).intersection(cls.IGNORED_NAMES)
        for name in names:
            lowered = name.lower()
            candidate = Path(directory) / name
            if (
                lowered == ".env"
                or lowered.startswith(".env.")
                or Path(lowered).suffix in PatchPolicy.PROTECTED_SUFFIXES
                or candidate.is_symlink()
            ):
                ignored.add(name)
        return ignored

    def _validate_storage_location(self, source: Path) -> None:
        storage = self.storage_root.resolve()
        if storage == source:
            raise PatchApplyError("Workspace storage cannot be the source repository")
        if source in storage.parents:
            first_part = storage.relative_to(source).parts[0]
            if first_part not in self.IGNORED_NAMES:
                raise PatchApplyError(
                    "Workspace storage inside a repository must use an ignored directory"
                )

    @staticmethod
    def _digest_paths(root: Path, paths: list[str]) -> str:
        digest = hashlib.sha256()
        for relative_path in sorted(paths):
            digest.update(relative_path.encode())
            path = root / relative_path
            digest.update(path.read_bytes() if path.is_file() else b"<missing>")
        return digest.hexdigest()

    @staticmethod
    def _git_apply(root: Path, patch: str, *, check_only: bool) -> None:
        git = shutil.which("git")
        if git is None:
            raise PatchApplyError("git executable is required to validate unified patches")
        command = [git, "apply", "--whitespace=nowarn"]
        if check_only:
            command.append("--check")
        try:
            result = subprocess.run(
                command,
                cwd=root,
                input=patch,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PatchApplyError("Patch validation timed out") from exc
        if result.returncode != 0:
            action = "validation" if check_only else "application"
            raise PatchApplyError(f"Patch {action} failed: {result.stderr.strip()}")
