"""Load world presets from YAML."""
from __future__ import annotations

from pathlib import Path

import yaml

from .models import WorldSpec

PRESET_DIR = Path(__file__).resolve().parents[3] / "presets"


def load_preset(name: str = "default") -> WorldSpec:
    path = PRESET_DIR / f"{name}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return WorldSpec(**data)
