"""Installs the git hooks and runs the checks when git calls them."""

import sys
from datetime import date
from pathlib import Path

from gitwarden import git
from gitwarden.allowlist import load_allowlist
from gitwarden.config import Config, load_config, pack_paths
from gitwarden.diff import ParsedDiff, parse_diff
from gitwarden.errors import GitWardenError
from gitwarden.report import format_result
from gitwarden.rules import load_rules
from gitwarden.scanner import ScanResult, scan

MARKER = "# gitwarden-managed"
HOOK_NAMES = ("pre-commit", "pre-push")


def hook_script(hook_name: str, python_path: str) -> str:
    """The small shell script git runs. It calls GitWarden with a fixed Python.

    Git for Windows runs hooks with its own `sh`, so this works on every OS.
    The full Python path is written in because on Windows `python` on PATH
    is often the wrong one, or missing.
    """
    python_path = python_path.replace("\\", "/")
    return (
        "#!/bin/sh\n"
        f"{MARKER} - do not edit; run `gitwarden install` to regenerate\n"
        f'GW_PY="{python_path}"\n'
        'if [ ! -f "$GW_PY" ]; then\n'
        "  echo \"GitWarden: its Python ($GW_PY) is missing. Run 'gitwarden install' again.\" >&2\n"
        "  exit 2\n"
        "fi\n"
        f'exec "$GW_PY" -m gitwarden hook {hook_name} "$@"\n'
    )


def install_hooks(
    root: Path, config: Config, force: bool = False, python_path: str | None = None
) -> list[Path]:
    """Write the enabled hooks. Refuses to replace someone else's hook unless force=True."""
    python_path = python_path or sys.executable
    folder = git.hooks_dir(root)
    wanted = []
    if config.hooks.pre_commit:
        wanted.append("pre-commit")
    if config.hooks.pre_push:
        wanted.append("pre-push")

    # Check every hook before writing any, so we never install half the set.
    for name in wanted:
        path = folder / name
        if path.exists() and not _is_ours(path) and not force:
            raise GitWardenError(
                f"{path} already exists and was not written by GitWarden.\n"
                f"Add this line to it so GitWarden runs too:\n"
                f'    "{python_path}" -m gitwarden hook {name} "$@" || exit $?\n'
                f"or run `gitwarden install --force` to replace it."
            )

    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for name in wanted:
        path = folder / name
        path.write_text(hook_script(name, python_path), encoding="utf-8", newline="\n")
        path.chmod(0o755)
        written.append(path)
    return written


def uninstall_hooks(root: Path) -> list[Path]:
    """Remove our hooks. Hooks written by anyone else are left alone."""
    folder = git.hooks_dir(root)
    removed = []
    for name in HOOK_NAMES:
        path = folder / name
        if path.exists() and _is_ours(path):
            path.unlink()
            removed.append(path)
    return removed


def run_hook(hook_name: str, args: list[str], stdin_text: str, today: date | None = None) -> int:
    """Entry point when git runs a hook. Returns the exit code: 0 ok, 1 blocked, 2 broken."""
    try:
        root = git.repo_root()
        git.check_git_version()
        if hook_name == "pre-commit":
            diff = parse_diff(git.staged_diff(root))
            return scan_and_report(root, diff, "commit", today)
        if hook_name == "pre-push":
            remote_name = args[0] if args else ""
            diff = diff_for_commits(root, _commits_from_push_input(root, remote_name, stdin_text))
            return scan_and_report(root, diff, "push", today)
        raise GitWardenError(f"unknown hook '{hook_name}'.")
    except GitWardenError as err:
        print(f"GitWarden could not run: {err}", file=sys.stderr)
        return 2


def scan_and_report(root: Path, diff: ParsedDiff, action: str, today: date | None = None) -> int:
    """Scan a diff with the repo's settings, print the report, and return the exit code."""
    config = load_config(root)
    result = scan_with_config(root, config, diff, today or date.today(), use_allowlist=True)
    print(format_result(result, config.scan.block_on, action), file=sys.stderr, end="")
    return 1 if result.blocking(config.scan.block_on) else 0


def scan_with_config(
    root: Path, config: Config, diff: ParsedDiff, today: date, use_allowlist: bool
) -> ScanResult:
    """Load rules (and the allowlist if asked) and scan. Shared by hooks and the CLI."""
    rules = load_rules(pack_paths(root, config), config.rules.enable, config.rules.disable)
    allowlist = load_allowlist(root) if use_allowlist else {}
    return scan(diff, rules, allowlist, config.scan, today)


def diff_for_commits(root: Path, shas: list[str]) -> ParsedDiff:
    """Parse each commit's own diff and put all added lines together."""
    combined = ParsedDiff()
    for sha in shas:
        part = parse_diff(git.commit_diff(root, sha), commit=sha)
        combined.lines.extend(part.lines)
        combined.binary_paths.extend(part.binary_paths)
    return combined


def _commits_from_push_input(root: Path, remote_name: str, stdin_text: str) -> list[str]:
    """Read git's pre-push input ('<local ref> <local sha> <remote ref> <remote sha>' per line)."""
    shas: list[str] = []
    for line in stdin_text.splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        _local_ref, local_sha, _remote_ref, remote_sha = parts
        if git.is_deleted_ref(local_sha):
            continue
        for sha in git.commits_to_push(root, local_sha, remote_sha, remote_name):
            if sha not in shas:
                shas.append(sha)
    return shas


def _is_ours(path: Path) -> bool:
    return MARKER in path.read_text(encoding="utf-8", errors="replace")
