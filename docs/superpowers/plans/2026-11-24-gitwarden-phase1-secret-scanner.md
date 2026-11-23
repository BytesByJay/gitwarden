# GitWarden Phase 0–1: Secret Scanner and Hooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `gitwarden` Python package and CLI that blocks commits and pushes containing secrets, offline, on Linux, macOS and Windows, in under one second for a typical change.

**Architecture:** Small single-purpose modules with plain functions and dataclasses. `git.py` is the only module that runs git; `diff.py` turns diff text into added lines; `scanner.py` applies TOML-defined rules (keyword check → regex → entropy/stopwords → allowlist) with no I/O; `report.py` formats output; `hooks.py` installs a tiny `sh` hook script and runs the checks; `cli.py` is the Typer front end. Pydantic only validates the hand-written TOML files.

**Tech Stack:** Python 3.11+ (`tomllib`), Typer, Pydantic 2, pytest, ruff, git 2.36+, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-23-gitwarden-phase1-secret-scanner-design.md`

## Global Constraints

- Python `>=3.11`; git `>=2.36` (checked at runtime; needed for `--remerge-diff`).
- Runtime dependencies: `typer>=0.12`, `pydantic>=2.6` only. Dev: `pytest>=8`, `ruff>=0.6`.
- Must work on Linux, macOS and Windows (Git for Windows runs hooks with its bundled `sh`).
- **Code must be simple enough for a junior developer:** plain functions and `@dataclass`; no class hierarchies, ABCs, metaclasses, plugin registries, own decorators or DI frameworks; Pydantic only for the two hand-written TOML file types (config, rule packs) and the allowlist file; modules under ~200 lines (cli.py may be slightly over), functions under ~30 lines; type hints everywhere; docstrings say *why*; clear names; error messages say what to do next.
- Never store or print a raw secret: findings carry only a redacted line and a 12-hex fingerprint.
- Exit codes everywhere: `0` clean, `1` blocking findings, `2` GitWarden could not run (also blocks).
- Messages never mention `--no-verify`.
- Output is ASCII only.
- Ruff: line length 100, rules `E, F, I, B, UP`; code must pass `ruff check` and `ruff format --check`.
- Every commit message ends with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Commands below use `.venv/bin/...`; on Windows use `.venv\Scripts\...`.

## File map

| File | Job |
|---|---|
| `pyproject.toml` | Package metadata, deps, `gitwarden` console script, pytest and ruff settings |
| `src/gitwarden/__init__.py` | `__version__` |
| `src/gitwarden/__main__.py` | Entry point; sends `hook ...` straight to `hooks.run_hook` (fast path, no Typer) |
| `src/gitwarden/errors.py` | `GitWardenError` and `describe()` for Pydantic errors |
| `src/gitwarden/diff.py` | Diff text → `AddedLine`s and binary paths |
| `src/gitwarden/rules.py` | Rule pack models, loader, enable/disable |
| `src/gitwarden/builtin_rules.toml` | The 23 built-in rules (22 on, 1 off by default) |
| `src/gitwarden/config.py` | `.gitwarden.toml` models and loader |
| `src/gitwarden/allowlist.py` | Fingerprints, `.gitwarden-allow.toml` read/write, entry checks |
| `src/gitwarden/scanner.py` | `scan()`: file skipping, rule matching, redaction, allowlist |
| `src/gitwarden/report.py` | Text for blocked commits/pushes and allowlist listings |
| `src/gitwarden/git.py` | Every git call |
| `src/gitwarden/hooks.py` | Hook script, install/uninstall, `run_hook`, shared scan helpers |
| `src/gitwarden/cli.py` | Typer commands |
| `tests/conftest.py` | `repo` fixture and git helpers |
| `tests/fakes.py` | Fake secret generator for the test set |
| `tests/corpus/leaks.toml`, `tests/corpus/clean.toml` | The test set (66 leak cases, 30 clean cases) |
| `.github/workflows/ci.yml` | CI: 3 OSes × Python 3.11 and 3.13 |

---

## Tasks


### Task 1: Project setup: package, CLI with --version, CI

**Why:** Gives every later task a package to add to, a test runner, lint, and CI on all three OSes.

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.gitattributes`
- Create: `src/gitwarden/__init__.py`
- Create: `src/gitwarden/errors.py`
- Create: `src/gitwarden/__main__.py`
- Create: `src/gitwarden/cli.py`
- Create: `.github/workflows/ci.yml`
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `gitwarden.__version__: str` = `"0.1.0"`
  - `gitwarden.errors.GitWardenError(Exception)`: raised for every setup problem; hooks turn it into exit code 2
  - `gitwarden.errors.describe(err: pydantic.ValidationError) -> str`: short `field: message` text
  - `gitwarden.cli.app: typer.Typer` (Task 11 replaces this file with the full CLI)
  - `gitwarden.__main__.main() -> None`: `python -m gitwarden hook <name> ...` calls `gitwarden.hooks.run_hook` (written in Task 10) without importing Typer; anything else runs `cli.app`

**Notes:**
- The repo already has `README.md` (`# gitwarden`); leave it, Task 12 rewrites it.
- `__main__.py` imports `gitwarden.hooks` only when the first argument is `hook`, so it works now even though `hooks.py` arrives in Task 10.

- [ ] **Step 1: Create `pyproject.toml`**

````toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "gitwarden"
version = "0.1.0"
description = "Local Git assistant that blocks secrets before they leave your machine"
readme = "README.md"
requires-python = ">=3.11"
dependencies = ["typer>=0.12", "pydantic>=2.6"]

[project.optional-dependencies]
dev = ["pytest>=8", "ruff>=0.6"]

[project.scripts]
gitwarden = "gitwarden.__main__:main"

[tool.hatch.build.targets.wheel]
packages = ["src/gitwarden"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["perf: speed checks that run the real hook"]

[tool.ruff]
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]
````

- [ ] **Step 2: Create `.gitignore`**

````
.venv/
__pycache__/
*.egg-info/
.pytest_cache/
.ruff_cache/
dist/
build/
````

- [ ] **Step 3: Create `.gitattributes`**

````
* text=auto eol=lf
````

- [ ] **Step 4: Create the virtual environment with the tools**

```bash
python3 -m venv .venv
.venv/bin/pip install "typer>=0.12" "pydantic>=2.6" "pytest>=8" "ruff>=0.6"
```

(Windows: `py -3.11 -m venv .venv` and use `.venv\Scripts\` instead of `.venv/bin/` in every command.)

- [ ] **Step 5: Write the failing test: `tests/test_cli.py`**

````python
import subprocess
import sys

from typer.testing import CliRunner

from gitwarden import __version__
from gitwarden.cli import app

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_python_dash_m_runs_the_cli():
    result = subprocess.run(
        [sys.executable, "-m", "gitwarden", "--version"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert __version__ in result.stdout
````

- [ ] **Step 6: Run the test and watch it fail**

```bash
.venv/bin/pytest tests/test_cli.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gitwarden'` (nothing is written yet).

- [ ] **Step 7: Write `src/gitwarden/__init__.py`**

````python
"""GitWarden: blocks secrets before they leave your machine."""

__version__ = "0.1.0"
````

- [ ] **Step 8: Write `src/gitwarden/errors.py`**

````python
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
````

- [ ] **Step 9: Write `src/gitwarden/__main__.py`**

````python
"""`python -m gitwarden` and the `gitwarden` command start here."""

import sys


def main() -> None:
    """Hooks go straight to hooks.run_hook (skipping the CLI library keeps them fast)."""
    for stream in (sys.stdout, sys.stderr):
        # Never crash on a character the console can't show (Windows consoles).
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    if len(sys.argv) >= 3 and sys.argv[1] == "hook":
        from gitwarden.hooks import run_hook

        hook_name = sys.argv[2]
        stdin_text = sys.stdin.read() if hook_name == "pre-push" else ""
        sys.exit(run_hook(hook_name, sys.argv[3:], stdin_text))

    from gitwarden.cli import app

    app()


if __name__ == "__main__":
    main()
````

- [ ] **Step 10: Write `src/gitwarden/cli.py`**

````python
"""The `gitwarden` command. Task 11 adds scan, install, uninstall, allow and rules."""

from typing import Annotated

import typer

from gitwarden import __version__

app = typer.Typer(
    help="GitWarden blocks secrets before they leave your machine.",
    no_args_is_help=True,
    add_completion=False,
)


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
````

- [ ] **Step 11: Write `.github/workflows/ci.yml`**

````yaml
name: CI

on:
  push:
  pull_request:

jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
        python: ["3.11", "3.13"]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - name: Install
        run: python -m pip install -e ".[dev]"
      - name: Lint
        run: |
          ruff check .
          ruff format --check .
      - name: Test
        run: pytest -v
````

- [ ] **Step 12: Install the package with dev tools**

```bash
.venv/bin/pip install -e ".[dev]"
```

- [ ] **Step 13: Run the tests and see them pass**

```bash
.venv/bin/pytest tests/test_cli.py -v
```

Expected: all PASS.

- [ ] **Step 14: Run the whole suite and lint**

```bash
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Expected: everything passes, `All checks passed!`, no files to reformat.

- [ ] **Step 15: Commit**

```bash
git add pyproject.toml .gitignore .gitattributes tests/test_cli.py src/gitwarden/__init__.py src/gitwarden/errors.py src/gitwarden/__main__.py src/gitwarden/cli.py .github/workflows/ci.yml
git commit -m "Set up package, CLI --version and CI

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```


### Task 2: Diff parser

**Why:** Turns `git diff` text into the added lines the scanner checks. Pure string work, no git needed.

**Files:**
- Create: `src/gitwarden/diff.py`
- Create: `tests/test_diff.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `@dataclass AddedLine(path: str, line_no: int, text: str, commit: str | None = None)`
  - `@dataclass ParsedDiff(lines: list[AddedLine] = [], binary_paths: list[str] = [])`
  - `parse_diff(diff_text: str, commit: str | None = None) -> ParsedDiff`
  - `lines_from_file(path: str, content: str) -> list[AddedLine]`

**Notes:**
- Header lines (`---`, `+++`, `Binary files ...`) are only read before a file's first `@@`. After that, a line starting with `+` is always content, even `+++ text`.

- [ ] **Step 1: Write the failing test: `tests/test_diff.py`**

````python
from gitwarden.diff import AddedLine, lines_from_file, parse_diff

NEW_FILE_DIFF = """\
diff --git a/app/settings.py b/app/settings.py
new file mode 100644
index 0000000..3b18e51
--- /dev/null
+++ b/app/settings.py
@@ -0,0 +1,2 @@
+DEBUG = False
+TOKEN = "abc"
"""

MODIFIED_DIFF = """\
diff --git a/config.yml b/config.yml
index 1111111..2222222 100644
--- a/config.yml
+++ b/config.yml
@@ -3 +3 @@ name: app
-password: old
+password: new
@@ -10,0 +11,2 @@ other:
+  a: 1
+  b: 2
"""


def test_new_file_lines_are_added_with_line_numbers():
    parsed = parse_diff(NEW_FILE_DIFF)
    assert parsed.lines == [
        AddedLine("app/settings.py", 1, "DEBUG = False"),
        AddedLine("app/settings.py", 2, 'TOKEN = "abc"'),
    ]


def test_removed_lines_are_ignored_and_hunks_set_line_numbers():
    parsed = parse_diff(MODIFIED_DIFF)
    assert [(line.line_no, line.text) for line in parsed.lines] == [
        (3, "password: new"),
        (11, "  a: 1"),
        (12, "  b: 2"),
    ]


def test_added_line_that_starts_with_plus_signs_is_content_not_header():
    diff = MODIFIED_DIFF + "@@ -20,0 +21 @@\n+++ not a header\n"
    parsed = parse_diff(diff)
    assert parsed.lines[-1] == AddedLine("config.yml", 21, "++ not a header")


def test_binary_files_are_reported_not_scanned():
    diff = (
        "diff --git a/logo.png b/logo.png\n"
        "new file mode 100644\n"
        "index 0000000..1234567\n"
        "Binary files /dev/null and b/logo.png differ\n"
    )
    parsed = parse_diff(diff)
    assert parsed.lines == []
    assert parsed.binary_paths == ["logo.png"]


def test_renamed_file_uses_new_name_and_no_newline_marker_is_ignored():
    diff = (
        "diff --git a/old name.txt b/new name.txt\n"
        "similarity index 80%\n"
        "rename from old name.txt\n"
        "rename to new name.txt\n"
        "--- a/old name.txt\t\n"
        "+++ b/new name.txt\t\n"
        "@@ -1 +1 @@\n"
        "-hello\n"
        "+hello world\n"
        "\\ No newline at end of file\n"
    )
    parsed = parse_diff(diff)
    assert parsed.lines == [AddedLine("new name.txt", 1, "hello world")]


def test_commit_sha_is_attached_and_crlf_is_stripped():
    diff = NEW_FILE_DIFF.replace("+DEBUG = False\n", "+DEBUG = False\r\n")
    parsed = parse_diff(diff, commit="abc123")
    assert parsed.lines[0] == AddedLine("app/settings.py", 1, "DEBUG = False", "abc123")


def test_lines_from_file_numbers_every_line():
    assert lines_from_file("a.txt", "one\r\ntwo\n") == [
        AddedLine("a.txt", 1, "one"),
        AddedLine("a.txt", 2, "two"),
        AddedLine("a.txt", 3, ""),
    ]
````

- [ ] **Step 2: Run the test and watch it fail**

```bash
.venv/bin/pytest tests/test_diff.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gitwarden.diff'`.

- [ ] **Step 3: Write `src/gitwarden/diff.py`**

````python
"""Turn `git diff` output into the list of lines that were added.

We only scan added lines: deleting a secret should never block a commit.
"""

import re
from dataclasses import dataclass, field

# "@@ -10,2 +12,3 @@" -> the new file's changes start at line 12
HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
# "Binary files /dev/null and b/logo.png differ"
BINARY_LINE = re.compile(r"^Binary files (.+?) and (.+) differ$")


@dataclass
class AddedLine:
    """One added line: which file, which line number, and its text."""

    path: str
    line_no: int
    text: str
    commit: str | None = None  # None for staged changes, else the commit SHA


@dataclass
class ParsedDiff:
    """Everything a diff tells the scanner: added lines and binary files."""

    lines: list[AddedLine] = field(default_factory=list)
    binary_paths: list[str] = field(default_factory=list)


def parse_diff(diff_text: str, commit: str | None = None) -> ParsedDiff:
    """Read unified diff text (from `git diff` or `git show`) and collect the added lines."""
    result = ParsedDiff()
    path: str | None = None  # file we are in; None for deleted files
    in_hunk = False  # False while reading a file's header lines
    line_no = 0  # line number in the new file of the next added or context line

    for raw in diff_text.split("\n"):
        if raw.startswith("diff --git "):
            path, in_hunk = None, False
            continue
        hunk = HUNK_HEADER.match(raw)
        if hunk:
            in_hunk = True
            line_no = int(hunk.group(1))
            continue
        if not in_hunk:
            path = _read_header_line(raw, path, result)
            continue
        if raw.startswith("+"):
            if path is not None:
                result.lines.append(AddedLine(path, line_no, raw[1:].rstrip("\r"), commit))
            line_no += 1
        elif raw.startswith(" "):
            line_no += 1
        # "-" lines and "\ No newline at end of file" don't move the new file's line number

    return result


def lines_from_file(path: str, content: str) -> list[AddedLine]:
    """Treat every line of a whole file as added (used by `gitwarden scan PATH`)."""
    lines = []
    for number, text in enumerate(content.split("\n"), start=1):
        lines.append(AddedLine(path, number, text.rstrip("\r")))
    return lines


def _read_header_line(raw: str, path: str | None, result: ParsedDiff) -> str | None:
    """Handle one line from a file's header. Returns the (maybe new) current path."""
    if raw.startswith("+++ "):
        return _clean_path(raw[4:])
    binary = BINARY_LINE.match(raw)
    if binary:
        binary_path = _clean_path(binary.group(2))
        if binary_path is not None:
            result.binary_paths.append(binary_path)
    return path


def _clean_path(name: str) -> str | None:
    """'b/src/app.py' -> 'src/app.py'; '/dev/null' (file deleted) -> None."""
    name = name.rstrip("\t")  # git adds a tab after file names that contain spaces
    if name.startswith('"') and name.endswith('"'):
        name = name[1:-1]  # git quotes names with special characters
    if name == "/dev/null":
        return None
    if name.startswith("b/"):
        return name[2:]
    return name
````

- [ ] **Step 4: Run the tests and see them pass**

```bash
.venv/bin/pytest tests/test_diff.py -v
```

Expected: all PASS.

- [ ] **Step 5: Run the whole suite and lint**

```bash
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Expected: everything passes, `All checks passed!`, no files to reformat.

- [ ] **Step 6: Commit**

```bash
git add tests/test_diff.py src/gitwarden/diff.py
git commit -m "Add diff parser for added lines

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```


### Task 3: Rules: pack format, loader, built-in rules

**Why:** Defines what a secret looks like. The built-in pack is final here; Task 7 proves it with the test set.

**Files:**
- Create: `src/gitwarden/rules.py`
- Create: `src/gitwarden/builtin_rules.toml`
- Create: `tests/test_rules.py`

**Interfaces:**
- Consumes: `GitWardenError`, `describe` (Task 1)
- Produces:
  - `Severity = Literal["low", "medium", "high"]`, `SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3}`
  - `@dataclass Rule(id: str, description: str, severity: str, keywords: list[str], regex: re.Pattern[str], secret_group: int, min_entropy: float, stopwords: list[str], enabled: bool)`; `id` is `"<pack>/<rule>"`, keywords and stopwords are lowercase
  - `load_pack(path: Path) -> tuple[str, list[Rule]]`
  - `load_all_rules(pack_paths: list[Path]) -> list[Rule]`: built-in pack first, then client packs, on or off
  - `load_rules(pack_paths: list[Path], enable: list[str], disable: list[str]) -> list[Rule]`: only the rules that are switched on

**Notes:**
- Rule order matters: when two rules find the same secret on a line, the first wins. Specific rules come first in `builtin_rules.toml`, generic ones last.
- Regexes are TOML literal strings (`'''...'''`), so backslashes are written once.

- [ ] **Step 1: Write the failing test: `tests/test_rules.py`**

````python
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
````

- [ ] **Step 2: Run the test and watch it fail**

```bash
.venv/bin/pytest tests/test_rules.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gitwarden.rules'`.

