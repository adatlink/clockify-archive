from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.11+ only
    tomllib = None  # type: ignore


@dataclass
class Settings:
    api_key: str | None = None
    workspace: str | None = None
    base_url: str = "https://api.clockify.me/api/v1"


CONFIG_CANDIDATES = (
    Path("~/.config/clockify-archive/config.toml").expanduser(),
    Path("~/.config/clockify-tools/config.toml").expanduser(),
    Path("~/.config/clockify-import/config.toml").expanduser(),
)


def _extract_clockify(data: dict[str, Any]) -> dict[str, Any]:
    for key in ("clockify", "default", "settings"):
        section = data.get(key)
        if isinstance(section, dict):
            return section
    return data


def load_settings(config_path: str | None = None) -> Settings:
    settings = Settings()
    candidates = [Path(config_path).expanduser()] if config_path else list(CONFIG_CANDIDATES)
    for path in candidates:
        if not path.exists() or tomllib is None:
            continue
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        cfg = _extract_clockify(data)
        settings.api_key = cfg.get("api_key") or cfg.get("apiKey") or settings.api_key
        settings.workspace = cfg.get("workspace") or cfg.get("workspace_id") or settings.workspace
        settings.base_url = cfg.get("base_url") or settings.base_url
        break

    settings.api_key = os.getenv("CLOCKIFY_API_KEY", settings.api_key)
    settings.workspace = os.getenv("CLOCKIFY_WORKSPACE", settings.workspace)
    settings.base_url = os.getenv("CLOCKIFY_BASE_URL", settings.base_url)
    return settings


def write_example_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(str(path))
    path.write_text(
        '[clockify]\n'
        'api_key = "YOUR_CLOCKIFY_API_KEY"\n'
        'workspace = "workspace-id-or-exact-name"\n'
        'base_url = "https://api.clockify.me/api/v1"\n',
        encoding="utf-8",
    )
