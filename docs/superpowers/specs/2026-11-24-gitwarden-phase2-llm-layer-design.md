# GitWarden Phase 2: Local LLM layer — design

- **Status:** approved in brainstorming, 2026-11-24
- **Builds on:** Phase 1 (`2026-11-23-gitwarden-phase1-secret-scanner-design.md`), merged in PR #1.
- **Scope:** running a local model with llamafile, `gitwarden commit` (draft a commit message on request), an advisory model opinion on blocked findings, and `gitwarden llm check`.
- **Out of scope:** Ollama or any model server, automatic drafting in `prepare-commit-msg`, the model changing any block/pass decision, SQLite logging and notes (Phase 3).

## Goal

Help developers with a local model without slowing down or weakening Phase 1. Plain `git commit` and the secret check stay exactly as they are. AI help is opt-in, runs only when asked for or when a commit is already blocked, and can never let a secret through.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Developer hardware | 16 GB RAM, no GPU (answered by the user) | Fits a 3–4B model at 4-bit (about 2.5 GB RAM) on the CPU, roughly 5–10 s per short answer. |
| Default model | Qwen2.5-3B-Instruct, Q4_K_M `.gguf`; Llama-3.2-3B-Instruct as the alternative | Good small instruct models; both formats supported by `prompt_format`. |
| How the model runs | GitWarden runs llamafile itself as a **one-off command** per request (prompt in, text out, process exits), with a hard timeout | Chosen by the user (option B over a background server). One-off mode needs no ports, no background process and no process management on Windows. The OS file cache makes later runs load faster. |
| Ollama | Dropped from Phase 2 | It always needs its background server, which is the approach not chosen. Can be added later as a second runner. |
| Model power over findings | **Advisory only**: the model adds an opinion; rules alone decide block/pass | Chosen by the user. A wrong or tricked model can never let a secret through. |
| Commit message drafting | **On request** with `gitwarden commit`; plain `git commit` is untouched | Chosen by the user. A 5–10 s wait only happens when asked for. |
| Model input for reviews | Redacted lines only, never the raw secret | Keeps Phase 1's rule that a raw secret is never stored or shown, including in the temporary prompt file. |
| Network | None. llamafile runs as a local program | "No code leaves the company" holds by construction. |
| Downloads | GitWarden never downloads anything; the README explains where to get llamafile and the model | Keeps installs reviewable; a company can use an internal mirror. |
| Code style | Same as Phase 1: simple enough for a junior developer | See the Phase 1 spec, "Code style". |

## 1. Components

```
src/gitwarden/
├── llm.py        # runs llamafile once: ask(prompt, settings) -> str | None
├── prompts.py    # prompt texts and the chat formats (chatml, llama3)
├── draft.py      # staged diff -> short summary -> commit message draft
└── review.py     # blocked findings -> one model call -> opinions
```

Changes to existing modules:

- `config.py`: new `[llm]` table (below).
- `cli.py`: new commands `gitwarden commit` and `gitwarden llm check`.
- `hooks.py`: after printing a blocking report, call `review.py` if enabled. The exit code is computed before and is never changed by it.
- `git.py`: `diff_stat_staged(root) -> str`, `recent_subjects(root, count) -> list[str]`, `git_dir(root) -> Path`.

### `llm.py`

```
@dataclass LlmAnswer(text: str | None, error: str | None, seconds: float)
ask(prompt: str, settings: LlmConfig) -> LlmAnswer
```

- Writes the prompt to a temporary file, runs llamafile with a timeout, deletes the file in a `finally` block, and returns the answer text. Every failure (program missing, model missing, timeout, crash, empty output) returns `text=None` with a one-line `error`. **It never raises.**
- The command is built in one function, `build_command(settings, prompt_path) -> list[str]`:
  `[llamafile, "-m", model, "-f", prompt_path, "-n", max_tokens, "--temp", "0.2", "--no-display-prompt", "--log-disable"]`.
  **The exact flags must be checked against `--help` of the pinned llamafile release** (the README names the version) as the first implementation step; only `build_command` changes if they differ.
- The prompt goes in a file (`-f`), not on the command line: no Windows command-length limit, and the diff isn't visible in the process list.
- On a timeout, `subprocess.run(timeout=...)` kills the process.

