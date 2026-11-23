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
