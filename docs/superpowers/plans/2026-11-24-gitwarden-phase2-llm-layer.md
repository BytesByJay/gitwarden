# GitWarden Phase 2: Local LLM Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Optional, local-only AI help: `gitwarden commit` drafts a commit message with a small local model, and blocked findings get an advisory model opinion, without ever changing whether a commit or push is blocked.

**Architecture:** `llm.py` is the only module that runs the model: one `llamafile --cli` command per question, the prompt in a temporary file, a hard timeout, and every failure turned into "no answer". `prompts.py` holds the texts and chat formats. `review.py` adds opinions after the normal report in `hooks.scan_and_report`. `draft.py` builds a capped diff summary, asks for a message and hands it to `git commit -e -F`. `cli.py` adds `commit` and `llm check`.

**Tech Stack:** Python 3.11+, existing Typer/Pydantic/pytest/ruff, llamafile 0.10.6 (CPU-only "thin" build), Qwen2.5-3B-Instruct Q4_K_M `.gguf`. No new Python dependencies.

**Spec:** `docs/superpowers/specs/2026-11-24-gitwarden-phase2-llm-layer-design.md`
**Builds on:** Phase 1 (merged in PR #1). Work on branch `phase2-llm-layer`.

## Global Constraints

- No new runtime dependencies; the model is run with `subprocess` from the standard library.
- No network calls anywhere. GitWarden never downloads files.
- `[llm] enabled = false` by default; with it off, behaviour is exactly Phase 1.
- **The model never changes an exit code or a block/pass decision.** Rules alone decide.
- The model only ever sees redacted lines, never a raw secret.
- Every model problem (missing files, timeout, crash, empty or garbled answer) means "no AI help" and is never raised.
- llamafile command (0.10.6): `[sh] <llamafile> --cli -m <model> -f <prompt file> -n <max_tokens> --temp 0.2 --no-display-prompt --log-disable`; `sh` on Linux/macOS, the `.exe` directly on Windows.
- Same code style as Phase 1: simple enough for a junior developer (plain functions and dataclasses, short functions, type hints, docstrings that say why, clear error messages). `cli.py` may be about 270 lines.
- Works on Linux, macOS and Windows; CI matrix unchanged.
- Ruff: line length 100, rules `E, F, I, B, UP`; must pass `ruff check` and `ruff format --check`.
- **Commit messages are plain: no AI or Claude name, no `Co-Authored-By` line.**
- Commands below use `.venv/bin/...`; on Windows use `.venv\Scripts\...`.

## File map

| File | Job |
|---|---|
| `src/gitwarden/config.py` (modify) | New `LlmConfig` and `Config.llm` |
| `src/gitwarden/prompts.py` (new) | Prompt texts; ChatML and Llama 3 formats |
| `src/gitwarden/llm.py` (new) | Runs llamafile once per question; `ask()`, `check_setup()` |
| `src/gitwarden/git.py` (modify) | `git_dir`, `staged_file_names`, `staged_stat`, `recent_subjects`, `commit_with_editor` |
| `src/gitwarden/review.py` (new) | Advisory opinions on blocked findings |
| `src/gitwarden/hooks.py` (modify) | `scan_and_report` prints opinions after a blocking report |
| `src/gitwarden/draft.py` (new) | `run_commit`, `make_draft`, summary and clean-up |
| `src/gitwarden/cli.py` (modify) | `gitwarden commit`, `gitwarden llm check` |
| `tests/test_model.py` (new) | Real-model tests, skipped unless set up |
| `README.md`, `pyproject.toml` (modify) | Setup guide; `model` test marker |

Modified files are shown in full so each task can be applied without guessing.

---

## Tasks


### Task 1: Config: the [llm] table

**Why:** Every later task reads these settings. AI help stays off unless a developer switches it on.

**Files:**
- Modify (whole file shown): `src/gitwarden/config.py`
- Modify (whole file shown): `tests/test_config.py`

**Interfaces:**
- Consumes: Phase 1 `config.py` (`Config`, `load_config`)
- Produces:
  - `PromptFormat = Literal["chatml", "llama3"]`
  - Pydantic model `LlmConfig(enabled: bool = False, llamafile: str = "~/.gitwarden/llamafile", model: str = "~/.gitwarden/qwen2.5-3b-instruct-q4_k_m.gguf", prompt_format: PromptFormat = "chatml", timeout_seconds: int = 30 (>0), max_tokens: int = 200 (>0), review_findings: bool = True)`
  - `Config.llm: LlmConfig`

**Notes:**
- Both files are shown in full; the only changes are the `LlmConfig` model, `Config.llm`, and the new tests at the end of `test_config.py`.

- [ ] **Step 1: Write the failing test: `tests/test_config.py`**

````python
from pathlib import Path

import pytest

from gitwarden.config import CONFIG_FILE, Config, LlmConfig, load_config, pack_paths
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


def test_llm_is_off_by_default_with_sensible_defaults(tmp_path):
    llm = load_config(tmp_path).llm
    assert llm == LlmConfig()
    assert llm.enabled is False
    assert llm.prompt_format == "chatml"
    assert llm.timeout_seconds == 30
    assert llm.max_tokens == 200
    assert llm.review_findings is True
    assert llm.model.endswith(".gguf")


def test_llm_values_are_read(tmp_path):
    write_config(
        tmp_path,
        '[llm]\nenabled = true\nprompt_format = "llama3"\ntimeout_seconds = 60\n'
        'model = "~/models/llama.gguf"\n',
    )
    llm = load_config(tmp_path).llm
    assert llm.enabled is True
    assert llm.prompt_format == "llama3"
    assert llm.timeout_seconds == 60
    assert llm.model == "~/models/llama.gguf"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('[llm]\nprompt_format = "mistral"\n', "llm.prompt_format"),
        ("[llm]\ntimeout_seconds = 0\n", "llm.timeout_seconds"),
        ("[llm]\nturbo = true\n", "llm.turbo"),
    ],
)
def test_llm_mistakes_are_errors(tmp_path, text, message):
    write_config(tmp_path, text)
    with pytest.raises(GitWardenError, match=message):
        load_config(tmp_path)
````

- [ ] **Step 2: Run the test and watch it fail**

```bash
.venv/bin/pytest tests/test_config.py -v
```

Expected: FAIL with `ImportError: cannot import name 'LlmConfig' from 'gitwarden.config'`.

- [ ] **Step 3: Write `src/gitwarden/config.py`**

````python
"""Reads the team's settings from .gitwarden.toml in the repo root."""

import re
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from gitwarden.errors import GitWardenError, describe
from gitwarden.rules import Severity

CONFIG_FILE = ".gitwarden.toml"
PromptFormat = Literal["chatml", "llama3"]


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


class LlmConfig(BaseModel):
    """[llm]: the optional local model. Off until a developer sets it up."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    llamafile: str = "~/.gitwarden/llamafile"  # on Windows ".exe" is added automatically
    model: str = "~/.gitwarden/qwen2.5-3b-instruct-q4_k_m.gguf"
    prompt_format: PromptFormat = "chatml"
    timeout_seconds: int = Field(default=30, gt=0)
    max_tokens: int = Field(default=200, gt=0)
    review_findings: bool = True


class Config(BaseModel):
    """The whole .gitwarden.toml file. Every key has a default."""

    model_config = ConfigDict(extra="forbid")

    hooks: HooksConfig = HooksConfig()
    scan: ScanConfig = ScanConfig()
    rules: RulesConfig = RulesConfig()
    allowlist: AllowlistConfig = AllowlistConfig()
    llm: LlmConfig = LlmConfig()


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
git commit -m "Add [llm] settings to the config file"
```


### Task 2: Prompt texts and chat formats

**Why:** Small models only follow instructions in the chat format they were trained on. All prompt text lives in one place.

**Files:**
- Create: `src/gitwarden/prompts.py`
- Create: `tests/test_prompts.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `COMMIT_SYSTEM: str`, `REVIEW_SYSTEM: str`, `CHECK_SYSTEM: str`, `CHECK_QUESTION: str`
  - `wrap(system: str, user: str, prompt_format: str) -> str` (`"chatml"` or `"llama3"`)

**Notes:**
- `REVIEW_SYSTEM` must never contain the words "commit message"; a Task 6 test relies on that to tell the two prompts apart.

- [ ] **Step 1: Write the failing test: `tests/test_prompts.py`**

````python
from gitwarden.prompts import COMMIT_SYSTEM, REVIEW_SYSTEM, wrap


def test_chatml_format():
    assert wrap("Be brief.", "Hi", "chatml") == (
        "<|im_start|>system\nBe brief.<|im_end|>\n"
        "<|im_start|>user\nHi<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


def test_llama3_format():
    assert wrap("Be brief.", "Hi", "llama3") == (
        "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
        "Be brief.<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
        "Hi<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
    )


def test_system_texts_ask_for_the_right_output():
    assert "72 characters" in COMMIT_SYSTEM
    assert "<number>: <real|test|unsure> | <short reason>" in REVIEW_SYSTEM
    # the review prompt must never look like a commit-message request
    assert "commit message" not in REVIEW_SYSTEM.lower()
````

- [ ] **Step 2: Run the test and watch it fail**

```bash
.venv/bin/pytest tests/test_prompts.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gitwarden.prompts'`.

- [ ] **Step 3: Write `src/gitwarden/prompts.py`**

````python
"""The texts we send to the local model, and the chat formats small models expect.