### Config: `[llm]` in `.gitwarden.toml`

```toml
[llm]
enabled = false                                   # off until set up
llamafile = "~/.gitwarden/llamafile"              # llamafile.exe on Windows
model = "~/.gitwarden/qwen2.5-3b-instruct-q4_k_m.gguf"
prompt_format = "chatml"                          # chatml | llama3
timeout_seconds = 30                              # > 0
max_tokens = 200                                  # > 0
review_findings = true
```

`~` is expanded. Unknown keys and bad values are config errors (exit `2`), as in Phase 1. When `enabled = false`, nothing in this phase runs.

### `prompts.py`

- `wrap(system: str, user: str, prompt_format: str) -> str` produces the full prompt text in ChatML (`<|im_start|>system ... <|im_end|>`, ending with `<|im_start|>assistant\n`) or Llama 3 format (`<|begin_of_text|><|start_header_id|>system<|end_header_id|> ... <|eot_id|>`, ending with the assistant header).
- `COMMIT_SYSTEM` and `REVIEW_SYSTEM` are the fixed instruction texts (below).

## 2. `gitwarden commit`

1. Nothing staged: stop with "Nothing is staged. Use `git add` first." (exit 1).
2. Run the Phase 1 scan on the staged changes. If it blocks, print the normal report (with model opinions, section 3) and stop with exit 1. No drafting.
3. If `[llm] enabled` is false: print "AI drafting is off (`[llm] enabled = false`); opening the editor empty." and go to step 7 without a draft.
4. Build the summary (`draft.build_summary`):
   - `git diff --cached --stat` output
   - changed lines from the staged diff (`+` and `-` lines, context dropped), **at most 40 lines per file and 3 000 characters in total**; anything cut is marked `... (N more lines)`
   - subjects of the last 5 commits (`git log -5 --format=%s`), for style; none in a new repo
5. Ask the model with `COMMIT_SYSTEM`:
   "Write a git commit message for the change below. First line: a summary of at most 72 characters in the imperative mood (for example 'Add login rate limit'). Then a blank line, then at most 3 short bullet points. Output only the commit message." Print "Drafting a commit message with the local model... (the first run of the day can take ~15 s)" to stderr first.
6. Tidy the answer (`draft.clean_message`): strip surrounding whitespace, code fences and quotes, and a leading `Commit message:` line. An empty result counts as no draft.
7. Commit: write the draft (or nothing) to `<git dir>/GITWARDEN_DRAFT_MSG` and run `git commit -e -F <that file>` attached to the terminal (stdin, stdout and stderr not captured), so the developer's editor opens. Without a draft, run plain `git commit`. GitWarden exits with git's exit code. The pre-commit hook runs as usual. An empty message aborts, as git always does.
8. If the model fails: print "GitWarden couldn't draft a message (<error>); opening the editor empty." and continue as in step 7 without a draft.

Not included: passing other `git commit` flags through (`--amend`, `-a`), committing without the editor, choosing between several drafts.

Speed target: with the default model on a 16 GB no-GPU laptop, a warm draft of a capped summary takes about 10 s or less. This is measured with `gitwarden llm check` and the model tests (section 4), not enforced in CI.

## 3. Advisory opinion on blocked findings

Runs only when `[llm] enabled` and `review_findings` are true **and** there is at least one blocking finding (pre-commit, pre-push, `gitwarden scan`, `gitwarden commit`).

1. The normal report is printed first.
2. One model call covers the first 5 blocking findings. For each, the prompt holds a number, the rule id and description, the path, and the **redacted** line. Nothing else from the file.
3. `REVIEW_SYSTEM` asks for exactly one line per finding: `<number>: <real|test|unsure> | <short reason>`.
4. `review.parse_opinions` keeps only lines matching `^\s*(\d+)\s*:\s*(real|test|unsure)\s*\|\s*(.+)$` (case-insensitive), for numbers that exist. Anything else is dropped.
5. Printed to stderr after the report:
   ```
   Local model's opinion (advisory only, does not change the result):
     config/settings.py:14  real    - production settings file, AWS key format
     tests/test_login.py:3  test    - path is under tests/ and the value looks like a placeholder
   If one really is a test value, use `gitwarden allow` as shown above.
   ```
