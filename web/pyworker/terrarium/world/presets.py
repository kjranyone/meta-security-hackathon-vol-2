"""Load world presets from YAML."""
from __future__ import annotations

from pathlib import Path

import yaml

from .models import WorldSpec

PRESET_DIR = Path(__file__).resolve().parents[3] / "presets"


def load_preset(name: str = "default") -> WorldSpec:
    if name == "earth_all":
        # 全国家AI化プリセットはGeoJSONから手続き生成（決定論）
        from .earth_all import build_earth_all
        return build_earth_all()
    if name.startswith("gen:"):
        # 生成世界（ドメインランダム化）: gen:<seed>
        from .worldgen import GenParams, generate_world
        return generate_world(GenParams(seed=int(name.split(":", 1)[1])))
    path = PRESET_DIR / f"{name}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return WorldSpec(**data)