A model only follows instructions well when the prompt uses the exact chat
format it was trained on, so `wrap()` adds that format around our text.
"""

COMMIT_SYSTEM = (
    "You write git commit messages. Write a commit message for the change below. "
    "First line: a summary of at most 72 characters in the imperative mood "
    "(for example 'Add login rate limit'). Then a blank line, then at most 3 short "
    "bullet points starting with '- '. Output only the commit message, nothing else."
)

REVIEW_SYSTEM = (
    "You help a developer judge findings from a secret scanner. Each finding shows "
    "the rule, the file path and the line, with the secret partly hidden by * characters. "
    "For each finding write exactly one line in this form: "
    "<number>: <real|test|unsure> | <short reason>. "
    "Say 'test' only when the path or the names clearly show test, example or "
    "placeholder data. Output nothing else."
)

CHECK_SYSTEM = "You are a helpful assistant."
CHECK_QUESTION = "Reply with the single word OK."


def wrap(system: str, user: str, prompt_format: str) -> str:
    """Put the system and user text into the model's chat format, ready for its answer."""
    if prompt_format == "llama3":
        return (
            "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
            f"{system}<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
            f"{user}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
        )
    # chatml: the format used by Qwen models
    return (
        f"<|im_start|>system\n{system}<|im_end|>\n"
        f"<|im_start|>user\n{user}<|im_end|>\n"
        "<|im_start|>assistant\n"
    )
````

- [ ] **Step 4: Run the tests and see them pass**

```bash
.venv/bin/pytest tests/test_prompts.py -v
```

Expected: all PASS.

- [ ] **Step 5: Run the whole suite and lint**

```bash
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Expected: everything passes, `All checks passed!`, no files to reformat.

- [ ] **Step 6: Commit**

```bash
git add tests/test_prompts.py src/gitwarden/prompts.py
git commit -m "Add prompt texts and chat formats"
```


### Task 3: Model runner (llm.py)

**Why:** The only module that starts llamafile. Every failure becomes 'no answer' with a reason, so nothing can block a commit.

**Files:**
- Create: `src/gitwarden/llm.py`
- Create: `tests/test_llm.py`

**Interfaces:**
- Consumes: `LlmConfig` (Task 1)
- Produces:
  - `@dataclass LlmAnswer(text: str | None, error: str | None, seconds: float)`
  - `ask(prompt: str, settings: LlmConfig) -> LlmAnswer` (never raises)
  - `check_setup(settings: LlmConfig) -> str | None` (first problem with its fix)
  - `llamafile_path(settings, windows=IS_WINDOWS) -> Path`, `model_path(settings) -> Path`, `build_command(settings, prompt_path, windows=IS_WINDOWS) -> list[str]`
  - `LLAMAFILE_RELEASE = "0.10.6"`

**Notes:**
- Flags checked against the llamafile 0.10.6 documentation: `--cli` is required for answer-once mode (without it llamafile starts a server plus a chat); `-m`, `-f`, `-n`, `--temp`, `--no-display-prompt`, `--log-disable` exist; `--silent-prompt` does not.
- On Linux and macOS the command starts with `sh`: llamafile's file is a shell script on the outside, which Python's `subprocess` can't start directly. On Windows the `.exe` runs directly.
- Not yet confirmed on real hardware: that stdout holds only the answer. `test_model.py` (Task 8) checks it on a real laptop.
- Tests replace `subprocess.run`, so no model is needed. The `windows` parameter lets both platforms be tested anywhere.

- [ ] **Step 1: Write the failing test: `tests/test_llm.py`**

````python
import subprocess
from pathlib import Path

import pytest

from gitwarden import llm
from gitwarden.config import LlmConfig


@pytest.fixture
def settings(tmp_path: Path) -> LlmConfig:
    """Settings whose llamafile and model files exist (empty files are enough here)."""
    config = LlmConfig(
        enabled=True,
        llamafile=str(tmp_path / "llamafile"),
        model=str(tmp_path / "model.gguf"),
        timeout_seconds=30,
        max_tokens=50,
    )
    program = llm.llamafile_path(config)
    program.write_text("fake program")
    program.chmod(0o755)
    llm.model_path(config).write_text("fake model")
    return config


class FakeRun:
    """Stands in for subprocess.run: records the command and the prompt file's text."""

    def __init__(self, stdout=b"", stderr=b"", returncode=0, raises=None):
        self.stdout, self.stderr, self.returncode, self.raises = stdout, stderr, returncode, raises
        self.command: list[str] = []
        self.prompt_path: Path | None = None
        self.prompt_text = ""

    def __call__(self, command, **kwargs):
        self.command = command
        self.prompt_path = Path(command[command.index("-f") + 1])
        self.prompt_text = self.prompt_path.read_text(encoding="utf-8")
        assert kwargs["timeout"] == 30
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(command, self.returncode, self.stdout, self.stderr)


def use_fake(monkeypatch, fake: FakeRun) -> FakeRun:
    monkeypatch.setattr(llm.subprocess, "run", fake)
    return fake


def test_build_command_on_linux_and_macos_uses_sh(settings, tmp_path):
    command = llm.build_command(settings, tmp_path / "p.txt", windows=False)
    assert command == [
        "sh",
        str(tmp_path / "llamafile"),
        "--cli",
        "-m",
        str(tmp_path / "model.gguf"),
        "-f",
        str(tmp_path / "p.txt"),
        "-n",
        "50",
        "--temp",
        "0.2",
        "--no-display-prompt",
        "--log-disable",
    ]


def test_build_command_on_windows_runs_the_exe_directly(settings, tmp_path):
    command = llm.build_command(settings, tmp_path / "p.txt", windows=True)
    assert command[0] == str(tmp_path / "llamafile.exe")
    assert command[1] == "--cli"


def test_windows_adds_exe_only_when_missing():
    plain = LlmConfig(llamafile="/tools/llamafile")
    already = LlmConfig(llamafile="/tools/llamafile.exe")
    assert llm.llamafile_path(plain, windows=True).name == "llamafile.exe"
    assert llm.llamafile_path(already, windows=True).name == "llamafile.exe"
    assert llm.llamafile_path(plain, windows=False).name == "llamafile"


def test_ask_returns_the_answer_and_deletes_the_prompt_file(settings, monkeypatch):
    fake = use_fake(monkeypatch, FakeRun(stdout=b"  OK \n"))
    answer = llm.ask("Say OK", settings)
    assert answer.text == "OK"
    assert answer.error is None
    assert fake.prompt_text == "Say OK"
    assert not fake.prompt_path.exists()


def test_timeout_gives_no_answer_and_still_deletes_the_prompt(settings, monkeypatch):
    fake = use_fake(monkeypatch, FakeRun(raises=subprocess.TimeoutExpired("llamafile", 30)))
    answer = llm.ask("Say OK", settings)
    assert answer.text is None
    assert answer.error == "timed out after 30 s"
    assert not fake.prompt_path.exists()


@pytest.mark.parametrize(
    ("fake", "error"),
    [
        (
            FakeRun(returncode=1, stderr=b"\nerror: bad model file\nmore"),
            "llamafile failed: error: bad model file",
        ),
        (FakeRun(stdout=b"   \n"), "the model gave an empty answer"),
        (FakeRun(raises=OSError(8, "Exec format error")), "could not start llamafile:"),
    ],
)
def test_failures_give_no_answer_with_a_reason(settings, monkeypatch, fake, error):
    use_fake(monkeypatch, fake)
    answer = llm.ask("Say OK", settings)
    assert answer.text is None
    assert answer.error.startswith(error)


def test_missing_files_give_no_answer_without_running_anything(settings, monkeypatch):
    fake = use_fake(monkeypatch, FakeRun(stdout=b"OK"))
    llm.model_path(settings).unlink()
    assert llm.ask("x", settings).error.startswith("model file not found at")
    llm.llamafile_path(settings).unlink()
    assert llm.ask("x", settings).error.startswith("llamafile not found at")
    assert fake.command == []


def test_check_setup_names_the_first_problem(settings):
    assert llm.check_setup(settings) is None
    assert "Set `enabled = true`" in llm.check_setup(LlmConfig(enabled=False))
    llm.model_path(settings).unlink()
    assert "model file not found" in llm.check_setup(settings)
    llm.llamafile_path(settings).unlink()
    message = llm.check_setup(settings)
    assert "llamafile not found" in message
    assert "llamafile-0.10.6-thin" in message
````

- [ ] **Step 2: Run the test and watch it fail**

```bash
.venv/bin/pytest tests/test_llm.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gitwarden.llm'`.

