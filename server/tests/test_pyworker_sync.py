"""web/pyworker/ が server/src と同期しているかを検証する。

engine.py 等を変更して scripts/sync_pyworker.py の再実行を忘れると、
ブラウザ実行版(live)だけ古い力学で動き、ネイティブとのbit一致主張が
黙って破れる。このテストはその drift をCI/pytestで拾う。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1]
REPO = SERVER.parent
PW = REPO / "web" / "pyworker"

_spec = importlib.util.spec_from_file_location(
    "sync_pyworker", SERVER / "scripts" / "sync_pyworker.py")
sync_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync_mod)
SUBSET = sync_mod.SUBSET


@pytest.mark.parametrize("rel", SUBSET)
def test_pyworker_file_matches_source(rel: str) -> None:
    src = (SERVER / "src" / rel).read_bytes()
    dst = (PW / rel).read_bytes()
    assert src == dst, (
        f"web/pyworker/{rel} が server/src と不一致 — "
        "`uv run python scripts/sync_pyworker.py` を実行してコミットしてください")


def test_pyworker_manifest_and_shims() -> None:
    man = json.loads((PW / "manifest.json").read_text(encoding="utf-8"))
    assert set(SUBSET) <= set(man["py"]), "manifestがSUBSETを網羅していない(sync再実行)"
    for shim in ("pydantic.py", "yaml.py", "driver.py"):
        assert (PW / shim).exists(), f"shim {shim} が無い(sync再実行)"
    assert (REPO / "web" / man["weights"]).exists(), "配信重みが無い"
