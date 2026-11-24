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


def test_staged_helpers(repo):
    assert gw_git.recent_subjects(repo, 5) == []  # no commits yet
    commit_file(repo, "a.txt", "one\n", "Add a")
    commit_file(repo, "b.txt", "two\n", "Add b")
    assert gw_git.recent_subjects(repo, 5) == ["Add b", "Add a"]
    assert gw_git.recent_subjects(repo, 1) == ["Add b"]

    git(repo, "rm", "-q", "a.txt")
    write(repo, "c.txt", "three\n")
    git(repo, "add", "c.txt")
    assert sorted(gw_git.staged_file_names(repo)) == ["a.txt", "c.txt"]
    assert "c.txt" in gw_git.staged_stat(repo)
    assert gw_git.git_dir(repo) == (repo / ".git").resolve()


def test_commit_with_editor_uses_the_draft(repo, monkeypatch):
    monkeypatch.setenv("GIT_EDITOR", "true")  # an editor that changes nothing
    write(repo, "a.txt", "one\n")
    git(repo, "add", "a.txt")
    assert gw_git.commit_with_editor(repo, "Add a file\n\n- first line") == 0
    message = git(repo, "log", "-1", "--format=%B").stdout.strip()
    assert message == "Add a file\n\n- first line"


def test_commit_with_editor_without_draft_aborts_on_empty_message(repo, monkeypatch):
    monkeypatch.setenv("GIT_EDITOR", "true")
    write(repo, "a.txt", "one\n")
    git(repo, "add", "a.txt")
    assert gw_git.commit_with_editor(repo, None) != 0
    assert git(repo, "log", check=False).returncode != 0  # still no commits
