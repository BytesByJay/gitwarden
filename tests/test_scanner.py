from datetime import date

from fakes import fake

from gitwarden.allowlist import AllowEntry, fingerprint
from gitwarden.config import ScanConfig
from gitwarden.diff import AddedLine, ParsedDiff
from gitwarden.rules import load_rules
from gitwarden.scanner import redact, scan, shannon_entropy

TODAY = date(2026, 11, 23)
RULES = load_rules([], enable=[], disable=[])
TOKEN = fake("github_token")


def scan_lines(*lines: AddedLine, allowlist=None, settings=None, binary=None):
    diff = ParsedDiff(lines=list(lines), binary_paths=binary or [])
    return scan(diff, RULES, allowlist or {}, settings or ScanConfig(), TODAY)


def test_finds_a_token_and_never_keeps_the_raw_secret():
    result = scan_lines(AddedLine("ci.sh", 3, f"export GITHUB_TOKEN={TOKEN}"))
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.rule_id == "generic/github-token"
    assert (finding.path, finding.line_no, finding.severity) == ("ci.sh", 3, "high")
    assert TOKEN not in finding.redacted_line
    assert finding.redacted_line == f"export GITHUB_TOKEN={redact(TOKEN)}"
    assert finding.fingerprint == fingerprint("generic/github-token", "ci.sh", TOKEN)


def test_same_secret_found_by_two_rules_is_reported_once():
    # secret-assignment would also match this quoted token; github-token comes first
    result = scan_lines(AddedLine("a.py", 1, f'token = "{TOKEN}"'))
    assert [f.rule_id for f in result.findings] == ["generic/github-token"]


def test_every_secret_on_the_line_is_hidden_in_every_finding():
    key = fake("aws_access_key_id")
    result = scan_lines(AddedLine("a.env", 1, f"A={TOKEN} B={key}"))
    assert len(result.findings) == 2
    for finding in result.findings:
        assert TOKEN not in finding.redacted_line
        assert key not in finding.redacted_line


def test_clean_line_has_no_findings():
    assert scan_lines(AddedLine("a.py", 1, "print('hello')")).findings == []


def test_lockfiles_binary_and_excluded_files_are_skipped_and_listed():
    settings = ScanConfig(paths_exclude=["^vendor/"])
    result = scan_lines(
        AddedLine("web/package-lock.json", 1, f"x={TOKEN}"),
        AddedLine("vendor/lib.py", 1, f"x={TOKEN}"),
        settings=settings,
        binary=["logo.png"],
    )
    assert result.findings == []
    reasons = {(s.path, s.reason) for s in result.skipped}
    assert reasons == {
        ("logo.png", "binary file"),
        ("web/package-lock.json", "lockfile"),
        ("vendor/lib.py", "excluded by paths_exclude"),
    }


def test_file_with_too_much_added_text_is_skipped():
    big_line = "x" * 2000
    lines = [AddedLine("dump.sql", n, big_line) for n in range(1, 600)]
    result = scan_lines(*lines, settings=ScanConfig(max_file_kb=1))
    assert [(s.path, s.reason) for s in result.skipped] == [("dump.sql", "more than 1 KB added")]


def test_very_long_line_is_cut_and_warned_about():
    line = AddedLine("min.js", 1, "a" * 50 + TOKEN)
    result = scan_lines(line, settings=ScanConfig(max_line_chars=40))
    assert result.findings == []
    assert "only the first 40 were scanned" in result.warnings[0]


def test_allowlisted_finding_is_hidden_until_it_expires():
    line = AddedLine("tests/t.py", 1, f"x = {TOKEN}")
    entry = AllowEntry(
        fingerprint=fingerprint("generic/github-token", "tests/t.py", TOKEN),
        rule="generic/github-token",
        path="tests/t.py",
        reason="fake token for a test",
        added_by="Test Dev",
        added=date(2026, 11, 1),
        expires=TODAY,  # still valid on its last day
    )
    allowlist = {entry.fingerprint: entry}
    result = scan_lines(line, allowlist=allowlist)
    assert result.findings == [] and result.allowed_count == 1

    later = scan(ParsedDiff([line]), RULES, allowlist, ScanConfig(), date(2026, 11, 24))
    assert len(later.findings) == 1
    assert later.findings[0].expired_allow == entry


def test_blocking_respects_block_on():
    result = scan_lines(AddedLine("a.ts", 1, f"const t = '{fake('jwt')}';"))
    assert result.findings[0].severity == "medium"
    assert len(result.blocking("medium")) == 1
    assert result.blocking("high") == []


def test_entropy_and_redact():
    assert shannon_entropy("") == 0.0
    assert shannon_entropy("aaaa") == 0.0
    assert shannon_entropy("abcd") == 2.0
    assert redact("short") == "*****"
    assert redact("ABCDEFGHIJKLMNOPQRST") == "ABCD************QRST"
