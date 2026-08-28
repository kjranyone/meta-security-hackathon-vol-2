"""ギャップ①: earth_jpnでの層交換battery(憲章第2条3項の達成)。

台湾海峡危機シナリオを固定し、「同盟網」と「核保有構成」だけを交換して
日本指標の感構造を分離する。決定論エンジンにより差分は交換に純粋に帰属する。

軸:
  alliance: none(earth) / us_hub(earth_jpn) / us_hub_ambig(TWN非同盟=戦略的曖昧性)
  nuclear: 現状(USA,RUS,CHN,EUR,IND) / 拡散(+IRN,KOR,SAU) / 日本核保有(+JPN)

Usage: uv run python scripts/japan_layer_swap.py [--seeds 10] [--ticks 36]
出力: analysis/out/japan_layer_swap.json + 標準出力に表
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

from terrarium.agents.heuristic import HeuristicPolicy
from terrarium.sim.engine import Engine
from terrarium.sim.interventions import Intervention, Scenario
from terrarium.world.presets import load_preset

SERVER_ROOT = Path(__file__).resolve().parents[1]

CRISIS = Scenario(interventions=[
    Intervention(tick=2, type="global_slider",
                 params={"param": "ai_aggression", "value": 1.6}),
    Intervention(tick=2, type="set_param",
                 params={"nation": "CHN", "param": "aggression", "value": 0.9}),
    Intervention(tick=2, type="set_param",
                 params={"nation": "CHN", "param": "paranoia", "value": 0.8}),
    Intervention(tick=2, type="set_param",
                 params={"nation": "TWN", "param": "aggression", "value": 0.8}),
    Intervention(tick=4, type="disinfo", params={"target": "TWN", "intensity": 2.0}),
    Intervention(tick=6, type="disinfo", params={"target": "CHN", "intensity": 2.0}),
])

NUCLEAR_BASE = ["USA", "RUS", "CHN", "EUR", "IND"]
NUCLEAR_ARMS = {
    "current": NUCLEAR_BASE,
    "diffusion": NUCLEAR_BASE + ["IRN", "KOR", "SAU"],
    "jpn_armed": NUCLEAR_BASE + ["JPN"],
}


def build(preset: str, drop_twn_pair: bool, nuclear: list[str], seed: int) -> Engine:
    spec = copy.deepcopy(load_preset(preset))
    if drop_twn_pair:
        spec.initial_alliances = [p for p in spec.initial_alliances if "TWN" not in p]
    spec.factor_holders["nuclear"] = nuclear
    policies = {ns.id: HeuristicPolicy() for ns in spec.nations}
    return Engine(spec, policies, seed=seed, out_dir=None)


def run_cell(alliance: str, nuclear_name: str, seed: int, ticks: int) -> dict:
    preset = {"none": "earth", "us_hub": "earth_jpn",
              "us_hub_ambig": "earth_jpn"}[alliance]
    eng = build(preset, alliance == "us_hub_ambig", NUCLEAR_ARMS[nuclear_name], seed)
    scenario = Scenario(interventions=[
        Intervention(tick=iv.tick, type=iv.type, params=dict(iv.params))
        for iv in CRISIS.interventions])
    for t in range(ticks):
        eng.tick_no = t
        for iv in scenario.interventions:
            if iv.tick == t:
                eng.apply_intervention(iv)
        eng.step()
    j = eng.nations["JPN"]
    evs = eng.event_log.records
    jpn_wars = sum(1 for r in evs if r.type == "war_start" and "JPN" in (r.targets or []))
    jpn_act = sum(1 for r in evs if r.type == "alliance_activation" and r.actor == "JPN")
    any_act = sum(1 for r in evs if r.type == "alliance_activation")
    world_wars = sum(1 for r in evs if r.type == "war_start")
    return {"jpn_war": jpn_wars, "jpn_activated": jpn_act, "any_activation": any_act,
            "world_wars": world_wars, "jpn_default": j.defaults,
            "jpn_collapsed": j.collapsed, "jpn_gdp": j.gdp,
            "jpn_stab": j.stability, "jpn_nuclear": "nuclear" in j.factors}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--ticks", type=int, default=36)
    args = ap.parse_args(argv)
    rows = []
    for alliance in ("none", "us_hub", "us_hub_ambig"):
        for nuclear in ("current", "diffusion", "jpn_armed"):
            cells = [run_cell(alliance, nuclear, s, args.ticks)
                     for s in range(args.seeds)]
            n = len(cells)
            agg = {
                "alliance": alliance, "nuclear": nuclear,
                "jpn_war_rate": sum(c["jpn_war"] > 0 for c in cells) / n,
                "jpn_activated": sum(c["jpn_activated"] for c in cells),
                "any_activation": sum(c["any_activation"] for c in cells),
                "jpn_default_rate": sum(c["jpn_default"] > 0 for c in cells) / n,
                "jpn_collapse_rate": sum(c["jpn_collapsed"] for c in cells) / n,
                "world_wars_mean": sum(c["world_wars"] for c in cells) / n,
                "jpn_gdp_mean": sum(c["jpn_gdp"] for c in cells) / n,
                "jpn_stab_mean": sum(c["jpn_stab"] for c in cells) / n,
            }
            rows.append(agg)
            print(f"{alliance:14s} × {nuclear:11s}: 日本参戦 {agg['jpn_war_rate']*100:3.0f}% "
                  f"日本履行 {agg['jpn_activated']:2d} 同盟履行計 {agg['any_activation']:3d} "
                  f"破綻 {agg['jpn_default_rate']*100:3.0f}% 崩壊 {agg['jpn_collapse_rate']*100:3.0f}% "
                  f"世界戦争 {agg['world_wars_mean']:4.1f} GDP {agg['jpn_gdp_mean']:4.2f} "
                  f"安定 {agg['jpn_stab_mean']:5.1f}", flush=True)
    out = SERVER_ROOT.parent / "analysis" / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "japan_layer_swap.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1))
    print(f"saved -> analysis/out/japan_layer_swap.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
