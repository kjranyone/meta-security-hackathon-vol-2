"""God server (FastAPI + WebSocket) integration tests."""
import json

import pytest
from fastapi.testclient import TestClient

from terrarium.server.app import app


def recv_until(ws, pred, limit: int = 40):
    for _ in range(limit):
        m = ws.receive_json()
        if pred(m):
            return m
    raise AssertionError("expected message not received")


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_meta_and_ticks_stream(client):
    with client.websocket_connect("/ws") as ws:
        meta = recv_until(ws, lambda m: m.get("type") == "meta")
        assert len(meta["geo"]["nations"]) >= 8
        assert len(meta["geo"]["chokepoints"]) >= 4
        tick = recv_until(ws, lambda m: m.get("type") == "tick")
        assert "nations" in tick and "prices" in tick and "metrics" in tick


def test_intervene_broadcasts_god_event(client):
    with client.websocket_connect("/ws") as ws:
        recv_until(ws, lambda m: m.get("type") == "meta")
        ws.send_json({"cmd": "pause"})
        recv_until(ws, lambda m: m.get("type") == "status" and m["running"] is False)
        ws.send_json({"cmd": "intervene", "type": "close_chokepoint",
                      "params": {"chokepoint": "#0", "duration": 5}})
        god = recv_until(ws, lambda m: m.get("type") == "god")
        assert "封鎖" in god["event"]["text"]


def test_step_and_speed(client):
    with client.websocket_connect("/ws") as ws:
        recv_until(ws, lambda m: m.get("type") == "meta")
        ws.send_json({"cmd": "pause"})
        recv_until(ws, lambda m: m.get("type") == "status" and m["running"] is False)
        ws.send_json({"cmd": "step"})
        tick = recv_until(ws, lambda m: m.get("type") == "tick")
        assert tick["tick"] >= 0
        ws.send_json({"cmd": "speed", "ms": 400})
        st = recv_until(ws, lambda m: m.get("type") == "status" and m["speed_ms"] == 400)
        assert st["speed_ms"] == 400


def test_reset_endpoint(client):
    r = client.post("/api/reset", json={"preset": "default", "policy": "mock_llm",
                                        "seed": 1, "ticks": 12, "autoplay": False})
    assert r.status_code == 200
    body = r.json()
    assert body["max_ticks"] == 12 and body["running"] is False