- [ ] **Step 3: Write `src/gitwarden/llm.py`**

````python
"""Runs the local model: one llamafile command per question, then it exits.

There is no server and no network. Every problem (missing files, too slow,
crash) gives an answer with text=None and a one-line error, so callers can
simply carry on without AI help. Nothing here ever raises.
"""

import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from gitwarden.config import LlmConfig

IS_WINDOWS = os.name == "nt"
LLAMAFILE_RELEASE = "0.10.6"  # the release the command below was written for


@dataclass
class LlmAnswer:
    """What came back from the model."""

    text: str | None  # None means "no answer"; `error` says why
    error: str | None
    seconds: float


def llamafile_path(settings: LlmConfig, windows: bool = IS_WINDOWS) -> Path:
    """Where the llamafile program is. Windows needs the '.exe' ending, so we add it there.

    This lets one shared .gitwarden.toml say "~/.gitwarden/llamafile" for everyone.
    """
    path = Path(settings.llamafile).expanduser()
    if windows and path.suffix.lower() != ".exe":
        path = path.with_name(path.name + ".exe")
    return path


def model_path(settings: LlmConfig) -> Path:
    """Where the model (.gguf) file is."""
    return Path(settings.model).expanduser()


def build_command(settings: LlmConfig, prompt_path: Path, windows: bool = IS_WINDOWS) -> list[str]:
    """The llamafile command for one question. The only place that knows llamafile's flags.

    On Linux and macOS llamafile is started through `sh`: its file format is a
    shell script on the outside, which Python cannot start directly.
    """
    program = str(llamafile_path(settings, windows))
    start = [program] if windows else ["sh", program]
    return [
        *start,
        "--cli",  # answer once and exit (no server, no chat)
        "-m",
        str(model_path(settings)),
        "-f",
        str(prompt_path),  # the prompt comes from a file, not the command line
        "-n",
        str(settings.max_tokens),
        "--temp",
        "0.2",  # low randomness: we want plain, predictable answers
        "--no-display-prompt",
        "--log-disable",
    ]


def check_setup(settings: LlmConfig) -> str | None:
    """The first setup problem, with how to fix it, or None if the files look ready."""
    if not settings.enabled:
        return "AI help is off. Set `enabled = true` under [llm] in .gitwarden.toml."
    program = llamafile_path(settings)
    if not program.is_file():
        return (
            f"llamafile not found at {program}. Download llamafile-{LLAMAFILE_RELEASE}-thin "
            "from https://github.com/mozilla-ai/llamafile/releases and save it there."
        )
    if not IS_WINDOWS and not os.access(program, os.X_OK):
        return f"{program} is not executable. Run: chmod +x {program}"
    model = model_path(settings)
    if not model.is_file():
        return f"model file not found at {model}. Download it and save it there."
    return None


def ask(prompt: str, settings: LlmConfig) -> LlmAnswer:
    """Ask the model one question and wait at most `timeout_seconds` for the answer."""
    start = time.perf_counter()
    program = llamafile_path(settings)
    if not program.is_file():
        return _answer(start, error=f"llamafile not found at {program}")
    if not model_path(settings).is_file():
        return _answer(start, error=f"model file not found at {model_path(settings)}")

    prompt_path = _write_prompt_file(prompt)
    try:
        completed = subprocess.run(
            build_command(settings, prompt_path),
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=settings.timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return _answer(start, error=f"timed out after {settings.timeout_seconds} s")
    except OSError as err:
        return _answer(start, error=f"could not start llamafile: {err}")
    finally:
        prompt_path.unlink(missing_ok=True)  # the prompt may hold code: never leave it behind

    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace")
        return _answer(start, error=f"llamafile failed: {_first_line(stderr)}")
    text = completed.stdout.decode("utf-8", errors="replace").strip()
    if not text:
        return _answer(start, error="the model gave an empty answer")
    return _answer(start, text=text)


def _write_prompt_file(prompt: str) -> Path:
    """Save the prompt to a temporary file that llamafile reads with -f."""
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=".txt", prefix="gitwarden-", delete=False
    ) as handle:
        handle.write(prompt)
    return Path(handle.name)


def _answer(start: float, text: str | None = None, error: str | None = None) -> LlmAnswer:
    return LlmAnswer(text=text, error=error, seconds=time.perf_counter() - start)


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return "no error message"
````

- [ ] **Step 4: Run the tests and see them pass**

```bash
.venv/bin/pytest tests/test_llm.py -v
```

Expected: all PASS.

- [ ] **Step 5: Run the whole suite and lint**

