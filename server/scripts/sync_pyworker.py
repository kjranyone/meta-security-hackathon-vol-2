"""ブラウザライブ実行用に terrarium の Python コード一式を web/pyworker/ へ同期する。

神モード(live.html)は Pyodide(CPython+WASM)上で**本物の engine.py と numpy 推論**
を走らせる — 力学をJSに移植しないので、ネイティブ実行と同じ決定論・同じ重み
(bit一致)になる。このスクリプトは:

1. terrarium の必要サブセット(エンジン/RL/エージェント)を web/pyworker/terrarium/ へ複写
2. pydantic の純Pythonシム(検証なし・フィールド既定値とmodel_dumpのみ)と
   yaml スタブを置く (WASMビルドにC拡張のpydantic-coreが無いため)
3. プリセットをネイティブ側で model_dump した spec JSON を web/pyworker/worlds/ へ
4. ドライバ(driver.py = サーバSessionのWSプロトコル互換)を書き出す

engine側を変更したら再実行してコミットする。
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER / "src"))

WEB_PW = SERVER.parent / "web" / "pyworker"

SUBSET = [
    "terrarium/__init__.py",
    "terrarium/agents/__init__.py",
    "terrarium/agents/base.py",
    "terrarium/agents/heuristic.py",
    "terrarium/agents/rl_policy.py",
    "terrarium/sim/__init__.py",
    "terrarium/sim/engine.py",
    "terrarium/sim/events.py",
    "terrarium/sim/interventions.py",
    "terrarium/rl/__init__.py",
    "terrarium/rl/env.py",
    "terrarium/rl/nets.py",
    "terrarium/world/__init__.py",
    "terrarium/world/clock.py",
    "terrarium/world/factors.py",
    "terrarium/world/models.py",
    "terrarium/world/presets.py",
    "terrarium/world/tech.py",
]

PYDANTIC_SHIM = '''"""純Python pydanticシム(WASMビルド用)。

