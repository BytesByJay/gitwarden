"""The only module that runs git. Everything else works with plain strings."""

import re
import subprocess
from pathlib import Path

from gitwarden.errors import GitWardenError

MIN_GIT_VERSION = (2, 36)  # --remerge-diff needs 2.36

# Diff options used everywhere. They make the output the same on every machine,
# whatever the developer's own git settings are.
DIFF_OPTIONS = [
    "-U0",  # no context lines: we only need added lines
    "--no-color",
    "--no-ext-diff",  # ignore external diff tools
    "--no-textconv",  # ignore text converters
    "--src-prefix=a/",  # fixed prefixes, even if the user set diff.noprefix
    "--dst-prefix=b/",
    "--diff-filter=ACMR",  # added, copied, modified, renamed (not deleted)
]


def run_git(args: list[str], cwd: Path | None = None) -> str:
    """Run `git <args>` and return its output. Any failure raises GitWardenError."""
    command = ["git", "-c", "core.quotePath=false", *args]
    try:
        completed = subprocess.run(command, cwd=cwd, capture_output=True)
    except FileNotFoundError as err:
        raise GitWardenError("git is not installed or not on PATH.") from err
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise GitWardenError(f"`git {' '.join(args)}` failed: {message}")
    return completed.stdout.decode("utf-8", errors="replace")


def check_git_version() -> None:
    """Stop with a clear message if git is older than 2.36."""
    output = run_git(["--version"])  # "git version 2.43.0" or "git version 2.45.1.windows.1"
    match = re.search(r"(\d+)\.(\d+)", output)
    if match is None:
        raise GitWardenError(f"could not read the git version from: {output.strip()}")
    version = (int(match.group(1)), int(match.group(2)))
    if version < MIN_GIT_VERSION:
        raise GitWardenError(
            f"git {version[0]}.{version[1]} is too old; GitWarden needs git 2.36 or newer."
        )


def repo_root(cwd: Path | None = None) -> Path:
    """The top folder of the repository we are in."""
    try:
        output = run_git(["rev-parse", "--show-toplevel"], cwd)
    except GitWardenError as err:
        raise GitWardenError("not inside a git repository.") from err
    return Path(output.strip()).resolve()


def hooks_dir(root: Path) -> Path:
    """Where git looks for hooks. Respects core.hooksPath."""
    output = run_git(["rev-parse", "--git-path", "hooks"], root)
    return (root / output.strip()).resolve()


def staged_diff(root: Path) -> str:
    """The diff of what is staged for the next commit."""
    return run_git(["diff", "--cached", *DIFF_OPTIONS], root)


def commit_diff(root: Path, sha: str) -> str:
    """The diff one commit adds. For a merge, only the lines added while resolving conflicts."""
    return run_git(["show", "--format=", "--remerge-diff", *DIFF_OPTIONS, sha], root)


def commits_in_range(root: Path, range_spec: str) -> list[str]:
    """Commit SHAs in a range like 'main..HEAD', oldest first."""
    return run_git(["rev-list", "--reverse", range_spec], root).split()


def commits_to_push(root: Path, local_sha: str, remote_sha: str, remote_name: str) -> list[str]:
    """The commits a push sends, oldest first.

    For a new branch, or when the remote's commit is unknown here (for example a
    force push after someone else pushed), we take every commit the remote's
    branches don't have yet.
    """
    if _is_zero(remote_sha) or not commit_exists(root, remote_sha):
        args = ["rev-list", "--reverse", local_sha, "--not", f"--remotes={remote_name}"]
    else:
        args = ["rev-list", "--reverse", f"{remote_sha}..{local_sha}"]
    return run_git(args, root).split()


def commit_exists(root: Path, sha: str) -> bool:
    """True if this commit is in the local repository."""
    try:
        run_git(["cat-file", "-e", f"{sha}^{{commit}}"], root)
    except GitWardenError:
        return False
    return True


def is_deleted_ref(sha: str) -> bool:
    """In pre-push input, an all-zero local SHA means the branch is being deleted."""
    return _is_zero(sha)


def user_name(root: Path) -> str:
    """git config user.name, or 'unknown' if it isn't set."""
    try:
        return run_git(["config", "user.name"], root).strip() or "unknown"
    except GitWardenError:
        return "unknown"


def stage_file(root: Path, relative_path: str) -> None:
    """git add one file."""
    run_git(["add", "--", relative_path], root)


def _is_zero(sha: str) -> bool:
    return set(sha) == {"0"}
