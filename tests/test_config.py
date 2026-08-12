from pathlib import Path

import pytest

from lawsearch.config import ConfigError, load_api_key, load_settings


def test_settings_store_only_external_key_path(tmp_path: Path):
    """Changing Settings to hold a credential value must fail this test."""
    key_file = tmp_path / "law-key.txt"
    config = tmp_path / "config.local.toml"
    config.write_text(
        f'api_key_file = "{key_file.as_posix()}"\ncache_path = "data/cache.db"\n',
        encoding="utf-8",
    )

    settings = load_settings(tmp_path, {})

    assert settings.api_key_file == key_file
    assert settings.cache_path == tmp_path / "data" / "cache.db"
    assert not hasattr(settings, "api_key")


def test_plaintext_key_is_trimmed(tmp_path: Path):
    """Removing whitespace normalization must fail this test."""
    key_file = tmp_path / "key.txt"
    key_file.write_text("  approved-key  \n", encoding="utf-8")

    assert load_api_key(key_file) == "approved-key"


def test_labeled_key_file_selects_exact_law_api_field(tmp_path: Path):
    """Returning the whole multi-key file or a neighboring value must fail."""
    key_file = tmp_path / "my_api_keys.txt"
    key_file.write_text(
        "API keys\n"
        "6. unrelated service: wrong-value\n"
        "7. 국가법령정보 공동활용: selected-law-value\n"
        "8. another service: another-wrong-value\n",
        encoding="utf-8",
    )

    assert load_api_key(key_file) == "selected-law-value"


def test_empty_key_file_is_rejected(tmp_path: Path):
    """Removing empty-key validation must fail this test."""
    key_file = tmp_path / "key.txt"
    key_file.write_text(" \n", encoding="utf-8")

    with pytest.raises(ConfigError, match="비어"):
        load_api_key(key_file)


def test_environment_overrides_local_config(tmp_path: Path):
    """Ignoring LAW_* overrides must fail this test."""
    config_key = tmp_path / "config-key.txt"
    override_key = tmp_path / "override-key.txt"
    (tmp_path / "config.local.toml").write_text(
        f'api_key_file = "{config_key.as_posix()}"\ncache_path = "data/config.db"\n',
        encoding="utf-8",
    )

    settings = load_settings(
        tmp_path,
        {"LAW_API_KEY_FILE": str(override_key), "LAW_CACHE_PATH": "data/override.db"},
    )

    assert settings.api_key_file == override_key
    assert settings.cache_path == tmp_path / "data" / "override.db"
