"""The scanner: checks added lines against the rules. No git, no files, no printing.

Steps for each line, cheapest first:
  1. skip the whole file if it is binary, a lockfile, excluded, or too big
  2. for each rule: keyword check, then regex, then entropy and stopwords
  3. look the finding up in the allowlist
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from gitwarden.allowlist import AllowEntry, fingerprint
from gitwarden.config import ScanConfig
from gitwarden.diff import AddedLine, ParsedDiff
from gitwarden.rules import SEVERITY_ORDER, Rule

LOCKFILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Cargo.lock",
    "go.sum",
}
MAX_SHOWN_CHARS = 160  # longest line we print in a report


@dataclass
class Finding:
    """One secret found. Holds no raw secret: only a redacted line and a fingerprint."""

    rule_id: str
    severity: str
    description: str
    path: str
    line_no: int
    commit: str | None
    redacted_line: str
    fingerprint: str
    expired_allow: AllowEntry | None = None  # set when an allowlist entry existed but expired


@dataclass
class Skipped:
    """A file that was not scanned, and why."""

    path: str
    reason: str


@dataclass
class ScanResult:
    """Everything one scan found."""

    findings: list[Finding] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    allowed_count: int = 0  # findings hidden by a valid allowlist entry

    def blocking(self, block_on: str) -> list[Finding]:
        """Findings at or above the `block_on` severity."""
        level = SEVERITY_ORDER[block_on]
        return [f for f in self.findings if SEVERITY_ORDER[f.severity] >= level]


def scan(
    diff: ParsedDiff,
    rules: list[Rule],
    allowlist: dict[str, AllowEntry],
    settings: ScanConfig,
    today: date,
) -> ScanResult:
    """Check every added line in the diff and return what was found."""
    result = ScanResult()
    for path in diff.binary_paths:
        _skip(result, path, "binary file")

    excludes = [re.compile(pattern) for pattern in settings.paths_exclude]
    sizes = _added_size_by_file(diff.lines)
    for line in diff.lines:
        size_kb = sizes[(line.commit, line.path)] / 1024
        reason = _skip_reason(line.path, size_kb, excludes, settings.max_file_kb)
        if reason:
            _skip(result, line.path, reason)
            continue
        _scan_line(line, rules, allowlist, settings.max_line_chars, today, result)
    return result


def find_secrets(rule: Rule, text: str) -> list[str]:
    """All secrets this rule finds in one line of text."""
    lowered = text.lower()
    if not any(keyword in lowered for keyword in rule.keywords):
        return []
    secrets = []
    for match in rule.regex.finditer(text):
        secret = match.group(rule.secret_group)
        if not secret:
            continue
        if rule.min_entropy and shannon_entropy(secret) < rule.min_entropy:
            continue
        if any(word in secret.lower() for word in rule.stopwords):
            continue
        secrets.append(secret)
    return secrets


def shannon_entropy(text: str) -> float:
    """How random a string looks, in bits per character. 'aaaa' -> 0.0, random base64 -> ~5."""
    if not text:
        return 0.0
    total = len(text)
    counts = Counter(text)
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


def redact(secret: str) -> str:
    """'AKIAABCDEFGHIJKLWXYZ' -> 'AKIA************WXYZ'. Short secrets are hidden completely."""
    if len(secret) < 12:
        return "*" * len(secret)
    return secret[:4] + "*" * (len(secret) - 8) + secret[-4:]


def _scan_line(
    line: AddedLine,
    rules: list[Rule],
    allowlist: dict[str, AllowEntry],
    max_line_chars: int,
    today: date,
    result: ScanResult,
) -> None:
    """Run every rule on one line and add findings to `result`."""
    text = line.text
    if len(text) > max_line_chars:
        result.warnings.append(
            f"{line.path}:{line.line_no}: line has {len(text)} characters; "
            f"only the first {max_line_chars} were scanned"
        )
        text = text[:max_line_chars]

    # Collect (rule, secret) pairs. If two rules find the same secret, the first rule wins.
    hits: list[tuple[Rule, str]] = []
    for rule in rules:
        for secret in find_secrets(rule, text):
            if all(secret != found for _, found in hits):
                hits.append((rule, secret))
    if not hits:
        return

    # Hide every secret found on the line before showing the line to anyone.
    shown = text.strip()
    for _, secret in hits:
        shown = shown.replace(secret, redact(secret))
    if len(shown) > MAX_SHOWN_CHARS:
        shown = shown[:MAX_SHOWN_CHARS] + "..."

    for rule, secret in hits:
        finding = Finding(
            rule_id=rule.id,
            severity=rule.severity,
            description=rule.description,
            path=line.path,
            line_no=line.line_no,
            commit=line.commit,
            redacted_line=shown,
            fingerprint=fingerprint(rule.id, line.path, secret),
        )
        entry = allowlist.get(finding.fingerprint)
        if entry is None:
            result.findings.append(finding)
        elif entry.expires < today:
            finding.expired_allow = entry
            result.findings.append(finding)
        else:
            result.allowed_count += 1


def _added_size_by_file(lines: list[AddedLine]) -> dict[tuple[str | None, str], int]:
    """Characters added per (commit, file). Used for the max_file_kb limit."""
    sizes: dict[tuple[str | None, str], int] = {}
    for line in lines:
        key = (line.commit, line.path)
        sizes[key] = sizes.get(key, 0) + len(line.text) + 1
    return sizes


def _skip_reason(
    path: str, size_kb: float, excludes: list[re.Pattern[str]], max_file_kb: int
) -> str | None:
    """Why this file should not be scanned, or None to scan it."""
    if any(pattern.search(path) for pattern in excludes):
        return "excluded by paths_exclude"
    if path.rsplit("/", 1)[-1] in LOCKFILES:
        return "lockfile"
    if size_kb > max_file_kb:
        return f"more than {max_file_kb} KB added"
    return None


def _skip(result: ScanResult, path: str, reason: str) -> None:
    """Record a skipped file once."""
    if not any(skipped.path == path for skipped in result.skipped):
        result.skipped.append(Skipped(path, reason))
