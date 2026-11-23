"""Reads the team's settings from .gitwarden.toml in the repo root."""

import re
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from gitwarden.errors import GitWardenError, describe
from gitwarden.rules import Severity

CONFIG_FILE = ".gitwarden.toml"


class HooksConfig(BaseModel):
    """[hooks]: which hooks `gitwarden install` writes."""

    model_config = ConfigDict(extra="forbid")

    pre_commit: bool = True
    pre_push: bool = True


class ScanConfig(BaseModel):
    """[scan]: what blocks, and what is too big to scan."""

    model_config = ConfigDict(extra="forbid")

    block_on: Severity = "medium"
    max_file_kb: int = Field(default=512, gt=0)
    max_line_chars: int = Field(default=20000, gt=0)
    paths_exclude: list[str] = []


class RulesConfig(BaseModel):
    """[rules]: client packs to load and rules to switch on or off."""

    model_config = ConfigDict(extra="forbid")

    packs: list[str] = []
    disable: list[str] = []
    enable: list[str] = []


class AllowlistConfig(BaseModel):
    """[allowlist]: how long an exception may last."""

    model_config = ConfigDict(extra="forbid")

    max_days: int = Field(default=90, gt=0)


class Config(BaseModel):
    """The whole .gitwarden.toml file. Every key has a default."""

    model_config = ConfigDict(extra="forbid")

    hooks: HooksConfig = HooksConfig()
    scan: ScanConfig = ScanConfig()
    rules: RulesConfig = RulesConfig()
    allowlist: AllowlistConfig = AllowlistConfig()


def load_config(repo_root: Path) -> Config:
    """Read .gitwarden.toml. A missing file means all defaults; a broken file is an error."""
    path = repo_root / CONFIG_FILE
    if not path.exists():
        return Config()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        config = Config.model_validate(data)
    except tomllib.TOMLDecodeError as err:
        raise GitWardenError(f"{CONFIG_FILE}: not valid TOML: {err}") from err
    except ValidationError as err:
        raise GitWardenError(f"{CONFIG_FILE}: {describe(err)}") from err

    for pattern in config.scan.paths_exclude:
        try:
            re.compile(pattern)
        except re.error as err:
            raise GitWardenError(
                f"{CONFIG_FILE}: bad regex in paths_exclude '{pattern}': {err}"
            ) from err
    return config


def pack_paths(repo_root: Path, config: Config) -> list[Path]:
    """Turn the `packs` entries into real paths: '~' is expanded, relative means repo root."""
    paths = []
    for entry in config.rules.packs:
        path = Path(entry).expanduser()
        if not path.is_absolute():
            path = repo_root / path
        paths.append(path)
    return paths
