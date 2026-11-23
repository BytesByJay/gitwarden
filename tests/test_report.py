from datetime import date

from gitwarden.allowlist import AllowEntry
from gitwarden.report import format_allowlist, format_result
from gitwarden.scanner import Finding, ScanResult, Skipped


def make_finding(severity: str = "high", commit: str | None = None) -> Finding:
    return Finding(
        rule_id="generic/aws-access-key-id",
        severity=severity,
        description="AWS access key ID",
        path="config/settings.py",
        line_no=14,
        commit=commit,
        redacted_line='AWS_KEY = "AKIA************WXYZ"',
        fingerprint="3f9a1c2e7d40",
    )


def make_entry(fp: str, expires: date) -> AllowEntry:
    return AllowEntry(
        fingerprint=fp,
        rule="generic/jwt",
        path="tests/a.py",
        reason="fake",
        added_by="Asha",
        added=date(2026, 11, 1),
        expires=expires,
    )


def test_nothing_to_say_gives_empty_text():
    assert format_result(ScanResult(), "medium", "commit") == ""


def test_blocked_commit_report():
    result = ScanResult(findings=[make_finding()], skipped=[Skipped("dump.sql", "lockfile")])
    text = format_result(result, "medium", "commit")
    assert text.startswith("GitWarden blocked this commit: 1 finding\n")
    assert "config/settings.py:14   generic/aws-access-key-id (high)" in text
    assert 'AWS_KEY = "AKIA************WXYZ"' in text
    assert "fingerprint: 3f9a1c2e7d40" in text
    assert "not scanned: dump.sql (lockfile)" in text
    assert 'gitwarden allow 3f9a1c2e7d40 --reason "..." --expires YYYY-MM-DD' in text
    assert "--no-verify" not in text


def test_push_report_shows_commit_and_range_hint():
    result = ScanResult(findings=[make_finding(commit="0123456789abcdef")])
    text = format_result(result, "medium", "push")
    assert text.startswith("GitWarden blocked this push")
    assert "config/settings.py:14 (commit 01234567)" in text
    assert "--range <remote>/<branch>..HEAD" in text


def test_findings_below_block_level_are_warnings_only():
    text = format_result(ScanResult(findings=[make_finding("low")]), "medium", "commit")
    assert "blocked" not in text
    assert text.startswith("Warnings (below the blocking level):")


def test_expired_allow_entry_is_explained():
    finding = make_finding()
    finding.expired_allow = make_entry("3f9a1c2e7d40", date(2026, 11, 20))
    text = format_result(ScanResult(findings=[finding]), "medium", "commit")
    assert "allowlist entry 3f9a1c2e7d40 expired on 2026-11-20 (reason: fake)" in text


def test_allowlist_listing_puts_expired_and_soon_first():
    today = date(2026, 11, 23)
    entries = [
        make_entry("aaaaaaaaaaaa", date(2027, 2, 1)),
        make_entry("bbbbbbbbbbbb", date(2026, 11, 30)),
        make_entry("cccccccccccc", date(2026, 11, 1)),
    ]
    text = format_allowlist(entries, today)
    order = [line.split()[0] for line in text.splitlines() if not line.startswith(" ")]
    assert order == ["cccccccccccc", "bbbbbbbbbbbb", "aaaaaaaaaaaa"]
    assert "EXPIRED 2026-11-01" in text
    assert "expires soon 2026-11-30" in text
    assert format_allowlist([], today) == "The allowlist is empty.\n"
