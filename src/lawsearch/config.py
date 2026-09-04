"""Local, secret-safe configuration loading."""

from dataclasses import dataclass
from os import environ as process_environ
from pathlib import Path
from typing import Mapping
import tomllib


class ConfigError(ValueError):
    """Raised when local configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    api_key_file: Path | None
    cache_path: Path


def load_settings(
    project_root: Path, environ: Mapping[str, str] | None = None
) -> Settings:
    """Resolve the key-file and cache paths without loading the credential.

    A missing ``config.local.toml`` is not an error — the Streamlit Cloud
    deployment has no such file and supplies the key through ``st.secrets``.
    """
    config_path = project_root / "config.local.toml"
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        config = {}
    except tomllib.TOMLDecodeError as error:
        raise ConfigError("로컬 설정 파일 형식이 올바르지 않습니다.") from error

    environment = process_environ if environ is None else environ
    api_key_file = environment.get("LAW_API_KEY_FILE", config.get("api_key_file"))
    cache_path = (
        environment.get("LAW_CACHE_PATH", config.get("cache_path")) or "data/cache.db"
    )

    resolved_cache_path = Path(cache_path)
    if not resolved_cache_path.is_absolute():
        resolved_cache_path = project_root / resolved_cache_path

    return Settings(
        api_key_file=Path(api_key_file) if api_key_file else None,
        cache_path=resolved_cache_path,
    )


def load_api_key(path: Path) -> str:
    """Load one plaintext API key without exposing it in error messages."""
    value = path.read_text(encoding="utf-8-sig").strip()
    if not value:
        raise ConfigError("API 인증정보 파일이 비어 있습니다.")
    lines = value.splitlines()
    if len(lines) > 1:
        target = "7. 국가법령정보 공동활용"
        for line in lines:
            label, separator, field_value = line.partition(":")
            if separator and label.strip() == target and field_value.strip():
                return field_value.strip()
        raise ConfigError("API 인증정보 파일에 국가법령정보 공동활용 항목이 없습니다.")
    return value
