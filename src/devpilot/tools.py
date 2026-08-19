from __future__ import annotations

import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from devpilot.config import Settings


class ToolExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class RepositoryInspector:
    settings: Settings
    max_files: int = 5000
    sample_limit: int = 40

    def inspect(self, repository_path: str) -> dict[str, Any]:
        root = self._resolve_allowed_path(repository_path)
        files: list[str] = []
        ignored_parts = {".git", ".venv", "node_modules", "dist", "__pycache__", "var"}
        for path in root.rglob("*"):
            if any(part in ignored_parts for part in path.parts):
                continue
            if path.is_file():
                files.append(path.relative_to(root).as_posix())
                if len(files) >= self.max_files:
                    break
        files.sort()
        digest = hashlib.sha256("\n".join(files).encode()).hexdigest()
        languages = self._language_counts(files)
        return {
            "root": str(root),
            "file_count": len(files),
            "truncated": len(files) >= self.max_files,
            "tree_digest": digest,
            "languages": languages,
            "sample_files": files[: self.sample_limit],
        }

    def _resolve_allowed_path(self, repository_path: str) -> Path:
        requested = Path(repository_path)
        if not requested.is_absolute():
            requested = self.settings.allowed_repository_root / requested
        resolved = requested.resolve()
        allowed = self.settings.allowed_repository_root
        if resolved != allowed and allowed not in resolved.parents:
            raise ToolExecutionError(f"Repository path must stay inside {allowed}")
        if not resolved.is_dir():
            raise ToolExecutionError(f"Repository path does not exist: {resolved}")
        return resolved

    @staticmethod
    def _language_counts(files: list[str]) -> dict[str, int]:
        extensions = {
            ".py": "Python",
            ".ts": "TypeScript",
            ".tsx": "TypeScript",
            ".js": "JavaScript",
            ".java": "Java",
            ".go": "Go",
            ".rs": "Rust",
        }
        result: dict[str, int] = {}
        for filename in files:
            language = extensions.get(Path(filename).suffix.lower())
            if language:
                result[language] = result.get(language, 0) + 1
        return result


@dataclass(frozen=True)
class LocalTestRunner:
    settings: Settings

    def run(self, repository_root: str) -> dict[str, Any]:
        if not self.settings.enable_local_execution:
            return {
                "status": "skipped",
                "reason": (
                    "Local execution is disabled. Set "
                    "DEVPILOT_ENABLE_LOCAL_EXECUTION=true to opt in."
                ),
                "command": None,
            }
        root = Path(repository_root).resolve()
        command = [sys.executable, "-m", "pytest", "-q"]
        try:
            result = subprocess.run(
                command,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=self.settings.test_timeout_seconds,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolExecutionError(
                f"Test command exceeded {self.settings.test_timeout_seconds} seconds"
            ) from exc
        return {
            "status": "passed" if result.returncode == 0 else "failed",
            "return_code": result.returncode,
            "command": command,
            "stdout": result.stdout[-8000:],
            "stderr": result.stderr[-8000:],
        }