- [ ] **Step 3: Write `src/gitwarden/rules.py`**

````python
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
````

- [ ] **Step 4: Write `src/gitwarden/builtin_rules.toml`**

````toml
# GitWarden's built-in rules.
#
# Each [[rules]] entry finds one kind of secret. How a line is checked:
#   1. the line must contain one of the rule's `keywords` (any case), else the rule is skipped
#   2. the `regex` must match; capture group `secret_group` is the secret
#   3. the secret must have at least `min_entropy` randomness and contain none of the `stopwords`
#
# Order matters: when two rules find the same secret on a line, the first rule wins.
# So specific rules (AWS, GitHub, ...) come first and the generic ones come last.

[pack]
id = "generic"
description = "Generic credentials: cloud keys, tokens, private keys, passwords"

# catches: -----BEGIN RSA PRIVATE KEY-----
[[rules]]
id = "private-key"
description = "Private key block"
severity = "high"
keywords = ["private key"]
regex = '''-----BEGIN[A-Z ]*PRIVATE KEY(?: BLOCK)?-----'''
secret_group = 0

# catches: AWS_ACCESS_KEY_ID=AKIA + 16 upper-case letters or digits
[[rules]]
id = "aws-access-key-id"
description = "AWS access key ID"
severity = "high"
keywords = ["akia", "asia", "abia", "acca"]
regex = '''\b((?:AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16})\b'''
secret_group = 1
stopwords = ["example"]

# catches: aws_secret_access_key = <40 base64 characters>
[[rules]]
id = "aws-secret-access-key"
description = "AWS secret access key"
severity = "high"
keywords = ["secret_access_key", "secretaccesskey", "secret-access-key", "secret.access.key"]
regex = '''(?i)aws[_.-]?secret[_.-]?access[_.-]?key["']?\s*[:=]\s*["']?([A-Za-z0-9/+]{40})(?![A-Za-z0-9/+=])'''
secret_group = 1
min_entropy = 3.0
stopwords = ["example"]

# catches: "private_key_id": "<40 hex characters>" in a GCP service-account JSON file
[[rules]]
id = "gcp-service-account"
description = "Google Cloud service-account key file"
severity = "high"
keywords = ["private_key_id"]
regex = '''"private_key_id"\s*:\s*"([a-f0-9]{40})"'''
secret_group = 1

# catches: AccountKey=<86 base64 characters>== in an Azure storage connection string
[[rules]]
id = "azure-storage-key"
description = "Azure storage account key"
severity = "high"
keywords = ["accountkey"]
regex = '''(?i)AccountKey=([A-Za-z0-9+/]{86}==)'''
secret_group = 1

# catches: ghp_ + 36 letters or digits (also gho_, ghu_, ghs_, ghr_)
[[rules]]
id = "github-token"
description = "GitHub token"
severity = "high"
keywords = ["ghp_", "gho_", "ghu_", "ghs_", "ghr_"]
regex = '''\b((?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36})\b'''
secret_group = 1

# catches: github_pat_ + 82 letters, digits or underscores
[[rules]]
id = "github-fine-grained-token"
description = "GitHub fine-grained personal access token"
severity = "high"
keywords = ["github_pat_"]
regex = '''\b(github_pat_[A-Za-z0-9_]{82})\b'''
secret_group = 1

# catches: glpat- + 20 or more letters, digits, - or _
[[rules]]
id = "gitlab-token"
description = "GitLab personal access token"
severity = "high"
keywords = ["glpat-"]
regex = '''\b(glpat-[A-Za-z0-9_-]{20,})'''
secret_group = 1

# catches: xoxb-1234-5678-abcd... (also xoxa-, xoxp-, xoxr-, xoxs-)
[[rules]]
id = "slack-token"
description = "Slack token"
severity = "high"
keywords = ["xox"]
regex = '''\b(xox[abprs]-[0-9A-Za-z-]{10,})'''
secret_group = 1

# catches: https://hooks.slack.com/services/T.../B.../...
[[rules]]
id = "slack-webhook"
description = "Slack incoming webhook URL"
severity = "high"
keywords = ["hooks.slack.com"]
regex = '''(https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]{20,})'''
secret_group = 1

# catches: sk_live_... or rk_live_...
[[rules]]
id = "stripe-live-key"
description = "Stripe live secret or restricted key"
severity = "high"
keywords = ["_live_"]
regex = '''\b((?:sk|rk)_live_[A-Za-z0-9]{20,})\b'''
secret_group = 1

# catches: SG.<22 characters>.<43 characters>
[[rules]]
id = "sendgrid-key"
description = "SendGrid API key"
severity = "high"
keywords = ["sg."]
regex = '''\b(SG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43})(?![A-Za-z0-9_-])'''
secret_group = 1

# catches: AIza + 35 characters
[[rules]]
id = "google-api-key"
description = "Google API key"
severity = "high"
keywords = ["aiza"]
regex = '''\b(AIza[0-9A-Za-z_-]{35})(?![0-9A-Za-z_-])'''
secret_group = 1

# catches: npm_ + 36 letters or digits
[[rules]]
id = "npm-token"
description = "npm access token"
severity = "high"
keywords = ["npm_"]
regex = '''\b(npm_[A-Za-z0-9]{36})\b'''
secret_group = 1

# catches: sk-proj-..., sk-ant-..., sk-... (OpenAI, Anthropic and similar LLM API keys)
[[rules]]
id = "llm-api-key"
description = "LLM provider API key (OpenAI, Anthropic and similar)"
severity = "high"
keywords = ["sk-"]
regex = '''\b(sk-[A-Za-z0-9_-]{32,})'''
secret_group = 1
min_entropy = 3.5

# catches: eyJhbGciOi....eyJzdWIiOi....signature
[[rules]]
id = "jwt"
description = "JSON Web Token"
severity = "medium"
keywords = ["eyj"]
regex = '''\b(eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})'''
secret_group = 1

# catches: postgres://app:s3cretPass@db.internal:5432/app (also mysql, mongodb, redis, amqp)
[[rules]]
id = "database-url-password"
description = "Database or queue URL with a password in it"
severity = "high"
keywords = ["postgres", "mysql", "mongodb", "redis", "amqp"]
regex = '''(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|rediss?|amqps?)://[^:/\s"'@]*:([^@/\s"']+)@'''
secret_group = 1
stopwords = ["$", "{{", "<", "%s", "password", "changeme", "example"]

# catches: jdbc:sqlserver://db;user=app;password=s3cretPass
[[rules]]
id = "jdbc-password"
description = "JDBC connection string with a password in it"
severity = "high"
keywords = ["jdbc:"]
regex = '''(?i)jdbc:[a-z0-9]+:[^\s"']*[;?&]password=([^;&\s"']+)'''
secret_group = 1
stopwords = ["$", "{{", "<", "%s", "password", "changeme", "example"]

