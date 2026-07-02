import sys
import json
from pathlib import Path


def _config_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "config"
    return Path(__file__).resolve().parents[2] / "config"


def _config_path() -> Path:
    return _config_dir() / "config.json"


def config_exists() -> bool:
    return _config_path().exists()


def load_config():
    config_path = _config_path()
    with config_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_config(data: dict) -> None:
    config_dir = _config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = _config_dir() / "config.json"
    with config_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)
