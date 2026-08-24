"""危機安定性実験: AI意思決定者と抑止構成がエスカレーションをどう変えるか。

Q1: heuristic / RL / LLM の政府はエスカレーション速度を変えるか
Q2: 抑止(核保有構成)はAI相手でも機能するか

固定された危機(earth_chaos)の下で、意思決定層と核保有構成だけを交換して
多seedで測定する。出力はCSV + 集計。

Usage:
  uv run python -m terrarium.runner.stability --policy heuristic --deterrence status --seeds 10
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from ..agents.heuristic import HeuristicPolicy
from ..agents.llm import make_policy_factory
from ..sim.engine import Engine
from ..sim.interventions import Scenario, load_scenario
from ..world.presets import load_preset

SERVER_ROOT = Path(__file__).resolve().parents[3]
MODELS = SERVER_ROOT / "models"
SPECIFIC = {"USA": "selfplay_earth_USA.npz", "CHN": "selfplay_earth_CHN.npz",
            "JPN": "selfplay_debtors_JPN.npz", "EGY": "selfplay_debtors_EGY.npz"}
EXPANDED_GRANTS = ["IRN", "KOR", "SAU"]


def policies_for(policy: str, spec, seed: int):
    if policy == "heuristic":
        return {ns.id: HeuristicPolicy() for ns in spec.nations}
    if policy == "rl":
        nids, wpaths = [], []
        for ns in spec.nations:
            w = SPECIFIC.get(ns.id)
            path = MODELS / w if w else MODELS / "generalist.npz"
            if not path.exists():
                return {ns.id: HeuristicPolicy() for ns in spec.nations}
            nids.append(ns.id)
            wpaths.append(str(path))
        factory = make_policy_factory("rl", seed=seed,
                                      rl_nation=",".join(nids),
                                      rl_weights=",".join(wpaths))
        return {ns.id: factory(ns) for ns in spec.nations}
    if policy == "llm":
        factory = make_policy_factory("llm", seed=seed)
        return {ns.id: factory(ns) for ns in spec.nations}
    raise ValueError(policy)


def apply_deterrence(eng: Engine, mode: str) -> None:
    if mode == "none":
        for nat in eng.nations.values():
            if "nuclear" in nat.factors:
                nat.factors.remove("nuclear")
    elif mode == "expanded":
        for nid in EXPANDED_GRANTS:
            if nid in eng.nations and "nuclear" not in eng.nations[nid].factors:
                eng.nations[nid].factors.append("nuclear")


def run_one(policy: str, deterrence: str, seed: int, ticks: int) -> dict:
    spec = load_preset("earth")
    pol = policies_for(policy, spec, seed)
    eng = Engine(spec, pol, seed=seed, out_dir=None)
    apply_deterrence(eng, deterrence)
    eng.run(ticks, load_scenario("scenarios/earth_chaos.yaml"))
    if policy == "llm":
        calls = sum(getattr(p, "calls", 0) for p in eng.policies.values())
        fbs = sum(getattr(p, "fallbacks", 0) for p in eng.policies.values())
        if calls + fbs > 0:
            print(f"[stab] llm real calls {calls} / fallback {fbs}", flush=True)
    evs = eng.event_log.records
    wars = [e for e in evs if e.type == "war_start"]
    holders = {nid for nid, n in eng.nations.items() if "nuclear" in n.factors}
    m0, m1 = eng.series[0], eng.series[-1]
    return {
        "policy": policy, "deterrence": deterrence, "seed": seed, "ticks": ticks,
        "wars_started": len(wars),
        "first_war_tick": wars[0].tick if wars else -1,
        "wars_with_nuclear_side": sum(1 for e in wars
                                      if any(t in holders for t in (e.targets or []))),
        "defaults": m1["defaults"],
        "gdp_delta_pct": round((m1["world_gdp"] / m0["world_gdp"] - 1) * 100, 2),
        "mean_unemployment": m1["mean_unemployment"],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Crisis stability experiment (Q1+Q2)")
    ap.add_argument("--policy", required=True, choices=["heuristic", "rl", "llm"])
    ap.add_argument("--deterrence", default="status", choices=["status", "none", "expanded"])
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--ticks", type=int, default=24)
    ap.add_argument("--out", default=None, help="CSV path")
    args = ap.parse_args(argv)

    rows = []
    for s in range(args.seeds):
        r = run_one(args.policy, args.deterrence, s, args.ticks)
        rows.append(r)
        print(f"[stab] {args.policy}/{args.deterrence} seed={s} "
              f"wars={r['wars_started']} first_t={r['first_war_tick']} "
              f"nuke_wars={r['wars_with_nuclear_side']} gdp={r['gdp_delta_pct']}%", flush=True)

    out = Path(args.out) if args.out else SERVER_ROOT.parent / "analysis" / "out" / f"stability_{args.policy}_{args.deterrence}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    n = len(rows)
    wars = [r["wars_started"] for r in rows]
    first = [r["first_war_tick"] for r in rows if r["first_war_tick"] >= 0]
    nuke = [r["wars_with_nuclear_side"] for r in rows]
    print(f"[stab] SUMMARY {args.policy}/{args.deterrence}: wars {sum(wars)/n:.1f}±"
          f"{(sum((x-sum(wars)/n)**2 for x in wars)/n)**0.5:.1f} | "
          f"first_t median {sorted(first)[len(first)//2] if first else -1} | "
          f"nuke-side wars {sum(nuke)}")
    print(f"[stab] wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