# catches: https://deploy:s3cretPass@git.internal/repo.git
[[rules]]
id = "url-credentials"
description = "Web URL with a username and password in it"
severity = "medium"
keywords = ["http"]
regex = '''(?i)\bhttps?://[^:/\s"'@]+:([^@/\s"']{3,})@'''
secret_group = 1
stopwords = ["$", "{{", "<", "%s", "password", "changeme", "example"]

# catches: Authorization: Basic dXNlcjpwYXNzd29yZA==
[[rules]]
id = "basic-auth-header"
description = "HTTP Basic authorization header"
severity = "medium"
keywords = ["authorization"]
regex = '''(?i)authorization["']?\s*[:=]\s*["']?basic\s+([A-Za-z0-9+/]{8,}={0,2})'''
secret_group = 1

# catches: db_password = "s3cretPass99", "apiKey": "...", SECRET_KEY = '...'
[[rules]]
id = "secret-assignment"
description = "Password, secret, token or API key written in quotes"
severity = "medium"
keywords = ["pass", "pwd", "secret", "token", "key"]
regex = '''(?i)(?:password|passwd|pwd|secret|secret[_-]?key|token|api[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret)["']?\s*(?::=|=>|[:=])\s*["']([^"'\s]{8,})["']'''
secret_group = 1
min_entropy = 3.0
stopwords = ["example", "changeme", "placeholder", "your", "xxxx", "dummy", "test", "fake", "sample", "redacted", "<", "{{", "${", "%s"]

# catches: DB_PASSWORD=s3cretPass99 in .env files, password: s3cretPass99 in YAML
[[rules]]
id = "password-unquoted"
description = "Password written without quotes (.env, YAML, .properties)"
severity = "medium"
keywords = ["pass", "pwd"]
regex = '''(?i)^\s*(?:export\s+)?[a-z0-9_.-]*(?:password|passwd|pwd)\s*[=:]\s*([^\s"'#$(){}\[\]<>,;]{8,})\s*$'''
secret_group = 1
min_entropy = 2.5
stopwords = ["example", "changeme", "placeholder", "your", "xxxx", "dummy", "test", "fake", "sample", "redacted", "password"]

# catches: any long random-looking string in quotes. Off by default: too noisy without the LLM review.
[[rules]]
id = "high-entropy-string"
description = "Long random-looking string in quotes"
severity = "low"
keywords = ["\"", "'"]
regex = '''["']([A-Za-z0-9+/=_-]{32,})["']'''
secret_group = 1
min_entropy = 4.5
enabled = false
````

- [ ] **Step 5: Run the tests and see them pass**

```bash
.venv/bin/pytest tests/test_rules.py -v
```

Expected: all PASS.

- [ ] **Step 6: Run the whole suite and lint**

```bash
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Expected: everything passes, `All checks passed!`, no files to reformat.

- [ ] **Step 7: Commit**

```bash
git add tests/test_rules.py src/gitwarden/rules.py src/gitwarden/builtin_rules.toml
git commit -m "Add rule pack loader and built-in rules

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```


### Task 4: Config file (.gitwarden.toml)

**Why:** One committed file per repo holds the team's settings. Typos are errors so protection can't be switched off by accident.

**Files:**
- Create: `src/gitwarden/config.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Consumes: `GitWardenError`, `describe` (Task 1); `Severity` (Task 3)
- Produces:
  - `CONFIG_FILE = ".gitwarden.toml"`
  - Pydantic models `Config(hooks: HooksConfig, scan: ScanConfig, rules: RulesConfig, allowlist: AllowlistConfig)`
  - `HooksConfig(pre_commit: bool = True, pre_push: bool = True)`
  - `ScanConfig(block_on: Severity = "medium", max_file_kb: int = 512, max_line_chars: int = 20000, paths_exclude: list[str] = [])`
  - `RulesConfig(packs: list[str] = [], disable: list[str] = [], enable: list[str] = [])`, `AllowlistConfig(max_days: int = 90)`
  - `load_config(repo_root: Path) -> Config`
  - `pack_paths(repo_root: Path, config: Config) -> list[Path]`

- [ ] **Step 1: Write the failing test: `tests/test_config.py`**

````python
from pathlib import Path

import pytest

from gitwarden.config import CONFIG_FILE, Config, load_config, pack_paths
from gitwarden.errors import GitWardenError


def write_config(root: Path, text: str) -> None:
    (root / CONFIG_FILE).write_text(text, encoding="utf-8")


def test_missing_file_gives_defaults(tmp_path):
    config = load_config(tmp_path)
    assert config == Config()
    assert config.scan.block_on == "medium"
    assert config.scan.max_file_kb == 512
    assert config.hooks.pre_commit and config.hooks.pre_push
    assert config.allowlist.max_days == 90


def test_values_are_read(tmp_path):
    write_config(
        tmp_path,
        '[scan]\nblock_on = "high"\npaths_exclude = ["^docs/"]\n'
        '[rules]\ndisable = ["generic/jwt"]\n'
        "[hooks]\npre_push = false\n",
    )
    config = load_config(tmp_path)
    assert config.scan.block_on == "high"
    assert config.scan.paths_exclude == ["^docs/"]
    assert config.rules.disable == ["generic/jwt"]
    assert config.hooks.pre_push is False


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('[scan]\nblock_on = "urgent"\n', "scan.block_on"),
        ("[scan]\nmax_file_kb = 0\n", "scan.max_file_kb"),
        ("[scan]\nblok_on = 'high'\n", "scan.blok_on"),
        ("[scan\n", "not valid TOML"),
        ("[scan]\npaths_exclude = ['(']\n", "bad regex in paths_exclude"),
    ],
)
def test_mistakes_are_errors(tmp_path, text, message):
    write_config(tmp_path, text)
    with pytest.raises(GitWardenError, match=message.replace("[", r"\[")):
        load_config(tmp_path)


def test_pack_paths_are_relative_to_repo_root(tmp_path):
    absolute = (tmp_path / "elsewhere" / "other.toml").as_posix()
    write_config(tmp_path, f'[rules]\npacks = ["rules/acme.toml", "{absolute}"]\n')
    paths = pack_paths(tmp_path, load_config(tmp_path))
    assert paths[0] == tmp_path / "rules/acme.toml"
    assert paths[1] == Path(absolute)
````

- [ ] **Step 2: Run the test and watch it fail**

```bash
.venv/bin/pytest tests/test_config.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gitwarden.config'`.

- [ ] **Step 3: Write `src/gitwarden/config.py`**

````python
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
````

- [ ] **Step 4: Run the tests and see them pass**

```bash
.venv/bin/pytest tests/test_config.py -v
```

Expected: all PASS.

- [ ] **Step 5: Run the whole suite and lint**

```bash
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Expected: everything passes, `All checks passed!`, no files to reformat.

- [ ] **Step 6: Commit**

```bash
git add tests/test_config.py src/gitwarden/config.py
git commit -m "Add .gitwarden.toml config loading

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```


### Task 5: Allowlist with expiry dates

**Why:** Reviewed exceptions for false positives. Each needs a reason and an expiry date, and lives in a committed file.

**Files:**
- Create: `src/gitwarden/allowlist.py`
- Create: `tests/test_allowlist.py`

**Interfaces:**
- Consumes: `GitWardenError`, `describe` (Task 1)
- Produces:
  - `ALLOW_FILE = ".gitwarden-allow.toml"`
  - Pydantic model `AllowEntry(fingerprint: str (12 hex), rule: str, path: str, reason: str, added_by: str, added: date, expires: date)`
  - `fingerprint(rule_id: str, path: str, secret: str) -> str`: first 12 hex chars of sha256(rule_id + "\n" + path + "\n" + secret)
  - `load_allowlist(repo_root: Path) -> dict[str, AllowEntry]` keyed by fingerprint
  - `check_new_entry(reason: str, expires: date, today: date, max_days: int) -> None`
  - `add_entry(repo_root: Path, entry: AllowEntry) -> Path`

**Notes:**
- An entry is valid up to and including its `expires` day.
- There is no TOML writer in the standard library, so `add_entry` writes the text itself. `json.dumps` gives correctly escaped TOML basic strings.

- [ ] **Step 1: Write the failing test: `tests/test_allowlist.py`**

````python
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
````

- [ ] **Step 2: Run the test and watch it fail**

```bash
.venv/bin/pytest tests/test_allowlist.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gitwarden.allowlist'`.

- [ ] **Step 3: Write `src/gitwarden/allowlist.py`**

````python
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
````

- [ ] **Step 4: Run the tests and see them pass**

```bash
.venv/bin/pytest tests/test_allowlist.py -v
```

Expected: all PASS.

- [ ] **Step 5: Run the whole suite and lint**

