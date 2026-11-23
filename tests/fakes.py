"""Fake secrets for the test set.

The test cases in tests/corpus/ hold placeholders like {{github_token}} instead of
realistic tokens. Keeping real-looking tokens out of the repo means GitHub push
protection (and GitWarden itself) won't block pushes of this project.
fill() swaps each placeholder for a fake value with the right format.
"""

import base64
import random
import re
import string

LETTERS_DIGITS = string.ascii_letters + string.digits
UPPER_DIGITS = string.ascii_uppercase + string.digits
BASE64_CHARS = LETTERS_DIGITS + "+/"
URL_SAFE = LETTERS_DIGITS + "-_"
HEX = "0123456789abcdef"

PLACEHOLDER = re.compile(r"\{\{([a-z0-9_]+)\}\}")


def _pick(rng: random.Random, chars: str, length: int) -> str:
    return "".join(rng.choice(chars) for _ in range(length))


def _basic_auth(rng: random.Random) -> str:
    user_and_password = "deploy:" + _pick(rng, LETTERS_DIGITS, 14)
    return base64.b64encode(user_and_password.encode()).decode()


GENERATORS = {
    "aws_access_key_id": lambda r: "AKIA" + _pick(r, UPPER_DIGITS, 16),
    "aws_secret_access_key": lambda r: _pick(r, BASE64_CHARS, 40),
    "gcp_private_key_id": lambda r: _pick(r, HEX, 40),
    "azure_account_key": lambda r: _pick(r, BASE64_CHARS, 86) + "==",
    "github_token": lambda r: "ghp_" + _pick(r, LETTERS_DIGITS, 36),
    "github_pat": lambda r: (
        "github_pat_" + _pick(r, LETTERS_DIGITS, 22) + "_" + _pick(r, LETTERS_DIGITS, 59)
    ),
    "gitlab_token": lambda r: "glpat-" + _pick(r, LETTERS_DIGITS, 20),
    "slack_token": lambda r: (
        "xoxb-"
        + _pick(r, string.digits, 12)
        + "-"
        + _pick(r, string.digits, 12)
        + "-"
        + _pick(r, LETTERS_DIGITS, 24)
    ),
    "slack_webhook": lambda r: (
        "https://hooks.slack.com/services/T"
        + _pick(r, UPPER_DIGITS, 8)
        + "/B"
        + _pick(r, UPPER_DIGITS, 8)
        + "/"
        + _pick(r, LETTERS_DIGITS, 24)
    ),
    "stripe_key": lambda r: "sk_live_" + _pick(r, LETTERS_DIGITS, 24),
    "sendgrid_key": lambda r: "SG." + _pick(r, URL_SAFE, 22) + "." + _pick(r, URL_SAFE, 43),
    "google_api_key": lambda r: "AIza" + _pick(r, URL_SAFE, 35),
    "npm_token": lambda r: "npm_" + _pick(r, LETTERS_DIGITS, 36),
    "llm_api_key": lambda r: "sk-proj-" + _pick(r, LETTERS_DIGITS, 48),
    "jwt": lambda r: (
        "eyJ"
        + _pick(r, URL_SAFE, 20)
        + ".eyJ"
        + _pick(r, URL_SAFE, 30)
        + "."
        + _pick(r, URL_SAFE, 43)
    ),
    "password": lambda r: _pick(r, LETTERS_DIGITS, 16),
    "basic_auth": _basic_auth,
}


def fill(template: str, seed: int = 1234) -> str:
    """Replace every {{name}} in the template with a fake value (same seed = same values)."""
    rng = random.Random(seed)

    def replace(match: re.Match[str]) -> str:
        return GENERATORS[match.group(1)](rng)

    return PLACEHOLDER.sub(replace, template)


def fake(name: str, seed: int = 1234) -> str:
    """One fake value, for example fake("github_token")."""
    return fill("{{" + name + "}}", seed)