```bash
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Expected: everything passes, `All checks passed!`, no files to reformat.

- [ ] **Step 6: Commit**

```bash
git add tests/test_llm.py src/gitwarden/llm.py
git commit -m "Add llamafile runner with timeout and safe failures"
```


### Task 4: Git helpers for drafting

**Why:** Drafting needs the file list, recent commit subjects, and a way to run `git commit` with the editor attached to the terminal.

**Files:**
- Modify (whole file shown): `src/gitwarden/git.py`
- Modify (whole file shown): `tests/test_git.py`

**Interfaces:**
- Consumes: Phase 1 `git.py` and `tests/conftest.py`
- Produces:
  - `git_dir(root: Path) -> Path`
  - `staged_file_names(root: Path) -> list[str]` (includes deleted files)
  - `staged_stat(root: Path) -> str`
  - `recent_subjects(root: Path, count: int) -> list[str]` (newest first; `[]` in a new repo)
  - `commit_with_editor(root: Path, message: str | None) -> int` (git's exit code; the terminal is not captured, so the editor opens)

**Notes:**
- `GIT_EDITOR=true` in tests is an editor that saves nothing. Git runs the editor through `sh`, also on Windows, so this works on every OS.

- [ ] **Step 1: Write the failing test: `tests/test_git.py`**

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


def test_staged_helpers(repo):
    assert gw_git.recent_subjects(repo, 5) == []  # no commits yet
    commit_file(repo, "a.txt", "one\n", "Add a")
    commit_file(repo, "b.txt", "two\n", "Add b")
    assert gw_git.recent_subjects(repo, 5) == ["Add b", "Add a"]
    assert gw_git.recent_subjects(repo, 1) == ["Add b"]

    git(repo, "rm", "-q", "a.txt")
    write(repo, "c.txt", "three\n")
    git(repo, "add", "c.txt")
    assert sorted(gw_git.staged_file_names(repo)) == ["a.txt", "c.txt"]
    assert "c.txt" in gw_git.staged_stat(repo)
    assert gw_git.git_dir(repo) == (repo / ".git").resolve()


def test_commit_with_editor_uses_the_draft(repo, monkeypatch):
    monkeypatch.setenv("GIT_EDITOR", "true")  # an editor that changes nothing
    write(repo, "a.txt", "one\n")
    git(repo, "add", "a.txt")
    assert gw_git.commit_with_editor(repo, "Add a file\n\n- first line") == 0
    message = git(repo, "log", "-1", "--format=%B").stdout.strip()
    assert message == "Add a file\n\n- first line"


def test_commit_with_editor_without_draft_aborts_on_empty_message(repo, monkeypatch):
    monkeypatch.setenv("GIT_EDITOR", "true")
    write(repo, "a.txt", "one\n")
    git(repo, "add", "a.txt")
    assert gw_git.commit_with_editor(repo, None) != 0
    assert git(repo, "log", check=False).returncode != 0  # still no commits
````

- [ ] **Step 2: Run the test and watch it fail**

```bash
.venv/bin/pytest tests/test_git.py -v
```

Expected: FAIL with `AttributeError: module 'gitwarden.git' has no attribute 'recent_subjects'`.

- [ ] **Step 3: Write `src/gitwarden/git.py`**

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


def git_dir(root: Path) -> Path:
    """The repository's .git folder (a different place inside worktrees)."""
    output = run_git(["rev-parse", "--git-dir"], root)
    return (root / output.strip()).resolve()


def staged_file_names(root: Path) -> list[str]:
    """Names of all staged files, including deleted ones."""
    return run_git(["diff", "--cached", "--name-only"], root).splitlines()


def staged_stat(root: Path) -> str:
    """The short 'file | 12 +++--' overview of the staged changes."""
    return run_git(["diff", "--cached", "--stat", "--no-color"], root)


def recent_subjects(root: Path, count: int) -> list[str]:
    """First lines of the last `count` commits, newest first. Empty in a new repo."""
    try:
        output = run_git(["log", f"-{count}", "--format=%s"], root)
    except GitWardenError:
        return []  # a repository without commits yet
    return [line for line in output.splitlines() if line.strip()]


def commit_with_editor(root: Path, message: str | None) -> int:
    """Run `git commit` in the terminal so the developer's editor opens.

    With a message, the editor starts with it filled in. Returns git's exit code.
    """
    command = ["git", "commit"]
    if message is not None:
        draft_path = git_dir(root) / "GITWARDEN_DRAFT_MSG"
        draft_path.write_text(message + "\n", encoding="utf-8")
        command += ["-e", "-F", str(draft_path)]
    return subprocess.run(command, cwd=root).returncode


def _is_zero(sha: str) -> bool:
    return set(sha) == {"0"}
````

- [ ] **Step 4: Run the tests and see them pass**

```bash
.venv/bin/pytest tests/test_git.py -v
```

Expected: all PASS.

- [ ] **Step 5: Run the whole suite and lint**

```bash
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Expected: everything passes, `All checks passed!`, no files to reformat.

- [ ] **Step 6: Commit**

```bash
git add tests/test_git.py src/gitwarden/git.py
git commit -m "Add git helpers for commit drafting"
```


### Task 5: Model opinion on blocked findings

**Why:** Advisory help for the developer and the allowlist reviewer. The exit code is decided before the model is asked.

**Files:**
- Create: `src/gitwarden/review.py`
- Modify (whole file shown): `src/gitwarden/hooks.py`
- Create: `tests/test_review.py`

**Interfaces:**
- Consumes: `ask`, `LlmAnswer` (Task 3); `REVIEW_SYSTEM`, `wrap` (Task 2); `LlmConfig` (Task 1); Phase 1 `Finding`, `scan`, `run_hook`
- Produces:
  - `@dataclass Opinion(verdict: str, reason: str)`
  - `build_review_prompt(findings: list[Finding], prompt_format: str) -> str` (redacted lines only)
  - `parse_opinions(answer: str, count: int) -> dict[int, Opinion]`
  - `format_opinions(findings, opinions) -> str`
  - `review_findings(findings: list[Finding], settings: LlmConfig) -> str` (always text to print)
  - `hooks.scan_and_report` now prints the opinion after a blocking report when `[llm] enabled` and `review_findings` are on; its return value is unchanged

**Notes:**
- Tests replace `gitwarden.review.ask` (the name `review.py` imported), not `gitwarden.llm.ask`.

- [ ] **Step 1: Write the failing test: `tests/test_review.py`**

````python
from datetime import date

from conftest import git, write
from fakes import fake

from gitwarden import review
from gitwarden.config import LlmConfig, ScanConfig
from gitwarden.diff import AddedLine, ParsedDiff
from gitwarden.hooks import run_hook
from gitwarden.llm import LlmAnswer
from gitwarden.rules import load_rules
from gitwarden.scanner import scan

TOKEN = fake("github_token")
KEY = fake("aws_access_key_id")


def findings_for(*lines: AddedLine):
    rules = load_rules([], enable=[], disable=[])
    diff = ParsedDiff(lines=list(lines))
    return scan(diff, rules, {}, ScanConfig(), date(2026, 11, 24)).findings


def two_findings():
    return findings_for(
        AddedLine("config/settings.py", 14, f"AWS_KEY = '{KEY}'"),
        AddedLine("tests/test_login.py", 3, f"TOKEN = '{TOKEN}'"),
    )


def fake_ask(monkeypatch, answer: LlmAnswer) -> list[str]:
    """Replace the model with a canned answer; returns the list of prompts it was given."""
    prompts: list[str] = []

    def ask(prompt, settings):
        prompts.append(prompt)
        return answer

    monkeypatch.setattr(review, "ask", ask)
    return prompts


def test_prompt_has_redacted_lines_and_never_the_raw_secret():
    prompt = review.build_review_prompt(two_findings(), "chatml")
    assert "1. rule: generic/aws-access-key-id" in prompt
    assert "file: tests/test_login.py" in prompt
    assert KEY not in prompt
    assert TOKEN not in prompt
    assert prompt.startswith("<|im_start|>system")


def test_parse_keeps_only_well_formed_lines_for_known_numbers():
    answer = (
        "Here you go:\n"
        "1: REAL | production settings file\n"
        "2 : test |  path is under tests/\n"
        "3: test | there is no finding 3\n"
        "1: test | a second answer for 1 is ignored\n"
        "garbage"
    )
    opinions = review.parse_opinions(answer, count=2)
    assert opinions == {
        1: review.Opinion("real", "production settings file"),
        2: review.Opinion("test", "path is under tests/"),
    }


def test_review_prints_opinions(monkeypatch):
    fake_ask(monkeypatch, LlmAnswer("1: real | prod file\n2: test | under tests/", None, 1.0))
    text = review.review_findings(two_findings(), LlmConfig(enabled=True))
    assert text.startswith("Local model's opinion (advisory only, does not change the result):")
    assert "config/settings.py:14  real    - prod file" in text
    assert "tests/test_login.py:3  test    - under tests/" in text


def test_review_failures_print_one_line(monkeypatch):
    fake_ask(monkeypatch, LlmAnswer(None, "timed out after 30 s", 30.0))
    assert review.review_findings(two_findings(), LlmConfig()) == (
        "No model opinion: timed out after 30 s\n"
    )
    fake_ask(monkeypatch, LlmAnswer("I think they are fine", None, 1.0))
    assert review.review_findings(two_findings(), LlmConfig()) == (
        "No model opinion: answer not understood\n"
    )


def test_at_most_five_findings_are_sent(monkeypatch):
    prompts = fake_ask(monkeypatch, LlmAnswer(None, "x", 0.0))
    lines = [AddedLine(f"f{n}.env", 1, f"T={fake('github_token', seed=n)}") for n in range(7)]
    review.review_findings(findings_for(*lines), LlmConfig())
    assert "5. rule:" in prompts[0]
    assert "6. rule:" not in prompts[0]


