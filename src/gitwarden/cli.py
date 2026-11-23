"""The `gitwarden` command: scan, install, uninstall, allow, rules."""

import os
from datetime import date
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from gitwarden import __version__, git
from gitwarden.allowlist import ALLOW_FILE, AllowEntry, add_entry, check_new_entry, load_allowlist
from gitwarden.config import load_config, pack_paths
from gitwarden.diff import ParsedDiff, lines_from_file, parse_diff
from gitwarden.errors import GitWardenError
from gitwarden.hooks import diff_for_commits, install_hooks, scan_and_report, scan_with_config
from gitwarden.hooks import uninstall_hooks as remove_hooks
from gitwarden.report import format_allowlist
from gitwarden.rules import load_all_rules, load_pack, load_rules

app = typer.Typer(
    help="GitWarden blocks secrets before they leave your machine.",
    no_args_is_help=True,
    add_completion=False,
)
rules_app = typer.Typer(help="Look at and check rule packs.", no_args_is_help=True)
app.add_typer(rules_app, name="rules")


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"gitwarden {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_show_version, is_eager=True, help="Show the version."),
    ] = False,
) -> None:
    """GitWarden blocks secrets before they leave your machine."""


def _fail(err: GitWardenError) -> NoReturn:
    """Print a setup problem and exit with code 2."""
    typer.echo(f"GitWarden: {err}", err=True)
    raise typer.Exit(2)


@app.command()
def scan(
    paths: Annotated[list[Path] | None, typer.Argument(help="Files or folders to scan.")] = None,
    staged: Annotated[bool, typer.Option("--staged", help="Scan staged changes.")] = False,
    range_spec: Annotated[
        str | None, typer.Option("--range", help="Scan commits, e.g. main..HEAD.")
    ] = None,
) -> None:
    """Scan staged changes, a range of commits, or whole files. Exit 1 if secrets are found."""
    chosen = sum([staged, range_spec is not None, bool(paths)])
    if chosen != 1:
        typer.echo("Choose exactly one of: --staged, --range A..B, or file paths.", err=True)
        raise typer.Exit(2)
    try:
        root = git.repo_root()
        if staged:
            diff = parse_diff(git.staged_diff(root))
        elif range_spec is not None:
            diff = diff_for_commits(root, git.commits_in_range(root, range_spec))
        else:
            diff = _diff_for_files(root, paths or [])
        code = scan_and_report(root, diff, "scan")
    except GitWardenError as err:
        _fail(err)
    if code == 0:
        typer.echo("GitWarden: no secrets found.")
    raise typer.Exit(code)


@app.command()
def install(
    force: Annotated[bool, typer.Option("--force", help="Replace existing hooks.")] = False,
) -> None:
    """Install the pre-commit and pre-push hooks in this repository."""
    try:
        root = git.repo_root()
        git.check_git_version()
        written = install_hooks(root, load_config(root), force=force)
    except GitWardenError as err:
        _fail(err)
    for path in written:
        typer.echo(f"Installed {path}")


@app.command()
def uninstall() -> None:
    """Remove GitWarden's hooks from this repository."""
    try:
        removed = remove_hooks(git.repo_root())
    except GitWardenError as err:
        _fail(err)
    if not removed:
        typer.echo("No GitWarden hooks found.")
    for path in removed:
        typer.echo(f"Removed {path}")


@app.command()
def allow(
    fingerprint: Annotated[str | None, typer.Argument(help="Fingerprint from the report.")] = None,
    reason: Annotated[str, typer.Option(help="Why this is not a real secret.")] = "",
    expires: Annotated[str, typer.Option(help="Last valid day, YYYY-MM-DD.")] = "",
    range_spec: Annotated[
        str | None, typer.Option("--range", help="Look in these commits instead of staged.")
    ] = None,
    list_entries: Annotated[bool, typer.Option("--list", help="Show the allowlist.")] = False,
) -> None:
    """Add a reviewed exception for a false positive, or list the exceptions."""
    today = date.today()
    try:
        root = git.repo_root()
        if list_entries:
            typer.echo(format_allowlist(list(load_allowlist(root).values()), today), nl=False)
            return
        if not fingerprint:
            raise GitWardenError("give a fingerprint, or use --list.")
        _add_allow_entry(root, fingerprint, reason, expires, range_spec, today)
    except GitWardenError as err:
        _fail(err)
    typer.echo(f"Added {fingerprint} to {ALLOW_FILE} and staged it.")


@rules_app.command("list")
def rules_list() -> None:
    """Show every loaded rule and whether it is on."""
    try:
        root = git.repo_root()
        config = load_config(root)
        packs = pack_paths(root, config)
        all_rules = load_all_rules(packs)
        active = load_rules(packs, config.rules.enable, config.rules.disable)
    except GitWardenError as err:
        _fail(err)
    active_ids = {rule.id for rule in active}
    for rule in all_rules:
        state = "on " if rule.id in active_ids else "off"
        typer.echo(f"{state}  {rule.severity:<6}  {rule.id}  - {rule.description}")


@rules_app.command("check")
def rules_check(pack: Path) -> None:
    """Check a rule pack file for mistakes."""
    try:
        pack_id, rules = load_pack(pack)
    except GitWardenError as err:
        _fail(err)
    typer.echo(f"OK: pack '{pack_id}' with {len(rules)} rule(s).")


def _add_allow_entry(
    root: Path, fingerprint: str, reason: str, expires: str, range_spec: str | None, today: date
) -> None:
    """Find the finding with this fingerprint, then write and stage the allowlist entry."""
    config = load_config(root)
    try:
        expires_date = date.fromisoformat(expires)
    except ValueError as err:
        raise GitWardenError("--expires must be a date like 2026-12-31.") from err
    check_new_entry(reason, expires_date, today, config.allowlist.max_days)
    if fingerprint in load_allowlist(root):
        raise GitWardenError(
            f"{fingerprint} is already in {ALLOW_FILE}; edit or remove that entry first."
        )

    if range_spec is None:
        diff = parse_diff(git.staged_diff(root))
    else:
        diff = diff_for_commits(root, git.commits_in_range(root, range_spec))
    result = scan_with_config(root, config, diff, today, use_allowlist=False)
    matches = [f for f in result.findings if f.fingerprint == fingerprint]
    if not matches:
        where = f"commits {range_spec}" if range_spec else "the staged changes"
        raise GitWardenError(f"no finding with fingerprint {fingerprint} in {where}.")

    finding = matches[0]
    entry = AllowEntry(
        fingerprint=fingerprint,
        rule=finding.rule_id,
        path=finding.path,
        reason=reason.strip(),
        added_by=git.user_name(root),
        added=today,
        expires=expires_date,
    )
    add_entry(root, entry)
    git.stage_file(root, ALLOW_FILE)


def _diff_for_files(root: Path, paths: list[Path]) -> ParsedDiff:
    """Build a diff where every line of every given file counts as added."""
    diff = ParsedDiff()
    for file_path in _expand(paths):
        relative = os.path.relpath(file_path.resolve(), root).replace("\\", "/")
        data = file_path.read_bytes()
        if b"\0" in data[:8000]:
            diff.binary_paths.append(relative)
            continue
        diff.lines.extend(lines_from_file(relative, data.decode("utf-8", errors="replace")))
    return diff


def _expand(paths: list[Path]) -> list[Path]:
    """Files as given; folders become every file inside them (skipping .git)."""
    files = []
    for path in paths:
        if not path.exists():
            raise GitWardenError(f"{path} does not exist.")
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and ".git" not in child.parts:
                    files.append(child)
        else:
            files.append(path)
    return files
