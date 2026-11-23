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
