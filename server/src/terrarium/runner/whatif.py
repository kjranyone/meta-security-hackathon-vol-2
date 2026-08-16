"""IF-history runner: fork a recorded run at a past tick with an extra god
intervention — "過去、●●年に△△していたら" mode.

Because the engine is deterministic, replaying the base run's
(seed, preset, policy, scenario) reproduces its history bit-for-bit up to the
fork tick; the injected intervention then branches the timeline. The runner
writes a divergence report (first differing tick, final metric deltas, events
that only happened / never happened in the fork) next to the fork's logs.

Example:
  uv run python -m terrarium.runner.whatif \
      --base earth_earth_financial_crisis \
      --base-scenario scenarios/earth_financial_crisis.yaml \
      --tick 6 --iv bailout:nation=JPN
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..sim.interventions import Intervention, Scenario, load_scenario
from ..util.env import load_env
from ..world.presets import load_preset
from .ab import run_once

SERVER_ROOT = Path(__file__).resolve().parents[3]
LOGS = SERVER_ROOT / "logs"


def parse_value(v: str):
    if v.lower() in ("none", "null"):
        return None
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


def parse_iv(spec: str, tick: int) -> Intervention:
    """'bailout:nation=JPN' or 'close_chokepoint:chokepoint=Strait of Hormuz,duration=20'"""
    if ":" not in spec:
        raise ValueError(f"--iv must be 'type:key=value,...' (got {spec!r})")
    type_, _, kv = spec.partition(":")
    params = {}
    for part in kv.split(","):
        if not part:
            continue
        k, _, v = part.partition("=")
        params[k.strip()] = parse_value(v.strip())
    return Intervention(tick=tick, type=type_.strip(), params=params)


def load_base(base: str) -> dict:
    rj = LOGS / base / "run.json"
    if not rj.exists():
        raise FileNotFoundError(f"base run not found: {rj}")
    return json.loads(rj.read_text(encoding="utf-8"))


def unique_name(base_name: str) -> Path:
    out = LOGS / base_name
    n = 2
    while out.exists():
        out = LOGS / f"{base_name}_{n}"
        n += 1
    return out


def divergence_report(base: str, fork: str, fork_tick: int, ivs: list[Intervention]) -> dict:
    def series(run):
        import csv
        with (LOGS / run / "series.csv").open() as f:
            return list(csv.DictReader(f))

    def events(run):
        return [json.loads(l) for l in (LOGS / run / "events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

    b, f = series(base), series(fork)
    keys = [k for k in b[0] if k != "tick"]
    first_div = None
    for rb, rf in zip(b, f):
        if int(rb["tick"]) < fork_tick:
            continue
        if any(rb[k] != rf[k] for k in keys):
            first_div = int(rb["tick"])
            break
    final_delta = {k: round(float(f[-1][k]) - float(b[-1][k]), 4) for k in keys
                   if k in ("world_gdp", "defaults", "wars", "mean_stability", "mean_debt_gdp")}
    be, fe = events(base), events(fork)

    def sig(e):
        return (e["type"], e["tick"], e["actor"])

    bset, fset = {sig(e) for e in be}, {sig(e) for e in fe}
    only_fork = sorted(fset - bset)
    only_base = sorted(bset - fset)
    interesting = ("sovereign_default", "war_start", "collapse", "alliance_formed", "tech_emergence")
    return {
        "base_run": base,
        "fork_run": fork,
        "fork_tick": fork_tick,
        "interventions": [iv.model_dump() for iv in ivs],
        "first_divergence_tick": first_div,
        "final_metric_deltas": final_delta,
        "only_in_fork": [{"type": t, "tick": tk, "actor": a} for t, tk, a in only_fork
                         if t in interesting],
        "only_in_base": [{"type": t, "tick": tk, "actor": a} for t, tk, a in only_base
                         if t in interesting],
    }


def main(argv: list[str] | None = None) -> int:
    load_env(SERVER_ROOT / ".env")
    ap = argparse.ArgumentParser(description="IF-history fork: rewrite one intervention in the past")
    ap.add_argument("--base", required=True, help="base run name under server/logs/")
    ap.add_argument("--tick", type=int, required=True, help="fork tick (intervention applies at this month)")
    ap.add_argument("--iv", action="append", required=True,
                    help="intervention 'type:key=value,...' (repeatable), e.g. bailout:nation=JPN")
    ap.add_argument("--name", default=None, help="output run name (default <base>_if_t<tick>)")
    # provenance overrides for runs whose run.json lacks "config"
    ap.add_argument("--preset", default=None)
    ap.add_argument("--gen-seed", type=int, default=None)
    ap.add_argument("--policy", default=None)
    ap.add_argument("--rl-nation", default=None)
    ap.add_argument("--rl-weights", default=None)
    ap.add_argument("--base-scenario", default=None, help="scenario YAML the base run used (if not in run.json)")
    args = ap.parse_args(argv)

    meta = load_base(args.base)
    cfg = meta.get("config") or {}
    seed = meta["seed"]
    ticks = meta["ticks"]
    preset = args.preset or cfg.get("preset") or "earth"
    gen_seed = args.gen_seed if args.gen_seed is not None else cfg.get("gen_seed")
    gen_nations = cfg.get("gen_nations") or 8
    policy = args.policy or cfg.get("policy") or "mock_llm"
    if policy in ("llm", "hybrid") and not args.policy:
        print(f"[whatif] ⚠ base policy '{policy}' is nondeterministic; forking with mock_llm "
              f"(deterministic forks need a deterministic policy)")
        policy = "mock_llm"
    rl_nation = args.rl_nation or cfg.get("rl_nation")
    rl_weights = args.rl_weights or cfg.get("rl_weights")
    scenario_path = args.base_scenario or cfg.get("scenario")
    if scenario_path is None:
        god_events = sum(1 for l in (LOGS / args.base / "events.jsonl").read_text().splitlines()
                         if '"god_intervention"' in l)
        if god_events:
            print(f"[whatif] ⚠ base run has {god_events} god_intervention events but no recorded "
                  f"scenario — pass --base-scenario to reproduce them in the fork")
    if args.tick >= ticks:
        raise SystemExit(f"fork tick {args.tick} outside base history (0..{ticks - 1})")

    base_scenario = load_scenario(scenario_path)
    ivs = [parse_iv(s, args.tick) for s in args.iv]
    scenario = Scenario(
        name=f"{base_scenario.name}_if",
        description=f"IF fork of {args.base} at t{args.tick}",
        interventions=list(base_scenario.interventions) + ivs,
    )

    if gen_seed is not None:
        from ..world.worldgen import GenParams, generate_world
        spec = generate_world(GenParams(seed=gen_seed, n_nations=gen_nations))
    else:
        spec = load_preset(preset)

    name = args.name or f"{args.base}_if_t{args.tick}"
    out = unique_name(name)
    fork_cfg = {**cfg, "policy": policy, "rl_nation": rl_nation, "rl_weights": rl_weights,
                "scenario": scenario_path, "if_base": args.base, "if_tick": args.tick,
                "if_ivs": [iv.model_dump() for iv in ivs]}
    run_once(spec, seed=seed, ticks=ticks, policy=policy, scenario=scenario,
             name=out.name, out=out, rl_nation=rl_nation, rl_weights=rl_weights,
             run_config=fork_cfg)

    report = divergence_report(args.base, out.name, args.tick, ivs)
    (out / "whatif.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[whatif] fork '{out.name}' -> {out}")
    print(f"[whatif] IF: t{args.tick} で {[iv.type + str(iv.params) for iv in ivs]} していたら")
    print(f"[whatif] 歴史が分岐した最初のtick: t{report['first_divergence_tick']}")
    print(f"[whatif] 最終指標の差分: {report['final_metric_deltas']}")
    for e in report["only_in_base"]:
        print(f"[whatif]   元の歴史でだけ起きた: t{e['tick']} {e['actor']} {e['type']}")
    for e in report["only_in_fork"]:
        print(f"[whatif]   IF世界で新たに起きた: t{e['tick']} {e['actor']} {e['type']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
