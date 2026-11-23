from pathlib import Path

import pytest

from gitwarden.errors import GitWardenError
from gitwarden.rules import load_all_rules, load_pack, load_rules

GOOD_PACK = """\
[pack]
id = "acme"
description = "Acme client rules"

[[rules]]
id = "project-codename"
description = "Acme's secret project name"
severity = "high"
keywords = ["bluebird"]
regex = '''(?i)\\b(bluebird-[0-9]{3})\\b'''
secret_group = 1
"""


def write_pack(tmp_path: Path, text: str, name: str = "pack.toml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_load_pack_builds_namespaced_rules(tmp_path):
    pack_id, rules = load_pack(write_pack(tmp_path, GOOD_PACK))
    assert pack_id == "acme"
    assert [rule.id for rule in rules] == ["acme/project-codename"]
    rule = rules[0]
    assert rule.keywords == ["bluebird"]
    assert rule.regex.search("ship BlueBird-042 today").group(1) == "BlueBird-042"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (('severity = "high"', 'severity = "urgent"'), "severity"),
        (("secret_group = 1", "secret_group = 3"), "only 1 group"),
        (("regex = '''", "regex = '''(\n"), "bad regex"),
        (("secret_group = 1", 'secret_group = 1\ncolour = "red"'), "colour"),
        (('id = "acme"', 'id = "Acme Corp"'), "pack.id"),
    ],
)
def test_broken_packs_fail_loudly_with_file_name(tmp_path, change, message):
    path = write_pack(tmp_path, GOOD_PACK.replace(*change))
    with pytest.raises(GitWardenError) as error:
        load_pack(path)
    assert str(path) in str(error.value)
    assert message in str(error.value)


def test_not_toml_and_missing_file_are_errors(tmp_path):
    with pytest.raises(GitWardenError, match="not valid TOML"):
        load_pack(write_pack(tmp_path, "this is = = not toml"))
    with pytest.raises(GitWardenError, match="cannot read"):
        load_pack(tmp_path / "missing.toml")


def test_duplicate_rule_id_in_one_pack_is_an_error(tmp_path):
    rule_block = GOOD_PACK.split("[[rules]]")[1]
    path = write_pack(tmp_path, GOOD_PACK + "\n[[rules]]" + rule_block)
    with pytest.raises(GitWardenError, match="used twice"):
        load_pack(path)


def test_load_rules_includes_builtin_and_client_packs(tmp_path):
    rules = load_rules([write_pack(tmp_path, GOOD_PACK)], enable=[], disable=[])
    ids = [rule.id for rule in rules]
    assert "generic/aws-access-key-id" in ids
    assert "acme/project-codename" in ids


def test_rules_that_are_off_by_default_need_enable():
    ids = [rule.id for rule in load_rules([], enable=[], disable=[])]
    assert "generic/high-entropy-string" not in ids
    enabled = load_rules([], enable=["generic/high-entropy-string"], disable=[])
    assert "generic/high-entropy-string" in [rule.id for rule in enabled]


def test_disable_turns_a_rule_off():
    ids = [rule.id for rule in load_rules([], enable=[], disable=["generic/jwt"])]
    assert "generic/jwt" not in ids


def test_unknown_rule_id_in_enable_or_disable_is_an_error():
    with pytest.raises(GitWardenError, match="unknown rule id 'generic/jwtt'"):
        load_rules([], enable=[], disable=["generic/jwtt"])


def test_same_pack_id_twice_is_an_error(tmp_path):
    first = write_pack(tmp_path, GOOD_PACK, "one.toml")
    second = write_pack(tmp_path, GOOD_PACK, "two.toml")
    with pytest.raises(GitWardenError, match="already used"):
        load_rules([first, second], enable=[], disable=[])


def test_load_all_rules_includes_rules_that_are_off():
    ids = [rule.id for rule in load_all_rules([])]
    assert "generic/high-entropy-string" in ids