```bash
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Expected: everything passes, `All checks passed!`, no files to reformat.

- [ ] **Step 6: Commit**

```bash
git add tests/test_allowlist.py src/gitwarden/allowlist.py
git commit -m "Add allowlist with reasons and expiry dates

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```


### Task 6: Scanner

**Why:** The heart of GitWarden: applies rules to added lines, skips files that shouldn't be scanned, redacts, and applies the allowlist. No I/O.

**Files:**
- Create: `src/gitwarden/scanner.py`
- Create: `tests/fakes.py`
- Create: `tests/test_scanner.py`

**Interfaces:**
- Consumes: `AddedLine`, `ParsedDiff` (Task 2); `Rule`, `SEVERITY_ORDER`, `load_rules` (Task 3); `ScanConfig` (Task 4); `AllowEntry`, `fingerprint` (Task 5)
- Produces:
  - `@dataclass Finding(rule_id, severity, description, path, line_no, commit, redacted_line, fingerprint, expired_allow: AllowEntry | None = None)`: never holds the raw secret
  - `@dataclass Skipped(path: str, reason: str)`
  - `@dataclass ScanResult(findings: list[Finding], skipped: list[Skipped], warnings: list[str], allowed_count: int)` with method `blocking(block_on: str) -> list[Finding]`
  - `scan(diff: ParsedDiff, rules: list[Rule], allowlist: dict[str, AllowEntry], settings: ScanConfig, today: date) -> ScanResult`
  - `find_secrets(rule: Rule, text: str) -> list[str]`, `shannon_entropy(text: str) -> float`, `redact(secret: str) -> str`
  - `tests/fakes.py`: `fill(template: str, seed: int = 1234) -> str` and `fake(name: str, seed: int = 1234) -> str` make format-valid fake secrets

**Notes:**
- `max_file_kb` is measured on the text *added* to a file in this change (no extra git call per file, which keeps the hook fast).
- `tests/fakes.py` exists so the repo never holds realistic-looking tokens; GitHub push protection would block them.

- [ ] **Step 1: Add test data / helper: `tests/fakes.py`**

````python
"""Fake secrets for the test set.

The test cases in tests/corpus/ hold placeholders like {{github_token}} instead of
realistic tokens. Keeping real-looking tokens out of the repo means GitHub push
protection (and GitWarden itself) won't block pushes of this project.
fill() swaps each placeholder for a fake value with the right format.
"""

import base64
import random
import re
import string

LETTERS_DIGITS = string.ascii_letters + string.digits
UPPER_DIGITS = string.ascii_uppercase + string.digits
BASE64_CHARS = LETTERS_DIGITS + "+/"
URL_SAFE = LETTERS_DIGITS + "-_"
HEX = "0123456789abcdef"

PLACEHOLDER = re.compile(r"\{\{([a-z0-9_]+)\}\}")


def _pick(rng: random.Random, chars: str, length: int) -> str:
    return "".join(rng.choice(chars) for _ in range(length))


def _basic_auth(rng: random.Random) -> str:
    user_and_password = "deploy:" + _pick(rng, LETTERS_DIGITS, 14)
    return base64.b64encode(user_and_password.encode()).decode()


GENERATORS = {
    "aws_access_key_id": lambda r: "AKIA" + _pick(r, UPPER_DIGITS, 16),
    "aws_secret_access_key": lambda r: _pick(r, BASE64_CHARS, 40),
    "gcp_private_key_id": lambda r: _pick(r, HEX, 40),
    "azure_account_key": lambda r: _pick(r, BASE64_CHARS, 86) + "==",
    "github_token": lambda r: "ghp_" + _pick(r, LETTERS_DIGITS, 36),
    "github_pat": lambda r: (
        "github_pat_" + _pick(r, LETTERS_DIGITS, 22) + "_" + _pick(r, LETTERS_DIGITS, 59)
    ),
    "gitlab_token": lambda r: "glpat-" + _pick(r, LETTERS_DIGITS, 20),
    "slack_token": lambda r: (
        "xoxb-"
        + _pick(r, string.digits, 12)
        + "-"
        + _pick(r, string.digits, 12)
        + "-"
        + _pick(r, LETTERS_DIGITS, 24)
    ),
    "slack_webhook": lambda r: (
        "https://hooks.slack.com/services/T"
        + _pick(r, UPPER_DIGITS, 8)
        + "/B"
        + _pick(r, UPPER_DIGITS, 8)
        + "/"
        + _pick(r, LETTERS_DIGITS, 24)
    ),
    "stripe_key": lambda r: "sk_live_" + _pick(r, LETTERS_DIGITS, 24),
    "sendgrid_key": lambda r: "SG." + _pick(r, URL_SAFE, 22) + "." + _pick(r, URL_SAFE, 43),
    "google_api_key": lambda r: "AIza" + _pick(r, URL_SAFE, 35),
    "npm_token": lambda r: "npm_" + _pick(r, LETTERS_DIGITS, 36),
    "llm_api_key": lambda r: "sk-proj-" + _pick(r, LETTERS_DIGITS, 48),
    "jwt": lambda r: (
        "eyJ"
        + _pick(r, URL_SAFE, 20)
        + ".eyJ"
        + _pick(r, URL_SAFE, 30)
        + "."
        + _pick(r, URL_SAFE, 43)
    ),
    "password": lambda r: _pick(r, LETTERS_DIGITS, 16),
    "basic_auth": _basic_auth,
}


def fill(template: str, seed: int = 1234) -> str:
    """Replace every {{name}} in the template with a fake value (same seed = same values)."""
    rng = random.Random(seed)

    def replace(match: re.Match[str]) -> str:
        return GENERATORS[match.group(1)](rng)

    return PLACEHOLDER.sub(replace, template)


def fake(name: str, seed: int = 1234) -> str:
    """One fake value, for example fake("github_token")."""
    return fill("{{" + name + "}}", seed)
````

- [ ] **Step 2: Write the failing test: `tests/test_scanner.py`**

````python
from datetime import date

from fakes import fake

from gitwarden.allowlist import AllowEntry, fingerprint
from gitwarden.config import ScanConfig
from gitwarden.diff import AddedLine, ParsedDiff
from gitwarden.rules import load_rules
from gitwarden.scanner import redact, scan, shannon_entropy

TODAY = date(2026, 11, 23)
RULES = load_rules([], enable=[], disable=[])
TOKEN = fake("github_token")


def scan_lines(*lines: AddedLine, allowlist=None, settings=None, binary=None):
    diff = ParsedDiff(lines=list(lines), binary_paths=binary or [])
    return scan(diff, RULES, allowlist or {}, settings or ScanConfig(), TODAY)


def test_finds_a_token_and_never_keeps_the_raw_secret():
    result = scan_lines(AddedLine("ci.sh", 3, f"export GITHUB_TOKEN={TOKEN}"))
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.rule_id == "generic/github-token"
    assert (finding.path, finding.line_no, finding.severity) == ("ci.sh", 3, "high")
    assert TOKEN not in finding.redacted_line
    assert finding.redacted_line == f"export GITHUB_TOKEN={redact(TOKEN)}"
    assert finding.fingerprint == fingerprint("generic/github-token", "ci.sh", TOKEN)


def test_same_secret_found_by_two_rules_is_reported_once():
    # secret-assignment would also match this quoted token; github-token comes first
    result = scan_lines(AddedLine("a.py", 1, f'token = "{TOKEN}"'))
    assert [f.rule_id for f in result.findings] == ["generic/github-token"]


def test_every_secret_on_the_line_is_hidden_in_every_finding():
    key = fake("aws_access_key_id")
    result = scan_lines(AddedLine("a.env", 1, f"A={TOKEN} B={key}"))
    assert len(result.findings) == 2
    for finding in result.findings:
        assert TOKEN not in finding.redacted_line
        assert key not in finding.redacted_line


def test_clean_line_has_no_findings():
    assert scan_lines(AddedLine("a.py", 1, "print('hello')")).findings == []


def test_lockfiles_binary_and_excluded_files_are_skipped_and_listed():
    settings = ScanConfig(paths_exclude=["^vendor/"])
    result = scan_lines(
        AddedLine("web/package-lock.json", 1, f"x={TOKEN}"),
        AddedLine("vendor/lib.py", 1, f"x={TOKEN}"),
        settings=settings,
        binary=["logo.png"],
    )
    assert result.findings == []
    reasons = {(s.path, s.reason) for s in result.skipped}
    assert reasons == {
        ("logo.png", "binary file"),
        ("web/package-lock.json", "lockfile"),
        ("vendor/lib.py", "excluded by paths_exclude"),
    }


def test_file_with_too_much_added_text_is_skipped():
    big_line = "x" * 2000
    lines = [AddedLine("dump.sql", n, big_line) for n in range(1, 600)]
    result = scan_lines(*lines, settings=ScanConfig(max_file_kb=1))
    assert [(s.path, s.reason) for s in result.skipped] == [("dump.sql", "more than 1 KB added")]


def test_very_long_line_is_cut_and_warned_about():
    line = AddedLine("min.js", 1, "a" * 50 + TOKEN)
    result = scan_lines(line, settings=ScanConfig(max_line_chars=40))
    assert result.findings == []
    assert "only the first 40 were scanned" in result.warnings[0]


def test_allowlisted_finding_is_hidden_until_it_expires():
    line = AddedLine("tests/t.py", 1, f"x = {TOKEN}")
    entry = AllowEntry(
        fingerprint=fingerprint("generic/github-token", "tests/t.py", TOKEN),
        rule="generic/github-token",
        path="tests/t.py",
        reason="fake token for a test",
        added_by="Test Dev",
        added=date(2026, 11, 1),
        expires=TODAY,  # still valid on its last day
    )
    allowlist = {entry.fingerprint: entry}
    result = scan_lines(line, allowlist=allowlist)
    assert result.findings == [] and result.allowed_count == 1

    later = scan(ParsedDiff([line]), RULES, allowlist, ScanConfig(), date(2026, 11, 24))
    assert len(later.findings) == 1
    assert later.findings[0].expired_allow == entry


def test_blocking_respects_block_on():
    result = scan_lines(AddedLine("a.ts", 1, f"const t = '{fake('jwt')}';"))
    assert result.findings[0].severity == "medium"
    assert len(result.blocking("medium")) == 1
    assert result.blocking("high") == []


def test_entropy_and_redact():
    assert shannon_entropy("") == 0.0
    assert shannon_entropy("aaaa") == 0.0
    assert shannon_entropy("abcd") == 2.0
    assert redact("short") == "*****"
    assert redact("ABCDEFGHIJKLMNOPQRST") == "ABCD************QRST"
````

- [ ] **Step 3: Run the test and watch it fail**

```bash
.venv/bin/pytest tests/test_scanner.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gitwarden.scanner'`.

- [ ] **Step 4: Write `src/gitwarden/scanner.py`**

````python
"""The scanner: checks added lines against the rules. No git, no files, no printing.

Steps for each line, cheapest first:
  1. skip the whole file if it is binary, a lockfile, excluded, or too big
  2. for each rule: keyword check, then regex, then entropy and stopwords
  3. look the finding up in the allowlist
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from gitwarden.allowlist import AllowEntry, fingerprint
from gitwarden.config import ScanConfig
from gitwarden.diff import AddedLine, ParsedDiff
from gitwarden.rules import SEVERITY_ORDER, Rule

LOCKFILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Cargo.lock",
    "go.sum",
}
MAX_SHOWN_CHARS = 160  # longest line we print in a report


@dataclass
class Finding:
    """One secret found. Holds no raw secret: only a redacted line and a fingerprint."""

    rule_id: str
    severity: str
    description: str
    path: str
    line_no: int
    commit: str | None
    redacted_line: str
    fingerprint: str
    expired_allow: AllowEntry | None = None  # set when an allowlist entry existed but expired


@dataclass
class Skipped:
    """A file that was not scanned, and why."""

    path: str
    reason: str


@dataclass
class ScanResult:
    """Everything one scan found."""

    findings: list[Finding] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    allowed_count: int = 0  # findings hidden by a valid allowlist entry

    def blocking(self, block_on: str) -> list[Finding]:
        """Findings at or above the `block_on` severity."""
        level = SEVERITY_ORDER[block_on]
        return [f for f in self.findings if SEVERITY_ORDER[f.severity] >= level]


def scan(
    diff: ParsedDiff,
    rules: list[Rule],
    allowlist: dict[str, AllowEntry],
    settings: ScanConfig,
    today: date,
) -> ScanResult:
    """Check every added line in the diff and return what was found."""
    result = ScanResult()
    for path in diff.binary_paths:
        _skip(result, path, "binary file")

    excludes = [re.compile(pattern) for pattern in settings.paths_exclude]
    sizes = _added_size_by_file(diff.lines)
    for line in diff.lines:
        size_kb = sizes[(line.commit, line.path)] / 1024
        reason = _skip_reason(line.path, size_kb, excludes, settings.max_file_kb)
        if reason:
            _skip(result, line.path, reason)
            continue
        _scan_line(line, rules, allowlist, settings.max_line_chars, today, result)
    return result


def find_secrets(rule: Rule, text: str) -> list[str]:
    """All secrets this rule finds in one line of text."""
    lowered = text.lower()
    if not any(keyword in lowered for keyword in rule.keywords):
        return []
    secrets = []
    for match in rule.regex.finditer(text):
        secret = match.group(rule.secret_group)
        if not secret:
            continue
        if rule.min_entropy and shannon_entropy(secret) < rule.min_entropy:
            continue
        if any(word in secret.lower() for word in rule.stopwords):
            continue
        secrets.append(secret)
    return secrets


def shannon_entropy(text: str) -> float:
    """How random a string looks, in bits per character. 'aaaa' -> 0.0, random base64 -> ~5."""
    if not text:
        return 0.0
    total = len(text)
    counts = Counter(text)
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


def redact(secret: str) -> str:
    """'AKIAABCDEFGHIJKLWXYZ' -> 'AKIA************WXYZ'. Short secrets are hidden completely."""
    if len(secret) < 12:
        return "*" * len(secret)
    return secret[:4] + "*" * (len(secret) - 8) + secret[-4:]


def _scan_line(
    line: AddedLine,
    rules: list[Rule],
    allowlist: dict[str, AllowEntry],
    max_line_chars: int,
    today: date,
    result: ScanResult,
) -> None:
    """Run every rule on one line and add findings to `result`."""
    text = line.text
    if len(text) > max_line_chars:
        result.warnings.append(
            f"{line.path}:{line.line_no}: line has {len(text)} characters; "
            f"only the first {max_line_chars} were scanned"
        )
        text = text[:max_line_chars]

    # Collect (rule, secret) pairs. If two rules find the same secret, the first rule wins.
    hits: list[tuple[Rule, str]] = []
    for rule in rules:
        for secret in find_secrets(rule, text):
            if all(secret != found for _, found in hits):
                hits.append((rule, secret))
    if not hits:
        return

    # Hide every secret found on the line before showing the line to anyone.
    shown = text.strip()
    for _, secret in hits:
        shown = shown.replace(secret, redact(secret))
    if len(shown) > MAX_SHOWN_CHARS:
        shown = shown[:MAX_SHOWN_CHARS] + "..."

    for rule, secret in hits:
        finding = Finding(
            rule_id=rule.id,
            severity=rule.severity,
            description=rule.description,
            path=line.path,
            line_no=line.line_no,
            commit=line.commit,
            redacted_line=shown,
            fingerprint=fingerprint(rule.id, line.path, secret),
        )
        entry = allowlist.get(finding.fingerprint)
        if entry is None:
            result.findings.append(finding)
        elif entry.expires < today:
            finding.expired_allow = entry
            result.findings.append(finding)
        else:
            result.allowed_count += 1


def _added_size_by_file(lines: list[AddedLine]) -> dict[tuple[str | None, str], int]:
    """Characters added per (commit, file). Used for the max_file_kb limit."""
    sizes: dict[tuple[str | None, str], int] = {}
    for line in lines:
        key = (line.commit, line.path)
        sizes[key] = sizes.get(key, 0) + len(line.text) + 1
    return sizes


def _skip_reason(
    path: str, size_kb: float, excludes: list[re.Pattern[str]], max_file_kb: int
) -> str | None:
    """Why this file should not be scanned, or None to scan it."""
    if any(pattern.search(path) for pattern in excludes):
        return "excluded by paths_exclude"
    if path.rsplit("/", 1)[-1] in LOCKFILES:
        return "lockfile"
    if size_kb > max_file_kb:
        return f"more than {max_file_kb} KB added"
    return None


def _skip(result: ScanResult, path: str, reason: str) -> None:
    """Record a skipped file once."""
    if not any(skipped.path == path for skipped in result.skipped):
        result.skipped.append(Skipped(path, reason))
````

- [ ] **Step 5: Run the tests and see them pass**

```bash
.venv/bin/pytest tests/test_scanner.py -v
```

Expected: all PASS.

- [ ] **Step 6: Run the whole suite and lint**

```bash
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Expected: everything passes, `All checks passed!`, no files to reformat.

- [ ] **Step 7: Commit**

```bash
git add tests/fakes.py tests/test_scanner.py src/gitwarden/scanner.py
git commit -m "Add scanner with redaction, file skipping and allowlist

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```


### Task 7: Test set: recall and false-positive targets

**Why:** Proves the spec's targets: at least 95% of leak cases caught, at most 5% of clean cases blocked, at least 3 cases per rule.

**Files:**
- Create: `tests/corpus/leaks.toml`
- Create: `tests/corpus/clean.toml`
- Create: `tests/test_corpus.py`

**Interfaces:**
- Consumes: `fill` (Task 6); `lines_from_file`, `ParsedDiff` (Task 2); `load_rules` (Task 3); `ScanConfig` (Task 4); `scan` (Task 6)
- Produces:
  - The test set files; later rule changes must keep these tests green

**Notes:**
- This task adds tests only: the rules from Task 3 should already pass. If a case is missed, fix the rule in `builtin_rules.toml`, never the test case.
- Run with `-s` to see the printed recall and false-positive numbers.

- [ ] **Step 1: Add test data / helper: `tests/corpus/leaks.toml`**

````toml
# Leak cases: every case must produce a finding from `rule`.
# {{name}} placeholders are filled with fake secrets by tests/fakes.py at test time.

[[case]]
rule = "generic/private-key"
path = "deploy/id_rsa"
text = "-----BEGIN RSA PRIVATE KEY-----"

[[case]]
rule = "generic/private-key"
path = "certs/server.key"
text = "-----BEGIN PRIVATE KEY-----"

[[case]]
rule = "generic/private-key"
path = "config/keys.py"
text = 'SSH_KEY = """-----BEGIN OPENSSH PRIVATE KEY-----'

