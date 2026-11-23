# GitWarden Phase 0–1: Secret scanner and hooks — design

- **Status:** approved in brainstorming, 2026-11-23
- **Scope:** project setup (Phase 0, code parts only) and the rule-based secret scanner with `pre-commit` and `pre-push` hooks (Phase 1).
- **Out of scope:** LLM layer, SQLite event store, Obsidian notes, `prepare-commit-msg`, `post-commit`, global install, server-side mode, JSON output. The `Finding` object and the config file are shaped so those can be added later.

## Goal

A Python package and CLI, `gitwarden`, that developers install locally. It blocks commits and pushes that add secrets. It runs fully offline, works the same on Linux, macOS and Windows, and scans a typical staged change in under one second.

## Code style: simple enough for a junior developer

This is a hard requirement, equal to correctness.

- Plain functions and `@dataclass` objects. No class hierarchies, abstract base classes, metaclasses, plugin registries, decorators of our own, or dependency-injection frameworks.
- Pydantic is used only to validate the two TOML files people write by hand (config and rule packs), because it gives clear error messages.
- One job per module. Aim for modules under about 200 lines and functions under about 30 lines.
- Type hints on every function. A short docstring on every public function that says *why* it exists, not just what it does.
- Clear names over short names (`added_lines`, not `al`). No one-line tricks; a plain `for` loop is fine.
- Each built-in rule has a `description` and a comment with an example of what it catches.
- Error messages say what went wrong and what to do next.
- When there is a choice between a feature and simpler code, choose simpler code unless the feature is needed for safety.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Detection engine | Our own pure-Python engine (regex + entropy), rules in TOML | `pip install` works on every OS with no extra binary; we control speed, rule format, allowlist and finding format. Rejected: wrapping gitleaks (per-OS binary, its config model), building on `detect-secrets` (awkward plugin model, file-oriented, entropy-heavy). Public gitleaks patterns may be used as a reference for regexes. |
| Target platforms | Linux, macOS, Windows | All three are in use. |
| Client-specific rules | Generic rules built in, plus a rule-pack file format. No client patterns built in. | Teams add their own packs. |
| Git host / CI | GitHub, CI on GitHub Actions | Answered by the user. |
| Python | 3.11+ (uses built-in `tomllib`) | |
| Git | 2.36+ (needed for `--remerge-diff`) | One code path instead of a fallback for old git. Checked at startup. |
| Dependencies | runtime: `typer`, `pydantic`; dev: `pytest`, `ruff` | |

## 1. Components and package layout

```
gitwarden/
├── pyproject.toml
├── .github/workflows/ci.yml
├── src/gitwarden/
│   ├── __main__.py           # `python -m gitwarden`; sends `hook` straight to hooks.py (no Typer import)
│   ├── cli.py                # Typer app: scan, install, uninstall, allow, rules
│   ├── config.py             # reads .gitwarden.toml
│   ├── git.py                # the only module that runs git (subprocess)
│   ├── diff.py               # unified diff text -> list[AddedLine]
│   ├── rules.py              # Rule model, loads built-in and client packs
│   ├── builtin_rules.toml    # the generic rule pack
│   ├── scanner.py            # scan(added_lines, rules, allowlist) -> ScanResult
│   ├── allowlist.py          # reads/writes .gitwarden-allow.toml, fingerprints
│   ├── report.py             # human-readable output; always redacted
│   └── hooks.py              # install/uninstall hook scripts, hook entrypoints
└── tests/
    ├── corpus/leaks/         # templates with {{placeholders}}
    ├── corpus/clean/
    ├── fakes.py              # generates fake secrets for the templates
    └── test_*.py
```

Boundaries:

