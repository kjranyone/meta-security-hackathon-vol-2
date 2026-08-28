"""日本の安全保障リスクカード(憲章第2条のツール)。
事案→機序→数値(差分)を分離提示する。全run同seed・決定論。
Usage: uv run python scripts/japan_risk_battery.py
"""
"""日本の安全保障リスクカード(憲章第2条の初回実装)。
事案→機序→数値(差分)を分離提示する。全run同seed=42・36ヶ月・決定論。"""
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

SERVER = Path("/Users/kojiro/Documents/GitHub/kjranyone/meta-security-hackathon-vol-2/server")
SCENARIOS = [
    ("baseline", None),
    ("hormuz", "scenarios/earth_hormuz.yaml"),
    ("taiwan", "scenarios/earth_taiwan.yaml"),
    ("triple", "scenarios/earth_triple_crisis.yaml"),
    ("fin_crisis", "scenarios/earth_financial_crisis.yaml"),
    ("chaos", "scenarios/earth_chaos.yaml"),
    ("disinfo_jpn", "scenarios/earth_disinfo_jpn.yaml"),
    ("ban_fusion", "scenarios/earth_ban_fusion.yaml"),
]

def run(name, scen):
    cmd = ["uv", "run", "python", "-m", "terrarium.runner.headless",
           "--preset", "earth", "--seed", "42", "--ticks", "36",
           "--policy", "mock_llm"]
    if scen:
        cmd += ["--scenario", scen]
    out = subprocess.run(cmd, cwd=SERVER, capture_output=True, text=True)
    if out.returncode != 0:
        print(f"[{name}] FAILED", out.stderr[-200:], file=sys.stderr)
        return None
    # stdoutの "run 'NAME' -> PATH" から正確なログ先を取る
    log = None
    for line in out.stdout.splitlines():
        if line.startswith("[terrarium] run ") and "->" in line:
            log = Path(line.split("->")[1].strip())
    if log is None or not (log / "replay.jsonl").exists():
        print(f"[{name}] no log found: {out.stdout[-200:]}", file=sys.stderr)
        return None
    rep = [json.loads(l) for l in (log / "replay.jsonl").open() if "\"nations\"" in l]
    evs = [json.loads(l) for l in (log / "events.jsonl").open()]
    final = rep[-1]
    j = final["nations"]["JPN"]
    rep = [r for r in rep if "nations" in r]
    base = rep[0]["nations"]["JPN"]
    # JPN関連イベント(機序の抽出)
    j_evs = []
    for e in evs:
        t = e.get("type", "")
        actors = [e.get("actor")] + (e.get("targets") or [])
        if "JPN" in actors and t in ("war_start", "war_end", "sovereign_default",
                                     "shortage", "mobilization", "alliance_activation",
                                     "insurgency", "god_intervention", "rate_hike",
                                     "peace_settlement", "cyber_attack"):
            j_evs.append((e.get("tick"), t, e.get("targets"), e.get("parents")))
    return {
        "gdp": j["gdp"], "stab": j["stability"], "unemp": j["unemployment"],
        "debt": j["debt_gdp"], "defaults": j["defaults"],
        "collapsed": j["collapsed"], "at_war": bool(j["at_war_with"]),
        "infl": j["inflation"], "fx": j["fx"],
        "p_energy": final["prices"].get("energy", 1.0),
        "p_food": final["prices"].get("food", 1.0),
        "p_chips": final["prices"].get("chips", 1.0),
        "j_events": j_evs,
    }

results = {}
for name, scen in SCENARIOS:
    results[name] = run(name, scen)
    r = results[name]
    if r:
        print(f"{name:12s} GDP {r['gdp']:5.1f} 安定 {r['stab']:5.1f} 失業 {r['unemp']:4.1f}% "
              f"債務 {r['debt']:5.1f}% 破綻 {r['defaults']} 戦争 {r['at_war']} "
              f"E {r['p_energy']:.2f} F {r['p_food']:.2f} C {r['p_chips']:.2f}", flush=True)
SERVER.parent / "analysis" / "out".write_text(json.dumps(
    {k: {kk: vv for kk, vv in v.items()} for k, v in results.items() if v},
    ensure_ascii=False, indent=1, default=str))
print("saved analysis/out/japan_risk.json")