[[case]]
rule = "generic/aws-access-key-id"
path = ".env"
text = "AWS_ACCESS_KEY_ID={{aws_access_key_id}}"

[[case]]
rule = "generic/aws-access-key-id"
path = "settings.py"
text = 'aws_key = "{{aws_access_key_id}}"'

[[case]]
rule = "generic/aws-access-key-id"
path = "config/app.yaml"
text = "  access_key: {{aws_access_key_id}}"

[[case]]
rule = "generic/aws-secret-access-key"
path = ".env"
text = "AWS_SECRET_ACCESS_KEY={{aws_secret_access_key}}"

[[case]]
rule = "generic/aws-secret-access-key"
path = "credentials.json"
text = '  "aws_secret_access_key": "{{aws_secret_access_key}}",'

[[case]]
rule = "generic/aws-secret-access-key"
path = "src/main/resources/application.properties"
text = "aws.secretAccessKey={{aws_secret_access_key}}"

[[case]]
rule = "generic/gcp-service-account"
path = "service-account.json"
text = '  "private_key_id": "{{gcp_private_key_id}}",'

[[case]]
rule = "generic/gcp-service-account"
path = "infra/gcp-key.json"
text = '{"type": "service_account", "private_key_id": "{{gcp_private_key_id}}"}'

[[case]]
rule = "generic/gcp-service-account"
path = "tests/fixtures/sa.json"
text = '"private_key_id":"{{gcp_private_key_id}}"'

[[case]]
rule = "generic/azure-storage-key"
path = "appsettings.json"
text = '"Storage": "DefaultEndpointsProtocol=https;AccountName=acme;AccountKey={{azure_account_key}};EndpointSuffix=core.windows.net"'

[[case]]
rule = "generic/azure-storage-key"
path = ".env"
text = "AZURE_STORAGE=DefaultEndpointsProtocol=https;AccountName=acme;AccountKey={{azure_account_key}}"

[[case]]
rule = "generic/azure-storage-key"
path = "deploy.ps1"
text = '$conn = "AccountName=acme;accountkey={{azure_account_key}}"'

[[case]]
rule = "generic/github-token"
path = ".github/scripts/release.sh"
text = "export GITHUB_TOKEN={{github_token}}"

[[case]]
rule = "generic/github-token"
path = "ci.yml"
text = "    token: {{github_token}}"

[[case]]
rule = "generic/github-token"
path = "tools/sync.py"
text = 'headers = {"Authorization": "token {{github_token}}"}'

[[case]]
rule = "generic/github-fine-grained-token"
path = ".env"
text = "GH_PAT={{github_pat}}"

[[case]]
rule = "generic/github-fine-grained-token"
path = "scripts/clone.sh"
text = "git clone https://x-access-token:{{github_pat}}@github.com/acme/app.git"

[[case]]
rule = "generic/github-fine-grained-token"
path = "config.json"
text = '{"github": "{{github_pat}}"}'

[[case]]
rule = "generic/gitlab-token"
path = ".env"
text = "GITLAB_TOKEN={{gitlab_token}}"

[[case]]
rule = "generic/gitlab-token"
path = ".gitlab-ci.yml"
text = "  PRIVATE_TOKEN: {{gitlab_token}}"

[[case]]
rule = "generic/gitlab-token"
path = "scripts/api.py"
text = 'requests.get(url, headers={"PRIVATE-TOKEN": "{{gitlab_token}}"})'

[[case]]
rule = "generic/slack-token"
path = ".env"
text = "SLACK_BOT_TOKEN={{slack_token}}"

[[case]]
rule = "generic/slack-token"
path = "bot/config.yaml"
text = "slack:\n  token: {{slack_token}}"

[[case]]
rule = "generic/slack-token"
path = "bot/app.js"
text = "const client = new WebClient('{{slack_token}}');"

[[case]]
rule = "generic/slack-webhook"
path = "alerts.py"
text = 'WEBHOOK = "{{slack_webhook}}"'

[[case]]
rule = "generic/slack-webhook"
path = "monitoring/alertmanager.yml"
text = "    api_url: {{slack_webhook}}"

[[case]]
rule = "generic/slack-webhook"
path = "notify.sh"
text = "curl -X POST -d @msg.json {{slack_webhook}}"

[[case]]
rule = "generic/stripe-live-key"
path = ".env"
text = "STRIPE_SECRET_KEY={{stripe_key}}"

[[case]]
rule = "generic/stripe-live-key"
path = "billing/client.rb"
text = "Stripe.api_key = '{{stripe_key}}'"

[[case]]
rule = "generic/stripe-live-key"
path = "billing/config.ts"
text = "export const stripeKey = `{{stripe_key}}`;"

[[case]]
rule = "generic/sendgrid-key"
path = ".env"
text = "SENDGRID_API_KEY={{sendgrid_key}}"

[[case]]
rule = "generic/sendgrid-key"
path = "mail/send.py"
text = 'sg = SendGridAPIClient("{{sendgrid_key}}")'

[[case]]
rule = "generic/sendgrid-key"
path = "config/mail.yml"
text = "sendgrid: {{sendgrid_key}}"

[[case]]
rule = "generic/google-api-key"
path = "web/index.html"
text = '<script src="https://maps.googleapis.com/maps/api/js?key={{google_api_key}}"></script>'

[[case]]
rule = "generic/google-api-key"
path = "android/app/google-services.json"
text = '"current_key": "{{google_api_key}}"'

[[case]]
rule = "generic/google-api-key"
path = ".env"
text = "GOOGLE_API_KEY={{google_api_key}}"

[[case]]
rule = "generic/npm-token"
path = ".npmrc"
text = "//registry.npmjs.org/:_authToken={{npm_token}}"

[[case]]
rule = "generic/npm-token"
path = ".env"
text = "NPM_TOKEN={{npm_token}}"

[[case]]
rule = "generic/npm-token"
path = "ci/publish.sh"
text = 'echo "//registry.npmjs.org/:_authToken={{npm_token}}" > ~/.npmrc'

[[case]]
rule = "generic/llm-api-key"
path = ".env"
text = "OPENAI_API_KEY={{llm_api_key}}"

[[case]]
rule = "generic/llm-api-key"
path = "agent/llm.py"
text = 'client = OpenAI(api_key="{{llm_api_key}}")'

[[case]]
rule = "generic/llm-api-key"
path = "notebooks/test.ipynb"
text = '    "os.environ[\"OPENAI_API_KEY\"] = \"{{llm_api_key}}\"\n",'

[[case]]
rule = "generic/jwt"
path = "tests/api_test.http"
text = "Authorization: Bearer {{jwt}}"

[[case]]
rule = "generic/jwt"
path = "frontend/src/api.ts"
text = "const SESSION = '{{jwt}}';"

[[case]]
rule = "generic/jwt"
path = "postman_collection.json"
text = '"value": "{{jwt}}"'

[[case]]
rule = "generic/database-url-password"
path = ".env"
text = "DATABASE_URL=postgres://app:{{password}}@db.internal:5432/app"

[[case]]
rule = "generic/database-url-password"
path = "docker-compose.yml"
text = "      MONGO_URL: mongodb+srv://admin:{{password}}@cluster0.mongodb.net/prod"

[[case]]
rule = "generic/database-url-password"
path = "worker/settings.py"
text = 'BROKER_URL = "redis://:{{password}}@cache.internal:6379/0"'

[[case]]
rule = "generic/jdbc-password"
path = "src/main/resources/application.properties"
text = "spring.datasource.url=jdbc:sqlserver://db.internal:1433;databaseName=app;user=app;password={{password}}"

[[case]]
rule = "generic/jdbc-password"
path = "conf/db.conf"
text = 'url = "jdbc:mysql://db.internal/app?user=app&password={{password}}"'

[[case]]
rule = "generic/jdbc-password"
path = "Main.java"
text = 'String url = "jdbc:postgresql://db/app?password={{password}}&ssl=true";'

[[case]]
rule = "generic/url-credentials"
path = "scripts/deploy.sh"
text = "git push https://deploy:{{password}}@git.internal/acme/app.git"

[[case]]
rule = "generic/url-credentials"
path = "requirements.txt"
text = "--extra-index-url https://ci:{{password}}@pypi.internal/simple"

[[case]]
rule = "generic/url-credentials"
path = "config.yaml"
text = "registry: http://admin:{{password}}@registry.internal:5000"

[[case]]
rule = "generic/basic-auth-header"
path = "scripts/call.sh"
text = 'curl -H "Authorization: Basic {{basic_auth}}" https://api.internal/v1'

[[case]]
rule = "generic/basic-auth-header"
path = "client.py"
text = 'headers = {"Authorization": "Basic {{basic_auth}}"}'

[[case]]
rule = "generic/basic-auth-header"
path = "monitoring/probe.yml"
text = "    authorization: Basic {{basic_auth}}"

[[case]]
rule = "generic/secret-assignment"
path = "app/settings.py"
text = 'DB_PASSWORD = "{{password}}"'

[[case]]
rule = "generic/secret-assignment"
path = "config/app.json"
text = '  "apiKey": "{{password}}",'

[[case]]
rule = "generic/secret-assignment"
path = "src/Config.java"
text = 'private static final String CLIENT_SECRET = "{{password}}";'

[[case]]
rule = "generic/password-unquoted"
path = ".env"
text = "DB_PASSWORD={{password}}"

[[case]]
rule = "generic/password-unquoted"
path = "config/database.yml"
text = "production:\n  password: {{password}}"

[[case]]
rule = "generic/password-unquoted"
path = "src/main/resources/application.properties"
text = "spring.datasource.password={{password}}"
````

- [ ] **Step 2: Add test data / helper: `tests/corpus/clean.toml`**

````toml
# Clean cases: these look risky but hold no secret. None should produce a blocking finding.

[[case]]
path = "src/ids.py"
text = 'REQUEST_ID = "3f2b8c1e-9d4a-4f6b-8e2a-1c5d7f9b0a3e"'

[[case]]
path = "CHANGELOG.md"
text = "Fixed in commit 9fceb02d0ae598e95dc970b74767f19372d61af8."

[[case]]
path = "package-lock.json"
text = '      "integrity": "sha512-Vg2Oau7kL7aD7k6s5Sv4V8Q2k3rOW0z9GJ8n1sY7mEw9oQz0hU4tP5bLr8C6xT3nF2aK9dJ1eZ0yW4vX7uM5gA=="'

[[case]]
path = "web/logo.css"
text = ".logo { background: url(data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==); }"

[[case]]
path = "app/settings.py"
text = 'DB_PASSWORD = os.environ["DB_PASSWORD"]'

