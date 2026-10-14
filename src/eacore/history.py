"""Versions of a repository file in git history."""

import subprocess
from pathlib import Path


def _git(path: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=path.parent, check=True, capture_output=True).stdout


def git_versions(path: Path) -> list[tuple[str, str]]:
    """(sha, subject) of every commit that changed ``path``, oldest first."""
    out = _git(path, "log", "--reverse", "--format=%H%x09%s", "--", path.name).decode("utf-8")
    return [tuple(line.split("\t", 1)) for line in out.splitlines() if line]


def extract_version(rev: str, path: Path, dest: Path) -> Path:
    """Write ``path`` as of ``rev`` to ``dest``."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_git(path, "show", f"{rev}:./{path.name}"))
    return dest