def stage_secret(repo):
    write(repo, ".gitwarden.toml", "[llm]\nenabled = true\n")
    write(repo, "ci.sh", f"TOKEN={TOKEN}\n")
    git(repo, "add", "ci.sh")


def test_blocked_hook_shows_opinion_and_still_exits_1(repo, monkeypatch, capsys):
    stage_secret(repo)
    fake_ask(monkeypatch, LlmAnswer("1: test | looks fake", None, 1.0))
    assert run_hook("pre-commit", [], "") == 1
    err = capsys.readouterr().err
    assert "GitWarden blocked this commit" in err
    assert "ci.sh:1  test    - looks fake" in err


def test_blocked_hook_with_failing_model_still_exits_1(repo, monkeypatch, capsys):
    stage_secret(repo)
    fake_ask(monkeypatch, LlmAnswer(None, "timed out after 30 s", 30.0))
    assert run_hook("pre-commit", [], "") == 1
    assert "No model opinion: timed out after 30 s" in capsys.readouterr().err


def test_model_is_not_asked_when_off_or_when_nothing_blocks(repo, monkeypatch):
    prompts = fake_ask(monkeypatch, LlmAnswer("1: test | x", None, 1.0))
    write(repo, "ci.sh", f"TOKEN={TOKEN}\n")
    git(repo, "add", "ci.sh")
    assert run_hook("pre-commit", [], "") == 1  # [llm] is off by default
    git(repo, "rm", "-q", "--cached", "ci.sh")
    write(repo, ".gitwarden.toml", "[llm]\nenabled = true\n")
    write(repo, "app.py", "print('hi')\n")
    git(repo, "add", "app.py")
    assert run_hook("pre-commit", [], "") == 0
    assert prompts == []
````

- [ ] **Step 2: Run the test and watch it fail**

```bash
.venv/bin/pytest tests/test_review.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gitwarden.review'`.

- [ ] **Step 3: Write `src/gitwarden/review.py`**

````python
"""The local model's opinion on blocked findings. Advisory only.

The scanner and the rules decide whether a commit is blocked. This module only
adds a short opinion ("looks like a test value") to help the developer and the
person reviewing an allowlist entry. It never changes an exit code.
"""

import re
from dataclasses import dataclass

from gitwarden.config import LlmConfig
from gitwarden.llm import ask
from gitwarden.prompts import REVIEW_SYSTEM, wrap
from gitwarden.scanner import Finding

MAX_FINDINGS = 5  # one model call for the first 5 findings keeps the wait short
OPINION_LINE = re.compile(r"^\s*(\d+)\s*:\s*(real|test|unsure)\s*\|\s*(.+)$", re.IGNORECASE)


@dataclass
class Opinion:
    """The model's view of one finding."""

    verdict: str  # "real", "test" or "unsure"
    reason: str


def build_review_prompt(findings: list[Finding], prompt_format: str) -> str:
    """One prompt for all findings. It holds redacted lines only, never a raw secret."""
    parts = []
    for number, finding in enumerate(findings, start=1):
        parts.append(
            f"{number}. rule: {finding.rule_id} ({finding.description})\n"
            f"   file: {finding.path}\n"
            f"   line: {finding.redacted_line}"
        )
    return wrap(REVIEW_SYSTEM, "\n".join(parts), prompt_format)


def parse_opinions(answer: str, count: int) -> dict[int, Opinion]:
    """Read lines like '2: test | path is under tests/'. Lines in any other form are ignored."""
    opinions: dict[int, Opinion] = {}
    for line in answer.splitlines():
        match = OPINION_LINE.match(line)
        if match is None:
            continue
        number = int(match.group(1))
        if 1 <= number <= count and number not in opinions:
            opinions[number] = Opinion(match.group(2).lower(), match.group(3).strip())
    return opinions


def format_opinions(findings: list[Finding], opinions: dict[int, Opinion]) -> str:
    """The text printed under the report."""
    lines = ["Local model's opinion (advisory only, does not change the result):"]
    for number, finding in enumerate(findings, start=1):
        opinion = opinions.get(number)
        if opinion is not None:
            where = f"{finding.path}:{finding.line_no}"
            lines.append(f"  {where}  {opinion.verdict:<7} - {opinion.reason}")
    lines.append("If one really is a test value, use `gitwarden allow` as shown above.")
    return "\n".join(lines) + "\n"


def review_findings(findings: list[Finding], settings: LlmConfig) -> str:
    """Ask the model about the findings. Always returns text to print, never raises."""
    shown = findings[:MAX_FINDINGS]
    answer = ask(build_review_prompt(shown, settings.prompt_format), settings)
    if answer.text is None:
        return f"No model opinion: {answer.error}\n"
    opinions = parse_opinions(answer.text, len(shown))
    if not opinions:
        return "No model opinion: answer not understood\n"
    return format_opinions(shown, opinions)
````

- [ ] **Step 4: Write `src/gitwarden/hooks.py`**

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
from gitwarden.review import review_findings
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
    blocking = result.blocking(config.scan.block_on)
    exit_code = 1 if blocking else 0  # decided here; the model's opinion never changes it

    if blocking and config.llm.enabled and config.llm.review_findings:
        print("Asking the local model for its opinion...", file=sys.stderr)
        print(review_findings(blocking, config.llm), file=sys.stderr, end="")
    return exit_code


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

- [ ] **Step 5: Run the tests and see them pass**

```bash
.venv/bin/pytest tests/test_review.py -v
```

Expected: all PASS.

- [ ] **Step 6: Run the whole suite and lint**

