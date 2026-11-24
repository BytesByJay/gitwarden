"""The local model's opinion on blocked findings. Advisory only.

The scanner and the rules decide whether a commit is blocked. This module only
adds a short opinion ("looks like a test value") to help the developer and the
person reviewing an allowlist entry. It never changes an exit code.
"""

import re
from dataclasses import dataclass

from gitwarden.config import LlmConfig
from gitwarden.llm import ask
from gitwarden.prompts import REVIEW_SYSTEM, wrap
from gitwarden.scanner import Finding

MAX_FINDINGS = 5  # one model call for the first 5 findings keeps the wait short
OPINION_LINE = re.compile(r"^\s*(\d+)\s*:\s*(real|test|unsure)\s*\|\s*(.+)$", re.IGNORECASE)


@dataclass
class Opinion:
    """The model's view of one finding."""

    verdict: str  # "real", "test" or "unsure"
    reason: str


def build_review_prompt(findings: list[Finding], prompt_format: str) -> str:
    """One prompt for all findings. It holds redacted lines only, never a raw secret."""
    parts = []
    for number, finding in enumerate(findings, start=1):
        parts.append(
            f"{number}. rule: {finding.rule_id} ({finding.description})\n"
            f"   file: {finding.path}\n"
            f"   line: {finding.redacted_line}"
        )
    return wrap(REVIEW_SYSTEM, "\n".join(parts), prompt_format)


def parse_opinions(answer: str, count: int) -> dict[int, Opinion]:
    """Read lines like '2: test | path is under tests/'. Lines in any other form are ignored."""
    opinions: dict[int, Opinion] = {}
    for line in answer.splitlines():
        match = OPINION_LINE.match(line)
        if match is None:
            continue
        number = int(match.group(1))
        if 1 <= number <= count and number not in opinions:
            opinions[number] = Opinion(match.group(2).lower(), match.group(3).strip())
    return opinions


def format_opinions(findings: list[Finding], opinions: dict[int, Opinion]) -> str:
    """The text printed under the report."""
    lines = ["Local model's opinion (advisory only, does not change the result):"]
    for number, finding in enumerate(findings, start=1):
        opinion = opinions.get(number)
        if opinion is not None:
            where = f"{finding.path}:{finding.line_no}"
            lines.append(f"  {where}  {opinion.verdict:<7} - {opinion.reason}")
    lines.append("If one really is a test value, use `gitwarden allow` as shown above.")
    return "\n".join(lines) + "\n"


def review_findings(findings: list[Finding], settings: LlmConfig) -> str:
    """Ask the model about the findings. Always returns text to print, never raises."""
    shown = findings[:MAX_FINDINGS]
    answer = ask(build_review_prompt(shown, settings.prompt_format), settings)
    if answer.text is None:
        return f"No model opinion: {answer.error}\n"
    opinions = parse_opinions(answer.text, len(shown))
    if not opinions:
        return "No model opinion: answer not understood\n"
    return format_opinions(shown, opinions)
