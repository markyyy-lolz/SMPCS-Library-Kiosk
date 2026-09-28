from __future__ import annotations
import json
import os
from pathlib import Path
from dotenv import load_dotenv

APP_DIR = Path(os.getenv("APPDATA", Path.home())) / "SMPCS_Library"
APP_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(APP_DIR / ".env")
load_dotenv()

def config_path() -> Path:
    return APP_DIR / "config.json"

def load_config() -> dict:
    p = config_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_config(data: dict) -> None:
    tmp = config_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(config_path())

def get_value(key: str, default=None):
    return load_config().get(key, os.getenv(key, default))