```bash
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Expected: everything passes, `All checks passed!`, no files to reformat.

- [ ] **Step 7: Commit**

```bash
git add tests/test_review.py src/gitwarden/review.py src/gitwarden/hooks.py
git commit -m "Add advisory model opinion on blocked findings"
```


### Task 6: Commit message drafting (draft.py)

**Why:** `gitwarden commit`: secret check, short summary, model draft, editor, commit, with an empty editor whenever the model can't help.

**Files:**
- Create: `src/gitwarden/draft.py`
- Create: `tests/test_draft.py`

**Interfaces:**
- Consumes: Tasks 1–5; Phase 1 `scan_and_report`, `parse_diff`, `git.staged_diff`
- Produces:
  - `run_commit(root: Path) -> int`
  - `make_draft(root: Path, diff_text: str, settings: LlmConfig) -> LlmAnswer` (cleaned text, or `text=None`)
  - `build_summary(stat: str, diff_text: str, recent_subjects: list[str]) -> str`
  - `changed_lines_by_file(diff_text: str) -> dict[str, list[str]]`, `clean_message(answer: str) -> str`
  - `MAX_LINES_PER_FILE = 40`, `MAX_SUMMARY_CHARS = 3000`, `RECENT_COMMITS = 5`

**Notes:**
- Recent subjects go first in the summary, so the 3 000-character cut never removes them.

- [ ] **Step 1: Write the failing test: `tests/test_draft.py`**

````python
import pytest
from conftest import commit_file, git, write
from fakes import fake

from gitwarden import draft
from gitwarden.config import LlmConfig
from gitwarden.llm import LlmAnswer
from gitwarden.prompts import COMMIT_SYSTEM

DIFF = """\
diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@ -1 +1,2 @@
-print('hi')
+print('hello')
+print('bye')
diff --git a/notes.txt b/notes.txt
new file mode 100644
--- /dev/null
+++ b/notes.txt
@@ -0,0 +1 @@
+first note
"""


def test_changed_lines_are_grouped_by_file():
    assert draft.changed_lines_by_file(DIFF) == {
        "app.py": ["-print('hi')", "+print('hello')", "+print('bye')"],
        "notes.txt": ["+first note"],
    }


def test_summary_has_subjects_stat_and_lines():
    summary = draft.build_summary(" app.py | 3 ++-\n", DIFF, ["Add login", "Fix typo"])
    assert summary.startswith("Recent commit messages in this repository")
    assert "- Add login" in summary
    assert "app.py | 3 ++-" in summary
    assert "=== app.py\n-print('hi')\n+print('hello')" in summary


def test_summary_limits_lines_per_file_and_total_size():
    many = "\n".join(f"+line {n}" for n in range(100))
    diff = f"diff --git a/big.py b/big.py\n--- a/big.py\n+++ b/big.py\n@@ -0,0 +1,100 @@\n{many}\n"
    summary = draft.build_summary("", diff, [])
    assert "+line 39" in summary
    assert "+line 40" not in summary
    assert "... (60 more lines)" in summary

    huge = "\n".join(f"+{'x' * 70} {n}" for n in range(40))
    files = "".join(
        f"diff --git a/f{n}.py b/f{n}.py\n--- a/f{n}.py\n+++ b/f{n}.py\n@@ -0,0 +1,40 @@\n{huge}\n"
        for n in range(5)
    )
    summary = draft.build_summary("", files, [])
    assert summary.endswith("\n... (cut to keep it short)")
    assert len(summary) <= draft.MAX_SUMMARY_CHARS + len("\n... (cut to keep it short)")


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("Add login\n\n- check password", "Add login\n\n- check password"),
        ("```\nAdd login\n```", "Add login"),
        ("Commit message: Add login", "Add login"),
        ("Commit message:\nAdd login\n\n- detail", "Add login\n\n- detail"),
        ('"Add login"', "Add login"),
        ("```text\n```", ""),
    ],
)
def test_clean_message(answer, expected):
    assert draft.clean_message(answer) == expected


def fake_ask(monkeypatch, module, answer: LlmAnswer) -> list[str]:
    prompts: list[str] = []

    def ask(prompt, settings):
        prompts.append(prompt)
        return answer

    monkeypatch.setattr(module, "ask", ask)
    return prompts


def test_make_draft_sends_the_summary_and_cleans_the_answer(repo, monkeypatch):
    commit_file(repo, "a.txt", "one\n", "Add a")
    write(repo, "a.txt", "one\ntwo\n")
    git(repo, "add", "a.txt")
    prompts = fake_ask(monkeypatch, draft, LlmAnswer("```\nExtend a\n```", None, 2.0))
    answer = draft.make_draft(repo, "diff text here", LlmConfig(enabled=True))
    assert answer.text == "Extend a"
    assert COMMIT_SYSTEM in prompts[0]
    assert "- Add a" in prompts[0]
    assert "a.txt" in prompts[0]

    fake_ask(monkeypatch, draft, LlmAnswer("```\n```", None, 2.0))
    empty = draft.make_draft(repo, "", LlmConfig(enabled=True))
    assert (empty.text, empty.error) == (None, "the model gave an empty answer")


@pytest.fixture
def ai_repo(repo, monkeypatch):
    """A repo with [llm] switched on and an editor that accepts whatever it is given."""
    monkeypatch.setenv("GIT_EDITOR", "true")
    commit_file(repo, ".gitwarden.toml", "[llm]\nenabled = true\n", "Add config")
    return repo


def last_message(repo) -> str:
    return git(repo, "log", "-1", "--format=%B").stdout.strip()


def test_commit_uses_the_draft(ai_repo, monkeypatch):
    fake_ask(monkeypatch, draft, LlmAnswer("Add hello script\n\n- prints hello", None, 3.0))
    write(ai_repo, "hello.py", "print('hello')\n")
    git(ai_repo, "add", "hello.py")
    assert draft.run_commit(ai_repo) == 0
    assert last_message(ai_repo) == "Add hello script\n\n- prints hello"


def test_commit_without_a_draft_opens_an_empty_editor(ai_repo, monkeypatch, capsys):
    fake_ask(monkeypatch, draft, LlmAnswer(None, "timed out after 30 s", 30.0))
    write(ai_repo, "hello.py", "print('hello')\n")
    git(ai_repo, "add", "hello.py")
    assert draft.run_commit(ai_repo) != 0  # empty message: git aborts, as always
    assert "couldn't draft a message (timed out after 30 s)" in capsys.readouterr().err
    assert last_message(ai_repo) == "Add config"


def test_commit_with_ai_off_does_not_ask(repo, monkeypatch, capsys):
    monkeypatch.setenv("GIT_EDITOR", "true")
    prompts = fake_ask(monkeypatch, draft, LlmAnswer("x", None, 1.0))
    write(repo, "hello.py", "print('hello')\n")
    git(repo, "add", "hello.py")
    assert draft.run_commit(repo) != 0
    assert "AI drafting is off" in capsys.readouterr().err
    assert prompts == []


def test_nothing_staged(ai_repo, capsys):
    assert draft.run_commit(ai_repo) == 1
    assert "Nothing is staged" in capsys.readouterr().err


def test_staged_secret_stops_before_drafting(ai_repo, monkeypatch):
    from gitwarden import review

    draft_prompts = fake_ask(monkeypatch, draft, LlmAnswer("x", None, 1.0))
    fake_ask(monkeypatch, review, LlmAnswer("1: real | token", None, 1.0))
    write(ai_repo, "ci.sh", f"TOKEN={fake('github_token')}\n")
    git(ai_repo, "add", "ci.sh")
    assert draft.run_commit(ai_repo) == 1
    assert draft_prompts == []
    assert last_message(ai_repo) == "Add config"
````

- [ ] **Step 2: Run the test and watch it fail**

```bash
.venv/bin/pytest tests/test_draft.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gitwarden.draft'`.

- [ ] **Step 3: Write `src/gitwarden/draft.py`**

````python
"""`gitwarden commit`: draft a commit message with the local model, then commit.

The summary sent to the model is kept short on purpose: on a laptop without a
GPU, reading the prompt is the slow part, so a capped summary keeps the wait
around 10 seconds.
"""

import sys
from pathlib import Path

from gitwarden import git
from gitwarden.config import LlmConfig, load_config
from gitwarden.diff import parse_diff
from gitwarden.hooks import scan_and_report
from gitwarden.llm import LlmAnswer, ask
from gitwarden.prompts import COMMIT_SYSTEM, wrap

MAX_LINES_PER_FILE = 40
MAX_SUMMARY_CHARS = 3000
RECENT_COMMITS = 5


def run_commit(root: Path) -> int:
    """Check for secrets, draft a message, open the editor, commit. Returns the exit code."""
    if not git.staged_file_names(root):
        print("Nothing is staged. Use `git add` first.", file=sys.stderr)
        return 1

    diff_text = git.staged_diff(root)
    if scan_and_report(root, parse_diff(diff_text), "commit") != 0:
        return 1  # a secret is staged: don't spend time drafting

    config = load_config(root)
    if not config.llm.enabled:
        print(
            "AI drafting is off (`[llm] enabled = false`); opening the editor empty.",
            file=sys.stderr,
        )
        return git.commit_with_editor(root, None)

    print(
        "Drafting a commit message with the local model... "
        "(the first run of the day can take ~15 s)",
        file=sys.stderr,
    )
    answer = make_draft(root, diff_text, config.llm)
    if answer.text is None:
        print(
            f"GitWarden couldn't draft a message ({answer.error}); opening the editor empty.",
            file=sys.stderr,
        )
        return git.commit_with_editor(root, None)
    return git.commit_with_editor(root, answer.text)


def make_draft(root: Path, diff_text: str, settings: LlmConfig) -> LlmAnswer:
    """Ask the model for a message and tidy it. text=None if there is no usable draft."""
    summary = build_summary(
        git.staged_stat(root), diff_text, git.recent_subjects(root, RECENT_COMMITS)
    )
    answer = ask(wrap(COMMIT_SYSTEM, summary, settings.prompt_format), settings)
    if answer.text is None:
        return answer
    message = clean_message(answer.text)
    if not message:
        return LlmAnswer(None, "the model gave an empty answer", answer.seconds)
    return LlmAnswer(message, None, answer.seconds)


def build_summary(stat: str, diff_text: str, recent_subjects: list[str]) -> str:
    """A short description of the change: recent subjects, file list, and changed lines."""
    parts: list[str] = []
    if recent_subjects:
        parts.append("Recent commit messages in this repository (match their style):")
        parts.extend(f"- {subject}" for subject in recent_subjects)
        parts.append("")
    parts.append("Files changed:")
    parts.append(stat.rstrip())
    parts.append("")
    parts.append("Changed lines (+ added, - removed):")
    for path, lines in changed_lines_by_file(diff_text).items():
        parts.append(f"=== {path}")
        parts.extend(lines[:MAX_LINES_PER_FILE])
        hidden = len(lines) - MAX_LINES_PER_FILE
        if hidden > 0:
            parts.append(f"... ({hidden} more lines)")

    summary = "\n".join(parts)
    if len(summary) > MAX_SUMMARY_CHARS:
        summary = summary[:MAX_SUMMARY_CHARS] + "\n... (cut to keep it short)"
    return summary


