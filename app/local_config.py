from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Any


CONFIG_FILE_NAME = "app_config.json"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / CONFIG_FILE_NAME


class ConfigError(Exception):
    """Raised when the local app configuration cannot be loaded or saved."""


@dataclass(slots=True)
class AppConfig:
    api_base_url: str = ""
    auth_token: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        return cls(
            api_base_url=str(data.get("api_base_url") or "").strip(),
            auth_token=str(data.get("auth_token") or ""),
        )


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    if not config_path.exists():
        return AppConfig()

    try:
        with config_path.open("r", encoding="utf-8") as config_file:
            data = json.load(config_file)
    except JSONDecodeError as exc:
        raise ConfigError("O arquivo app_config.json esta invalido.") from exc
    except OSError as exc:
        raise ConfigError("Nao foi possivel ler o app_config.json.") from exc

    if not isinstance(data, dict):
        raise ConfigError("O arquivo app_config.json esta em um formato invalido.")

    return AppConfig.from_dict(data)


def save_config(config: AppConfig, config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with config_path.open("w", encoding="utf-8") as config_file:
            json.dump(asdict(config), config_file, indent=2)
            config_file.write("\n")
    except OSError as exc:
        raise ConfigError("Nao foi possivel salvar o app_config.json.") from exc
