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
