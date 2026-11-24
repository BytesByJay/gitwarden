"""Tests with the real local model. Skipped unless both settings below are given (never in CI).

Run on a company laptop to measure real speed and check answer quality:

    GITWARDEN_TEST_LLAMAFILE=~/.gitwarden/llamafile \
    GITWARDEN_TEST_MODEL=~/.gitwarden/qwen2.5-3b-instruct-q4_k_m.gguf \
    .venv/bin/pytest -m model -s
"""

import os
from datetime import date

import pytest
from conftest import commit_file, git, write
from fakes import fake

from gitwarden import git as gw_git
from gitwarden.config import LlmConfig, ScanConfig
from gitwarden.diff import AddedLine, ParsedDiff
from gitwarden.draft import make_draft
from gitwarden.llm import ask
from gitwarden.prompts import CHECK_QUESTION, CHECK_SYSTEM, wrap
from gitwarden.review import build_review_prompt, parse_opinions
from gitwarden.rules import load_rules
from gitwarden.scanner import scan

LLAMAFILE = os.environ.get("GITWARDEN_TEST_LLAMAFILE", "")
MODEL = os.environ.get("GITWARDEN_TEST_MODEL", "")

pytestmark = [
    pytest.mark.model,
    pytest.mark.skipif(
        not (LLAMAFILE and MODEL),
        reason="set GITWARDEN_TEST_LLAMAFILE and GITWARDEN_TEST_MODEL to run",
    ),
]


def real_settings() -> LlmConfig:
    return LlmConfig(
        enabled=True,
        llamafile=LLAMAFILE,
        model=MODEL,
        prompt_format=os.environ.get("GITWARDEN_TEST_FORMAT", "chatml"),
        timeout_seconds=180,
    )


def test_tiny_question_cold_and_warm():
    settings = real_settings()
    prompt = wrap(CHECK_SYSTEM, CHECK_QUESTION, settings.prompt_format)
    first = ask(prompt, settings)
    second = ask(prompt, settings)
    print(f"\nfirst answer: {first.seconds:.1f} s, second answer: {second.seconds:.1f} s")
    assert first.text, first.error
    assert second.text, second.error


def test_draft_has_a_short_first_line(repo):
    commit_file(repo, "app.py", "def greet():\n    return 'hi'\n", "Add greet function")
    write(repo, "app.py", "def greet(name):\n    return f'hi {name}'\n")
    git(repo, "add", "app.py")
    answer = make_draft(repo, gw_git.staged_diff(repo), real_settings())
    print(f"\ndraft in {answer.seconds:.1f} s:\n{answer.text}")
    assert answer.text, answer.error
    assert len(answer.text.splitlines()[0]) <= 72


def test_review_calls_a_fixture_value_a_test_value():
    line = AddedLine(
        "tests/fixtures/fake_users.py", 3, f'FAKE_API_TOKEN = "{fake("github_token")}"'
    )
    rules = load_rules([], enable=[], disable=[])
    findings = scan(ParsedDiff([line]), rules, {}, ScanConfig(), date(2026, 11, 24)).findings
    settings = real_settings()
    answer = ask(build_review_prompt(findings, settings.prompt_format), settings)
    print(f"\nreview in {answer.seconds:.1f} s:\n{answer.text}")
    assert answer.text, answer.error
    assert parse_opinions(answer.text, 1)[1].verdict == "test"
