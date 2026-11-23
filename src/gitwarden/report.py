"""Turns scan results into text for people. Secrets are already redacted by the scanner."""

from datetime import date, timedelta

from gitwarden.allowlist import AllowEntry
from gitwarden.scanner import Finding, ScanResult

TITLES = {
    "commit": "GitWarden blocked this commit",
    "push": "GitWarden blocked this push",
    "scan": "GitWarden found secrets",
}


def format_result(result: ScanResult, block_on: str, action: str) -> str:
    """The full report. `action` is 'commit', 'push' or 'scan'. Empty string if nothing to say."""
    blocking = result.blocking(block_on)
    below_level = [f for f in result.findings if f not in blocking]
    lines: list[str] = []

    if blocking:
        lines.append(f"{TITLES[action]}: {_plural(len(blocking), 'finding')}")
        lines.append("")
        for finding in blocking:
            lines.extend(_finding_lines(finding))
    if below_level:
        lines.append("Warnings (below the blocking level):")
        lines.append("")
        for finding in below_level:
            lines.extend(_finding_lines(finding))
    for warning in result.warnings:
        lines.append(f"  warning: {warning}")
    for skipped in result.skipped:
        lines.append(f"  not scanned: {skipped.path} ({skipped.reason})")
    if blocking:
        lines.append("")
        lines.extend(_next_steps(action, blocking[0].fingerprint))

    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def format_allowlist(entries: list[AllowEntry], today: date) -> str:
    """List allowlist entries: expired first, then those expiring within 14 days, then the rest."""
    if not entries:
        return "The allowlist is empty.\n"
    soon = today + timedelta(days=14)

    def sort_key(entry: AllowEntry) -> tuple[int, date]:
        if entry.expires < today:
            return (0, entry.expires)
        if entry.expires <= soon:
            return (1, entry.expires)
        return (2, entry.expires)

    lines = []
    for entry in sorted(entries, key=sort_key):
        if entry.expires < today:
            status = f"EXPIRED {entry.expires.isoformat()}"
        elif entry.expires <= soon:
            status = f"expires soon {entry.expires.isoformat()}"
        else:
            status = f"expires {entry.expires.isoformat()}"
        lines.append(f"{entry.fingerprint}  {status}  {entry.rule}  {entry.path}")
        lines.append(f"    reason: {entry.reason} (added by {entry.added_by} on {entry.added})")
    return "\n".join(lines) + "\n"


def _finding_lines(finding: Finding) -> list[str]:
    """The lines that describe one finding."""
    where = f"{finding.path}:{finding.line_no}"
    if finding.commit:
        where += f" (commit {finding.commit[:8]})"
    lines = [
        f"  {where}   {finding.rule_id} ({finding.severity})",
        f"      {finding.redacted_line}",
        f"      fingerprint: {finding.fingerprint}",
    ]
    entry = finding.expired_allow
    if entry is not None:
        lines.append(
            f"      allowlist entry {entry.fingerprint} expired on "
            f"{entry.expires.isoformat()} (reason: {entry.reason})"
        )
    lines.append("")
    return lines


def _next_steps(action: str, example_fingerprint: str) -> list[str]:
    """What the developer should do now."""
    allow = f'gitwarden allow {example_fingerprint} --reason "..." --expires YYYY-MM-DD'
    if action == "push":
        return [
            "The secret is inside a commit you are pushing. Remove it from those commits",
            "(for example with `git rebase -i`). If it's a known false positive:",
            f"    {allow} --range <remote>/<branch>..HEAD",
            "    then commit .gitwarden-allow.toml and push again.",
        ]
    return [
        "Remove the secret and stage the file again. If it's a known false positive:",
        f"    {allow}",
    ]


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"
