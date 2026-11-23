"""The one error type GitWarden raises on purpose."""

from pydantic import ValidationError


class GitWardenError(Exception):
    """A setup problem: bad config, broken rule pack, git missing, and so on.

    Hooks turn this into exit code 2, which blocks the commit or push:
    if the check can't run, it must not pass quietly.
    """


def describe(err: ValidationError) -> str:
    """Turn a Pydantic error into short lines like 'scan.block_on: Input should be ...'."""
    lines = []
    for problem in err.errors():
        where = ".".join(str(part) for part in problem["loc"]) or "(top level)"
        lines.append(f"{where}: {problem['msg']}")
    return "; ".join(lines)
