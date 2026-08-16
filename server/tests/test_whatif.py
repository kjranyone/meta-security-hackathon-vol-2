import csv

import pytest

from terrarium.runner.ab import run_once
from terrarium.runner.whatif import divergence_report, parse_iv, parse_value
from terrarium.sim.interventions import Intervention, Scenario
from terrarium.world.presets import load_preset


def _series(path):
    with (path / "series.csv").open() as f:
        return list(csv.DictReader(f))


def test_parse_iv():
    iv = parse_iv("close_chokepoint:chokepoint=Strait of Hormuz,duration=20", tick=3)
    assert iv.type == "close_chokepoint"
    assert iv.tick == 3
    assert iv.params == {"chokepoint": "Strait of Hormuz", "duration": 20}
    assert parse_value("1.5") == 1.5
    assert parse_value("7") == 7
    assert parse_value("abc") == "abc"
    assert parse_value("None") is None
    with pytest.raises(ValueError):
        parse_iv("bailout", tick=1)


def test_if_fork_identical_before_fork_diverges_after(tmp_path):
    """IF-history determinism: the fork reproduces the base history
    bit-for-bit before the fork tick and branches after it."""
    spec = load_preset("default")
    run_once(spec, seed=42, ticks=16, policy="mock_llm",
             scenario=Scenario(name="baseline"), name="base", out=tmp_path / "base")

    iv = Intervention(tick=8, type="create_resource",
                      params={"nation": "VLT", "resource": "fab", "quantity": 2})
    run_once(spec, seed=42, ticks=16, policy="mock_llm",
             scenario=Scenario(name="if", interventions=[iv]), name="fork", out=tmp_path / "fork")

    b, f = _series(tmp_path / "base"), _series(tmp_path / "fork")
    assert len(b) == len(f) == 16
    assert b[:8] == f[:8], "history must be identical before the fork tick"
    assert any(x != y for x, y in zip(b[8:], f[8:])), "history must diverge after the fork"


def test_divergence_report(monkeypatch, tmp_path):
    from terrarium.runner import whatif as w

    spec = load_preset("default")
    run_once(spec, seed=42, ticks=12, policy="mock_llm",
             scenario=Scenario(name="baseline"), name="base", out=tmp_path / "base")
    iv = Intervention(tick=5, type="rate_hike", params={"value": 0.05})
    run_once(spec, seed=42, ticks=12, policy="mock_llm",
             scenario=Scenario(name="if", interventions=[iv]), name="fork", out=tmp_path / "fork")

    monkeypatch.setattr(w, "LOGS", tmp_path)
    report = w.divergence_report("base", "fork", 5, [iv])
    assert report["first_divergence_tick"] is not None
    assert report["first_divergence_tick"] >= 5
    assert "world_gdp" in report["final_metric_deltas"]
    assert report["interventions"][0]["type"] == "rate_hike"
    assert isinstance(report["only_in_base"], list)