6. If the model fails or no line parses: print one line, `No model opinion: <error>` (or `No model opinion: answer not understood`), and nothing else.
7. **The exit code is decided before the review and is never changed by it.**

## 4. `gitwarden llm check`, errors, testing

### `gitwarden llm check`

Checks, stopping at the first problem with its fix, exit `2`:

1. `[llm] enabled` is true. Fix: set it in `.gitwarden.toml`.
2. The llamafile path exists. On Linux and macOS it must be executable (fix: `chmod +x <path>`). On Windows the name must end in `.exe` (fix: rename it).
3. The model path exists.
4. A tiny prompt ("Reply with the single word OK.") returns any non-empty text within the timeout. If the error output mentions `run-detectors` or the program won't start on Linux or WSL (a known binfmt problem), the message points to the "Gotchas" section of the llamafile README for the pinned release.

On success: `OK: model answered in 6.8 s (the first run after a restart is slower; run again for the warm time)`, exit `0`.

### Error handling

| Situation | Behaviour |
|---|---|
| `[llm] enabled = false` | Nothing from this phase runs; `gitwarden commit` opens the editor empty |
| llamafile or model missing | `LlmAnswer.text = None`, `error` names the missing path |
| Slower than `timeout_seconds` | Process killed; `error = "timed out after N s"` |
| Non-zero exit | `error` = first line of its stderr |
| Empty or unusable answer | Draft: editor opens empty. Review: `No model opinion: answer not understood` |
| Bad `[llm]` config | Config error, exit `2` (Phase 1 rule) |

No model problem ever blocks a commit or push, or changes an exit code.

### Tests (CI, no real model)

- `llm.py`: `subprocess.run` is replaced by a fake. Tests check the exact command from `build_command`, that the prompt file holds the prompt and is deleted afterwards (also after a timeout), and that a missing program, a missing model, a timeout, a non-zero exit and empty output each give `text=None` with the right `error`.
- `prompts.py`: `wrap` output for both formats against fixed expected strings.
- `draft.py`: summary limits (40 lines per file, 3 000 characters, `... (N more lines)` marker, recent subjects included); `clean_message` on fenced, quoted, prefixed and empty answers.
- `review.py`: the prompt contains redacted lines and **no raw secret** (checked with a fake secret from `tests/fakes.py`); at most 5 findings; parsing of good, mixed and garbage answers; output text.
- Integration (real repos, `ask` replaced by a fake):
  - `gitwarden commit` with a draft: `GIT_EDITOR=true` (git runs the editor through `sh`, also on Windows, so `true` is a no-op everywhere), and the new commit's message equals the draft
  - model returns nothing: an empty editor aborts the commit with git's normal message
  - staged secret: stops before drafting (`ask` is called at most once, for the review, and never with the commit-message prompt)
  - a blocked pre-commit with review on: exit code 1, opinion section printed
  - the same with `ask` failing: exit code 1, `No model opinion:` printed
- Config: `[llm]` defaults, `~` expansion, bad `prompt_format`, unknown key.

### Real-model tests (local only)

Marked `@pytest.mark.model`. They run only when both `GITWARDEN_TEST_LLAMAFILE` and `GITWARDEN_TEST_MODEL` are set, so they're skipped in CI. They:

- check that a draft for a small sample diff is non-empty with a first line of at most 72 characters
- check that a finding in `tests/fixtures/` with a placeholder-looking redacted value gets the verdict `test`
- print cold and warm timings

Run on a company laptop, this is the Phase 0 "measure speed on a typical laptop" step.

### README

A "Local AI help (optional)" section:

- which llamafile release to use (pinned) and the Qwen2.5-3B-Instruct Q4_K_M `.gguf`
- where to put both (`~/.gitwarden/`)
- `chmod +x` on Linux and macOS, renaming to `.exe` on Windows
- setting `[llm] enabled = true`, then running `gitwarden llm check`

A company may host both files on an internal mirror.

### CI

Unchanged: Linux, macOS and Windows × Python 3.11 and 3.13; ruff + pytest. Model tests are skipped.

## Open items

- **llamafile flags:** confirm the exact command-line flags against the pinned llamafile release before building `build_command`.
- **Real timings:** to be measured on an actual company laptop with `gitwarden llm check` and the model tests.
- **Phase 3:** the HR agreement on profile contents is still needed.
