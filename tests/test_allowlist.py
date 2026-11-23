from datetime import date

import pytest

from gitwarden.allowlist import (
    ALLOW_FILE,
    AllowEntry,
    add_entry,
    check_new_entry,
    fingerprint,
    load_allowlist,
)
from gitwarden.errors import GitWardenError

TODAY = date(2026, 11, 23)


def make_entry(**changes) -> AllowEntry:
    values = {
        "fingerprint": fingerprint("generic/jwt", "tests/a.py", "eyJfake"),
        "rule": "generic/jwt",
        "path": "tests/a.py",
        "reason": 'Fake token in a "unit" test',
        "added_by": "Asha Nair",
        "added": TODAY,
        "expires": date(2027, 1, 31),
    }
    values.update(changes)
    return AllowEntry(**values)


def test_fingerprint_is_short_stable_and_depends_on_path():
    first = fingerprint("generic/jwt", "a.py", "secret-value")
    assert len(first) == 12
    assert first == fingerprint("generic/jwt", "a.py", "secret-value")
    assert first != fingerprint("generic/jwt", "b.py", "secret-value")
    assert "secret" not in first


def test_missing_file_means_empty_allowlist(tmp_path):
    assert load_allowlist(tmp_path) == {}


def test_add_entry_then_load_gives_the_same_entry(tmp_path):
    entry = make_entry()
    add_entry(tmp_path, entry)
    add_entry(tmp_path, make_entry(fingerprint="0123456789ab", path="tests/b.py"))
    loaded = load_allowlist(tmp_path)
    assert loaded[entry.fingerprint] == entry
    assert len(loaded) == 2
    assert (tmp_path / ALLOW_FILE).read_text(encoding="utf-8").startswith("# Reviewed")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[[allow]]\nfingerprint = 'abc'\n", "allow.0"),
        ("not toml [", "not valid TOML"),
    ],
)
def test_broken_file_is_an_error(tmp_path, text, message):
    (tmp_path / ALLOW_FILE).write_text(text, encoding="utf-8")
    with pytest.raises(GitWardenError, match=message):
        load_allowlist(tmp_path)


def test_duplicate_fingerprint_is_an_error(tmp_path):
    add_entry(tmp_path, make_entry())
    add_entry(tmp_path, make_entry())
    with pytest.raises(GitWardenError, match="listed twice"):
        load_allowlist(tmp_path)


def test_new_entry_needs_reason_and_sensible_expiry():
    check_new_entry("fake value", date(2027, 2, 21), TODAY, max_days=90)
    with pytest.raises(GitWardenError, match="--reason is required"):
        check_new_entry("   ", date(2027, 1, 1), TODAY, max_days=90)
    with pytest.raises(GitWardenError, match="after today"):
        check_new_entry("fake", TODAY, TODAY, max_days=90)
    with pytest.raises(GitWardenError, match="at most 90 days"):
        check_new_entry("fake", date(2027, 2, 22), TODAY, max_days=90)