pydantic-core(Rust)はPyodideに無いため、terrariumが使う機能だけを再現する:
型付きフィールド+既定値、Field(default_factory=...)、ネストdict→モデル/enumの
強制変換(get_type_hints駆動)、model_dump()。スカラー検証は行わない —
specはネイティブ側で model_dump した JSON を渡す前提で、正当性は
ネイティブ実行が保証している。
"""
from __future__ import annotations

import enum as _enum
import json as _json
import typing as _t

_Hints = {}


class _FieldInfo:
    __slots__ = ("default", "default_factory")

    def __init__(self, default=None, default_factory=None):
        self.default = default
        self.default_factory = default_factory


def Field(default=None, *, default_factory=None, **_ignored):
    return _FieldInfo(default, default_factory)


def _collect_fields(cls):
    names: list[str] = []
    for k in reversed(cls.__mro__):
        for name in getattr(k, "__annotations__", {}):
            if name not in names and not name.startswith("_"):
                names.append(name)
    return names


def _hints(cls):
    if cls not in _Hints:
        try:
            _Hints[cls] = _t.get_type_hints(cls)
        except Exception:
            _Hints[cls] = {}
    return _Hints[cls]


def _is_union(tp):
    return _t.get_origin(tp) in (_t.Union,) or str(_t.get_origin(tp)).endswith("UnionType")


def _coerce(v, tp):
    """dict→BaseModel、str→Enum の強制変換(ネスト list/dict/Optional 対応)。
    型が付かない/スカラーはそのまま。"""
    if v is None or tp is None:
        return v
    origin = _t.get_origin(tp)
    if origin is list:
        args = _t.get_args(tp) or (None,)
        return [_coerce(x, args[0]) for x in v]
    if origin is dict:
        args = _t.get_args(tp)
        return {k: _coerce(x, args[1] if len(args) > 1 else None) for k, x in v.items()}
    if _is_union(tp):
        for a in _t.get_args(tp):
            if a is type(None):
                continue
            r = _coerce(v, a)
            if r is not v:
                return r
        return v
    if isinstance(tp, type) and issubclass(tp, _enum.Enum):
        return v if isinstance(v, tp) else tp(v)
    if isinstance(tp, type) and isinstance(v, dict) and hasattr(tp, "model_dump"):
        return tp(**v)
    return v


def _dump(v):
    if hasattr(v, "model_dump"):
        return v.model_dump()
    if isinstance(v, _enum.Enum):
        return v.value
    if isinstance(v, dict):
        return {k: _dump(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_dump(x) for x in v]
    return v


class BaseModel:
    def __init__(self, **data):
        cls = type(self)
        _missing = object()
        hints = _hints(cls)
        for name in _collect_fields(cls):
            if name in data:
                v = data.pop(name)
                setattr(self, name, _coerce(v, hints.get(name)))
                continue
            fi = getattr(cls, name, _missing)
            if fi is _missing:
                raise TypeError(f"{cls.__name__}: missing required field {name!r}")
            if isinstance(fi, _FieldInfo):
                v = fi.default_factory() if fi.default_factory is not None else fi.default
            else:
                v = fi   # プレーンなクラス既定値(None含む)
            setattr(self, name, _coerce(v, hints.get(name)))
        if data:
            raise TypeError(f"{cls.__name__}: unexpected fields {sorted(data)}")

    def model_dump(self):
        return {name: _dump(getattr(self, name)) for name in _collect_fields(type(self))}

    def model_dump_json(self):
        return _json.dumps(self.model_dump())

    def copy(self, **update):
        d = self.model_dump()
        d.update(update)
        return type(self)(**d)
'''

YAML_STUB = '''"""yamlスタブ: WASMビルドではシナリオYAMLを読まない(介入は直接構築)。
import自体は interventions/presets が行うので、モジュールとして存在すれば良い。"""


def safe_load(_s):
    raise RuntimeError("yaml is not available in the WASM build")
'''

DRIVER = '''"""ライブ神モードのドライバ: サーバSessionのWSプロトコルと同じ形で
Pyodide上のエンジンを駆動する。JS(Worker)から呼ばれる。