[[case]]
path = "docs/aws.md"
text = "Example: AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"

[[case]]
path = "docs/aws.md"
text = "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

[[case]]
path = "README.md"
text = 'api_key = "<your-api-key-here>"'

[[case]]
path = ".env.example"
text = "DB_PASSWORD=changeme"

[[case]]
path = "config/app.yaml"
text = "password: ${DB_PASSWORD}"

[[case]]
path = "docker-compose.yml"
text = "      DATABASE_URL: postgres://app:${POSTGRES_PASSWORD}@db:5432/app"

[[case]]
path = "docs/setup.md"
text = "Connect with postgres://user:password@localhost:5432/dev"

[[case]]
path = "src/auth.py"
text = "def check_password(password: str, hashed: str) -> bool:"

[[case]]
path = "src/auth.py"
text = "    password = request.form.get('password')"

[[case]]
path = "src/models.py"
text = "    password_hash = Column(String(128), nullable=False)"

[[case]]
path = "src/forms.py"
text = 'PASSWORD_FIELD_LABEL = "Enter your password"'

[[case]]
path = "tests/test_login.py"
text = 'password = "test-password-123"'

[[case]]
path = "src/nlp.py"
text = 'tokenizer = AutoTokenizer.from_pretrained("bert-base-uncased")'

[[case]]
path = "src/settings.py"
text = 'TOKEN_URL = "https://auth.example.com/oauth/token"'

[[case]]
path = "src/settings.py"
text = 'SECRET_KEY = os.getenv("SECRET_KEY")'

[[case]]
path = "web/src/i18n.ts"
text = "export const keyboardShortcutKey = 'ctrl+shift+k';"

[[case]]
path = "docs/api.md"
text = "Send the header `Authorization: Bearer <token>`."

[[case]]
path = "docs/api.md"
text = "curl -H 'Authorization: Basic $BASIC_AUTH' https://api.internal"

[[case]]
path = "web/styles.css"
text = ".sk-loader { animation: sk-bounce 1.4s infinite ease-in-out both; }"

[[case]]
path = "README.md"
text = "See https://github.com/acme/app/blob/main/docs/setup.md for setup."

[[case]]
path = "src/keys.py"
text = "PUBLIC_KEY_HEADER = '-----BEGIN PUBLIC KEY-----'"

[[case]]
path = "src/i18n/en.json"
text = '  "password_reset_title": "Reset your password",'

[[case]]
path = "src/config.py"
text = "MAX_PASSWORD_LENGTH = 128"

[[case]]
path = "infra/main.tf"
text = 'secret_name = "prod/db/credentials"'

[[case]]
path = "yarn.lock"
text = '  resolved "https://registry.yarnpkg.com/lodash/-/lodash-4.17.21.tgz#679591c564c3bffaae8454cf0b3df370c3d6911c"'
````

- [ ] **Step 3: Write the failing test: `tests/test_corpus.py`**

````python
"""The test set: proves the built-in rules catch leaks and leave clean code alone.

Targets from the spec: at least 95% of leak cases caught, at most 5% of clean
cases blocked.
"""

import tomllib
from datetime import date
from pathlib import Path

from fakes import fill

from gitwarden.config import ScanConfig
from gitwarden.diff import ParsedDiff, lines_from_file
from gitwarden.rules import load_rules
from gitwarden.scanner import scan

CORPUS = Path(__file__).parent / "corpus"
RULES = load_rules([], enable=[], disable=[])


def load_cases(name: str) -> list[dict]:
    return tomllib.loads((CORPUS / name).read_text(encoding="utf-8"))["case"]


def scan_text(path: str, text: str):
    diff = ParsedDiff(lines=lines_from_file(path, text))
    return scan(diff, RULES, {}, ScanConfig(), date(2026, 11, 23))


def test_every_enabled_rule_has_at_least_three_leak_cases():
    counts: dict[str, int] = {}
    for case in load_cases("leaks.toml"):
        counts[case["rule"]] = counts.get(case["rule"], 0) + 1
    for rule in RULES:
        assert counts.get(rule.id, 0) >= 3, f"{rule.id} needs at least 3 leak cases"


def test_recall_is_at_least_95_percent():
    cases = load_cases("leaks.toml")
    missed = []
    for number, case in enumerate(cases):
        text = fill(case["text"], seed=number)
        found = [f.rule_id for f in scan_text(case["path"], text).findings]
        if case["rule"] not in found:
            missed.append(f"{case['rule']} in {case['path']} (found: {found})")
    recall = 1 - len(missed) / len(cases)
    print(f"\nrecall: {recall:.1%} of {len(cases)} leak cases")
    for line in missed:
        print("  missed:", line)
    assert recall >= 0.95


def test_false_positive_rate_is_at_most_5_percent():
    cases = load_cases("clean.toml")
    flagged = []
    for case in cases:
        blocking = scan_text(case["path"], case["text"]).blocking("medium")
        if blocking:
            flagged.append(f"{case['path']}: {[f.rule_id for f in blocking]}")
    rate = len(flagged) / len(cases)
    print(f"\nfalse positives: {rate:.1%} of {len(cases)} clean cases")
    for line in flagged:
        print("  flagged:", line)
    assert rate <= 0.05
````

- [ ] **Step 4: Run the tests and see them pass**

```bash
.venv/bin/pytest tests/test_corpus.py -v
```

Expected: all PASS.

- [ ] **Step 5: Run the whole suite and lint**

```bash
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Expected: everything passes, `All checks passed!`, no files to reformat.

- [ ] **Step 6: Commit**

```bash
git add tests/corpus/leaks.toml tests/corpus/clean.toml tests/test_corpus.py
git commit -m "Add leak and clean test set with recall and false-positive targets

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```


### Task 8: Report text

**Why:** What the developer sees when something is blocked: where, which rule, the redacted line, and what to do next.

**Files:**
- Create: `src/gitwarden/report.py`
- Create: `tests/test_report.py`

**Interfaces:**
- Consumes: `Finding`, `ScanResult`, `Skipped` (Task 6); `AllowEntry` (Task 5)
- Produces:
  - `format_result(result: ScanResult, block_on: str, action: str) -> str`; `action` is `"commit"`, `"push"` or `"scan"`; returns `""` when there is nothing to say
  - `format_allowlist(entries: list[AllowEntry], today: date) -> str`

**Notes:**
- Output is plain ASCII, so it can't fail on a Windows console code page.
- The text never mentions `--no-verify`.

- [ ] **Step 1: Write the failing test: `tests/test_report.py`**

````python
from datetime import date

from gitwarden.allowlist import AllowEntry
from gitwarden.report import format_allowlist, format_result
from gitwarden.scanner import Finding, ScanResult, Skipped


def make_finding(severity: str = "high", commit: str | None = None) -> Finding:
    return Finding(
        rule_id="generic/aws-access-key-id",
        severity=severity,
        description="AWS access key ID",
        path="config/settings.py",
        line_no=14,
        commit=commit,
        redacted_line='AWS_KEY = "AKIA************WXYZ"',
        fingerprint="3f9a1c2e7d40",
    )


def make_entry(fp: str, expires: date) -> AllowEntry:
    return AllowEntry(
        fingerprint=fp,
        rule="generic/jwt",
        path="tests/a.py",
        reason="fake",
        added_by="Asha",
        added=date(2026, 11, 1),
        expires=expires,
    )


def test_nothing_to_say_gives_empty_text():
    assert format_result(ScanResult(), "medium", "commit") == ""


def test_blocked_commit_report():
    result = ScanResult(findings=[make_finding()], skipped=[Skipped("dump.sql", "lockfile")])
    text = format_result(result, "medium", "commit")
    assert text.startswith("GitWarden blocked this commit: 1 finding\n")
    assert "config/settings.py:14   generic/aws-access-key-id (high)" in text
    assert 'AWS_KEY = "AKIA************WXYZ"' in text
    assert "fingerprint: 3f9a1c2e7d40" in text
    assert "not scanned: dump.sql (lockfile)" in text
    assert 'gitwarden allow 3f9a1c2e7d40 --reason "..." --expires YYYY-MM-DD' in text
    assert "--no-verify" not in text


def test_push_report_shows_commit_and_range_hint():
    result = ScanResult(findings=[make_finding(commit="0123456789abcdef")])
    text = format_result(result, "medium", "push")
    assert text.startswith("GitWarden blocked this push")
    assert "config/settings.py:14 (commit 01234567)" in text
    assert "--range <remote>/<branch>..HEAD" in text


def test_findings_below_block_level_are_warnings_only():
    text = format_result(ScanResult(findings=[make_finding("low")]), "medium", "commit")
    assert "blocked" not in text
    assert text.startswith("Warnings (below the blocking level):")


def test_expired_allow_entry_is_explained():
    finding = make_finding()
    finding.expired_allow = make_entry("3f9a1c2e7d40", date(2026, 11, 20))
    text = format_result(ScanResult(findings=[finding]), "medium", "commit")
    assert "allowlist entry 3f9a1c2e7d40 expired on 2026-11-20 (reason: fake)" in text


def test_allowlist_listing_puts_expired_and_soon_first():
    today = date(2026, 11, 23)
    entries = [
        make_entry("aaaaaaaaaaaa", date(2027, 2, 1)),
        make_entry("bbbbbbbbbbbb", date(2026, 11, 30)),
        make_entry("cccccccccccc", date(2026, 11, 1)),
    ]
    text = format_allowlist(entries, today)
    order = [line.split()[0] for line in text.splitlines() if not line.startswith(" ")]
    assert order == ["cccccccccccc", "bbbbbbbbbbbb", "aaaaaaaaaaaa"]
    assert "EXPIRED 2026-11-01" in text
    assert "expires soon 2026-11-30" in text
    assert format_allowlist([], today) == "The allowlist is empty.\n"
````

- [ ] **Step 2: Run the test and watch it fail**

```bash
.venv/bin/pytest tests/test_report.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gitwarden.report'`.

- [ ] **Step 3: Write `src/gitwarden/report.py`**

````python
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
````

- [ ] **Step 4: Run the tests and see them pass**

```bash
.venv/bin/pytest tests/test_report.py -v
```

Expected: all PASS.

- [ ] **Step 5: Run the whole suite and lint**

