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
