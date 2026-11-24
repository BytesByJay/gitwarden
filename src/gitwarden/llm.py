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
