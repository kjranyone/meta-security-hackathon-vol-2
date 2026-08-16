"""Real-time god server: FastAPI + WebSocket.

Runs the Terrarium engine tick-by-tick in the background and streams
snapshots/events to all connected clients. The god client (web/god.html)
sends intervention commands that are applied between ticks.

Run:
  cd server && uv run uvicorn terrarium.server.app:app --port 8788
  open http://localhost:8788/            (god UI)
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..agents.llm import make_policy_factory
from ..sim.engine import Engine
from ..sim.interventions import Intervention, load_scenario
from ..util.env import load_env
from ..world.presets import load_preset
from ..world.worldgen import GenParams, generate_world

REPO_ROOT = Path(__file__).resolve().parents[4]
WEB_DIR = REPO_ROOT / "web"

load_env(REPO_ROOT / "server" / ".env")


class Session:
    """One live simulation + fan-out to websocket clients."""

    def __init__(self) -> None:
        self.engine: Optional[Engine] = None
        self.max_ticks: int = 60
        self.speed_ms: int = 1200
        self.running: bool = False
        self.clients: set[WebSocket] = set()
        self.lock = asyncio.Lock()
        self.task: Optional[asyncio.Task] = None
        self.scenario_schedule: list[Intervention] = []
        self.t: int = 0

    # ------------------------------------------------------------- lifecycle
    def build(self, preset: str = "earth", policy: str = "mock_llm", seed: int = 42,
              ticks: int = 60, gen_seed: Optional[int] = None,
              rl_nation: Optional[str] = None, rl_weights: Optional[str] = None,
              scenario: Optional[str] = None) -> None:
        if gen_seed is not None:
            spec = generate_world(GenParams(seed=gen_seed))
        else:
            spec = load_preset(preset)
        factory = make_policy_factory(policy, seed=seed, rl_nation=rl_nation, rl_weights=rl_weights)
        policies = {ns.id: factory(ns) for ns in spec.nations}
        self.engine = Engine(spec, policies, seed=seed, out_dir=None)
        self.max_ticks = ticks
        self.t = 0
        self.scenario_schedule = sorted(
            load_scenario(scenario).interventions, key=lambda i: i.tick
        ) if scenario else []

    def meta(self) -> dict:
        eng = self.engine
        return {
            "type": "meta",
            "seed": eng.seed,
            "geo": {
                "map_geojson": eng.spec.map_geojson,
                "nations": {
                    ns.id: {"name": ns.name, "color": ns.color,
                            "centroid": list(ns.centroid), "geo_ids": ns.geo_ids}
                    for ns in eng.spec.nations
                },
                "chokepoints": [{"name": cp.name, "lon": cp.lon, "lat": cp.lat}
                                for cp in eng.spec.chokepoints],
                "routes": [{"importer": r.importer, "exporter": r.exporter,
                            "commodity": r.commodity.value, "chokepoints": r.chokepoints}
                           for r in eng.spec.routes],
                "techs": [],
            },
            "status": self.status(),
        }

    def status(self) -> dict:
        return {"running": self.running, "speed_ms": self.speed_ms,
                "tick": self.t, "max_ticks": self.max_ticks}

    async def broadcast(self, message: dict) -> None:
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(json.dumps(message, ensure_ascii=False))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def loop(self) -> None:
        while True:
            await asyncio.sleep(self.speed_ms / 1000.0)
            if not self.running or self.engine is None:
                continue
            async with self.lock:
                eng = self.engine
                due = [iv for iv in self.scenario_schedule if iv.tick == self.t]
                for iv in due:
                    eng.apply_intervention(iv)
                eng.tick_no = self.t
                if self.t >= self.max_ticks:
                    self.running = False
                    await self.broadcast({"type": "end", **self.status()})
                    continue
                eng.step()
                self.t += 1
                snap = eng.snapshots[-1] if eng.snapshots else None
            if snap:
                await self.broadcast({"type": "tick", **snap})
            await self.broadcast({"type": "status", **self.status()})


session = Session()
app = FastAPI(title="Geopolitics Terrarium — God Server")


@app.on_event("startup")
async def _startup() -> None:
    session.build()
    session.running = True
    session.task = asyncio.create_task(session.loop())


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "god.html")


@app.post("/api/reset")
async def reset(payload: dict) -> dict:
    async with session.lock:
        session.running = False
        session.build(
            preset=payload.get("preset", "earth"),
            policy=payload.get("policy", "mock_llm"),
            seed=int(payload.get("seed", 42)),
            ticks=int(payload.get("ticks", 60)),
            gen_seed=payload.get("gen_seed"),
            rl_nation=payload.get("rl_nation"),
            rl_weights=payload.get("rl_weights"),
            scenario=payload.get("scenario"),
        )
        session.running = bool(payload.get("autoplay", True))
    await session.broadcast(session.meta())
    return session.status()


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    session.clients.add(ws)
    try:
        await ws.send_text(json.dumps(session.meta(), ensure_ascii=False))
        eng = session.engine
        for snap in (eng.snapshots[-5:] if eng else []):
            await ws.send_text(json.dumps({"type": "tick", **snap}, ensure_ascii=False))
        await ws.send_text(json.dumps({"type": "status", **session.status()}, ensure_ascii=False))
        while True:
            data = json.loads(await ws.receive_text())
            cmd = data.get("cmd")
            if cmd == "intervene":
                async with session.lock:
                    eng = session.engine
                    iv = Intervention(tick=session.t, type=data["type"], params=data.get("params", {}))
                    eng.apply_intervention(iv)
                    ev = eng.event_log.records[-1] if eng.event_log.records else None
                    await session.broadcast({"type": "god", "event": ev.model_dump() if ev else None})
            elif cmd == "pause":
                session.running = False
                await session.broadcast({"type": "status", **session.status()})
            elif cmd == "play":
                session.running = True
                await session.broadcast({"type": "status", **session.status()})
            elif cmd == "speed":
                session.speed_ms = max(100, min(5000, int(data.get("ms", session.speed_ms))))
                await session.broadcast({"type": "status", **session.status()})
            elif cmd == "step":
                async with session.lock:
                    eng = session.engine
                    eng.tick_no = session.t
                    if session.t < session.max_ticks:
                        eng.step()
                        session.t += 1
                        await session.broadcast({"type": "tick", **eng.snapshots[-1]})
                await session.broadcast({"type": "status", **session.status()})
            elif cmd == "reset":
                await reset(data)
    except WebSocketDisconnect:
        pass
    finally:
        session.clients.discard(ws)


app.mount("/static", StaticFiles(directory=REPO_ROOT), name="repo")
