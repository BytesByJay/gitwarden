"""Shared test helpers: a throw-away git repository for each test."""

import subprocess
from pathlib import Path

import pytest


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run git in `cwd` and return the finished process (text output)."""
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty git repo on branch main, made the current folder.

    The developer's own git settings are ignored (GIT_CONFIG_GLOBAL points to an
    empty file) so tests behave the same on every machine.
    """
    empty_config = tmp_path / "empty-gitconfig"
    empty_config.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")

    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Test Dev")
    git(root, "config", "user.email", "dev@example.com")
    git(root, "config", "commit.gpgsign", "false")
    monkeypatch.chdir(root)
    return root


def write(root: Path, relative_path: str, text: str) -> None:
    """Create or overwrite a file inside the repo."""
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def commit_file(root: Path, relative_path: str, text: str, message: str) -> None:
    """Write a file and commit it, skipping hooks (used to set up history)."""
    write(root, relative_path, text)
    git(root, "add", relative_path)
    git(root, "commit", "-q", "--no-verify", "-m", message)
