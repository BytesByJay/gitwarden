"""`gitwarden commit`: draft a commit message with the local model, then commit.

The summary sent to the model is kept short on purpose: on a laptop without a
GPU, reading the prompt is the slow part, so a capped summary keeps the wait
around 10 seconds.
"""

import sys
from pathlib import Path

from gitwarden import git
from gitwarden.config import LlmConfig, load_config
from gitwarden.diff import parse_diff
from gitwarden.hooks import scan_and_report
from gitwarden.llm import LlmAnswer, ask
from gitwarden.prompts import COMMIT_SYSTEM, wrap

MAX_LINES_PER_FILE = 40
MAX_SUMMARY_CHARS = 3000
RECENT_COMMITS = 5


def run_commit(root: Path) -> int:
    """Check for secrets, draft a message, open the editor, commit. Returns the exit code."""
    if not git.staged_file_names(root):
        print("Nothing is staged. Use `git add` first.", file=sys.stderr)
        return 1

    diff_text = git.staged_diff(root)
    if scan_and_report(root, parse_diff(diff_text), "commit") != 0:
        return 1  # a secret is staged: don't spend time drafting

    config = load_config(root)
    if not config.llm.enabled:
        print(
            "AI drafting is off (`[llm] enabled = false`); opening the editor empty.",
            file=sys.stderr,
        )
        return git.commit_with_editor(root, None)

    print(
        "Drafting a commit message with the local model... "
        "(the first run of the day can take ~15 s)",
        file=sys.stderr,
    )
    answer = make_draft(root, diff_text, config.llm)
    if answer.text is None:
        print(
            f"GitWarden couldn't draft a message ({answer.error}); opening the editor empty.",
            file=sys.stderr,
        )
        return git.commit_with_editor(root, None)
    return git.commit_with_editor(root, answer.text)


def make_draft(root: Path, diff_text: str, settings: LlmConfig) -> LlmAnswer:
    """Ask the model for a message and tidy it. text=None if there is no usable draft."""
    summary = build_summary(
        git.staged_stat(root), diff_text, git.recent_subjects(root, RECENT_COMMITS)
    )
    answer = ask(wrap(COMMIT_SYSTEM, summary, settings.prompt_format), settings)
    if answer.text is None:
        return answer
    message = clean_message(answer.text)
    if not message:
        return LlmAnswer(None, "the model gave an empty answer", answer.seconds)
    return LlmAnswer(message, None, answer.seconds)


def build_summary(stat: str, diff_text: str, recent_subjects: list[str]) -> str:
    """A short description of the change: recent subjects, file list, and changed lines."""
    parts: list[str] = []
    if recent_subjects:
        parts.append("Recent commit messages in this repository (match their style):")
        parts.extend(f"- {subject}" for subject in recent_subjects)
        parts.append("")
    parts.append("Files changed:")
    parts.append(stat.rstrip())
    parts.append("")
    parts.append("Changed lines (+ added, - removed):")
    for path, lines in changed_lines_by_file(diff_text).items():
        parts.append(f"=== {path}")
        parts.extend(lines[:MAX_LINES_PER_FILE])
        hidden = len(lines) - MAX_LINES_PER_FILE
        if hidden > 0:
            parts.append(f"... ({hidden} more lines)")

    summary = "\n".join(parts)
    if len(summary) > MAX_SUMMARY_CHARS:
        summary = summary[:MAX_SUMMARY_CHARS] + "\n... (cut to keep it short)"
    return summary


def changed_lines_by_file(diff_text: str) -> dict[str, list[str]]:
    """The '+' and '-' lines of a diff, grouped by file name."""
    files: dict[str, list[str]] = {}
    current: str | None = None
    for raw in diff_text.split("\n"):
        if raw.startswith("diff --git "):
            current = None
        elif current is None and raw.startswith("+++ "):
            current = raw[4:].rstrip("\t").removeprefix("b/")
            files[current] = []
        elif current is not None and raw.startswith(("+", "-")):
            files[current].append(raw.rstrip("\r"))
    return files


def clean_message(answer: str) -> str:
    """Remove the extras small models like to add: code fences, quotes, 'Commit message:'."""
    lines = [line for line in answer.strip().splitlines() if not line.strip().startswith("```")]
    if lines and lines[0].lower().startswith("commit message:"):
        rest = lines[0][len("commit message:") :].strip()
        lines = ([rest] if rest else []) + lines[1:]
    text = "\n".join(lines).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text