```bash
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Expected: everything passes, `All checks passed!`, no files to reformat.

- [ ] **Step 6: Commit**

```bash
git add tests/test_report.py src/gitwarden/report.py
git commit -m "Add report formatting

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```


### Task 9: Git access

**Why:** The one module that runs git, with fixed diff options so every developer's git settings give the same output.

**Files:**
- Create: `src/gitwarden/git.py`
- Create: `tests/conftest.py`
- Create: `tests/test_git.py`

**Interfaces:**
- Consumes: `GitWardenError` (Task 1); `parse_diff` (Task 2) in tests
- Produces:
  - `run_git(args: list[str], cwd: Path | None = None) -> str`
  - `check_git_version() -> None` (needs 2.36+)
  - `repo_root(cwd: Path | None = None) -> Path` (resolved), `hooks_dir(root: Path) -> Path` (respects core.hooksPath)
  - `staged_diff(root) -> str`, `commit_diff(root, sha) -> str` (uses `--remerge-diff`)
  - `commits_in_range(root, range_spec) -> list[str]`, `commits_to_push(root, local_sha, remote_sha, remote_name) -> list[str]` (oldest first)
  - `commit_exists(root, sha) -> bool`, `is_deleted_ref(sha) -> bool`, `user_name(root) -> str`, `stage_file(root, relative_path) -> None`
  - `tests/conftest.py`: fixture `repo` (empty repo on `main`, cwd set, global git config ignored), helpers `git(cwd, *args, check=True)`, `write(root, path, text)`, `commit_file(root, path, text, message)`

**Notes:**
- `core.quotePath=false` keeps non-ASCII file names readable in diff headers.
- If the remote's old commit isn't known locally (someone else pushed, then you force-push), `commits_to_push` falls back to "every commit the remote's branches don't have". That over-scans, which is the safe direction.

- [ ] **Step 1: Add test data / helper: `tests/conftest.py`**

````python
"""Shared test helpers: a throw-away git repository for each test."""

import subprocess
from pathlib import Path

import pytest


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run git in `cwd` and return the finished process (text output)."""
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty git repo on branch main, made the current folder.

    The developer's own git settings are ignored (GIT_CONFIG_GLOBAL points to an
    empty file) so tests behave the same on every machine.
    """
    empty_config = tmp_path / "empty-gitconfig"
    empty_config.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")

    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Test Dev")
    git(root, "config", "user.email", "dev@example.com")
    git(root, "config", "commit.gpgsign", "false")
    monkeypatch.chdir(root)
    return root


def write(root: Path, relative_path: str, text: str) -> None:
    """Create or overwrite a file inside the repo."""
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def commit_file(root: Path, relative_path: str, text: str, message: str) -> None:
    """Write a file and commit it, skipping hooks (used to set up history)."""
    write(root, relative_path, text)
    git(root, "add", relative_path)
    git(root, "commit", "-q", "--no-verify", "-m", message)
````

- [ ] **Step 2: Write the failing test: `tests/test_git.py`**

````python
import pytest
from conftest import commit_file, git, write

from gitwarden import git as gw_git
from gitwarden.diff import parse_diff
from gitwarden.errors import GitWardenError


def test_repo_root_and_not_a_repo(repo, tmp_path, monkeypatch):
    assert gw_git.repo_root() == repo.resolve()
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(GitWardenError, match="not inside a git repository"):
        gw_git.repo_root(outside)


def test_git_version_is_new_enough(repo):
    gw_git.check_git_version()


def test_staged_diff_ignores_user_diff_settings(repo):
    git(repo, "config", "diff.noprefix", "true")
    git(repo, "config", "color.ui", "always")
    write(repo, "src/app.py", "x = 1\n")
    git(repo, "add", "src/app.py")
    parsed = parse_diff(gw_git.staged_diff(repo))
    assert [(line.path, line.text) for line in parsed.lines] == [("src/app.py", "x = 1")]


def test_commit_diff_and_range(repo):
    commit_file(repo, "a.txt", "one\n", "first")
    commit_file(repo, "a.txt", "one\ntwo\n", "second")
    shas = gw_git.commits_in_range(repo, "HEAD~1..HEAD")
    assert len(shas) == 1
    parsed = parse_diff(gw_git.commit_diff(repo, shas[0]), commit=shas[0])
    assert [(line.line_no, line.text) for line in parsed.lines] == [(2, "two")]


def test_hooks_dir_respects_core_hooks_path(repo):
    assert gw_git.hooks_dir(repo) == (repo / ".git" / "hooks").resolve()
    git(repo, "config", "core.hooksPath", "team-hooks")
    assert gw_git.hooks_dir(repo) == (repo / "team-hooks").resolve()


def test_user_name_and_commit_exists(repo):
    assert gw_git.user_name(repo) == "Test Dev"
    commit_file(repo, "a.txt", "one\n", "first")
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    assert gw_git.commit_exists(repo, head)
    assert not gw_git.commit_exists(repo, "1" * 40)
````

- [ ] **Step 3: Run the test and watch it fail**

```bash
.venv/bin/pytest tests/test_git.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gitwarden.git'`.

- [ ] **Step 4: Write `src/gitwarden/git.py`**

````python
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
````

- [ ] **Step 5: Run the tests and see them pass**

```bash
.venv/bin/pytest tests/test_git.py -v
```

Expected: all PASS.

- [ ] **Step 6: Run the whole suite and lint**

```bash
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Expected: everything passes, `All checks passed!`, no files to reformat.

- [ ] **Step 7: Commit**

```bash
git add tests/conftest.py tests/test_git.py src/gitwarden/git.py
git commit -m "Add git access module

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```


### Task 10: Hooks: install, uninstall, pre-commit and pre-push

**Why:** Connects everything to git. Integration tests use real repos, real `git commit` and real `git push` to a bare remote.

**Files:**
- Create: `src/gitwarden/hooks.py`
- Create: `tests/test_hooks.py`

**Interfaces:**
- Consumes: everything from Tasks 1–9
- Produces:
  - `MARKER = "# gitwarden-managed"`, `HOOK_NAMES = ("pre-commit", "pre-push")`
  - `hook_script(hook_name: str, python_path: str) -> str`
  - `install_hooks(root: Path, config: Config, force: bool = False, python_path: str | None = None) -> list[Path]`
  - `uninstall_hooks(root: Path) -> list[Path]`
  - `run_hook(hook_name: str, args: list[str], stdin_text: str, today: date | None = None) -> int` (0 clean, 1 blocked, 2 broken)
  - `scan_and_report(root: Path, diff: ParsedDiff, action: str, today: date | None = None) -> int`: prints the report to stderr
  - `scan_with_config(root: Path, config: Config, diff: ParsedDiff, today: date, use_allowlist: bool) -> ScanResult`
  - `diff_for_commits(root: Path, shas: list[str]) -> ParsedDiff`

**Notes:**
- The hook script holds the full path of the Python that ran `install` (forward slashes). Git for Windows runs hooks with its own `sh`, so one script works on every OS.
- The integration tests run the hook with `sys.executable`, so the package must be installed in the venv (`pip install -e`), which Task 1 did.

- [ ] **Step 1: Write the failing test: `tests/test_hooks.py`**

````python
"""Integration tests: real git repos, real hooks, real `git commit` and `git push`."""

from datetime import date

import pytest
from conftest import commit_file, git, write
from fakes import fake

from gitwarden.allowlist import AllowEntry, add_entry, fingerprint
from gitwarden.config import Config, HooksConfig
from gitwarden.errors import GitWardenError
from gitwarden.hooks import MARKER, hook_script, install_hooks, run_hook, uninstall_hooks

TOKEN = fake("github_token")


@pytest.fixture
def remote(repo, tmp_path):
    """A bare repository added as `origin`, with one clean commit already pushed."""
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    git(repo, "remote", "add", "origin", str(bare))
    commit_file(repo, "README.md", "hello\n", "first")
    git(repo, "push", "-q", "origin", "main")
    return bare


def test_hook_script_uses_forward_slashes_and_marker():
    script = hook_script("pre-commit", "C:\\venv\\Scripts\\python.exe")
    assert script.startswith("#!/bin/sh\n")
    assert MARKER in script
    assert 'GW_PY="C:/venv/Scripts/python.exe"' in script
    assert 'exec "$GW_PY" -m gitwarden hook pre-commit "$@"' in script


def test_install_writes_enabled_hooks_and_uninstall_removes_them(repo):
    written = install_hooks(repo, Config())
    assert [path.name for path in written] == ["pre-commit", "pre-push"]
    only_commit = Config(hooks=HooksConfig(pre_push=False))
    assert [p.name for p in install_hooks(repo, only_commit)] == ["pre-commit"]
    removed = uninstall_hooks(repo)
    assert {path.name for path in removed} == {"pre-commit", "pre-push"}


def test_install_refuses_foreign_hook_unless_forced(repo):
    foreign = repo / ".git" / "hooks" / "pre-commit"
    foreign.write_text("#!/bin/sh\necho mine\n")
    with pytest.raises(GitWardenError, match="was not written by GitWarden"):
        install_hooks(repo, Config())
    assert not (repo / ".git" / "hooks" / "pre-push").exists()  # nothing half-installed
    install_hooks(repo, Config(), force=True)
    assert MARKER in foreign.read_text()
    foreign.write_text("#!/bin/sh\necho mine\n")
    uninstall_hooks(repo)
    assert foreign.exists()  # not ours, so left alone


def test_install_respects_core_hooks_path(repo):
    git(repo, "config", "core.hooksPath", "team-hooks")
    written = install_hooks(repo, Config())
    assert written[0] == (repo / "team-hooks" / "pre-commit").resolve()


def test_commit_with_secret_is_blocked(repo):
    install_hooks(repo, Config())
    write(repo, "ci.sh", f"export GITHUB_TOKEN={TOKEN}\n")
    git(repo, "add", "ci.sh")
    commit = git(repo, "commit", "-m", "add ci", check=False)
    assert commit.returncode != 0
    assert "GitWarden blocked this commit" in commit.stderr
    assert "generic/github-token" in commit.stderr
    assert TOKEN not in commit.stderr


def test_clean_commit_passes(repo):
    install_hooks(repo, Config())
    write(repo, "app.py", "print('hello')\n")
    git(repo, "add", "app.py")
    assert git(repo, "commit", "-m", "clean", check=False).returncode == 0


def test_allowlist_passes_until_expiry(repo):
    write(repo, "tests/t.py", f"TOKEN = {TOKEN}\n")
    git(repo, "add", "tests/t.py")
    entry = AllowEntry(
        fingerprint=fingerprint("generic/github-token", "tests/t.py", TOKEN),
        rule="generic/github-token",
        path="tests/t.py",
        reason="fake token for a test",
        added_by="Test Dev",
        added=date(2026, 11, 1),
        expires=date(2026, 12, 31),
    )
    add_entry(repo, entry)
    assert run_hook("pre-commit", [], "", today=date(2026, 12, 31)) == 0
    assert run_hook("pre-commit", [], "", today=date(2027, 1, 1)) == 1


def test_broken_config_blocks_with_exit_code_2(repo, capsys):
    write(repo, ".gitwarden.toml", "[scan]\nblock_on = 'urgent'\n")
    assert run_hook("pre-commit", [], "") == 2
    assert "GitWarden could not run" in capsys.readouterr().err


def test_push_blocks_secret_added_then_removed_in_history(repo, remote):
    install_hooks(repo, Config())
    commit_file(repo, "ci.sh", f"TOKEN={TOKEN}\n", "add token")  # --no-verify: a bypass
    commit_file(repo, "other.txt", "x\n", "unrelated")
    commit_file(repo, "ci.sh", "TOKEN=$FROM_ENV\n", "remove token")
    push = git(repo, "push", "origin", "main", check=False)
    assert push.returncode != 0
    assert "GitWarden blocked this push" in push.stderr
    assert "generic/github-token" in push.stderr


def test_push_of_new_branch_scans_only_new_commits(repo, remote):
    install_hooks(repo, Config())
    git(repo, "checkout", "-q", "-b", "feature")
    commit_file(repo, "feature.py", "print('new')\n", "feature work")
    push = git(repo, "push", "origin", "feature", check=False)
    assert push.returncode == 0, push.stderr


def test_push_scans_lines_added_while_fixing_a_merge_conflict(repo, remote):
    commit_file(repo, "app.py", "x = 1\n", "base")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "checkout", "-q", "-b", "feature")
    commit_file(repo, "app.py", "x = 2\n", "feature change")
    git(repo, "checkout", "-q", "main")
    commit_file(repo, "app.py", "x = 3\n", "main change")
    merge = git(repo, "merge", "feature", check=False)
    assert merge.returncode != 0  # conflict
    write(repo, "app.py", f"x = 4\nTOKEN = '{TOKEN}'\n")
    git(repo, "add", "app.py")
    git(repo, "commit", "-q", "--no-verify", "-m", "merge feature")

    install_hooks(repo, Config())
    push = git(repo, "push", "origin", "main", check=False)
    assert push.returncode != 0
    assert "generic/github-token" in push.stderr


def test_branch_deletion_push_is_not_scanned(repo, remote):
    git(repo, "push", "-q", "origin", "main:old")
    install_hooks(repo, Config())
    assert git(repo, "push", "origin", "--delete", "old", check=False).returncode == 0


def test_missing_python_gives_reinstall_message(repo):
    install_hooks(repo, Config(), python_path="/nonexistent/python")
    write(repo, "a.txt", "x\n")
    git(repo, "add", "a.txt")
    commit = git(repo, "commit", "-m", "x", check=False)
    assert commit.returncode != 0
    assert "Run 'gitwarden install' again" in commit.stderr
````

- [ ] **Step 2: Run the test and watch it fail**

```bash
.venv/bin/pytest tests/test_hooks.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gitwarden.hooks'`.

- [ ] **Step 3: Write `src/gitwarden/hooks.py`**

````python
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
````

- [ ] **Step 4: Run the tests and see them pass**

```bash
.venv/bin/pytest tests/test_hooks.py -v
```

Expected: all PASS.

- [ ] **Step 5: Run the whole suite and lint**

```bash
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Expected: everything passes, `All checks passed!`, no files to reformat.

- [ ] **Step 6: Commit**

```bash
git add tests/test_hooks.py src/gitwarden/hooks.py
git commit -m "Add hook install/uninstall and pre-commit/pre-push checks

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```


### Task 11: Full CLI: scan, install, uninstall, allow, rules

**Why:** The commands developers type. Replaces the Task 1 CLI with the full one.

**Files:**
- Modify (replace): `src/gitwarden/cli.py`
- Modify (replace): `tests/test_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 1–10
- Produces:
  - Commands: `gitwarden scan [--staged | --range A..B | PATH...]`, `install [--force]`, `uninstall`, `allow FINGERPRINT --reason TEXT --expires YYYY-MM-DD [--range A..B]`, `allow --list`, `rules list`, `rules check PACK`
  - Exit codes: 0 clean, 1 secrets found, 2 setup problem

**Notes:**
- This replaces both `src/gitwarden/cli.py` and `tests/test_cli.py` completely (the Task 1 tests are kept inside the new file).

