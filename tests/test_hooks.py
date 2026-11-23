"""Integration tests: real git repos, real hooks, real `git commit` and `git push`."""

from datetime import date

import pytest
from conftest import commit_file, git, write
from fakes import fake

from gitwarden.allowlist import AllowEntry, add_entry, fingerprint
from gitwarden.config import Config, HooksConfig
from gitwarden.errors import GitWardenError
from gitwarden.hooks import MARKER, hook_script, install_hooks, run_hook, uninstall_hooks

TOKEN = fake("github_token")


@pytest.fixture
def remote(repo, tmp_path):
    """A bare repository added as `origin`, with one clean commit already pushed."""
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    git(repo, "remote", "add", "origin", str(bare))
    commit_file(repo, "README.md", "hello\n", "first")
    git(repo, "push", "-q", "origin", "main")
    return bare


def test_hook_script_uses_forward_slashes_and_marker():
    script = hook_script("pre-commit", "C:\\venv\\Scripts\\python.exe")
    assert script.startswith("#!/bin/sh\n")
    assert MARKER in script
    assert 'GW_PY="C:/venv/Scripts/python.exe"' in script
    assert 'exec "$GW_PY" -m gitwarden hook pre-commit "$@"' in script


def test_install_writes_enabled_hooks_and_uninstall_removes_them(repo):
    written = install_hooks(repo, Config())
    assert [path.name for path in written] == ["pre-commit", "pre-push"]
    only_commit = Config(hooks=HooksConfig(pre_push=False))
    assert [p.name for p in install_hooks(repo, only_commit)] == ["pre-commit"]
    removed = uninstall_hooks(repo)
    assert {path.name for path in removed} == {"pre-commit", "pre-push"}


def test_install_refuses_foreign_hook_unless_forced(repo):
    foreign = repo / ".git" / "hooks" / "pre-commit"
    foreign.write_text("#!/bin/sh\necho mine\n")
    with pytest.raises(GitWardenError, match="was not written by GitWarden"):
        install_hooks(repo, Config())
    assert not (repo / ".git" / "hooks" / "pre-push").exists()  # nothing half-installed
    install_hooks(repo, Config(), force=True)
    assert MARKER in foreign.read_text()
    foreign.write_text("#!/bin/sh\necho mine\n")
    uninstall_hooks(repo)
    assert foreign.exists()  # not ours, so left alone


def test_install_respects_core_hooks_path(repo):
    git(repo, "config", "core.hooksPath", "team-hooks")
    written = install_hooks(repo, Config())
    assert written[0] == (repo / "team-hooks" / "pre-commit").resolve()


def test_commit_with_secret_is_blocked(repo):
    install_hooks(repo, Config())
    write(repo, "ci.sh", f"export GITHUB_TOKEN={TOKEN}\n")
    git(repo, "add", "ci.sh")
    commit = git(repo, "commit", "-m", "add ci", check=False)
    assert commit.returncode != 0
    assert "GitWarden blocked this commit" in commit.stderr
    assert "generic/github-token" in commit.stderr
    assert TOKEN not in commit.stderr


def test_clean_commit_passes(repo):
    install_hooks(repo, Config())
    write(repo, "app.py", "print('hello')\n")
    git(repo, "add", "app.py")
    assert git(repo, "commit", "-m", "clean", check=False).returncode == 0


def test_allowlist_passes_until_expiry(repo):
    write(repo, "tests/t.py", f"TOKEN = {TOKEN}\n")
    git(repo, "add", "tests/t.py")
    entry = AllowEntry(
        fingerprint=fingerprint("generic/github-token", "tests/t.py", TOKEN),
        rule="generic/github-token",
        path="tests/t.py",
        reason="fake token for a test",
        added_by="Test Dev",
        added=date(2026, 11, 1),
        expires=date(2026, 12, 31),
    )
    add_entry(repo, entry)
    assert run_hook("pre-commit", [], "", today=date(2026, 12, 31)) == 0
    assert run_hook("pre-commit", [], "", today=date(2027, 1, 1)) == 1


def test_broken_config_blocks_with_exit_code_2(repo, capsys):
    write(repo, ".gitwarden.toml", "[scan]\nblock_on = 'urgent'\n")
    assert run_hook("pre-commit", [], "") == 2
    assert "GitWarden could not run" in capsys.readouterr().err


def test_push_blocks_secret_added_then_removed_in_history(repo, remote):
    install_hooks(repo, Config())
    commit_file(repo, "ci.sh", f"TOKEN={TOKEN}\n", "add token")  # --no-verify: a bypass
    commit_file(repo, "other.txt", "x\n", "unrelated")
    commit_file(repo, "ci.sh", "TOKEN=$FROM_ENV\n", "remove token")
    push = git(repo, "push", "origin", "main", check=False)
    assert push.returncode != 0
    assert "GitWarden blocked this push" in push.stderr
    assert "generic/github-token" in push.stderr


def test_push_of_new_branch_scans_only_new_commits(repo, remote):
    install_hooks(repo, Config())
    git(repo, "checkout", "-q", "-b", "feature")
    commit_file(repo, "feature.py", "print('new')\n", "feature work")
    push = git(repo, "push", "origin", "feature", check=False)
    assert push.returncode == 0, push.stderr


def test_push_scans_lines_added_while_fixing_a_merge_conflict(repo, remote):
    commit_file(repo, "app.py", "x = 1\n", "base")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "checkout", "-q", "-b", "feature")
    commit_file(repo, "app.py", "x = 2\n", "feature change")
    git(repo, "checkout", "-q", "main")
    commit_file(repo, "app.py", "x = 3\n", "main change")
    merge = git(repo, "merge", "feature", check=False)
    assert merge.returncode != 0  # conflict
    write(repo, "app.py", f"x = 4\nTOKEN = '{TOKEN}'\n")
    git(repo, "add", "app.py")
    git(repo, "commit", "-q", "--no-verify", "-m", "merge feature")

    install_hooks(repo, Config())
    push = git(repo, "push", "origin", "main", check=False)
    assert push.returncode != 0
    assert "generic/github-token" in push.stderr


def test_branch_deletion_push_is_not_scanned(repo, remote):
    git(repo, "push", "-q", "origin", "main:old")
    install_hooks(repo, Config())
    assert git(repo, "push", "origin", "--delete", "old", check=False).returncode == 0


def test_missing_python_gives_reinstall_message(repo):
    install_hooks(repo, Config(), python_path="/nonexistent/python")
    write(repo, "a.txt", "x\n")
    git(repo, "add", "a.txt")
    commit = git(repo, "commit", "-m", "x", check=False)
    assert commit.returncode != 0
    assert "Run 'gitwarden install' again" in commit.stderr
