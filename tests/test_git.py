import pytest
from conftest import commit_file, git, write

from gitwarden import git as gw_git
from gitwarden.diff import parse_diff
from gitwarden.errors import GitWardenError


def test_repo_root_and_not_a_repo(repo, tmp_path, monkeypatch):
    assert gw_git.repo_root() == repo.resolve()
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(GitWardenError, match="not inside a git repository"):
        gw_git.repo_root(outside)


def test_git_version_is_new_enough(repo):
    gw_git.check_git_version()


def test_staged_diff_ignores_user_diff_settings(repo):
    git(repo, "config", "diff.noprefix", "true")
    git(repo, "config", "color.ui", "always")
    write(repo, "src/app.py", "x = 1\n")
    git(repo, "add", "src/app.py")
    parsed = parse_diff(gw_git.staged_diff(repo))
    assert [(line.path, line.text) for line in parsed.lines] == [("src/app.py", "x = 1")]


def test_commit_diff_and_range(repo):
    commit_file(repo, "a.txt", "one\n", "first")
    commit_file(repo, "a.txt", "one\ntwo\n", "second")
    shas = gw_git.commits_in_range(repo, "HEAD~1..HEAD")
    assert len(shas) == 1
    parsed = parse_diff(gw_git.commit_diff(repo, shas[0]), commit=shas[0])
    assert [(line.line_no, line.text) for line in parsed.lines] == [(2, "two")]


def test_hooks_dir_respects_core_hooks_path(repo):
    assert gw_git.hooks_dir(repo) == (repo / ".git" / "hooks").resolve()
    git(repo, "config", "core.hooksPath", "team-hooks")
    assert gw_git.hooks_dir(repo) == (repo / "team-hooks").resolve()


def test_user_name_and_commit_exists(repo):
    assert gw_git.user_name(repo) == "Test Dev"
    commit_file(repo, "a.txt", "one\n", "first")
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    assert gw_git.commit_exists(repo, head)
    assert not gw_git.commit_exists(repo, "1" * 40)
