"""現行エンジンがパリティ基準値(bit一致検証のfixture)と同一の出力を
産むことを検証する。engine.pyの力学を変えたら基準値の再生成
(scripts/parity_fixture.py)とブラウザ側再検証が必要であることを
この失敗が知らせる。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "parity_fixture", SERVER / "scripts/parity_fixture.py")
pf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pf)


def test_native_matches_parity_fixture() -> None:
    expected = json.loads((SERVER / "tests/fixtures/parity_earth_seed42.json")
                          .read_text(encoding="utf-8"))
    actual = pf.native_metrics()
    assert json.dumps(actual) == json.dumps(expected), (
        "ネイティブ実行がパリティ基準値と不一致 — engine.pyの力学が変わった。"
        "意図的なら scripts/parity_fixture.py で基準値を再生成し、"
        "ブラウザ側の再検証(node frontend/scripts/parity_check.mjs)も実行すること")
