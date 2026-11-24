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
