from datetime import date

from conftest import git, write
from fakes import fake

from gitwarden import review
from gitwarden.config import LlmConfig, ScanConfig
from gitwarden.diff import AddedLine, ParsedDiff
from gitwarden.hooks import run_hook
from gitwarden.llm import LlmAnswer
from gitwarden.rules import load_rules
from gitwarden.scanner import scan

TOKEN = fake("github_token")
KEY = fake("aws_access_key_id")


def findings_for(*lines: AddedLine):
    rules = load_rules([], enable=[], disable=[])
    diff = ParsedDiff(lines=list(lines))
    return scan(diff, rules, {}, ScanConfig(), date(2026, 11, 24)).findings


def two_findings():
    return findings_for(
        AddedLine("config/settings.py", 14, f"AWS_KEY = '{KEY}'"),
        AddedLine("tests/test_login.py", 3, f"TOKEN = '{TOKEN}'"),
    )


def fake_ask(monkeypatch, answer: LlmAnswer) -> list[str]:
    """Replace the model with a canned answer; returns the list of prompts it was given."""
    prompts: list[str] = []

    def ask(prompt, settings):
        prompts.append(prompt)
        return answer

    monkeypatch.setattr(review, "ask", ask)
    return prompts


def test_prompt_has_redacted_lines_and_never_the_raw_secret():
    prompt = review.build_review_prompt(two_findings(), "chatml")
    assert "1. rule: generic/aws-access-key-id" in prompt
    assert "file: tests/test_login.py" in prompt
    assert KEY not in prompt
    assert TOKEN not in prompt
    assert prompt.startswith("<|im_start|>system")


def test_parse_keeps_only_well_formed_lines_for_known_numbers():
    answer = (
        "Here you go:\n"
        "1: REAL | production settings file\n"
        "2 : test |  path is under tests/\n"
        "3: test | there is no finding 3\n"
        "1: test | a second answer for 1 is ignored\n"
        "garbage"
    )
    opinions = review.parse_opinions(answer, count=2)
    assert opinions == {
        1: review.Opinion("real", "production settings file"),
        2: review.Opinion("test", "path is under tests/"),
    }


def test_review_prints_opinions(monkeypatch):
    fake_ask(monkeypatch, LlmAnswer("1: real | prod file\n2: test | under tests/", None, 1.0))
    text = review.review_findings(two_findings(), LlmConfig(enabled=True))
    assert text.startswith("Local model's opinion (advisory only, does not change the result):")
    assert "config/settings.py:14  real    - prod file" in text
    assert "tests/test_login.py:3  test    - under tests/" in text


def test_review_failures_print_one_line(monkeypatch):
    fake_ask(monkeypatch, LlmAnswer(None, "timed out after 30 s", 30.0))
    assert review.review_findings(two_findings(), LlmConfig()) == (
        "No model opinion: timed out after 30 s\n"
    )
    fake_ask(monkeypatch, LlmAnswer("I think they are fine", None, 1.0))
    assert review.review_findings(two_findings(), LlmConfig()) == (
        "No model opinion: answer not understood\n"
    )


def test_at_most_five_findings_are_sent(monkeypatch):
    prompts = fake_ask(monkeypatch, LlmAnswer(None, "x", 0.0))
    lines = [AddedLine(f"f{n}.env", 1, f"T={fake('github_token', seed=n)}") for n in range(7)]
    review.review_findings(findings_for(*lines), LlmConfig())
    assert "5. rule:" in prompts[0]
    assert "6. rule:" not in prompts[0]


def stage_secret(repo):
    write(repo, ".gitwarden.toml", "[llm]\nenabled = true\n")
    write(repo, "ci.sh", f"TOKEN={TOKEN}\n")
    git(repo, "add", "ci.sh")


def test_blocked_hook_shows_opinion_and_still_exits_1(repo, monkeypatch, capsys):
    stage_secret(repo)
    fake_ask(monkeypatch, LlmAnswer("1: test | looks fake", None, 1.0))
    assert run_hook("pre-commit", [], "") == 1
    err = capsys.readouterr().err
    assert "GitWarden blocked this commit" in err
    assert "ci.sh:1  test    - looks fake" in err


def test_blocked_hook_with_failing_model_still_exits_1(repo, monkeypatch, capsys):
    stage_secret(repo)
    fake_ask(monkeypatch, LlmAnswer(None, "timed out after 30 s", 30.0))
    assert run_hook("pre-commit", [], "") == 1
    assert "No model opinion: timed out after 30 s" in capsys.readouterr().err


def test_model_is_not_asked_when_off_or_when_nothing_blocks(repo, monkeypatch):
    prompts = fake_ask(monkeypatch, LlmAnswer("1: test | x", None, 1.0))
    write(repo, "ci.sh", f"TOKEN={TOKEN}\n")
    git(repo, "add", "ci.sh")
    assert run_hook("pre-commit", [], "") == 1  # [llm] is off by default
    git(repo, "rm", "-q", "--cached", "ci.sh")
    write(repo, ".gitwarden.toml", "[llm]\nenabled = true\n")
    write(repo, "app.py", "print('hi')\n")
    git(repo, "add", "app.py")
    assert run_hook("pre-commit", [], "") == 0
    assert prompts == []
