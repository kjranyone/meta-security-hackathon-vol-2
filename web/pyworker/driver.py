"""ライブ神モードのドライバ: サーバSessionのWSプロトコルと同じ形で
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
