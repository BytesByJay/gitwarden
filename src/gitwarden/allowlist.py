"""The allowlist: reviewed exceptions for false positives, each with a reason and an expiry date.

The file is .gitwarden-allow.toml in the repo root. It is committed, so every
exception is seen in code review.
"""

import hashlib
import json
import tomllib
from datetime import date, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from gitwarden.errors import GitWardenError, describe

ALLOW_FILE = ".gitwarden-allow.toml"
FILE_HEADER = (
    "# Reviewed exceptions for GitWarden. Each entry needs a reason and an expiry date.\n"
    '# Add entries with: gitwarden allow <fingerprint> --reason "..." --expires YYYY-MM-DD\n'
)


class AllowEntry(BaseModel):
    """One [[allow]] entry."""

    model_config = ConfigDict(extra="forbid")

    fingerprint: str = Field(pattern=r"^[0-9a-f]{12}$")
    rule: str
    path: str
    reason: str = Field(min_length=1)
    added_by: str
    added: date
    expires: date


class AllowFile(BaseModel):
    """The whole allowlist file."""

    model_config = ConfigDict(extra="forbid")

    allow: list[AllowEntry] = []


def fingerprint(rule_id: str, path: str, secret: str) -> str:
    """A short ID for one finding that does not reveal the secret.

    The path is part of it, so allowing a fake password in a test file does
    not allow the same string anywhere else.
    """
    text = f"{rule_id}\n{path}\n{secret}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def load_allowlist(repo_root: Path) -> dict[str, AllowEntry]:
    """Read the allowlist, keyed by fingerprint. A missing file means no exceptions."""
    path = repo_root / ALLOW_FILE
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        parsed = AllowFile.model_validate(data)
    except tomllib.TOMLDecodeError as err:
        raise GitWardenError(f"{ALLOW_FILE}: not valid TOML: {err}") from err
    except ValidationError as err:
        raise GitWardenError(f"{ALLOW_FILE}: {describe(err)}") from err

    entries: dict[str, AllowEntry] = {}
    for entry in parsed.allow:
        if entry.fingerprint in entries:
            raise GitWardenError(f"{ALLOW_FILE}: fingerprint {entry.fingerprint} is listed twice")
        entries[entry.fingerprint] = entry
    return entries


def check_new_entry(reason: str, expires: date, today: date, max_days: int) -> None:
    """Refuse an exception without a reason, or one that lasts too long."""
    if not reason.strip():
        raise GitWardenError("--reason is required: say why this is not a real secret.")
    if expires <= today:
        raise GitWardenError("--expires must be a date after today.")
    latest = today + timedelta(days=max_days)
    if expires > latest:
        raise GitWardenError(
            f"--expires can be at most {max_days} days from today ({latest.isoformat()})."
        )


def add_entry(repo_root: Path, entry: AllowEntry) -> Path:
    """Append one entry to the allowlist file (created if missing). Returns the file path."""
    path = repo_root / ALLOW_FILE
    existing = path.read_text(encoding="utf-8") if path.exists() else FILE_HEADER
    if not existing.endswith("\n"):
        existing += "\n"
    block = "\n".join(
        [
            "[[allow]]",
            f"fingerprint = {_toml_string(entry.fingerprint)}",
            f"rule = {_toml_string(entry.rule)}",
            f"path = {_toml_string(entry.path)}",
            f"reason = {_toml_string(entry.reason)}",
            f"added_by = {_toml_string(entry.added_by)}",
            f"added = {entry.added.isoformat()}",
            f"expires = {entry.expires.isoformat()}",
        ]
    )
    path.write_text(existing + "\n" + block + "\n", encoding="utf-8", newline="\n")
    return path


def _toml_string(value: str) -> str:
    """Quote a string for TOML. JSON's escaping rules are valid TOML for basic strings."""
    return json.dumps(value, ensure_ascii=False)
