from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def load_env_file(path: Path | None = None) -> None:
    env_path = path or BASE_DIR / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _path_from_env(name: str, default: str) -> Path:
    raw_path = Path(os.environ.get(name, default)).expanduser()
    if raw_path.is_absolute():
        return raw_path
    return BASE_DIR / raw_path


def _int_from_env(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


@dataclass(frozen=True)
class AppConfig:
    host: str
    port: int
    database_path: Path
    static_dir: Path
    deepseek_api_key: str
    deepseek_api_url: str
    deepseek_model: str
    deepseek_timeout_seconds: int

    @classmethod
    def from_environment(cls) -> "AppConfig":
        load_env_file()

        return cls(
            host=os.environ.get("HOST", "127.0.0.1"),
            port=_int_from_env("PORT", 8000),
            database_path=_path_from_env("DATABASE_PATH", "data/campus_alerts.sqlite3"),
            static_dir=BASE_DIR / "static",
            deepseek_api_key=os.environ.get("DEEPSEEK_API_KEY", "").strip(),
            deepseek_api_url=os.environ.get(
                "DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions"
            ).strip(),
            deepseek_model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat").strip(),
            deepseek_timeout_seconds=_int_from_env("DEEPSEEK_TIMEOUT_SECONDS", 20),
        )

