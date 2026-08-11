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
    api_key_file: Path
    cache_path: Path


def load_settings(
    project_root: Path, environ: Mapping[str, str] | None = None
) -> Settings:
    """Load key-file and cache paths without loading the credential itself."""
    config_path = project_root / "config.local.toml"
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ConfigError("로컬 설정 파일을 찾을 수 없습니다.") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigError("로컬 설정 파일 형식이 올바르지 않습니다.") from error

    environment = process_environ if environ is None else environ
    api_key_file = environment.get("LAW_API_KEY_FILE", config.get("api_key_file"))
    cache_path = environment.get("LAW_CACHE_PATH", config.get("cache_path"))
    if not api_key_file or not cache_path:
        raise ConfigError("API 인증정보 파일 경로와 캐시 경로가 필요합니다.")

    resolved_cache_path = Path(cache_path)
    if not resolved_cache_path.is_absolute():
        resolved_cache_path = project_root / resolved_cache_path

    return Settings(api_key_file=Path(api_key_file), cache_path=resolved_cache_path)


def load_api_key(path: Path) -> str:
    """Load one plaintext API key without exposing it in error messages."""
    value = path.read_text(encoding="utf-8-sig").strip()
    if not value:
        raise ConfigError("API 인증정보 파일이 비어 있습니다.")
    return value