def changed_lines_by_file(diff_text: str) -> dict[str, list[str]]:
    """The '+' and '-' lines of a diff, grouped by file name."""
    files: dict[str, list[str]] = {}
    current: str | None = None
    for raw in diff_text.split("\n"):
        if raw.startswith("diff --git "):
            current = None
        elif current is None and raw.startswith("+++ "):
            current = raw[4:].rstrip("\t").removeprefix("b/")
            files[current] = []
        elif current is not None and raw.startswith(("+", "-")):
            files[current].append(raw.rstrip("\r"))
    return files


def clean_message(answer: str) -> str:
    """Remove the extras small models like to add: code fences, quotes, 'Commit message:'."""
    lines = [line for line in answer.strip().splitlines() if not line.strip().startswith("```")]
    if lines and lines[0].lower().startswith("commit message:"):
        rest = lines[0][len("commit message:") :].strip()
        lines = ([rest] if rest else []) + lines[1:]
    text = "\n".join(lines).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text
````

- [ ] **Step 4: Run the tests and see them pass**

```bash
.venv/bin/pytest tests/test_draft.py -v
```

Expected: all PASS.

- [ ] **Step 5: Run the whole suite and lint**

```bash
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Expected: everything passes, `All checks passed!`, no files to reformat.

- [ ] **Step 6: Commit**

```bash
git add tests/test_draft.py src/gitwarden/draft.py
git commit -m "Add commit message drafting"
```


### Task 7: CLI: gitwarden commit and gitwarden llm check

**Why:** The two commands developers type. `llm check` is also how a laptop's real speed is measured.

**Files:**
- Modify (whole file shown): `src/gitwarden/cli.py`
- Modify (whole file shown): `tests/test_cli.py`

**Interfaces:**
- Consumes: `run_commit` (Task 6); `ask`, `check_setup` (Task 3); `CHECK_SYSTEM`, `CHECK_QUESTION`, `wrap` (Task 2)
- Produces:
  - `gitwarden commit` (exit code = git's, or 1 when nothing is staged or a secret blocks)
  - `gitwarden llm check` (0 ready, 2 not ready with the fix printed)

**Notes:**
- `cli.py` grows to about 270 lines. It's a flat list of commands, so it stays one file.

- [ ] **Step 1: Write the failing test: `tests/test_cli.py`**

````python
import subprocess
import sys
from datetime import date, timedelta

from conftest import git, write
from fakes import fake
from typer.testing import CliRunner

from gitwarden import __version__, cli
from gitwarden.allowlist import ALLOW_FILE, fingerprint, load_allowlist
from gitwarden.cli import app
from gitwarden.llm import LlmAnswer

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


def test_commit_command_passes_on_the_exit_code(repo, monkeypatch):
    monkeypatch.setenv("GIT_EDITOR", "true")
    write(repo, "a.txt", "x\n")
    git(repo, "add", "a.txt")
    result = runner.invoke(app, ["commit"])
    assert result.exit_code != 0  # AI is off and the editor saved nothing: git aborts
    assert "AI drafting is off" in result.output


def test_llm_check_reports_the_setup_problem(repo):
    result = runner.invoke(app, ["llm", "check"])
    assert result.exit_code == 2
    assert "Not ready: AI help is off" in result.output


def test_llm_check_times_a_tiny_question(repo, monkeypatch):
    write(repo, ".gitwarden.toml", "[llm]\nenabled = true\n")
    monkeypatch.setattr(cli, "check_setup", lambda settings: None)
    monkeypatch.setattr(cli, "ask", lambda prompt, settings: LlmAnswer("OK", None, 6.84))
    result = runner.invoke(app, ["llm", "check"])
    assert result.exit_code == 0
    assert "OK: model answered in 6.8 s" in result.output


def test_llm_check_explains_the_linux_start_problem(repo, monkeypatch):
    write(repo, ".gitwarden.toml", "[llm]\nenabled = true\n")
    monkeypatch.setattr(cli, "check_setup", lambda settings: None)
    error = "could not start llamafile: [Errno 8] Exec format error"
    monkeypatch.setattr(cli, "ask", lambda prompt, settings: LlmAnswer(None, error, 0.1))
    result = runner.invoke(app, ["llm", "check"])
    assert result.exit_code == 2
    assert "troubleshooting" in result.output
````

- [ ] **Step 2: Run the test and watch it fail**

```bash
.venv/bin/pytest tests/test_cli.py -v
```

Expected: FAIL with the new tests fail because Typer reports `No such command 'commit'` and `No such command 'llm'`.

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
from gitwarden.draft import run_commit
from gitwarden.errors import GitWardenError
from gitwarden.hooks import diff_for_commits, install_hooks, scan_and_report, scan_with_config
from gitwarden.hooks import uninstall_hooks as remove_hooks
from gitwarden.llm import ask, check_setup
from gitwarden.prompts import CHECK_QUESTION, CHECK_SYSTEM, wrap
from gitwarden.report import format_allowlist
from gitwarden.rules import load_all_rules, load_pack, load_rules

app = typer.Typer(
    help="GitWarden blocks secrets before they leave your machine.",
    no_args_is_help=True,
    add_completion=False,
)
rules_app = typer.Typer(help="Look at and check rule packs.", no_args_is_help=True)
app.add_typer(rules_app, name="rules")
llm_app = typer.Typer(help="The optional local AI model.", no_args_is_help=True)
app.add_typer(llm_app, name="llm")


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


@app.command()
def commit() -> None:
    """Draft a commit message with the local model, open it in your editor, then commit."""
    try:
        root = git.repo_root()
        git.check_git_version()
        code = run_commit(root)
    except GitWardenError as err:
        _fail(err)
    raise typer.Exit(code)


@llm_app.command("check")
def llm_check() -> None:
    """Check that the local model is set up, and time one tiny question."""
    try:
        settings = load_config(git.repo_root()).llm
    except GitWardenError as err:
        _fail(err)
    problem = check_setup(settings)
    if problem is not None:
        typer.echo(f"Not ready: {problem}", err=True)
        raise typer.Exit(2)

    typer.echo("Asking the model a tiny question...")
    answer = ask(wrap(CHECK_SYSTEM, CHECK_QUESTION, settings.prompt_format), settings)
    if answer.text is None:
        typer.echo(f"Not ready: {answer.error}", err=True)
        if "run-detectors" in (answer.error or "") or "Exec format" in (answer.error or ""):
            typer.echo(
                "This is a known llamafile start-up problem on some Linux systems. See the "
                "troubleshooting page: https://docs.mozilla.ai/llamafile/reference/troubleshooting",
                err=True,
            )
        raise typer.Exit(2)
    typer.echo(
        f"OK: model answered in {answer.seconds:.1f} s "
        "(the first run after a restart is slower; run again for the warm time)"
    )


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
git commit -m "Add commit and llm check commands"
```


### Task 8: Real-model tests and setup instructions

**Why:** Measures real speed and answer quality on a company laptop (the Phase 0 benchmark), and tells developers how to set up the model.

**Files:**
- Modify (whole file shown): `pyproject.toml`
- Modify (whole file shown): `README.md`
- Create: `tests/test_model.py`

**Interfaces:**
- Consumes: everything above
- Produces:
  - `@pytest.mark.model` tests, skipped unless `GITWARDEN_TEST_LLAMAFILE` and `GITWARDEN_TEST_MODEL` are set; README section "Local AI help (optional)"

**Notes:**
- In CI and on machines without the model these 3 tests are reported as skipped. That is expected.
- To run them: download llamafile-0.10.6-thin and the model as the README says, then `GITWARDEN_TEST_LLAMAFILE=~/.gitwarden/llamafile GITWARDEN_TEST_MODEL=~/.gitwarden/qwen2.5-3b-instruct-q4_k_m.gguf .venv/bin/pytest -m model -s`.

