from pathlib import Path

import pytest

from gitwarden.config import CONFIG_FILE, Config, LlmConfig, load_config, pack_paths
from gitwarden.errors import GitWardenError


def write_config(root: Path, text: str) -> None:
    (root / CONFIG_FILE).write_text(text, encoding="utf-8")


def test_missing_file_gives_defaults(tmp_path):
    config = load_config(tmp_path)
    assert config == Config()
    assert config.scan.block_on == "medium"
    assert config.scan.max_file_kb == 512
    assert config.hooks.pre_commit and config.hooks.pre_push
    assert config.allowlist.max_days == 90


def test_values_are_read(tmp_path):
    write_config(
        tmp_path,
        '[scan]\nblock_on = "high"\npaths_exclude = ["^docs/"]\n'
        '[rules]\ndisable = ["generic/jwt"]\n'
        "[hooks]\npre_push = false\n",
    )
    config = load_config(tmp_path)
    assert config.scan.block_on == "high"
    assert config.scan.paths_exclude == ["^docs/"]
    assert config.rules.disable == ["generic/jwt"]
    assert config.hooks.pre_push is False


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('[scan]\nblock_on = "urgent"\n', "scan.block_on"),
        ("[scan]\nmax_file_kb = 0\n", "scan.max_file_kb"),
        ("[scan]\nblok_on = 'high'\n", "scan.blok_on"),
        ("[scan\n", "not valid TOML"),
        ("[scan]\npaths_exclude = ['(']\n", "bad regex in paths_exclude"),
    ],
)
def test_mistakes_are_errors(tmp_path, text, message):
    write_config(tmp_path, text)
    with pytest.raises(GitWardenError, match=message.replace("[", r"\[")):
        load_config(tmp_path)


def test_pack_paths_are_relative_to_repo_root(tmp_path):
    absolute = (tmp_path / "elsewhere" / "other.toml").as_posix()
    write_config(tmp_path, f'[rules]\npacks = ["rules/acme.toml", "{absolute}"]\n')
    paths = pack_paths(tmp_path, load_config(tmp_path))
    assert paths[0] == tmp_path / "rules/acme.toml"
    assert paths[1] == Path(absolute)


def test_llm_is_off_by_default_with_sensible_defaults(tmp_path):
    llm = load_config(tmp_path).llm
    assert llm == LlmConfig()
    assert llm.enabled is False
    assert llm.prompt_format == "chatml"
    assert llm.timeout_seconds == 30
    assert llm.max_tokens == 200
    assert llm.review_findings is True
    assert llm.model.endswith(".gguf")


def test_llm_values_are_read(tmp_path):
    write_config(
        tmp_path,
        '[llm]\nenabled = true\nprompt_format = "llama3"\ntimeout_seconds = 60\n'
        'model = "~/models/llama.gguf"\n',
    )
    llm = load_config(tmp_path).llm
    assert llm.enabled is True
    assert llm.prompt_format == "llama3"
    assert llm.timeout_seconds == 60
    assert llm.model == "~/models/llama.gguf"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('[llm]\nprompt_format = "mistral"\n', "llm.prompt_format"),
        ("[llm]\ntimeout_seconds = 0\n", "llm.timeout_seconds"),
        ("[llm]\nturbo = true\n", "llm.turbo"),
    ],
)
def test_llm_mistakes_are_errors(tmp_path, text, message):
    write_config(tmp_path, text)
    with pytest.raises(GitWardenError, match=message):
        load_config(tmp_path)
