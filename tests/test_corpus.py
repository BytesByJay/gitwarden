"""The test set: proves the built-in rules catch leaks and leave clean code alone.

Targets from the spec: at least 95% of leak cases caught, at most 5% of clean
cases blocked.
"""

import tomllib
from datetime import date
from pathlib import Path

from fakes import fill

from gitwarden.config import ScanConfig
from gitwarden.diff import ParsedDiff, lines_from_file
from gitwarden.rules import load_rules
from gitwarden.scanner import scan

CORPUS = Path(__file__).parent / "corpus"
RULES = load_rules([], enable=[], disable=[])


def load_cases(name: str) -> list[dict]:
    return tomllib.loads((CORPUS / name).read_text(encoding="utf-8"))["case"]


def scan_text(path: str, text: str):
    diff = ParsedDiff(lines=lines_from_file(path, text))
    return scan(diff, RULES, {}, ScanConfig(), date(2026, 11, 23))


def test_every_enabled_rule_has_at_least_three_leak_cases():
    counts: dict[str, int] = {}
    for case in load_cases("leaks.toml"):
        counts[case["rule"]] = counts.get(case["rule"], 0) + 1
    for rule in RULES:
        assert counts.get(rule.id, 0) >= 3, f"{rule.id} needs at least 3 leak cases"


def test_recall_is_at_least_95_percent():
    cases = load_cases("leaks.toml")
    missed = []
    for number, case in enumerate(cases):
        text = fill(case["text"], seed=number)
        found = [f.rule_id for f in scan_text(case["path"], text).findings]
        if case["rule"] not in found:
            missed.append(f"{case['rule']} in {case['path']} (found: {found})")
    recall = 1 - len(missed) / len(cases)
    print(f"\nrecall: {recall:.1%} of {len(cases)} leak cases")
    for line in missed:
        print("  missed:", line)
    assert recall >= 0.95


def test_false_positive_rate_is_at_most_5_percent():
    cases = load_cases("clean.toml")
    flagged = []
    for case in cases:
        blocking = scan_text(case["path"], case["text"]).blocking("medium")
        if blocking:
            flagged.append(f"{case['path']}: {[f.rule_id for f in blocking]}")
    rate = len(flagged) / len(cases)
    print(f"\nfalse positives: {rate:.1%} of {len(cases)} clean cases")
    for line in flagged:
        print("  flagged:", line)
    assert rate <= 0.05