- `git.py` is the only module that runs `git`. Everything else works on strings and dataclasses, so the scanner is tested without a repository.
- `diff.py` produces `AddedLine(path, line_no, text, commit)`, where `commit` is `None` for staged changes. Only **added** lines are scanned.
- `scanner.py` does no I/O.
- `Finding` (dataclass): `rule_id`, `severity`, `description`, `path`, `line_no`, `commit`, `redacted_line`, `fingerprint`. The raw secret is used to compute the fingerprint and is then dropped. It is never stored on a `Finding` and never printed.
- `ScanResult` (dataclass): `findings`, `expired_allows`, `skipped` (path + reason), `warnings`.
- Entropy is one small function in `scanner.py`, not its own module.

### Config

One file: `.gitwarden.toml` in the repo root, committed and shared by the team. If it is missing, defaults are used.

```toml
[hooks]
pre_commit = true
pre_push = true

[scan]
block_on = "medium"          # findings with severity >= this block; lower ones only warn
max_file_kb = 512
max_line_chars = 20000
paths_exclude = []           # regexes on repo-relative paths, e.g. '^tests/fixtures/'

[rules]
packs = []                   # paths to client rule-pack .toml files (relative to repo root, or absolute; ~ expanded)
disable = []                 # rule ids, e.g. "generic/jwt"
enable = []                  # turn on rules that are off by default

[allowlist]
max_days = 90
```

Unknown keys are an error, so a typo can't silently turn protection off.

## 2. Rule format and detection

Built-in rules and client packs use the same TOML format:

```toml
[pack]
id = "generic"               # [a-z0-9-]+; rule ids become "<pack>/<rule>"
description = "Generic credentials"

[[rules]]
id = "aws-access-key-id"
description = "AWS access key ID"
# catches: AWS_KEY = "AKIA...16 chars..."
severity = "high"            # high | medium | low
keywords = ["akia", "asia"]  # the line must contain one of these (any case) before the regex runs
regex = '''\b((?:AKIA|ASIA)[A-Z0-9]{16})\b'''
secret_group = 1             # which capture group is the secret (0 = whole match)
min_entropy = 0              # optional
stopwords = []               # optional; a secret containing any of these (any case) is ignored
enabled = true               # optional; false = off unless listed in [rules].enable
```

Detection for each added line, cheapest step first:

1. **File filters:** skip binary files, lockfiles (`package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `poetry.lock`, `Cargo.lock`, `go.sum`), files over `max_file_kb`, and paths matching `paths_exclude`. Every skip is recorded in `ScanResult.skipped`.
2. **Keyword pre-filter** for each rule.
3. **Regex match;** take `secret_group`.
4. **Rule checks:** `min_entropy`, `stopwords`.
5. **Allowlist** (section 4).

Lines longer than `max_line_chars` are cut to that length for scanning, with a warning.

The built-in `generic` pack has about 25 rules:

- **Cloud keys:** AWS access key ID and secret access key, GCP service-account JSON, Azure storage account key and connection string
- **Git and CI tokens:** GitHub (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, `github_pat_`), GitLab (`glpat-`)
- **Chat and payments:** Slack tokens (`xox[abpr]-`) and webhooks, Stripe (`sk_live_`, `rk_live_`)
- **Crypto and certs:** private key blocks (`-----BEGIN ... PRIVATE KEY-----`), JWT
- **Connection strings:** URLs with an embedded password for Postgres, MySQL, MongoDB, Redis and AMQP; JDBC with `password=`
- **Auth headers:** `Authorization: Basic ...`
- **Generic assignments:** password, secret, token and API-key assignments
- **Entropy:** `generic/high-entropy-string` (`enabled = false`)

Rule packs:

- Listed in config `[rules].packs`.
- A duplicate pack id, invalid regex, unknown field or bad severity is a load error that names the file. Load errors exit `2`. A pack is never skipped silently.
- `gitwarden rules list` shows every loaded rule with its id, severity and enabled state.
- `gitwarden rules check <pack.toml>` validates a pack file and reports errors.

## 3. Hooks and scan flow

### Install

`gitwarden install [--force]` (run inside a repo):

- Target folder: `git rev-parse --git-path hooks`. This respects `core.hooksPath`; the command prints the folder it used.
- Writes `pre-commit` and/or `pre-push` (per `[hooks]` config), mode 0755:

  ```sh
  #!/bin/sh
  # gitwarden-managed — do not edit; run `gitwarden install` to regenerate
  GW_PY="C:/Users/dev/.venvs/gw/Scripts/python.exe"
  if [ ! -f "$GW_PY" ]; then
    echo "GitWarden: its Python ($GW_PY) is missing. Run 'gitwarden install' again." >&2
    exit 2
  fi
  exec "$GW_PY" -m gitwarden hook pre-commit "$@"
  ```

  `GW_PY` is `sys.executable` at install time, with backslashes turned into forward slashes. Git for Windows runs hooks through its bundled `sh`, so one script works on every platform.
- If a hook file already exists without our marker line, `install` stops and prints the line the developer can add to their existing hook themselves. `--force` overwrites it.
- Running `install` again rewrites our own scripts.

`gitwarden uninstall` removes only files that contain the marker line.

### pre-commit

`git diff --cached -U0 --no-color --no-ext-diff --diff-filter=ACMR` → `diff.py` → scanner → report.

### pre-push

Read stdin lines in the form `<local ref> <local sha> <remote ref> <remote sha>`. The remote name is `$1`.

- **Local sha all zeros** (branch deletion): skip.
- **Remote sha all zeros** (new branch): commits = `git rev-list <local sha> --not --remotes=<remote>`.
- **Otherwise:** commits = `git rev-list <remote sha>..<local sha>`.
- Scan **each commit's own diff** with `git show -U0 --no-color --no-ext-diff --remerge-diff --format= <sha>`, one commit at a time. A secret added in one commit and deleted in a later one is still in the pushed history, so it still blocks. For merge commits, `--remerge-diff` shows only the lines added while resolving conflicts.

### Blocking and exit codes

- `0` clean (warnings may be printed), `1` blocking findings, `2` GitWarden could not run (git missing or too old, not a repo, bad config, pack or allowlist). Exit `2` also blocks.
- A finding blocks if its severity is at or above `block_on`. Lower ones print as warnings.
- `git commit --no-verify` and `git push --no-verify` can't be prevented locally; the Phase 5 server-side mode closes that gap. Messages don't mention `--no-verify`.

### Output

```
✖ GitWarden blocked this commit: 1 finding

  config/settings.py:14   generic/aws-access-key-id (high)
      AWS_KEY = "AKIA************WXYZ"
      fingerprint: 3f9a1c2e7d40

  Remove the secret and restage. If it's a known false positive:
      gitwarden allow 3f9a1c2e7d40 --reason "..." --expires 2026-12-31
```

Redaction: if the secret is 12 or more characters, keep its first 4 and last 4 characters and replace the rest with `*`. Shorter secrets are replaced fully with `*`. Pre-push output shows the short commit SHA next to the path.

### Manual scan

`gitwarden scan --staged`, `gitwarden scan --range A..B` (one commit at a time, like pre-push) and `gitwarden scan PATH...` (whole files, every line treated as added). These use the same engine and the same exit codes.

### Startup speed

`__main__.py` checks whether the first argument is `hook` and, if so, calls `hooks.run_hook()` directly without importing Typer. That's a plain `if`, nothing clever.

## 4. Allowlist

File: `.gitwarden-allow.toml` in the repo root, committed and reviewed like code.

```toml
[[allow]]
fingerprint = "3f9a1c2e7d40"
rule = "generic/generic-password-assignment"
path = "tests/test_login.py"
reason = "Fake password used by login unit test"
added_by = "Asha Nair"       # from git config user.name
added = 2026-11-23
expires = 2027-02-21
```

- Fingerprint = the first 12 hex characters of `sha256(rule_id + "\n" + path + "\n" + secret)`. The path is included, so an allow entry for a test file doesn't cover the same string elsewhere. The same 12 characters are printed in the output and typed into `gitwarden allow`.
- `expires` and a non-empty `reason` are required. `expires` must be after today and no more than `[allowlist].max_days` from today.
- An expired entry no longer suppresses anything. The finding blocks with the extra line `allowlist entry 3f9a1c2e7d40 expired on 2027-02-21 (reason: ...)`.
- `gitwarden allow <fingerprint> --reason TEXT --expires YYYY-MM-DD` re-runs the staged scan and checks that a finding with that fingerprint exists (error if not). It then appends the entry and runs `git add .gitwarden-allow.toml`, so the exception goes into the same commit.
- `gitwarden allow --list` shows entries: expired first, then those expiring within 14 days, then the rest.
- A malformed allowlist (bad TOML, missing field, bad date, duplicate fingerprint) is a config error, exit `2`.
- Known limit: a very weak "secret" could be guessed from its fingerprint. The allowlist is for test values and false positives, not real secrets.
- No inline ignore comments.

## 5. Errors, testing, targets

### Error handling

| Situation | Behaviour |
|---|---|
| Not a git repo, git missing or older than 2.36, bad config, pack or allowlist | Exit `2`, a one-line cause and what to do, blocks |
| File too big, binary, lockfile or excluded | Skipped and listed as `not scanned: <path> (<reason>)` |
| Non-UTF-8 content | Decoded with `errors="replace"`; the scan continues |
| Line longer than `max_line_chars` | Cut for scanning, warning printed |
| The hook's Python is missing | The shell script prints the reinstall message, exit `2` |

### Test set (`tests/corpus/`)

- **`leaks/`:** about 150 cases, at least 3 per enabled rule, in realistic places (`.env`, YAML, JSON, Python, Java `.properties`, URLs, quoted and unquoted). They're stored as **templates** such as `AWS_KEY = "{{aws_access_key_id}}"`, and `tests/fakes.py` fills them with seeded, format-valid fake values at test time. That way the repo holds no realistic-looking tokens, which GitHub push protection and GitWarden itself would otherwise block. Each case names the rule id it expects.
- **`clean/`:** about 100 cases that look risky but are safe: UUIDs, git SHAs, lockfile `integrity` hashes, base64 images, `password = os.environ["DB_PASSWORD"]`, documentation keys such as `AKIAIOSFODNN7EXAMPLE`, and placeholders like `<your-token-here>`.

### Targets checked by pytest on every change

1. **Recall:** at least 95% of leak cases produce a finding with the expected rule id. Misses are printed per rule.
2. **False positives:** at most 5% of clean files produce a blocking finding. The number is printed as the baseline for Phase 2.
3. **Speed:** a synthetic staged change of 200 files and 2 000 added lines, run through the installed `pre-commit` hook end to end (including Python startup), finishes in under 1 second on CI runners. Marked `@pytest.mark.perf`.
4. **Integration** (real repos in `tmp_path`):
   - a staged leak blocks
   - an allowlisted finding passes, then blocks after its expiry date (the date is injected)
   - pre-push blocks a secret added in commit 1 and removed in commit 3
   - pre-push on a new branch scans only commits not on the remote
   - pre-push scans lines added while resolving a merge conflict
   - install respects `core.hooksPath`
   - install refuses to overwrite a foreign hook without `--force`
   - a missing Python gives the reinstall message
5. **Unit:** diff parsing (renames, new files, binary markers, no newline at end of file), rule loading for good and broken packs, entropy, fingerprint stability, and redaction (no raw secret appears in any output).

### CI

GitHub Actions: a matrix of `ubuntu-latest`, `macos-latest` and `windows-latest` × Python `3.11` and `3.13`. Steps: `ruff check`, `ruff format --check`, `pytest` (including perf).

## Open items (not part of this build)

- **Model choice:** the Phase 0 model choice and laptop speed benchmark move to the Phase 2 (LLM layer) design.
- **Profile contents:** HR and management need to agree on what developer profiles may contain before Phase 3.
- **Developer hardware:** RAM and hardware details are needed for the Phase 2 model choice.
