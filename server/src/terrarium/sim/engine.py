"""The Terrarium simulation engine.

Tick pipeline (1 tick = 1 month):
  god interventions -> production -> trade (chokepoint-aware) -> market prices
  -> consumption/welfare -> nation decisions (policy layer) -> diplomacy
  -> conflict -> collapse checks -> snapshot & JSONL logging

Everything is deterministic given (seed, spec, policies, scenario):
no global RNG, only the seeded engine RNG, and nations/routes are iterated
in sorted order.
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import IO, Optional

from ..agents.base import Decisions, NationView
from ..world.models import (
    Commodity,
    GodParams,
    NationState,
    ResourceKind,
    WorldSpec,
    RESOURCE_TO_COMMODITY,
)
from ..world.factors import FACTORS_BY_ID
from ..world.tech import CATALOG, tech_catalog_index
from .events import EventLog
from .interventions import Intervention, Scenario

CONSUMPTION = {"energy": 1.0, "food": 1.0, "chips": 0.5, "minerals": 0.5, "space": 0.25}
DEFAULT_STOCKS = {"energy": 3.0, "food": 4.0, "chips": 2.0, "minerals": 2.0, "space": 1.0}
YIELD_PER_UNIT = 1.5
SHORTAGE_STABILITY_HIT = {"energy": 4.0, "food": 6.0, "chips": 2.0, "minerals": 3.0, "space": 0.5}
COMMODITY_YIELD_SLIDER = {
    Commodity.ENERGY: "energy_yield",
    Commodity.FOOD: "food_yield",
    Commodity.CHIPS: "chips_yield",
    Commodity.MINERALS: "minerals_yield",
    Commodity.SPACE: "space_yield",
}


class TempEffect:
    def __init__(self, until: int, nation: str, attr: str, mult: float):
        self.until, self.nation, self.attr, self.mult = until, nation, attr, mult


class Engine:
    def __init__(
        self,
        spec: WorldSpec,
        policies: dict,
        seed: int = 42,
        out_dir: Optional[Path] = None,
        run_name: str = "run",
        log_stream: Optional[IO[str]] = None,
        run_config: Optional[dict] = None,
    ):
        self.spec = spec
        self.policies = policies
        self.rng = random.Random(seed)
        self.seed = seed
        self.tick_no = 0
        self.god = GodParams()
        # provenance recorded into run.json so IF-history forks can replay
        # the exact (preset, policy, scenario) that produced this history
        self.run_config = run_config or {}
        self.chokepoints = {cp.name: cp for cp in spec.chokepoints}
        self._specs = {ns.id: ns for ns in spec.nations}
        self._ca_exports: dict[str, float] = {}
        self._ca_imports: dict[str, float] = {}
        self._shortages: dict[str, float] = {}
        self._abandon_votes: dict = {}
        self._last_decision: dict[str, dict] = {}
        self.global_co2 = 0.0
        self.prices = {c.value: 1.0 for c in Commodity}
        self.last_prices = dict(self.prices)
        self.nations: dict[str, NationState] = {}
        for ns in sorted(spec.nations, key=lambda n: n.id):
            self.nations[ns.id] = NationState(
                id=ns.id,
                name=ns.name,
                persona=ns.persona,
                color=ns.color,
                gdp=ns.gdp_t,
                population_m=ns.population_m,
                military=ns.military,
                stability=ns.stability,
                approval=ns.approval,
                aggression=ns.aggression,
                paranoia=ns.paranoia,
                stocks={**DEFAULT_STOCKS, **ns.stockpile_months},
                debt_gdp=ns.debt_gdp,
                renew_eff=ns.energy_renew,
                credibility=min(ns.stability, 90.0),
                base_aggression=ns.aggression,
                base_paranoia=ns.paranoia,
                trust={o.id: 20.0 for o in spec.nations if o.id != ns.id},
            )
        # active resource units per nation (destroy_resource removes units)
        self.nation_resources: dict[str, list[ResourceKind]] = {
            ns.id: list(ns.resources) for ns in sorted(spec.nations, key=lambda n: n.id)
        }
        self.initial_gdp = {n.id: n.gdp for n in self.nations.values()}
        self.wars: list[tuple[str, str]] = []
        self.temp_effects: list[TempEffect] = []
        self.news: list[str] = []
        self.out_dir = Path(out_dir) if out_dir else None
        self.event_log = EventLog(log_stream)
        # 戦略因子の初期保有（プリセットの factor_holders。無ければ因子なし世界）
        for fid, holders in (spec.factor_holders or {}).items():
            for nid in holders:
                if nid in self.nations and fid in FACTORS_BY_ID:
                    self.nations[nid].factors.append(fid)
        self.snapshots: list[dict] = []
        self._replay: Optional[IO[str]] = None
        self.run_name = run_name
        self.series: list[dict] = []
        self._pending_reopen: dict[str, int] = {}
        self._cp_cause: dict[str, str] = {}   # chokepoint name -> closure event id
        self._tick_throttled: list[str] = []  # this tick's trade_throttled event ids
        # emerging techs: unlocked flag + per-nation adoption
        self.tech_index = tech_catalog_index()
        self.tech_unlocked: dict[str, bool] = {t.id: t.unlock_tick <= 0 for t in CATALOG}
        self.tech_adopted: dict[str, set[str]] = {t.id: set() for t in CATALOG}
        self.banned_techs: set[str] = set()
        self._tech_cause: dict[str, str] = {}  # tech id -> emergence event id

    # ------------------------------------------------------------------ setup
    def open_replay(self) -> None:
        if self.out_dir is None:
            return
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._replay = (self.out_dir / "replay.jsonl").open("w", encoding="utf-8")
        meta = {
            "type": "meta",
            "run_name": self.run_name,
            "seed": self.seed,
            "spec": self.spec.model_dump(mode="json"),
            "geo": {
                "map_geojson": self.spec.map_geojson,
                "nations": {
                    ns.id: {"name": ns.name, "color": ns.color,
                            "centroid": list(ns.centroid), "geo_ids": ns.geo_ids}
                    for ns in self.spec.nations
                },
                "chokepoints": [
                    {"name": cp.name, "lon": cp.lon, "lat": cp.lat}
                    for cp in self.spec.chokepoints
                ],
                "routes": [
                    {"importer": r.importer, "exporter": r.exporter,
                     "commodity": r.commodity.value, "chokepoints": r.chokepoints}
                    for r in self.spec.routes
                ],
                "techs": [t.model_dump(mode="json") for t in CATALOG],
            },
        }
        self._replay.write(json.dumps(meta, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------- run
    def run(self, ticks: int, scenario: Scenario | None = None) -> None:
        scenario = scenario or Scenario()
        schedule: list[Intervention] = sorted(scenario.interventions, key=lambda i: i.tick)
        self.open_replay()
        for t in range(ticks):
            self.tick_no = t
            due = [i for i in schedule if i.tick == t]
            for iv in due:
                self.apply_intervention(iv)
            self.step()
        self.close()

    def close(self) -> None:
        if self._replay:
            self._replay.close()
            self._replay = None

    # -------------------------------------------------------------- god cards
    def _chokepoint_by_ref(self, ref: str):
        """Resolve a chokepoint by name or by '#N' index (sorted names) so
        scenarios written for hand-made presets also work on generated worlds."""
        if ref.startswith("#"):
            names = sorted(self.chokepoints)
            idx = int(ref[1:])
            return self.chokepoints.get(names[idx]) if 0 <= idx < len(names) else None
        return self.chokepoints.get(ref)

    def _nation_by_ref(self, ref: str) -> Optional[str]:
        if ref.startswith("#"):
            ids = sorted(self.nations)
            idx = int(ref[1:])
            return ids[idx] if 0 <= idx < len(ids) else None
        return ref if ref in self.nations else None

    def apply_intervention(self, iv: Intervention) -> None:
        p = iv.params
        if iv.type == "close_chokepoint":
            cp = self._chokepoint_by_ref(p["chokepoint"])
            if cp and not cp.closed:
                cp.closed, cp.closed_since = True, self.tick_no
                dur = p.get("duration")
                if dur:
                    self._pending_reopen[cp.name] = self.tick_no + int(dur)
                ev = self.event_log.emit(
                    self.tick_no, "god_intervention", f"神が海峡 {cp.name} を封鎖した",
                    actor="GOD", targets=[], data={"chokepoint": cp.name},
                )
                self._cp_cause[cp.name] = ev.id
        elif iv.type == "open_chokepoint":
            cp = self._chokepoint_by_ref(p["chokepoint"])
            if cp and cp.closed:
                cp.closed, cp.closed_since = False, None
                self._cp_cause.pop(cp.name, None)
                self.event_log.emit(
                    self.tick_no, "god_intervention", f"神が海峡 {cp.name} の封鎖を解いた",
                    actor="GOD", data={"chokepoint": cp.name},
                )
        elif iv.type == "destroy_resource":
            nid = self._nation_by_ref(p["nation"])
            res = ResourceKind(p["resource"])
            if nid is None:
                return
            units = self.nation_resources[nid]
            if res in units:
                units.remove(res)
                self.event_log.emit(
                    self.tick_no, "god_intervention",
                    f"神が {self.nations[nid].name} の {res.value} 生産能力を消し去った",
                    actor="GOD", targets=[nid], data={"nation": nid, "resource": res.value},
                )
        elif iv.type == "disaster":
            nid = self._nation_by_ref(p["nation"])
            if nid is None:
                return
            kind = p.get("kind", "drought")
            nat = self.nations[nid]
            if kind == "drought":
                self.temp_effects.append(TempEffect(self.tick_no + 6, nid, "food", 0.4))
            elif kind == "earthquake":
                nat.stability -= 10
                nat.gdp *= 0.98
            elif kind == "epidemic":
                nat.population_m *= 0.98
                nat.stability -= 8
            self.event_log.emit(
                self.tick_no, "god_intervention", f"神が {nat.name} に {kind} を降らせた",
                actor="GOD", targets=[nid], data={"nation": nid, "kind": kind},
            )
        elif iv.type == "disinfo":
            target = self._nation_by_ref(p["target"])
            if target is None:
                return
            intensity = float(p.get("intensity", 1.0)) * self.god.disinfo_intensity
            for nid, nat in self.nations.items():
                if nid != target:
                    nat.trust[target] = max(-100.0, nat.trust[target] - 15.0 * intensity)
            self.nations[target].paranoia = min(1.0, self.nations[target].paranoia + 0.06 * intensity)
            self.event_log.emit(
                self.tick_no, "disinfo",
                f"偽情報が流通し始めた: {self.nations[target].name} への疑念が急騰",
                actor="GOD", targets=[target], data={"target": target, "intensity": intensity},
            )
        elif iv.type == "create_resource":
            nid = self._nation_by_ref(p["nation"])
            if nid is None:
                return
            try:
                res = ResourceKind(p["resource"])
            except ValueError:
                return
            qty = max(1, int(p.get("quantity", 1)))
            for _ in range(qty):
                self.nation_resources[nid].append(res)
            self.event_log.emit(
                self.tick_no, "god_intervention",
                f"神が {self.nations[nid].name} に新たな {res.value} 資源を創り出した（×{qty}）",
                actor="GOD", targets=[nid], data={"nation": nid, "resource": res.value, "quantity": qty},
            )
        elif iv.type == "grant_tech":
            nid = self._nation_by_ref(p["nation"])
            tid = p["tech"]
            if nid is None or tid not in self.tech_index or tid in self.banned_techs:
                return
            self.tech_unlocked[tid] = True
            if nid not in self.tech_adopted[tid]:
                self._adopt_tech(nid, tid, forced=True)
        elif iv.type == "ban_tech":
            tid = p["tech"]
            if tid not in self.tech_index:
                return
            self.banned_techs.add(tid)
            self.tech_adopted[tid].clear()
            self.event_log.emit(
                self.tick_no, "god_intervention",
                f"神が「{self.tech_index[tid].name}」の研究を全世界で禁じた",
                actor="GOD", data={"tech": tid},
            )
        elif iv.type == "bailout":
            nid = self._nation_by_ref(p["nation"])
            if nid is None:
                return
            nat = self.nations[nid]
            nat.debt_gdp *= 0.6
            nat.credibility = max(nat.credibility, 60.0)
            nat.stability = min(100.0, nat.stability + 5.0)
            self.event_log.emit(
                self.tick_no, "god_intervention",
                f"神が {nat.name} に救済（ベイルアウト）を与えた。債務は削減され信用が部分的に回復",
                actor="GOD", targets=[nid], data={"nation": nid},
            )
        elif iv.type == "rate_hike":
            self.god.world_rate_hike = float(p.get("value", 0.02))
            self.event_log.emit(
                self.tick_no, "god_intervention",
                f"神が世界金利を +{self.god.world_rate_hike*100:.0f}% 引き上げた。全ての債務国の利払いが急増する",
                actor="GOD", data={"value": self.god.world_rate_hike},
            )
        elif iv.type == "set_param":
            nid = self._nation_by_ref(p["nation"])
            if nid is None:
                return
            param, value = p["param"], float(p["value"])
            setattr(self.nations[nid], param, value)
            self.event_log.emit(
                self.tick_no, "god_intervention",
                f"神が {self.nations[nid].name} の {param} を {value:.2f} に書き換えた",
                actor="GOD", targets=[nid], data={"nation": nid, "param": param, "value": value},
            )
        elif iv.type == "global_slider":
            setattr(self.god, p["param"], float(p["value"]))
            self.event_log.emit(
                self.tick_no, "god_intervention", f"神が世界パラメータ {p['param']} を {p['value']} にした",
                actor="GOD", data=p,
            )
        elif iv.type == "grant_factor":
            nid = self._nation_by_ref(p["nation"])
            fid = p.get("factor", "nuclear")
            if nid is None or fid not in FACTORS_BY_ID:
                return
            fspec = FACTORS_BY_ID[fid]
            if fid not in self.nations[nid].factors:
                self.nations[nid].factors.append(fid)
                self.nations[nid].factor_progress.pop(fid, None)
                self.event_log.emit(
                    self.tick_no, "god_intervention",
                    f"神が {self.nations[nid].name} に {fspec.name} を授けた（既成事実化）",
                    actor="GOD", targets=[nid], data={"nation": nid, "factor": fid},
                )

    # -------------------------------------------------------------- one tick
    def step(self) -> None:
        self._ca_exports = {}
        self._ca_imports = {}
        self._shortages = {}
        t = self.tick_no
        # reopen scheduled chokepoints
        for name, reopen_at in list(self._pending_reopen.items()):
            if t >= reopen_at:
                cp = self.chokepoints[name]
                cp.closed, cp.closed_since = False, None
                del self._pending_reopen[name]
                self._cp_cause.pop(name, None)
                self.event_log.emit(t, "god_intervention", f"海峡 {name} の封鎖が解かれた", actor="GOD")
        # expire temp effects
        self.temp_effects = [e for e in self.temp_effects if e.until > t]
        self._tick_throttled = []
        self._tech_step()

        supply = self._production()
        flows, unmet = self._trade(supply)
        self._market(supply, flows, unmet)
        self._consume(supply)
        decisions = self._decide()
        self._apply_decisions(decisions)
        self._factor_step()
        self._conflict()
        self._macro_update()
        self._snapshot()

    # ------------------------------------------------------------- tech layer
    def _tech_step(self) -> None:
        """Paper-level innovations mature into prototypes, then diffuse to
        nations according to their absorptive (research) capacity."""
        t = self.tick_no
        for tech in CATALOG:
            if not self.tech_unlocked[tech.id] and t >= tech.unlock_tick:
                self.tech_unlocked[tech.id] = True
                ev = self.event_log.emit(
                    t, "tech_emergence",
                    f"研究フロンティア突破: 「{tech.name}」が論文から原型へ（{tech.desc}）",
                    data={"tech": tech.id, "category": tech.category},
                )
                self._tech_cause[tech.id] = ev.id
            if not self.tech_unlocked[tech.id] or tech.id in self.banned_techs:
                continue
            for nid in sorted(self.nations):
                if nid in self.tech_adopted[tech.id]:
                    continue
                if self.rng.random() < 0.08 * self._research_capacity(nid):
                    self._adopt_tech(nid, tech.id)

    def _research_capacity(self, nid: str) -> float:
        nat = self.nations[nid]
        finance_units = sum(1 for r in self.nation_resources[nid] if r is ResourceKind.FINANCE)
        cap = 0.4 + min(1.2, nat.gdp / 8.0) + 0.25 * finance_units
        if nat.stocks.get("chips", 0) >= 2.0:
            cap += 0.3
        return max(0.2, min(2.0, cap))

    def _adopt_tech(self, nid: str, tech_id: str, forced: bool = False) -> None:
        tech = self.tech_index[tech_id]
        nat = self.nations[nid]
        self.tech_adopted[tech_id].add(nid)
        nat.aggression = min(1.0, nat.aggression + tech.aggression_shot)
        nat.paranoia = min(1.0, nat.paranoia + tech.paranoia_shot)
        if tech.trust_hit:
            for other, onat in self.nations.items():
                if other != nid:
                    onat.trust[nid] = max(-100.0, onat.trust[nid] - tech.trust_hit)
        parents = [self._tech_cause[tech_id]] if tech_id in self._tech_cause else []
        verb = "神が授けた" if forced else "導入に成功"
        self.event_log.emit(
            self.tick_no, "tech_adopted",
            f"{nat.name} が「{tech.name}」を{verb}",
            actor=nid, targets=[nid], parents=parents,
            data={"tech": tech_id, "category": tech.category, "forced": forced},
        )

    def _tech_factors(self, nid: str) -> tuple[dict[str, float], dict[str, float]]:
        mult = {c.value: 1.0 for c in Commodity}
        flat = {c.value: 0.0 for c in Commodity}
        for tech in CATALOG:
            if nid not in self.tech_adopted[tech.id]:
                continue
            for c, m in tech.mult.items():
                mult[c] *= m
            for c, f in tech.flat.items():
                flat[c] += f
        return mult, flat

    def _tech_military_mult(self, nid: str) -> float:
        m = 1.0
        for tech in CATALOG:
            if nid in self.tech_adopted[tech.id]:
                m *= tech.military_mult
        return m

    def _tech_socio_drifts(self, nid: str) -> tuple[float, float]:
        """(stability, approval) per-tick drifts from adopted socio/weapon techs."""
        s = a = 0.0
        for tech in CATALOG:
            if nid in self.tech_adopted[tech.id]:
                s += tech.stability_drift
                a += tech.approval_drift
        return s, a

    def _edu_factor(self, nid: str) -> float:
        return 0.6 + 0.8 * self._specs[nid].education

    def _techs_of(self, nid: str) -> list[str]:
        return sorted(tid for tid, owners in self.tech_adopted.items() if nid in owners)

    # ------------------------------------------------------------- production
    FAB_BLACKOUT_MULT = 0.4    # fabs without power run at 40%
    FAB_STARVED_MULT = 0.7     # fabs without minerals run at 70%

    def _production(self) -> dict[str, dict[str, float]]:
        """Domestic supply per nation, in months-of-own-demand units.
        Fabs need electricity and minerals; orbit units are chokepoint-free."""
        supply: dict[str, dict[str, float]] = {}
        for nid in sorted(self.nations):
            dom = {c.value: 0.0 for c in Commodity}
            nat = self.nations[nid]
            blackout = nat.stocks["energy"] < 0.5
            starved = nat.stocks["minerals"] < 0.3
            for res in self.nation_resources[nid]:
                if res is ResourceKind.FINANCE:
                    continue
                commodity = RESOURCE_TO_COMMODITY[res].value
                mult = 1.0
                for eff in self.temp_effects:
                    if eff.nation == nid:
                        mult *= eff.mult
                if res is ResourceKind.FAB:
                    if blackout:
                        mult *= self.FAB_BLACKOUT_MULT
                    if starved:
                        mult *= self.FAB_STARVED_MULT
                slider = getattr(self.god, COMMODITY_YIELD_SLIDER[Commodity(commodity)])
                dom[commodity] += YIELD_PER_UNIT * slider * mult
            # emerging techs: unconditional flat supply then multipliers
            t_mult, t_flat = self._tech_factors(nid)
            climate_food = 1.0 - min(0.15, self.global_co2 / 800.0)   # CO2蓄積→食料減産
            for c in dom:
                dom[c] = dom[c] * t_mult[c] * nat.infra + t_flat[c]
                if c == "food":
                    dom[c] *= climate_food
            supply[nid] = dom
        return supply

    # ------------------------------------------------------------------ trade
    def _trade(self, supply: dict[str, dict[str, float]]) -> tuple[dict, dict[str, float]]:
        """Resolve import needs through routes; chokepoint closure throttles capacity."""
        t = self.tick_no
        flows: dict[tuple[str, str, str], float] = {}
        unmet: dict[str, float] = {c.value: 0.0 for c in Commodity}
        # exporter surpluses (months of own demand they can spare)
        surplus: dict[tuple[str, str], float] = {}
        for nid in sorted(self.nations):
            nat = self.nations[nid]
            for c in Commodity:
                s = supply[nid][c.value] - CONSUMPTION[c.value]
                surplus[(nid, c.value)] = max(0.0, s) * (0.8 if nat.budget.get("stockpile", 0) > 0.3 else 1.0)

        # proportional rationing: when an exporter cannot serve all wants,
        # scale every route by the same factor (no first-come advantage)
        wants: dict[tuple[str, str, str], float] = {}
        demand_by: dict[tuple[str, str], float] = {}
        for route in sorted(self.spec.routes, key=lambda r: (r.importer, r.exporter, r.commodity.value)):
            imp, exp = self.nations[route.importer], self.nations[route.exporter]
            if route.exporter in imp.at_war_with or route.exporter in imp.sanctions_on:
                continue
            if route.importer in exp.sanctions_on:
                continue
            need = max(0.0, CONSUMPTION[route.commodity.value] - supply[route.importer][route.commodity.value])
            want = need * route.share * (1.3 if imp.budget.get("stockpile", 0) > 0.3 else 1.0)
            if want <= 0:
                continue
            wants[(route.importer, route.exporter, route.commodity.value)] = want
            demand_by[(route.exporter, route.commodity.value)] = (
                demand_by.get((route.exporter, route.commodity.value), 0.0) + want
            )

        initial_spare = dict(surplus)
        for route in sorted(self.spec.routes, key=lambda r: (r.importer, r.exporter, r.commodity.value)):
            key = (route.importer, route.exporter, route.commodity.value)
            want = wants.get(key)
            if want is None:
                continue
            imp, exp = self.nations[route.importer], self.nations[route.exporter]
            capacity = self.god.trade_efficiency
            blocked: list[str] = []
            for cpn in route.chokepoints:
                cp = self.chokepoints.get(cpn)
                if cp and cp.closed:
                    capacity *= 0.15
                    blocked.append(cpn)
            avail = surplus[(route.exporter, route.commodity.value)]
            total_demand = demand_by[(route.exporter, route.commodity.value)]
            ration = min(1.0, initial_spare[(route.exporter, route.commodity.value)] / total_demand) if total_demand > 0 else 0.0
            flow = max(0.0, min(want * ration, avail) * capacity)
            if flow <= 0:
                if blocked:
                    self._tick_throttled_note(route, blocked, capacity)
                continue
            surplus[(route.exporter, route.commodity.value)] -= flow
            flows[key] = flow
            if blocked:
                ev = self.event_log.emit(
                    t, "trade_throttled",
                    f"{imp.name}←{exp.name} の{route.commodity.value}航路、{','.join(blocked)} 封鎖で輸送力激減",
                    targets=[route.importer, route.exporter],
                    parents=[self._cp_cause[n] for n in blocked if n in self._cp_cause],
                    data={"routes": route.model_dump(), "capacity": capacity},
                )
                self._tick_throttled.append(ev.id)
            # exporter earns, importer receives
            revenue = 0.01 * flow * self.prices[route.commodity.value] * 12
            exp.gdp += revenue
            imp.stocks[route.commodity.value] += flow
            flow_val = flow * self.prices[route.commodity.value]
            self._ca_exports[route.exporter] = self._ca_exports.get(route.exporter, 0.0) + flow_val
            self._ca_imports[route.importer] = self._ca_imports.get(route.importer, 0.0) + flow_val
            failed = max(0.0, want - flow)
            if failed > 0:
                unmet[route.commodity.value] += failed

        return flows, unmet

    def _tick_throttled_note(self, route, blocked, capacity) -> None:
        imp, exp = self.nations[route.importer], self.nations[route.exporter]
        self.event_log.emit(
            self.tick_no, "trade_throttled",
            f"{imp.name}←{exp.name} の{route.commodity.value}航路、{','.join(blocked)} 封鎖で輸送力激減",
            targets=[route.importer, route.exporter],
            parents=[self._cp_cause[n] for n in blocked if n in self._cp_cause],
            data={"routes": route.model_dump(), "capacity": capacity},
        )

    # ----------------------------------------------------------------- market
    def _market(self, supply, flows, unmet: dict[str, float]) -> None:
        t = self.tick_no
        self.last_prices = dict(self.prices)
        for c in Commodity:
            world_demand = len(self.nations) * CONSUMPTION[c.value]
            world_supply = sum(supply[nid][c.value] for nid in self.nations)
            scarcity = max(0.0, world_demand - world_supply) / world_demand      # persistent level
            shock = min(1.0, unmet[c.value] / world_demand)                       # acute failed flows
            target = 1.0 + 1.5 * scarcity + 2.0 * shock
            if self.wars and c is Commodity.ENERGY:
                target *= 1.15
            self.prices[c.value] = min(4.0, max(0.5, 0.80 * self.prices[c.value] + 0.20 * target))
            if self.prices[c.value] / self.last_prices[c.value] > 1.12:
                self.event_log.emit(
                    t, "price_spike",
                    f"{c.value} の国際価格が急騰 ({self.last_prices[c.value]:.2f}→{self.prices[c.value]:.2f})",
                    parents=list(self._tick_throttled),
                    data={"commodity": c.value, "from": self.last_prices[c.value], "to": self.prices[c.value]},
                )

    # ------------------------------------------------------------- consumption
    CAUSAL_TYPES = ("trade_throttled", "disinfo", "god_intervention", "sanction",
                    "threat", "war_start", "price_spike", "shortage")

    def _causal_parents(self, nid: str, window: int = 14) -> list[str]:
        """Event ids in recent history that touched this nation (its upstream causes)."""
        out = []
        for rec in self.event_log.records[-window:]:
            if rec.type not in self.CAUSAL_TYPES:
                continue
            if rec.actor == nid or nid in rec.targets or rec.actor == "GOD":
                out.append(rec.id)
        return out[-3:]

    def _consume(self, supply) -> None:
        t = self.tick_no
        for nid in sorted(self.nations):
            nat = self.nations[nid]
            if nat.collapsed:
                nat.collapse_ticks = max(0, nat.collapse_ticks - 1)
                if nat.collapse_ticks == 0:
                    nat.collapsed = False
                    nat.stability = 35.0
                continue
            for c in Commodity:
                nat.stocks[c.value] += supply[nid][c.value]
                use = CONSUMPTION[c.value] * (0.85 if (nat.rationing and c is Commodity.FOOD) else 1.0)
                nat.stocks[c.value] -= use
                if nat.stocks[c.value] < 0:
                    severity = min(1.0, -nat.stocks[c.value])
                    nat.stocks[c.value] = 0.0
                    nat.stability -= SHORTAGE_STABILITY_HIT[c.value] * severity
                    self._shortages[nid] = self._shortages.get(nid, 0.0) + severity
                    if severity > 0.3:
                        self.event_log.emit(
                            t, "shortage",
                            f"{nat.name} で {c.value} が深刻な不足。備蓄底をつき社会不安が拡大",
                            actor=nid, targets=[nid],
                            parents=self._causal_parents(nid),
                            data={"commodity": c.value, "severity": severity},
                        )

    # --------------------------------------------------------------- decisions
    def nation_view(self, nid: str) -> NationView:
        """Single nation's observation of the world (shared by policies & RL).

        戦略推論に渡せるものは全部渡す: 時系列トレンド・貿易構造・世界情勢・
        他国の観測可能な概要・直前の自分の意思決定・tick付きイベント系列。
        """
        nat = self.nations[nid]
        me_view = dict(nat.view())
        me_view["techs"] = self._techs_of(nid)

        # --- 時系列トレンド（snapshotsからlag特徴量を計算） ---
        hist = self.snapshots[-13:]
        trends: dict = {"prices": {}, "me": {}}
        for c in self.prices:
            cur = self.prices[c]
            for lag in (1, 3, 6, 12):
                if len(hist) > lag:
                    old = hist[-1 - lag]["prices"].get(c, cur)
                    trends["prices"][f"{c}_vs_t{lag}"] = round(cur / max(0.01, old) - 1.0, 3)
        for key in ("gdp", "stability", "unemployment", "debt_gdp", "fx", "fx_reserves"):
            for lag in (3, 12):
                if len(hist) > lag:
                    old = hist[-1 - lag]["nations"].get(nid, {}).get(key)
                    if old is not None and old != 0:
                        trends["me"][f"{key}_vs_t{lag}"] = round(
                            (me_view.get(key, 0) - old) / abs(old), 3)
        # 信頼の変化（上位の関係者について）
        if len(hist) > 6:
            old_trust = hist[-7]["nations"].get(nid, {}).get("trust", {})
            deltas = []
            for o, v in nat.trust.items():
                d = v - old_trust.get(o, v)
                if abs(d) >= 3.0:
                    deltas.append({"nation": o, "delta": round(d, 1), "now": round(v, 1)})
            deltas.sort(key=lambda x: -abs(x["delta"]))
            trends["trust_changes"] = deltas[:6]

        # --- 世界情勢 ---
        m = hist[-1]["metrics"] if hist else {}
        world = {
            "world_gdp": m.get("world_gdp"),
            "world_gdp_vs_t12": None,
            "mean_unemployment": m.get("mean_unemployment"),
            "global_co2": m.get("global_co2"),
            "ongoing_wars": [list(w) for w in self.wars],
            "nuclear_holders": sorted(o for o, on in self.nations.items() if "nuclear" in on.factors),
        }
        if len(hist) > 12:
            old_m = hist[-13]["metrics"]
            if old_m.get("world_gdp"):
                world["world_gdp_vs_t12"] = round(m["world_gdp"] / old_m["world_gdp"] - 1.0, 3)

        # --- 貿易構造: 輸入依存と海峡曝露 ---
        dep = {c.value: 0.0 for c in Commodity}
        cp_exposure: dict[str, float] = {}
        suppliers: dict[str, dict[str, float]] = {}
        customers: dict[str, float] = {}
        for r in self.spec.routes:
            if r.importer == nid:
                dep[r.commodity.value] = min(1.0, dep[r.commodity.value] + r.share)
                suppliers.setdefault(r.commodity.value, {})
                suppliers[r.commodity.value][r.exporter] = round(
                    suppliers[r.commodity.value].get(r.exporter, 0.0) + r.share, 2)
                for cpn in r.chokepoints:
                    cp_exposure[cpn] = round(cp_exposure.get(cpn, 0.0) + r.share, 2)
            elif r.exporter == nid:
                customers[r.importer] = round(customers.get(r.importer, 0.0) + r.share, 2)
        trade = {
            "import_dependency": {k: round(v, 2) for k, v in dep.items() if v > 0},
            "chokepoint_exposure": dict(sorted(cp_exposure.items(), key=lambda x: -x[1])),
            "key_suppliers": suppliers,
            "key_customers": dict(sorted(customers.items(), key=lambda x: -x[1])[:6]),
        }

        # --- 他国の観測可能な概要（全員に近い相手上位。16国以下の世界では全員） ---
        others = sorted(self.nations.items())
        fog = getattr(self.god, "fog_of_war", 0.0)
        rel_full = {
            o: {
                "trust": round(onat.trust.get(nid, 0.0) + fog * (20.0 - onat.trust.get(nid, 0.0)), 1),
                "alliance": o in nat.alliances,
                "war": o in nat.at_war_with,
                "sanction": o in nat.sanctions_on,
                "gdp": round(onat.gdp, 1),
                "military": round(onat.military, 0),
                "stability": round(onat.stability, 0),
                "nuclear": "nuclear" in onat.factors,
            }
            for o, onat in others if o != nid
        }
        if len(rel_full) > 30:
            # 大世界では関連上位のみ（戦争・同盟・制裁・信頼両極端）
            ranked = sorted(
                rel_full.items(),
                key=lambda kv: (kv[1]["war"], kv[1]["alliance"], kv[1]["sanction"],
                                abs(kv[1]["trust"] - 20.0), kv[1]["gdp"]),
                reverse=True)
            rel_full = dict(ranked[:30])

        recent = [f"t{r.tick}: {r.text}" for r in self.event_log.records[-16:]]
        return NationView(
            tick=self.tick_no,
            me=me_view,
            prices=dict(self.prices),
            god_params=self.god.model_dump(),
            relations=rel_full,
            market_news=[f"{k} price {v:.2f}" for k, v in self.prices.items()],
            recent_events=recent,
            trends=trends,
            world=world,
            trade=trade,
            last_decision=self._last_decision.get(nid, {}),
        )

    def _decide(self) -> dict[str, Decisions]:
        out: dict[str, Decisions] = {}
        for nid in sorted(self.nations):
            policy = self.policies.get(nid) or self.policies.get("*")
            view = self.nation_view(nid)
            out[nid] = policy.decide(view)
        return out

    def _apply_decisions(self, decisions: dict[str, Decisions]) -> None:
        t = self.tick_no
        for nid in sorted(decisions):
            nat, d = self.nations[nid], decisions[nid]
            nat.budget = d.budget
            nat.rationing = d.rationing
            nat.doctrines = dict(d.doctrines or {})   # 戦略因子の自己選択を反映
            self._last_decision[nid] = {
                "budget": {k: round(v, 2) for k, v in (d.budget or {}).items()},
                "posture": d.military_posture,
                "rationing": d.rationing,
                "doctrines": dict(d.doctrines or {}),
            }
            if nat.propaganda and not d.propaganda:
                nat.propaganda = False
            elif d.propaganda:
                nat.propaganda = True
                nat.approval = min(100.0, nat.approval + 3.0)
                nat.paranoia = min(1.0, nat.paranoia + 0.01)
            self.event_log.emit(
                t, "policy_shift",
                f"{nat.name}: {d.rationale}",
                actor=nid, targets=[nid],
                data={"posture": d.military_posture, "rationing": d.rationing,
                      "propaganda": d.propaganda, "budget": d.budget},
            )

        # diplomacy, in two passes so offers see a consistent world
        for nid in sorted(decisions):
            nat, d = self.nations[nid], decisions[nid]
            for act in d.diplomacy:
                other = self.nations.get(act.target)
                if other is None or other.id == nid:
                    continue
                if act.kind == "improve":
                    nat.trust[act.target] = min(100.0, nat.trust[act.target] + 4.0)
                    other.trust[nid] = min(100.0, other.trust[nid] + 2.0)
                elif act.kind == "sanction":
                    if act.target not in nat.sanctions_on:
                        nat.sanctions_on.append(act.target)
                        other.trust[nid] = max(-100.0, other.trust[nid] - 12.0)
                        other.stability -= 1.0
                        other.paranoia = min(1.0, other.paranoia + 0.02)
                        self.event_log.emit(
                            t, "sanction", f"{nat.name} が {other.name} に制裁",
                            actor=nid, targets=[act.target], data={},
                        )
                elif act.kind == "alliance_offer":
                    if other.trust.get(nid, 0) > 25 and nid not in other.at_war_with:
                        if act.target not in nat.alliances:
                            nat.alliances.append(act.target)
                            other.alliances.append(nid)
                            self.event_log.emit(
                                t, "alliance_formed", f"{nat.name} と {other.name} が同盟を締結",
                                actor=nid, targets=[act.target], data={},
                            )
                elif act.kind == "threaten":
                    other.trust[nid] = max(-100.0, other.trust[nid] - 12.0)
                    other.paranoia = min(1.0, other.paranoia + 0.03)
                    other.aggression = min(1.0, other.aggression + 0.02)
                    self.event_log.emit(
                        t, "threat", f"{nat.name} が {other.name} に軍事的圧力/最後通牒",
                        actor=nid, targets=[act.target], data={},
                    )
                elif act.kind == "trade_pact":
                    nat.trust[act.target] = min(100.0, nat.trust[act.target] + 3.0)
                    other.trust[nid] = min(100.0, other.trust[nid] + 3.0)

    # ---------------------------------------------------------------- conflict
    def _conflict(self) -> None:
        t = self.tick_no
        # ongoing wars: attrition
        for a, b in list(self.wars):
            na, nb = self.nations[a], self.nations[b]
            dmg_a = 2.0 + self.rng.random() * 3.0
            dmg_b = 2.0 + self.rng.random() * 3.0
            na.military -= dmg_b
            nb.military -= dmg_a
            na.war_exhaustion += 4.0
            nb.war_exhaustion += 4.0
            for n in (na, nb):
                n.gdp *= 0.997
            if na.war_exhaustion > 40 or nb.war_exhaustion > 40 or self.rng.random() < 0.05:
                self.wars.remove((a, b))
                na.at_war_with.remove(b)
                nb.at_war_with.remove(a)
                self.event_log.emit(
                    t, "war_end", f"{na.name} と {nb.name} の戦争が終結（疲弊）",
                    targets=[a, b], data={"exhaustion_a": na.war_exhaustion, "exhaustion_b": nb.war_exhaustion},
                )
            continue

        # new skirmishes from tension
        ids = sorted(self.nations)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if b in self.nations[a].at_war_with:
                    continue
                na, nb = self.nations[a], self.nations[b]
                if na.collapsed or nb.collapsed:
                    continue
                rivalry_bonus = 0.15 if self._resource_dispute(a, b) else 0.0
                tension = (
                    0.5 * (na.aggression + nb.aggression) * self.god.ai_aggression * 0.5
                    + max(0.0, -na.trust.get(b, 0.0)) / 150.0
                    + 0.1 * (na.paranoia + nb.paranoia)
                    + rivalry_bonus
                )
                det = self._deterrence(a, b) or self._deterrence(b, a)
                if det is not None:
                    tension *= det
                if tension > 0.55 and self.rng.random() < (tension - 0.55):
                    self.wars.append((a, b))
                    na.at_war_with.append(b)
                    nb.at_war_with.append(a)
                    parents = [r.id for r in self.event_log.records[-10:]
                               if r.type in ("threat", "sanction", "shortage", "disinfo")
                               and (r.actor in (a, b) or a in r.targets or b in r.targets)]
                    self.event_log.emit(
                        t, "war_start", f"{na.name} と {nb.name} の間で武力衝突が勃発",
                        targets=[a, b], parents=parents,
                        data={"tension": round(tension, 3)},
                    )
                    # 相互防衛: 両側の同盟国が条約を履行するか（新イベント種で因果追跡）
                    wev = self.event_log.records[-1]
                    self._alliance_activation(b, a, wev)
                    self._alliance_activation(a, b, wev)
                    break

    def _resource_dispute(self, a: str, b: str) -> bool:
        for c in Commodity:
            sa = self.nations[a].stocks[c.value]
            sb = self.nations[b].stocks[c.value]
            if sa < 1.5 and sb < 1.5 and self.prices[c.value] > 1.4:
                return True
        return False

    # ------------------------------------------------------------------ finance
    TAX_RATE = 0.30             # annual govt revenue as share of GDP
    BASE_SPEND = 0.24           # annual non-discretionary spending share
    DEFAULT_SAFE = 0.015        # monthly interest below 1.5% of GDP: serviceable
    DEFAULT_FORCE = 0.03        # above 3%: mathematically insolvent

    def _bond_rate(self, nat) -> float:
        """Annual sovereign rate: base + credibility risk premium + inflation
        pass-through + god's world rate hike."""
        premium = (100.0 - nat.credibility) / 100.0 * 0.10
        infl_pass = min(0.15, max(0.0, nat.inflation - 0.05) * 2.0)
        return float(min(0.60, max(0.02, 0.02 + premium + infl_pass + self.god.world_rate_hike)))

    def _fiscal_step(self, nid: str, nat) -> None:
        t = self.tick_no
        at_war = bool(nat.at_war_with)
        mil = nat.budget.get("military", 0.2)
        wel = nat.budget.get("welfare", 0.3)
        # monthly flows (fraction of GDP)
        revenue = self.TAX_RATE / 12.0
        spending = (self.BASE_SPEND + 0.30 * mil * (2.0 if at_war else 1.0) + 0.10 * wel) / 12.0
        rate = self._bond_rate(nat)
        interest = (nat.debt_gdp / 100.0) * rate / 12.0
        deficit = spending + interest - revenue
        nat.debt_gdp = max(0.0, nat.debt_gdp + deficit * 100.0)

        # credibility dynamics (high debt alone erodes credit only slowly:
        # credible high-debt states like Japan must stay serviceable)
        nat.credibility = min(100.0, nat.credibility + 1.5)
        if nat.debt_gdp > 160.0:
            nat.credibility -= 2.5
        if nat.inflation > 0.10:
            nat.credibility -= 2.0
        nat.credibility = max(0.0, nat.credibility)
        if nat.default_cooldown > 0:
            nat.default_cooldown -= 1
            return

        # sovereign default check
        if interest > self.DEFAULT_SAFE:
            forced = interest > self.DEFAULT_FORCE
            p = 1.0 if forced else 0.10 + (interest - self.DEFAULT_SAFE) * 20.0
            if self.rng.random() < p:
                self._sovereign_default(nid, nat, rate)

    def _sovereign_default(self, nid: str, nat, rate: float) -> None:
        t = self.tick_no
        nat.defaults += 1
        nat.default_cooldown = 12                        # restructuring moratorium
        nat.inflation = min(1.0, nat.inflation + 0.15)   # currency crash
        nat.fx = max(0.3, nat.fx * 0.70)                 # 為替暴落
        nat.fx_reserves *= 0.6                           # 準備防衛で消耗
        nat.stability = max(0.0, nat.stability - 8.0)
        nat.credibility = 5.0
        nat.debt_gdp *= 0.50                              # restructuring haircut
        # austerity: creditor-imposed budget shift
        nat.budget = {"military": 0.10, "welfare": 0.30, "stockpile": 0.15, "subsidy": 0.45}
        parents = [r.id for r in self.event_log.records[-12:]
                   if r.type in ("war_start", "price_spike", "disaster", "god_intervention",
                                 "sovereign_default", "sanction", "shortage")
                   and (r.actor == nid or nid in r.targets or r.actor == "GOD")]
        ev = self.event_log.emit(
            t, "sovereign_default",
            f"{nat.name} が債務不履行（デフォルト）。通貨暴落と緊縮が始まる（利払い利率 {rate*100:.0f}%）",
            actor=nid, targets=[nid], parents=parents[-4:],
            data={"rate": round(rate, 3), "debt_gdp": round(nat.debt_gdp, 1)},
        )
        # contagion: creditor nations (finance hubs) take losses
        for other, onat in sorted(self.nations.items()):
            if other == nid:
                continue
            finance_units = sum(1 for r in self.nation_resources[other] if r is ResourceKind.FINANCE)
            if finance_units > 0:
                onat.gdp *= 1.0 - 0.005 * finance_units
                onat.credibility = max(0.0, onat.credibility - 8.0)
                self.event_log.emit(
                    t, "credibility_hit",
                    f"{onat.name} の金融機関が {nat.name} の債務で損失。信用が毀損し感染の火種に",
                    actor=other, targets=[other], parents=[ev.id],
                    data={"exposure": finance_units},
                )

    def _alliance_activation(self, a: str, b: str, war_ev) -> None:
        """相互防衛: bの同盟国が信頼に応じて参戦する（連鎖の深さは1に制限）。"""
        t = self.tick_no
        for x in sorted(self.nations):
            if x in (a, b) or a in self.nations[x].at_war_with:
                continue
            xnat = self.nations[x]
            if b not in xnat.alliances or xnat.collapsed:
                continue
            trust = xnat.trust.get(b, 0.0)
            if trust < 35.0:
                continue
            if self.rng.random() < 0.4 * (trust / 100.0):
                self.wars.append((x, a))
                xnat.at_war_with.append(a)
                self.nations[a].at_war_with.append(x)
                self.event_log.emit(
                    t, "alliance_activation",
                    f"{xnat.name} は同盟条約を履行し {self.nations[b].name} 側に参戦",
                    actor=x, targets=[a, b], parents=[war_ev.id],
                    data={"ally": b, "enemy": a, "trust": round(trust, 1)},
                )

    # ------------------------------------------------------------- macro/cycle
    def _factor_step(self) -> None:
        """戦略因子の解決: policyのdoctrine表明に従い取得進捗/放棄を遷移させる。"""
        t = self.tick_no
        for nid in sorted(self.nations):
            nat = self.nations[nid]
            if nat.collapsed:
                continue
            for fid, spec in FACTORS_BY_ID.items():
                holds = fid in nat.factors
                doctrine = nat.doctrines.get(fid, "hold")
                if not holds and doctrine == "pursue" and self._factor_prereq_ok(nid, spec):
                    nat.factor_progress[fid] = nat.factor_progress.get(fid, 0.0) + 100.0 / spec.acquisition_ticks
                    nat.gdp *= 1.0 - spec.pursuit_cost_gdp
                    if nat.factor_progress[fid] >= 100.0:
                        nat.factors.append(fid)
                        nat.factor_progress.pop(fid, None)
                        parents = [r.id for r in self.event_log.records[-12:]
                                   if r.type in ("threat", "war_start", "sanction", "disinfo", "god_intervention")
                                   and (r.actor == nid or nid in r.targets)]
                        self.event_log.emit(
                            t, "factor_acquired",
                            f"{nat.name} が {spec.name} を取得（新規保有）。地域の戦略均衡が変わる",
                            actor=nid, targets=[nid], parents=parents[-4:], data={"factor": fid},
                        )
                elif holds and doctrine == "abandon":
                    key = ("abandon", nid, fid)
                    self._abandon_votes[key] = self._abandon_votes.get(key, 0) + 1
                    if self._abandon_votes[key] >= 3:
                        nat.factors.remove(fid)
                        self._abandon_votes.pop(key, None)
                        nat.stability = max(0.0, nat.stability - spec.abandon_stability_hit)
                        for other in sorted(self.nations):
                            if other != nid and fid in self.nations[other].factors:
                                self.nations[other].trust[nid] = min(100.0, self.nations[other].trust[nid] + spec.abandon_trust_gain)
                        self.event_log.emit(
                            t, "factor_relinquished",
                            f"{nat.name} が {spec.name} を放棄。国内は揺れ、他国は歓迎する",
                            actor=nid, targets=[nid], data={"factor": fid},
                        )
                elif holds:
                    self._abandon_votes.pop(("abandon", nid, fid), None)
                elif doctrine != "pursue":
                    # 追求を止めると進捗は徐々に減る（遊離ガス）
                    if nat.factor_progress.get(fid, 0.0) > 0:
                        nat.factor_progress[fid] = max(0.0, nat.factor_progress[fid] - 100.0 / (spec.acquisition_ticks * 2))
                # 集団制裁レジーム: 加盟国の制裁対象をレジーム全体へ伝播
                if spec.collective_sanction and fid in nat.factors and nat.sanctions_on:
                    members = [o for o, on in sorted(self.nations.items())
                               if o != nid and fid in on.factors]
                    for target in list(nat.sanctions_on):
                        joined = [o for o in members if target not in self.nations[o].sanctions_on]
                        for o in joined:
                            self.nations[o].sanctions_on.append(target)
                        if joined:
                            self.event_log.emit(
                                t, "collective_sanction",
                                f"{self._fspec_name(fid)}: {self.nations[nid].name} の制裁に {len(joined)} 加盟国が同調（対象 {self.nations.get(target).name if target in self.nations else target}）",
                                actor=nid, targets=[target, *joined],
                                parents=[r.id for r in self.event_log.records[-6:] if r.type == "sanction" and r.actor == nid][-1:],
                                data={"factor": fid, "target": target, "joined": joined},
                            )

    @staticmethod
    def _fspec_name(fid: str) -> str:
        fs = FACTORS_BY_ID.get(fid)
        return fs.name if fs else fid

    def _factor_prereq_ok(self, nid: str, spec) -> bool:
        nat = self.nations[nid]
        for key, threshold in spec.prerequisites.items():
            if key == "allied_with_factor":
                if not any(o in nat.alliances and threshold in self.nations[o].factors
                           for o in self.nations):
                    return False
                continue
            if getattr(nat, key, 0.0) < threshold:
                return False
        return True

    def _deterrence(self, a: str, b: str) -> float | None:
        """a→bの開戦意欲への抑止係数。None=抑止なし。"""
        spec = FACTORS_BY_ID.get("nuclear")
        if not spec:
            return None
        a_holds = "nuclear" in self.nations[a].factors
        b_holds = "nuclear" in self.nations[b].factors
        if a_holds and b_holds:
            return spec.deterrence_mutual
        if b_holds and not a_holds:
            return spec.deterrence_vs_nonholder
        # 核傘: 保護国の抑止を係数付きで継承する
        umb = FACTORS_BY_ID.get("nuclear_umbrella")
        if umb and "nuclear_umbrella" in self.nations[b].factors and not a_holds:
            return spec.deterrence_vs_nonholder * (1.0 + umb.umbrella_deterrence) / 2.0
        return None

    def _macro_update(self) -> None:
        t = self.tick_no
        for nid in sorted(self.nations):
            nat = self.nations[nid]
            if nat.collapsed:
                continue
            spec = self._specs[nid]
            at_war_now = bool(nat.at_war_with)
            # inflation from import price exposure（通貨安は輸入インフレを増幅）
            infl_delta = 0.0
            for c in Commodity:
                dep = self._import_dependency(nid, c)
                infl_delta += dep * 0.25 * (self.prices[c.value] / max(0.01, self.last_prices[c.value]) - 1.0)
            infl_delta *= 1.0 / max(0.5, nat.fx)
            nat.inflation = max(-0.05, min(1.0, 0.85 * nat.inflation + 0.15 * 0.02 + infl_delta))
            # growth
            finance_units = sum(1 for r in self.nation_resources[nid] if r is ResourceKind.FINANCE)
            growth = 0.02 + 0.002 * finance_units - nat.inflation * 0.6
            # --- 労働: 失業率（生産ギャップ・戦争・福祉が決める） ---
            welfare_share = bud0 = nat.budget.get("welfare", 0.3)
            shortage_hits = self._shortages.get(nid, 0.0)
            u_target = (5.0 + max(0.0, 0.02 - growth) * 160.0 + (8.0 if at_war_now else 0.0)
                        + 5.0 * min(1.5, shortage_hits / 2.0)
                        - min(4.0, 6.0 * welfare_share))
            nat.unemployment = min(45.0, max(2.0, nat.unemployment + (u_target - nat.unemployment) * 0.25))
            growth -= max(0.0, nat.unemployment - 10.0) * 0.001          # 失業は生産を蝕む
            # --- 人口 ---
            nat.population_m *= 1.0 + spec.population_growth / 12.0 - (0.001 if at_war_now else 0.0)
            # --- インフラ投資（補助金シェアが蓄積、戦争は毀損） ---
            nat.infra = min(1.25, max(0.5, nat.infra + 0.004 * (nat.budget.get("subsidy", 0.25) * 2.2 - 0.7) - (0.006 if at_war_now else 0.0)))
            # --- 為替: インフレ差で調整、債務不履行で暴落（_sovereign_default参照） ---
            world_inf = sum(o.inflation for o in self.nations.values()) / len(self.nations)
            fx_sens = 0.6
            drain_mult = 1.0
            for fid in nat.factors:
                fs = FACTORS_BY_ID.get(fid)
                if fs:
                    fx_sens *= fs.fx_stabilize
                    drain_mult *= fs.reserves_drain_mult
            nat.fx = min(3.0, max(0.3, nat.fx * (1.0 + fx_sens * (world_inf - nat.inflation) / 12.0)))
            # --- 経常収支と外貨準備 ---
            exp_val = self._ca_exports.get(nid, 0.0)
            imp_val = self._ca_imports.get(nid, 0.0)
            nat.ca_last = exp_val - imp_val
            nat.fx_reserves = min(36.0, max(0.0, nat.fx_reserves + (exp_val - imp_val) * 0.02 * drain_mult))
            if nat.fx_reserves < 1.0:
                # 外貨準備枯渇: 輸入能力が落ち、スタグフレーションと政治的圧力
                growth -= 0.01
                nat.stability = max(0.0, nat.stability - 1.5)
                if int(nat.fx_reserves * 10) % 12 == 0:
                    self.event_log.emit(
                        t, "fx_crisis",
                        f"{nat.name} の外貨準備が枯渇（{nat.fx_reserves:.1f}ヶ月分）。輸入が絞られる",
                        actor=nid, targets=[nid], data={"reserves": round(nat.fx_reserves, 2)},
                    )
            # --- 安全保障ジレンマ: 信頼の低い大国の軍事優位が攻撃性を煽る ---
            rival_max = 0.0
            for o, onat in self.nations.items():
                if o == nid or onat.collapsed or nat.trust.get(o, 20.0) >= 15.0:
                    continue
                rival_max = max(rival_max, onat.military)
            if rival_max > nat.military * 1.2:
                nat.aggression = min(0.95, nat.aggression + 0.004)
                nat.paranoia = min(0.95, nat.paranoia + 0.003)

            # --- CO2: 化石エネルギー生産 × (1-実効再生比率) ---
            techs = self._techs_of(nid)
            renew = max(spec.energy_renew,
                        0.50 if "fusion" in techs else 0.35 if "space_solar" in techs else spec.energy_renew)
            nat.renew_eff = renew
            fossil_units = sum(1 for r in self.nation_resources[nid] if r in (ResourceKind.OIL, ResourceKind.GAS))
            co2_flow = fossil_units * (1.0 - renew)
            nat.co2_cum += co2_flow
            self.global_co2 += co2_flow
            if nat.stocks["chips"] <= 0.05:
                growth -= 0.01
                nat.military = max(0.0, nat.military - 1.0)
            if nat.stocks["space"] <= 0.05:
                # 軌道資産を失うと偵察・通信能力が落ち、軍事力が漸減する
                nat.military = max(0.0, nat.military - 1.5)
            bud = nat.budget
            mil_mult = self._tech_military_mult(nid)
            for fid in nat.factors:
                fspec = FACTORS_BY_ID.get(fid)
                if fspec:
                    mil_mult *= fspec.military_mult
            nat.military = min(150.0, nat.military + (2.0 * bud.get("military", 0.2)) * mil_mult - (0.5 if nid in [x for w in self.wars for x in w] else 0.0))
            nat.gdp *= 1.0 + growth
            # stability & approval
            t_stab, t_appr = self._tech_socio_drifts(nid)
            drift = 0.25 * (55.0 - nat.stability)
            welfare = 3.0 * bud.get("welfare", 0.3)
            gini_drag = max(0.0, spec.gini - 0.40) * 30.0     # 高不平等は社会を疲弊させる
            edu_lift = (spec.education - 0.5) * 0.8
            unemp_drag = max(0.0, nat.unemployment - 8.0) * 0.15
            nat.stability = max(0.0, min(100.0, nat.stability + drift + welfare - nat.inflation * 25.0 - nat.war_exhaustion * 0.05 - gini_drag - unemp_drag + t_stab))
            nat.approval = max(0.0, min(100.0, nat.approval + 0.2 * (50.0 - nat.approval) + (1.0 if bud.get("welfare", 0) > 0.35 else -0.5) - unemp_drag * 0.5 + edu_lift + t_appr))
            nat.war_exhaustion = max(0.0, nat.war_exhaustion - 0.5)
            # ---------------------------------------------------- fiscal block
            self._fiscal_step(nid, nat)
            # collapse check
            if nat.stability < 12.0:
                nat.collapse_ticks += 1
                if nat.collapse_ticks >= 3 and not nat.collapsed:
                    nat.collapsed = True
                    nat.collapse_ticks = 6
                    nat.alliances = []
                    nat.aggression = nat.base_aggression
                    nat.paranoia = nat.base_paranoia
                    for w in list(self.wars):
                        if nid in w:
                            other = w[1] if w[0] == nid else w[0]
                            self.wars.remove(w)
                            self.nations[other].at_war_with.remove(nid)
                            nat.at_war_with.remove(other)
                    self.event_log.emit(
                        t, "collapse", f"{nat.name} で政府が崩壊。国内は混乱状態に陥った",
                        actor=nid, targets=[nid], data={},
                    )
            elif nat.stability > 25.0:
                nat.collapse_ticks = 0

    def _import_dependency(self, nid: str, c: Commodity) -> float:
        dep = 0.0
        for r in self.spec.routes:
            if r.importer == nid and r.commodity is c:
                dep += r.share
        return min(1.0, dep)

    # --------------------------------------------------------------- snapshot
    def _snapshot(self) -> None:
        t = self.tick_no
        tick_events = [r for r in self.event_log.records if r.tick == t]
        nations_out = {}
        for nid in sorted(self.nations):
            nat = self.nations[nid]
            nations_out[nid] = {
                "name": nat.name, "color": nat.color,
                "gdp": round(nat.gdp, 4), "inflation": round(nat.inflation, 4),
                "stability": round(nat.stability, 2), "approval": round(nat.approval, 2),
                "military": round(nat.military, 2), "stocks": {k: round(v, 3) for k, v in nat.stocks.items()},
                "aggression": round(nat.aggression, 3), "paranoia": round(nat.paranoia, 3),
                "at_war_with": nat.at_war_with, "alliances": nat.alliances,
                "collapsed": nat.collapsed, "rationing": nat.rationing, "propaganda": nat.propaganda,
                "techs": self._techs_of(nid),
                "debt_gdp": round(nat.debt_gdp, 1), "credibility": round(nat.credibility, 1),
                "defaults": nat.defaults,
                # friendly度グラフ用: 他国への信頼度(0-100)。形式追加のみで挙動には影響しない
                "trust": {o: round(v, 1) for o, v in sorted(nat.trust.items())},
                "population_m": round(nat.population_m, 1),
                "unemployment": round(nat.unemployment, 2),
                "fx": round(nat.fx, 3),
                "fx_reserves": round(nat.fx_reserves, 1),
                "ca_last": round(nat.ca_last, 2),
                "infra": round(nat.infra, 3),
                "co2_cum": round(nat.co2_cum, 1),
                "renew_eff": round(nat.renew_eff, 2),
                "factors": list(nat.factors),
                "factor_progress": {k: round(v, 1) for k, v in nat.factor_progress.items()},
                "doctrines": dict(nat.doctrines),
            }
        metrics = {
            "world_gdp": round(sum(n.gdp for n in self.nations.values()), 4),
            "mean_stability": round(sum(n.stability for n in self.nations.values()) / len(self.nations), 2),
            "wars": len(self.wars),
            "collapsed": sum(1 for n in self.nations.values() if n.collapsed),
            "price_energy": round(self.prices["energy"], 4),
            "price_food": round(self.prices["food"], 4),
            "price_chips": round(self.prices["chips"], 4),
            "mean_inflation": round(sum(n.inflation for n in self.nations.values()) / len(self.nations), 5),
            "mean_debt_gdp": round(sum(n.debt_gdp for n in self.nations.values()) / len(self.nations), 1),
            "defaults": sum(n.defaults for n in self.nations.values()),
            "mean_unemployment": round(sum(n.unemployment for n in self.nations.values()) / len(self.nations), 2),
            "global_co2": round(self.global_co2, 1),
        }
        snap = {
            "type": "tick", "tick": t, "nations": nations_out,
            "prices": {k: round(v, 4) for k, v in self.prices.items()},
            "chokepoints": {name: cp.closed for name, cp in sorted(self.chokepoints.items())},
            "metrics": metrics,
            "events": [e.model_dump() for e in tick_events],
            "news": [e.text for e in tick_events if e.type in
                     ("war_start", "war_end", "collapse", "sanction", "alliance_formed",
                      "price_spike", "shortage", "disinfo", "god_intervention", "threat")],
        }
        self.snapshots.append(snap)
        self.series.append({"tick": t, **metrics})
        if self._replay:
            self._replay.write(json.dumps(snap, ensure_ascii=False) + "\n")

    # ----------------------------------------------------------------- output
    def write_outputs(self) -> None:
        if self.out_dir is None:
            return
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "events.jsonl").write_text(
            "\n".join(json.dumps(r.model_dump(), ensure_ascii=False) for r in self.event_log.records) + "\n",
            encoding="utf-8",
        )
        import csv

        with (self.out_dir / "series.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(self.series[0].keys()))
            writer.writeheader()
            writer.writerows(self.series)
        summary = {
            "run_name": self.run_name,
            "seed": self.seed,
            "ticks": self.tick_no + 1,
            "final_metrics": self.series[-1] if self.series else {},
            "event_counts": self._event_counts(),
            "wars": len(self.wars),
            "config": self.run_config,
        }
        (self.out_dir / "run.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _event_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.event_log.records:
            counts[r.type] = counts.get(r.type, 0) + 1
        return counts