- [ ] **Step 1: Write the failing test: `tests/test_model.py`**

````python
"""Tests with the real local model. Skipped unless both settings below are given (never in CI).

Run on a company laptop to measure real speed and check answer quality:

    GITWARDEN_TEST_LLAMAFILE=~/.gitwarden/llamafile \
    GITWARDEN_TEST_MODEL=~/.gitwarden/qwen2.5-3b-instruct-q4_k_m.gguf \
    .venv/bin/pytest -m model -s
"""

import os
from datetime import date

import pytest
from conftest import commit_file, git, write
from fakes import fake

from gitwarden import git as gw_git
from gitwarden.config import LlmConfig, ScanConfig
from gitwarden.diff import AddedLine, ParsedDiff
from gitwarden.draft import make_draft
from gitwarden.llm import ask
from gitwarden.prompts import CHECK_QUESTION, CHECK_SYSTEM, wrap
from gitwarden.review import build_review_prompt, parse_opinions
from gitwarden.rules import load_rules
from gitwarden.scanner import scan

LLAMAFILE = os.environ.get("GITWARDEN_TEST_LLAMAFILE", "")
MODEL = os.environ.get("GITWARDEN_TEST_MODEL", "")

pytestmark = [
    pytest.mark.model,
    pytest.mark.skipif(
        not (LLAMAFILE and MODEL),
        reason="set GITWARDEN_TEST_LLAMAFILE and GITWARDEN_TEST_MODEL to run",
    ),
]


def real_settings() -> LlmConfig:
    return LlmConfig(
        enabled=True,
        llamafile=LLAMAFILE,
        model=MODEL,
        prompt_format=os.environ.get("GITWARDEN_TEST_FORMAT", "chatml"),
        timeout_seconds=180,
    )


def test_tiny_question_cold_and_warm():
    settings = real_settings()
    prompt = wrap(CHECK_SYSTEM, CHECK_QUESTION, settings.prompt_format)
    first = ask(prompt, settings)
    second = ask(prompt, settings)
    print(f"\nfirst answer: {first.seconds:.1f} s, second answer: {second.seconds:.1f} s")
    assert first.text, first.error
    assert second.text, second.error


def test_draft_has_a_short_first_line(repo):
    commit_file(repo, "app.py", "def greet():\n    return 'hi'\n", "Add greet function")
    write(repo, "app.py", "def greet(name):\n    return f'hi {name}'\n")
    git(repo, "add", "app.py")
    answer = make_draft(repo, gw_git.staged_diff(repo), real_settings())
    print(f"\ndraft in {answer.seconds:.1f} s:\n{answer.text}")
    assert answer.text, answer.error
    assert len(answer.text.splitlines()[0]) <= 72


def test_review_calls_a_fixture_value_a_test_value():
    line = AddedLine(
        "tests/fixtures/fake_users.py", 3, f'FAKE_API_TOKEN = "{fake("github_token")}"'
    )
    rules = load_rules([], enable=[], disable=[])
    findings = scan(ParsedDiff([line]), rules, {}, ScanConfig(), date(2026, 11, 24)).findings
    settings = real_settings()
    answer = ask(build_review_prompt(findings, settings.prompt_format), settings)
    print(f"\nreview in {answer.seconds:.1f} s:\n{answer.text}")
    assert answer.text, answer.error
    assert parse_opinions(answer.text, 1)[1].verdict == "test"
````

- [ ] **Step 2: Write `pyproject.toml`**

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
markers = [
    "perf: speed checks that run the real hook",
    "model: tests that need the real local model (skipped unless set up)",
]

[tool.ruff]
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]
````

- [ ] **Step 3: Write `README.md`**

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
| `gitwarden commit` | Draft a commit message with the local model, then commit |
| `gitwarden llm check` | Check the local model setup and time one answer |

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

## Local AI help (optional)

GitWarden can use a small local model to draft commit messages (`gitwarden commit`) and to
give an opinion on blocked findings. It is **off by default**, runs fully on your machine
(no network), and never decides whether a commit is blocked: only the rules do that.

1. Make the folder `~/.gitwarden/` (on Windows: `%USERPROFILE%\.gitwarden\`).
2. Download **llamafile-0.10.6-thin** (CPU only, about 44 MB) from
   <https://github.com/mozilla-ai/llamafile/releases/tag/0.10.6> and save it as
   `~/.gitwarden/llamafile`. On Linux and macOS run `chmod +x ~/.gitwarden/llamafile`.
   On Windows save it as `llamafile.exe`.
3. Download the model **qwen2.5-3b-instruct-q4_k_m.gguf** (about 2 GB) from
   <https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF> into `~/.gitwarden/`.
   Your company may offer both files on an internal mirror instead.
4. Switch it on in `.gitwarden.toml`:

   ```toml
   [llm]
   enabled = true
   # llamafile = "~/.gitwarden/llamafile"     # ".exe" is added on Windows
   # model = "~/.gitwarden/qwen2.5-3b-instruct-q4_k_m.gguf"
   # prompt_format = "chatml"                 # "llama3" for Llama models
   # timeout_seconds = 30
   # review_findings = true
   ```

5. Run `gitwarden llm check`. It names any missing piece, then times one tiny question.

Then stage your changes and run `gitwarden commit` instead of `git commit`: your editor opens
with a drafted message to edit. Plain `git commit` keeps working exactly as before.

## Development

```sh
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest            # all tests, including the recall and speed targets
.venv/bin/pytest -m model -s   # real-model tests; need GITWARDEN_TEST_LLAMAFILE and GITWARDEN_TEST_MODEL
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```
````

- [ ] **Step 4: Run the tests and see them pass**

```bash
.venv/bin/pytest tests/test_model.py -v
```

Expected: all PASS.

- [ ] **Step 5: Run the whole suite and lint**

```bash
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Expected: everything passes, `All checks passed!`, no files to reformat.

- [ ] **Step 6: Commit**

```bash
git add tests/test_model.py pyproject.toml README.md
git commit -m "Add real-model tests and local AI setup guide"
```


---

## Spec coverage check

| Spec requirement | Task |
|---|---|
| `[llm]` table with defaults, `~` expansion, strict validation, off by default | 1, 3 |
| ChatML and Llama 3 prompt formats; commit and review prompt texts | 2 |
| One-off llamafile command, prompt via `-f` temp file deleted in `finally`, timeout kills the process, never raises | 3 |
| Windows `.exe` handling, `sh` on Linux/macOS, flags pinned to 0.10.6 | 3 |
| `gitwarden llm check`: enabled, program, executable bit, model, tiny question timing, Linux start-up hint | 3, 7 |
| `gitwarden commit`: nothing staged, secret check first, AI off message, progress message, capped summary (40 lines/file, 3 000 chars, recent 5 subjects), clean-up, `git commit -e -F`, empty-editor fallback, git's exit code | 4, 6, 7 |
| Advisory review: only when enabled and blocked, first 5 findings, redacted lines only, strict line parsing, one-line failure, exit code unchanged | 5 |
| Tests without a real model (fake `subprocess.run`, fake `ask`, `GIT_EDITOR=true`) | 3–7 |
| Real-model tests skipped unless env vars are set; timings printed | 8 |
| README setup guide (pinned release, model, paths, `chmod`, `.exe`, `llm check`) | 8 |
| CI unchanged | (no task needed) |

**Small clarifications versus the spec:**
- `.exe` is added to the llamafile path automatically on Windows, so one shared `.gitwarden.toml` works for everyone.
- The llamafile command includes `--cli` and starts through `sh` on Linux and macOS (from the 0.10.6 documentation; confirmed on real hardware by Task 8's tests).
- The spec's `diff_stat_staged` / `recent_subjects` git helpers are named `staged_stat` / `recent_subjects`, plus `staged_file_names` and `commit_with_editor`.

## After this plan

- **Real laptop check:** run `gitwarden llm check` and `pytest -m model -s` on a typical company laptop, and record the cold and warm timings.
- **Phase 3:** still needs the HR agreement on what developer profiles may contain.
