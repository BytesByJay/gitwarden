import pytest
from conftest import commit_file, git, write
from fakes import fake

from gitwarden import draft
from gitwarden.config import LlmConfig
from gitwarden.llm import LlmAnswer
from gitwarden.prompts import COMMIT_SYSTEM

DIFF = """\
diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@ -1 +1,2 @@
-print('hi')
+print('hello')
+print('bye')
diff --git a/notes.txt b/notes.txt
new file mode 100644
--- /dev/null
+++ b/notes.txt
@@ -0,0 +1 @@
+first note
"""


def test_changed_lines_are_grouped_by_file():
    assert draft.changed_lines_by_file(DIFF) == {
        "app.py": ["-print('hi')", "+print('hello')", "+print('bye')"],
        "notes.txt": ["+first note"],
    }


def test_summary_has_subjects_stat_and_lines():
    summary = draft.build_summary(" app.py | 3 ++-\n", DIFF, ["Add login", "Fix typo"])
    assert summary.startswith("Recent commit messages in this repository")
    assert "- Add login" in summary
    assert "app.py | 3 ++-" in summary
    assert "=== app.py\n-print('hi')\n+print('hello')" in summary


def test_summary_limits_lines_per_file_and_total_size():
    many = "\n".join(f"+line {n}" for n in range(100))
    diff = f"diff --git a/big.py b/big.py\n--- a/big.py\n+++ b/big.py\n@@ -0,0 +1,100 @@\n{many}\n"
    summary = draft.build_summary("", diff, [])
    assert "+line 39" in summary
    assert "+line 40" not in summary
    assert "... (60 more lines)" in summary

    huge = "\n".join(f"+{'x' * 70} {n}" for n in range(40))
    files = "".join(
        f"diff --git a/f{n}.py b/f{n}.py\n--- a/f{n}.py\n+++ b/f{n}.py\n@@ -0,0 +1,40 @@\n{huge}\n"
        for n in range(5)
    )
    summary = draft.build_summary("", files, [])
    assert summary.endswith("\n... (cut to keep it short)")
    assert len(summary) <= draft.MAX_SUMMARY_CHARS + len("\n... (cut to keep it short)")


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("Add login\n\n- check password", "Add login\n\n- check password"),
        ("```\nAdd login\n```", "Add login"),
        ("Commit message: Add login", "Add login"),
        ("Commit message:\nAdd login\n\n- detail", "Add login\n\n- detail"),
        ('"Add login"', "Add login"),
        ("```text\n```", ""),
    ],
)
def test_clean_message(answer, expected):
    assert draft.clean_message(answer) == expected


def fake_ask(monkeypatch, module, answer: LlmAnswer) -> list[str]:
    prompts: list[str] = []

    def ask(prompt, settings):
        prompts.append(prompt)
        return answer

    monkeypatch.setattr(module, "ask", ask)
    return prompts


def test_make_draft_sends_the_summary_and_cleans_the_answer(repo, monkeypatch):
    commit_file(repo, "a.txt", "one\n", "Add a")
    write(repo, "a.txt", "one\ntwo\n")
    git(repo, "add", "a.txt")
    prompts = fake_ask(monkeypatch, draft, LlmAnswer("```\nExtend a\n```", None, 2.0))
    answer = draft.make_draft(repo, "diff text here", LlmConfig(enabled=True))
    assert answer.text == "Extend a"
    assert COMMIT_SYSTEM in prompts[0]
    assert "- Add a" in prompts[0]
    assert "a.txt" in prompts[0]

    fake_ask(monkeypatch, draft, LlmAnswer("```\n```", None, 2.0))
    empty = draft.make_draft(repo, "", LlmConfig(enabled=True))
    assert (empty.text, empty.error) == (None, "the model gave an empty answer")


@pytest.fixture
def ai_repo(repo, monkeypatch):
    """A repo with [llm] switched on and an editor that accepts whatever it is given."""
    monkeypatch.setenv("GIT_EDITOR", "true")
    commit_file(repo, ".gitwarden.toml", "[llm]\nenabled = true\n", "Add config")
    return repo


def last_message(repo) -> str:
    return git(repo, "log", "-1", "--format=%B").stdout.strip()


def test_commit_uses_the_draft(ai_repo, monkeypatch):
    fake_ask(monkeypatch, draft, LlmAnswer("Add hello script\n\n- prints hello", None, 3.0))
    write(ai_repo, "hello.py", "print('hello')\n")
    git(ai_repo, "add", "hello.py")
    assert draft.run_commit(ai_repo) == 0
    assert last_message(ai_repo) == "Add hello script\n\n- prints hello"


def test_commit_without_a_draft_opens_an_empty_editor(ai_repo, monkeypatch, capsys):
    fake_ask(monkeypatch, draft, LlmAnswer(None, "timed out after 30 s", 30.0))
    write(ai_repo, "hello.py", "print('hello')\n")
    git(ai_repo, "add", "hello.py")
    assert draft.run_commit(ai_repo) != 0  # empty message: git aborts, as always
    assert "couldn't draft a message (timed out after 30 s)" in capsys.readouterr().err
    assert last_message(ai_repo) == "Add config"


def test_commit_with_ai_off_does_not_ask(repo, monkeypatch, capsys):
    monkeypatch.setenv("GIT_EDITOR", "true")
    prompts = fake_ask(monkeypatch, draft, LlmAnswer("x", None, 1.0))
    write(repo, "hello.py", "print('hello')\n")
    git(repo, "add", "hello.py")
    assert draft.run_commit(repo) != 0
    assert "AI drafting is off" in capsys.readouterr().err
    assert prompts == []


def test_nothing_staged(ai_repo, capsys):
    assert draft.run_commit(ai_repo) == 1
    assert "Nothing is staged" in capsys.readouterr().err


def test_staged_secret_stops_before_drafting(ai_repo, monkeypatch):
    from gitwarden import review

    draft_prompts = fake_ask(monkeypatch, draft, LlmAnswer("x", None, 1.0))
    fake_ask(monkeypatch, review, LlmAnswer("1: real | token", None, 1.0))
    write(ai_repo, "ci.sh", f"TOKEN={fake('github_token')}\n")
    git(ai_repo, "add", "ci.sh")
    assert draft.run_commit(ai_repo) == 1
    assert draft_prompts == []
    assert last_message(ai_repo) == "Add config"