- [ ] **Step 1: Write the failing test: `tests/test_cli.py`**

````python
import subprocess
import sys
from datetime import date, timedelta

from conftest import git, write
from fakes import fake
from typer.testing import CliRunner

from gitwarden import __version__
from gitwarden.allowlist import ALLOW_FILE, fingerprint, load_allowlist
from gitwarden.cli import app

runner = CliRunner()
TOKEN = fake("github_token")


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_python_dash_m_runs_the_cli():
    result = subprocess.run(
        [sys.executable, "-m", "gitwarden", "--version"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert __version__ in result.stdout


def test_scan_needs_exactly_one_mode(repo):
    result = runner.invoke(app, ["scan"])
    assert result.exit_code == 2
    assert "exactly one" in result.output


def test_scan_staged_finds_secret(repo):
    write(repo, "ci.sh", f"TOKEN={TOKEN}\n")
    git(repo, "add", "ci.sh")
    result = runner.invoke(app, ["scan", "--staged"])
    assert result.exit_code == 1
    assert "GitWarden found secrets: 1 finding" in result.output


def test_scan_files_and_folders(repo):
    write(repo, "src/settings.py", f"TOKEN = '{TOKEN}'\n")
    write(repo, "src/clean.py", "print('hi')\n")
    (repo / "src" / "image.bin").write_bytes(b"\x00\x01binary")
    result = runner.invoke(app, ["scan", "src"])
    assert result.exit_code == 1
    assert "src/settings.py:1" in result.output
    assert "not scanned: src/image.bin (binary file)" in result.output

    clean = runner.invoke(app, ["scan", "src/clean.py"])
    assert clean.exit_code == 0
    assert "no secrets found" in clean.output


def test_scan_range(repo):
    write(repo, "a.txt", "x\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "one")
    write(repo, "ci.sh", f"TOKEN={TOKEN}\n")
    git(repo, "add", "ci.sh")
    git(repo, "commit", "-q", "-m", "two")
    assert runner.invoke(app, ["scan", "--range", "HEAD~1..HEAD"]).exit_code == 1


def test_install_and_uninstall(repo):
    result = runner.invoke(app, ["install"])
    assert result.exit_code == 0
    assert "pre-commit" in result.output
    assert runner.invoke(app, ["uninstall"]).exit_code == 0
    assert "No GitWarden hooks found" in runner.invoke(app, ["uninstall"]).output


def test_allow_adds_entry_and_stages_file(repo):
    write(repo, "tests/t.py", f"TOKEN = {TOKEN}\n")
    git(repo, "add", "tests/t.py")
    fp = fingerprint("generic/github-token", "tests/t.py", TOKEN)
    expires = (date.today() + timedelta(days=30)).isoformat()
    result = runner.invoke(
        app, ["allow", fp, "--reason", "fake token for a test", "--expires", expires]
    )
    assert result.exit_code == 0, result.output
    entry = load_allowlist(repo)[fp]
    assert (entry.rule, entry.path, entry.added_by) == (
        "generic/github-token",
        "tests/t.py",
        "Test Dev",
    )
    staged = git(repo, "diff", "--cached", "--name-only").stdout
    assert ALLOW_FILE in staged
    assert runner.invoke(app, ["scan", "--staged"]).exit_code == 0

    listing = runner.invoke(app, ["allow", "--list"])
    assert fp in listing.output


def test_allow_rejects_unknown_fingerprint_and_bad_dates(repo):
    later = (date.today() + timedelta(days=10)).isoformat()
    unknown = runner.invoke(app, ["allow", "0123456789ab", "--reason", "x", "--expires", later])
    assert unknown.exit_code == 2
    assert "no finding with fingerprint" in unknown.output
    bad_date = runner.invoke(app, ["allow", "0123456789ab", "--reason", "x", "--expires", "soon"])
    assert bad_date.exit_code == 2
    assert "--expires must be a date" in bad_date.output


def test_rules_list_and_check(repo, tmp_path):
    listing = runner.invoke(app, ["rules", "list"])
    assert listing.exit_code == 0
    assert "on   high    generic/aws-access-key-id" in listing.output
    assert "off  low     generic/high-entropy-string" in listing.output

    bad_pack = tmp_path / "bad.toml"
    bad_pack.write_text("[pack]\nid = 'x'\n", encoding="utf-8")
    check = runner.invoke(app, ["rules", "check", str(bad_pack)])
    assert check.exit_code == 2
    assert "rules" in check.output


def test_not_a_repo_is_exit_code_2(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["install"])
    assert result.exit_code == 2
    assert "not inside a git repository" in result.output
````

- [ ] **Step 2: Run the test and watch it fail**

```bash
.venv/bin/pytest tests/test_cli.py -v
```

Expected: FAIL with `test_scan_needs_exactly_one_mode` and the other new tests fail with exit code 2 and `No such command 'scan'` (the Task 1 CLI only has `--version`).

- [ ] **Step 3: Write `src/gitwarden/cli.py`**

````python
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
````

- [ ] **Step 4: Run the tests and see them pass**

```bash
.venv/bin/pytest tests/test_cli.py -v
```

Expected: all PASS.

- [ ] **Step 5: Run the whole suite and lint**

```bash
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Expected: everything passes, `All checks passed!`, no files to reformat.

- [ ] **Step 6: Commit**

```bash
git add tests/test_cli.py src/gitwarden/cli.py
git commit -m "Add scan, install, uninstall, allow and rules commands

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```


### Task 12: Speed target, README, GitWarden's own config

**Why:** Proves the under-1-second target through the real hook, and documents usage.

**Files:**
- Modify (replace): `README.md`
- Create: `.gitwarden.toml`
- Create: `tests/test_perf.py`

**Interfaces:**
- Consumes: `install_hooks` (Task 10), `Config` (Task 4), test helpers (Task 9)
- Produces:
  - `@pytest.mark.perf` speed test; README; `.gitwarden.toml` for this repo

**Notes:**
- The speed test runs `git hook run pre-commit` (git 2.36+), so Python start-up time is included, as the spec requires.
- `.gitwarden.toml` here excludes `tests/` because the tests contain fake secrets on purpose. It does not affect the tests, which build their own config.

- [ ] **Step 1: Write the failing test: `tests/test_perf.py`**

````python
"""Speed target from the spec: a 200-file, 2 000-line staged change is checked in under 1 second.

This runs the real installed hook through `git hook run`, so Python startup counts.
"""

import time

import pytest
from conftest import git, write

from gitwarden.config import Config
from gitwarden.hooks import install_hooks

LIMIT_SECONDS = 1.0


@pytest.mark.perf
def test_pre_commit_hook_is_fast_on_a_big_change(repo):
    install_hooks(repo, Config())
    for file_number in range(200):
        lines = [
            f"value_{n} = compute({n}, name='item-{file_number}-{n}')  # note {n}"
            for n in range(10)
        ]
        write(repo, f"src/module_{file_number}.py", "\n".join(lines) + "\n")
    git(repo, "add", "-A")

    timings = []
    for _ in range(3):  # best of three, so one slow moment on CI doesn't fail the test
        start = time.perf_counter()
        run = git(repo, "hook", "run", "pre-commit", check=False)
        timings.append(time.perf_counter() - start)
        assert run.returncode == 0, run.stderr

    best = min(timings)
    print(f"\npre-commit on 200 files / 2000 lines: best {best:.2f}s of {timings}")
    assert best < LIMIT_SECONDS
````

- [ ] **Step 2: Write `README.md`**

````markdown
# GitWarden

GitWarden runs on your machine and stops secrets (API keys, tokens, private keys,
passwords) from leaving it in a commit or a push. It works offline on Linux, macOS
and Windows.

## Install

```sh
python -m pip install -e ".[dev]"   # from a clone of this repo
cd /path/to/your/repo
gitwarden install                   # adds the pre-commit and pre-push hooks
```

Needs Python 3.11+ and git 2.36+.

## What happens

- **On commit**, GitWarden scans the lines you added. If it finds a secret, the commit is blocked
  and you see where it is (the secret itself is never printed).
- **On push**, it scans every commit you are about to push, one by one. A secret that was
  added and later deleted is still in history, so it still blocks.
- Exit codes: `0` clean, `1` secrets found, `2` GitWarden could not run (also blocks).

## Commands

| Command | What it does |
|---|---|
| `gitwarden install [--force]` | Install the hooks in the current repo |
| `gitwarden uninstall` | Remove GitWarden's hooks |
| `gitwarden scan --staged` | Scan what is staged |
| `gitwarden scan --range main..HEAD` | Scan commits |
| `gitwarden scan PATH...` | Scan whole files or folders |
| `gitwarden allow FINGERPRINT --reason "..." --expires YYYY-MM-DD` | Allow a known false positive |
| `gitwarden allow --list` | Show allowed exceptions |
| `gitwarden rules list` | Show all rules |
| `gitwarden rules check PACK.toml` | Check a client rule pack |

## Settings: `.gitwarden.toml` in the repo root

```toml
[hooks]
pre_commit = true
pre_push = true

[scan]
block_on = "medium"        # low | medium | high
max_file_kb = 512
max_line_chars = 20000
paths_exclude = []         # regexes, e.g. '^tests/fixtures/'

[rules]
packs = []                 # client rule packs, e.g. "rules/acme.toml"
disable = []               # e.g. "generic/jwt"
enable = []                # e.g. "generic/high-entropy-string"

[allowlist]
max_days = 90
```

## Development

```sh
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest            # all tests, including the recall and speed targets
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```
````

- [ ] **Step 3: Write `.gitwarden.toml`**

````toml
# GitWarden's settings for its own repository.
# The tests hold fake secrets on purpose, so they are not scanned here.
[scan]
paths_exclude = ['^tests/']
````

- [ ] **Step 4: Run the tests and see them pass**

```bash
.venv/bin/pytest tests/test_perf.py -v
```

Expected: all PASS.

- [ ] **Step 5: Run the whole suite and lint**

```bash
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Expected: everything passes, `All checks passed!`, no files to reformat.

- [ ] **Step 6: Commit**

```bash
git add tests/test_perf.py README.md .gitwarden.toml
git commit -m "Add speed test, README and repo config

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```


---

## Spec coverage check

| Spec requirement | Task |
|---|---|
| Package layout, Typer CLI, Pydantic only for TOML files, simple-code rules | 1, all |
| Diff parsing of added lines only; binary files listed | 2 |
| Rule format (keywords, regex, secret_group, min_entropy, stopwords, enabled), namespaced ids, loud pack errors, `rules list` / `rules check` | 3, 11 |
| About 25 generic rules, entropy rule off by default | 3 (23 rules) |
| `.gitwarden.toml` with `[hooks]`, `[scan]`, `[rules]`, `[allowlist]`; unknown keys are errors | 4 |
| Allowlist: 12-hex fingerprint incl. path, reason + expiry required, `max_days` cap, expired entries block again, `allow` stages the file, `allow --list` ordering, no inline ignores | 5, 6, 8, 11 |
| File filters (binary, lockfiles, size, `paths_exclude`), long-line cut with warning, skips listed | 6, 8 |
| Redaction (first 4 + last 4 when 12+ chars), every secret on a line hidden | 6 |
| Recall ≥ 95%, false positives ≤ 5%, ≥ 3 cases per rule, templates + fake generator | 6, 7 |
| Report format, push hint, severity threshold `block_on`, warnings below it | 8 |
| Fixed diff options, git ≥ 2.36 check, `core.hooksPath` respected | 9 |
| Hook script with absolute Python path, refuse foreign hooks unless `--force`, uninstall only ours, missing-Python message | 10 |
| pre-commit on staged diff; pre-push per commit, new branch, deleted branch, merge conflict lines via `--remerge-diff`, unknown remote SHA | 9, 10 |
| Exit codes 0/1/2; setup errors block | 10, 11 |
| `scan --staged / --range / PATH...` | 11 |
| Under 1 second through the real hook, including Python start-up | 12 |
| CI: ubuntu/macos/windows × 3.11/3.13, ruff + pytest | 1 |

**Small clarifications versus the spec (the spec is updated to match):**
- The test set lives in two files (`tests/corpus/leaks.toml`, `clean.toml`) with 66 and 30 cases, at least 3 per rule, instead of ~150 / ~100 files in folders. Grow it as false positives are reported.
- `max_file_kb` counts the text added to a file in this change.
- An expired allowlist entry is attached to its finding (`Finding.expired_allow`) instead of a separate list.
- `gitwarden allow` takes `--range A..B` so a finding from a push can be allowed too.

## After this plan

Not part of this build (from the spec's open items): the Phase 2 model choice and laptop benchmark, the HR agreement on profile contents, and developer hardware details.
