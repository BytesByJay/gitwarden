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