メッセージ互換性が目的 — GodAppのUIはサーバ版と同じJSONを受けて動く。
"""
from __future__ import annotations

import json as _json
import os as _os

from terrarium.agents.rl_policy import RLPolicy
from terrarium.sim.engine import Engine
from terrarium.sim.interventions import Intervention
from terrarium.world.models import WorldSpec

SPEED_MS = 1200


class LiveSession:
    """サーバの Session(app.py) と同じ役割。1世界・1クライアント(Worker)。"""

    def __init__(self, spec_json: str, seed: int, ticks: int, weights_path: str):
        spec = WorldSpec(**_json.loads(spec_json))
        # 神モードのRTS時計(サーバと同一): 1tick=1時間・意思決定は週次
        spec.hours_per_tick = 1.0
        spec.decision_every_hours = 168.0
        policies = {ns.id: RLPolicy(ns.id, weights_path) for ns in spec.nations}
        self.eng = Engine(spec, policies, seed=seed, out_dir=None)
        self.max_ticks = ticks
        self.t = 0
        self.running = False
        self.speed_ms = SPEED_MS
        self.model_info = {
            "file": weights_path.rsplit("/", 1)[-1],
            "bytes": _os.path.getsize(weights_path),
            "nations": len(spec.nations),
        }

    # -------------------------------------------------------------- protocol
    def status(self) -> dict:
        return {"running": self.running, "speed_ms": self.speed_ms, "eff_ms": None,
                "tick": self.t, "max_ticks": self.max_ticks, "model": self.model_info}

    def meta(self) -> dict:
        eng, spec = self.eng, self.eng.spec
        return {
            "type": "meta", "run_name": "live-browser", "seed": eng.seed,
            "clock": {"hours_per_tick": eng.hpt,
                      "decision_every_hours": getattr(spec, "decision_every_hours", None)},
            "geo": {
                "map_geojson": spec.map_geojson,
                "nations": {ns.id: {"name": ns.name, "color": ns.color,
                                    "centroid": list(ns.centroid), "geo_ids": ns.geo_ids}
                            for ns in spec.nations},
                "chokepoints": [{"name": cp.name, "lon": cp.lon, "lat": cp.lat}
                                for cp in spec.chokepoints],
                "routes": [{"importer": r.importer, "exporter": r.exporter,
                            "commodity": r.commodity.value if hasattr(r.commodity, "value") else r.commodity,
                            "chokepoints": r.chokepoints} for r in spec.routes],
                "techs": [],
            },
            "status": self.status(),
        }

    def step(self) -> dict | None:
        eng = self.eng
        if self.t >= self.max_ticks:
            self.running = False
            return None
        eng.tick_no = self.t
        eng.step()
        self.t += 1
        snap = eng.snapshots[-1]
        # メモリ: snapshot/seriesは直近だけ残す(再送用に5件)
        del eng.snapshots[:-5]
        del eng.series[:-5]
        return {"type": "tick", **snap}

    def intervene(self, type_: str, params_json: str) -> dict:
        eng = self.eng
        iv = Intervention(tick=self.t, type=type_, params=_json.loads(params_json or "{}"))
        try:
            eng.apply_intervention(iv)
        except Exception as exc:  # サーバと同じ: 不正介入で死なない
            return {"type": "error", "message": f"intervention failed: {exc}"}
        ev = eng.event_log.records[-1] if eng.event_log.records else None
        return {"type": "god", "event": ev.model_dump() if ev else None}

    def recent(self) -> list[dict]:
        return [{"type": "tick", **s} for s in self.eng.snapshots]


def new_session(spec_json: str, seed: int, ticks: int, weights_path: str) -> LiveSession:
    return LiveSession(spec_json, seed, ticks, weights_path)
'''

PRESETS = ["earth", "earth_jpn", "default", "earth_all"]


def main() -> int:
    src = SERVER / "src"
    (WEB_PW / "terrarium").mkdir(parents=True, exist_ok=True)
    (WEB_PW / "worlds").mkdir(parents=True, exist_ok=True)
    for rel in SUBSET:
        dst = WEB_PW / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / rel, dst)
    (WEB_PW / "pydantic.py").write_text(PYDANTIC_SHIM, encoding="utf-8")
    (WEB_PW / "yaml.py").write_text(YAML_STUB, encoding="utf-8")
    (WEB_PW / "driver.py").write_text(DRIVER, encoding="utf-8")

    # プリセットはネイティブで構築してJSON化(earth_allの手続き生成もここで確定)
    from terrarium.world.presets import load_preset

    for name in PRESETS:
        spec = load_preset(name)
        (WEB_PW / "worlds" / f"{name}.json").write_text(
            json.dumps(spec.model_dump(mode="json"), ensure_ascii=False), encoding="utf-8")
        print(f"world {name}: {len(spec.nations)} nations")

    # 重み(モデル1本)を配信物へ
    wsrc = SERVER / "models" / "generalist_llm_deep_bc.npz"
    wdst = SERVER.parent / "web" / "models" / "generalist_llm_deep_bc.npz"
    wdst.parent.mkdir(parents=True, exist_ok=True)
    if not wdst.exists() or wdst.stat().st_size != wsrc.stat().st_size:
        shutil.copy2(wsrc, wdst)
    print(f"weights -> {wdt_rel(wdst)} ({wdst.stat().st_size} bytes)")

    # Workerが取得するファイル一覧
    manifest = {
        "py": ["pydantic.py", "yaml.py", "driver.py"] + SUBSET,
        "worlds": PRESETS,
        "weights": "models/generalist_llm_deep_bc.npz",
    }
    (WEB_PW / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"manifest -> {wdt_rel(WEB_PW / 'manifest.json')}")
    return 0


def wdt_rel(p: Path) -> str:
    return str(p.relative_to(SERVER.parent))


if __name__ == "__main__":
    raise SystemExit(main())
