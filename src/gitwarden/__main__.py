"""`python -m gitwarden` and the `gitwarden` command start here."""

import sys


def main() -> None:
    """Hooks go straight to hooks.run_hook (skipping the CLI library keeps them fast)."""
    for stream in (sys.stdout, sys.stderr):
        # Never crash on a character the console can't show (Windows consoles).
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    if len(sys.argv) >= 3 and sys.argv[1] == "hook":
        from gitwarden.hooks import run_hook

        hook_name = sys.argv[2]
        stdin_text = sys.stdin.read() if hook_name == "pre-push" else ""
        sys.exit(run_hook(hook_name, sys.argv[3:], stdin_text))

    from gitwarden.cli import app

    app()


if __name__ == "__main__":
    main()
