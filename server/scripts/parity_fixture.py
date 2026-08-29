"""ブラウザ実行(Pyodide)とのbit一致検証の基準値を生成する。

ネイティブ側で earth/seed42/介入モード時計(1h/tick, 週次決定)・400tick
(週次RL決定2回込み)を走らせ、tick毎のmetrics列を
tests/fixtures/parity_earth_seed42.json へ書き出す。

検証の全体手順は README「ブラウザ実行版」節:
  1. uv run python scripts/parity_fixture.py     # 基準値の生成
  2. uv run pytest tests/test_parity_fixture.py   # 現行エンジンが基準値通りか
  3. node ../frontend/scripts/parity_check.mjs   # ブラウザ実行が基準値とbit一致か
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER / "../web/pyworker"))

import driver  # noqa: E402

WORLD = SERVER / "../web/pyworker/worlds/earth.json"
TICKS = 400
SEED = 42
OUT = SERVER / "tests/fixtures/parity_earth_seed42.json"


def native_metrics() -> list[dict]:
    spec = WORLD.read_text(encoding="utf-8")
    s = driver.LiveSession(spec, SEED, TICKS,
                           str(SERVER / "models/generalist_llm_deep_bc.npz"))
    out = []
    for _ in range(TICKS):
        snap = s.step()
        if snap is None:
            break
        out.append(snap["metrics"])
    return out


if __name__ == "__main__":
    metrics = native_metrics()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(metrics, ensure_ascii=False), encoding="utf-8")
    print(f"{len(metrics)} ticks -> {OUT}")
    print("last:", metrics[-1])
