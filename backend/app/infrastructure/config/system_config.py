from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from app.domain.system_config import SystemConfig

SYSTEM_CONFIG_PATH = Path(__file__).resolve().parents[2] / "data" / "system_config.yaml"


@lru_cache(maxsize=1)
def load_system_config(path: str | Path | None = None) -> SystemConfig:
    config_path = Path(path) if path else SYSTEM_CONFIG_PATH
    with config_path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    return SystemConfig.model_validate(payload)
