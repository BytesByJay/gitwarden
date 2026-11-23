"""Rules: what a secret looks like. Loads the built-in pack and client rule packs."""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from gitwarden.errors import GitWardenError, describe

Severity = Literal["low", "medium", "high"]
SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3}
BUILTIN_PACK = Path(__file__).parent / "builtin_rules.toml"
ID_PATTERN = r"^[a-z0-9][a-z0-9-]*$"


class RuleSpec(BaseModel):
    """One [[rules]] entry exactly as written in a pack file."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ID_PATTERN)
    description: str
    severity: Severity
    keywords: list[str] = Field(min_length=1)
    regex: str
    secret_group: int = Field(default=0, ge=0)
    min_entropy: float = Field(default=0, ge=0)
    stopwords: list[str] = []
    enabled: bool = True


class PackInfo(BaseModel):
    """The [pack] table of a pack file."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ID_PATTERN)
    description: str = ""


class PackSpec(BaseModel):
    """A whole pack file."""

    model_config = ConfigDict(extra="forbid")

    pack: PackInfo
    rules: list[RuleSpec] = Field(min_length=1)


@dataclass
class Rule:
    """A ready-to-use rule: the regex is compiled, keywords and stopwords are lowercase."""

    id: str  # "<pack id>/<rule id>", for example "generic/aws-access-key-id"
    description: str
    severity: str
    keywords: list[str]
    regex: re.Pattern[str]
    secret_group: int
    min_entropy: float
    stopwords: list[str]
    enabled: bool


def load_pack(path: Path) -> tuple[str, list[Rule]]:
    """Read and check one pack file. Returns (pack id, rules). Any problem raises GitWardenError."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as err:
        raise GitWardenError(f"rule pack {path}: cannot read it ({err.strerror})") from err
    except tomllib.TOMLDecodeError as err:
        raise GitWardenError(f"rule pack {path}: not valid TOML: {err}") from err
    try:
        spec = PackSpec.model_validate(data)
    except ValidationError as err:
        raise GitWardenError(f"rule pack {path}: {describe(err)}") from err

    rules = []
    seen_ids = set()
    for rule_spec in spec.rules:
        if rule_spec.id in seen_ids:
            raise GitWardenError(f"rule pack {path}: rule id '{rule_spec.id}' is used twice")
        seen_ids.add(rule_spec.id)
        rules.append(_build_rule(spec.pack.id, rule_spec, path))
    return spec.pack.id, rules


def load_all_rules(pack_paths: list[Path]) -> list[Rule]:
    """Every rule from the built-in pack and the client packs, switched on or not."""
    all_rules: list[Rule] = []
    seen_packs: dict[str, Path] = {}
    for path in [BUILTIN_PACK, *pack_paths]:
        pack_id, rules = load_pack(path)
        if pack_id in seen_packs:
            raise GitWardenError(
                f"rule pack {path}: pack id '{pack_id}' is already used by {seen_packs[pack_id]}"
            )
        seen_packs[pack_id] = path
        all_rules.extend(rules)
    return all_rules


def load_rules(pack_paths: list[Path], enable: list[str], disable: list[str]) -> list[Rule]:
    """Load the built-in pack plus client packs and return the rules that are switched on.

    `enable` turns on rules that are off by default; `disable` turns rules off.
    Unknown rule ids in either list are an error, so a typo can't silently weaken protection.
    """
    all_rules = load_all_rules(pack_paths)
    known_ids = {rule.id for rule in all_rules}
    for rule_id in [*enable, *disable]:
        if rule_id not in known_ids:
            raise GitWardenError(
                f"config: unknown rule id '{rule_id}' (see `gitwarden rules list`)"
            )

    active = []
    for rule in all_rules:
        switched_on = (rule.enabled or rule.id in enable) and rule.id not in disable
        if switched_on:
            active.append(rule)
    return active


def _build_rule(pack_id: str, spec: RuleSpec, path: Path) -> Rule:
    """Compile the regex and check that `secret_group` exists in it."""
    full_id = f"{pack_id}/{spec.id}"
    try:
        regex = re.compile(spec.regex)
    except re.error as err:
        raise GitWardenError(f"rule pack {path}: rule '{spec.id}' has a bad regex: {err}") from err
    if spec.secret_group > regex.groups:
        raise GitWardenError(
            f"rule pack {path}: rule '{spec.id}' uses secret_group {spec.secret_group}, "
            f"but its regex has only {regex.groups} group(s)"
        )
    return Rule(
        id=full_id,
        description=spec.description,
        severity=spec.severity,
        keywords=[keyword.lower() for keyword in spec.keywords],
        regex=regex,
        secret_group=spec.secret_group,
        min_entropy=spec.min_entropy,
        stopwords=[word.lower() for word in spec.stopwords],
        enabled=spec.enabled,
    )
