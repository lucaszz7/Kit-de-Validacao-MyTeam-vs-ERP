import json
from pathlib import Path


def _config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "config.json"


def load_config():
    config_path = _config_path()
    with config_path.open("r", encoding="utf-8") as file:
        return json.load(file)