"""The Terrarium simulation engine.

Tick pipeline:
  god interventions -> production -> trade (chokepoint-aware) -> market prices
  -> consumption/welfare -> nation decisions (policy layer) -> diplomacy
  -> conflict -> collapse checks -> snapshot & JSONL logging

Clock: every dynamic is calibrated in REAL HOURS (world/clock.py) and
advanced by spec.hours_per_tick per tick. 720h/tick reproduces the classic
monthly-compressed clock used by experiments; 1h/tick is the live god mode
where interventions propagate with realistic delays (markets in hours,
shipping in weeks, GDP in quarters, mobilization in days).

Everything is deterministic given (seed, spec, policies, scenario):
no global RNG, only the seeded engine RNG, and nations/routes are iterated
in sorted order.
"""
from __future__ import annotations

import json
import math
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
from ..world import clock as TC
from ..world.factors import FACTORS_BY_ID
from ..world.tech import CATALOG, tech_catalog_index
from .events import EventLog
from .interventions import Intervention, Scenario

CONSUMPTION = {"energy": 1.0, "food": 1.0, "chips": 0.5, "minerals": 0.5, "space": 0.25}
DEFAULT_STOCKS = {"energy": 3.0, "food": 4.0, "chips": 2.0, "minerals": 2.0, "space": 1.0}
YIELD_PER_UNIT = 1.5
IMPORT_INFLATION_CAP = 0.35   # 輸入価格のCPIパススルーウェイト上限
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
        # ---- シミュレーション時計: 全動力学は実時間(時間)で校正される ----
        self.hpt = float(getattr(spec, "hours_per_tick", 720.0) or 720.0)
        self._dec_every = getattr(spec, "decision_every_hours", None)
        self._cached_decisions: Optional[dict[str, Decisions]] = None
        self._decisions_fresh = True
        self._dec_elapsed_hours = self.hpt
        self._last_dec_hour = 0.0
        self._next_dec_hour = self.hpt
        # 崩壊/回復の実時間しきい値（旧: 3/6 tick = 月次）
        self._collapse_need_ticks = TC.ticks_for(3.0 * TC.HOURS_PER_MONTH, self.hpt)
        self._recover_ticks = TC.ticks_for(6.0 * TC.HOURS_PER_MONTH, self.hpt)
        # 遅延伝播キュー: 動員(開戦前のラダー)と同盟参戦協議
        self._pending_wars: list[dict] = []
        # 戦争強度 (a,b)->intensity 1.0-3.0: 限定戦争から総力戦へのエスカレーション
        self._war_intensity: dict[tuple, float] = {}
        self._war_casualties: dict[str, float] = {}   # nid -> 人口損失(百万人)
        self._pending_alliance: list[dict] = []
        self._seq = 0
        # 市場: 期待(恐怖)プレミアムと価格履歴(日次急騰判定用)
        self._fear: dict[str, float] = {c.value: 0.0 for c in Commodity}
        self._price_hist: list[tuple[float, dict[str, float]]] = []
        self._spike_last: dict[str, float] = {}
        # 高頻度時計でのイベント再送抑止
        self._tt_last: dict[tuple, float] = {}
        self._fxwarn_last: dict[str, float] = {}
        # 市場の裁定材料: 航路需要とその遮断率（価格シグナルの分母）
        self._wants_total: dict[str, float] = {c.value: 0.0 for c in Commodity}
        self._blocked_wants: dict[str, float] = {c.value: 0.0 for c in Commodity}
        # 輸出フロー累計（月次レート換算して成長ボーナスに使う）
        self._export_flow: dict[str, float] = {}
        # 連続不足の深度（月換算で蓄積し、深刻度とする）
        self._shortage_since: dict[tuple, float] = {}
        self._last_sev: dict[tuple, float] = {}
        # provenance recorded into run.json so IF-history forks can replay
        # the exact (preset, policy, scenario) that produced this history
        self.run_config = run_config or {}
        # 力学バージョン: v4で実時間校正（それ以前のログは月次複利の旧力学）
        self.run_config.setdefault("engine", "v4-realtime-clock")
        self.chokepoints = {cp.name: cp for cp in spec.chokepoints}
        self._specs = {ns.id: ns for ns in spec.nations}
        self._ca_exports: dict[str, float] = {}
        self._ca_imports: dict[str, float] = {}
        self._shortages: dict[str, float] = {}
        self._abandon_votes: dict = {}
        # 政策決定の履歴（直近5期。一貫性と後悔の材料）
        self._decision_history: dict[str, list] = {}
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
                unemployment=getattr(ns, "unemployment", 6.0),
                doctrine_risk=getattr(ns, "doctrine_risk", 0.5),
                doctrine_militarism=getattr(ns, "doctrine_militarism", 0.3),
                doctrine_revisionism=getattr(ns, "doctrine_revisionism", 0.2),
                doctrine_vengeance=getattr(ns, "doctrine_vengeance", 0.3),
                doctrine_treaty_fidelity=getattr(ns, "doctrine_treaty_fidelity", 0.7),
                nuclear_posture=getattr(ns, "nuclear_posture", "mad"),
                regime=getattr(ns, "regime", "hybrid"),
                local_debt_share=(
                    ns.local_debt_share if getattr(ns, "local_debt_share", -1.0) >= 0
                    else min(0.95, max(0.1,
                        0.35 + min(0.40, ns.gdp_t / 8.0)
                        + 0.25 * (ResourceKind.FINANCE in ns.resources)))
                ),
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
        # 前tickの軍事力（リチャードソン軍拡反応の検出用）
        self._mil_prev: dict[str, float] = {nid: n.military for nid, n in self.nations.items()}
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

    # ----------------------------------------------------------------- clock
    def _hours_now(self) -> float:
        return self.tick_no * self.hpt

    def _fm(self) -> float:
        """1tick = 何ヶ月分か（月次レートのスカラー化、上限1）。"""
        return TC.frac(self.hpt, TC.HOURS_PER_MONTH)

    def _fy(self) -> float:
        """1tick = 何年分か（年率レートの複利化用）。"""
        return self.hpt / TC.HOURS_PER_YEAR

    def _alpha(self, tau_h: float) -> float:
        return TC.alpha(self.hpt, tau_h)

    def _hazard(self, p_month: float) -> float:
        return TC.hazard(self.hpt, p_month)

    def _ticks_for(self, hours: float) -> int:
        return TC.ticks_for(hours, self.hpt)

    def _clock_step(self) -> None:
        """実時間で走る緩和過程: 海峡スロットルと市場の恐怖プレミアム。"""
        for cp in self.chokepoints.values():
            target = 1.0 if cp.closed else 0.0
            tau = TC.REROUTE_TAU if cp.closed else TC.REOPEN_TAU
            cp.throttle += (target - cp.throttle) * self._alpha(tau)
        decay = math.exp(-self.hpt / TC.FEAR_TAU)
        for c in self._fear:
            self._fear[c] *= decay

    def _price_ref(self, window_h: float) -> dict[str, float]:
        """window時間前の時点の価格（履歴から最近傍）。"""
        now = self._hours_now()
        ref = None
        for hour, prices in reversed(self._price_hist):
            if hour <= now - window_h:
                ref = prices
                break
        return ref if ref is not None else (self._price_hist[0][1] if self._price_hist else dict(self.prices))

    def _process_pending(self) -> None:
        """実時間の遅延が満ちた予約（動員完了・同盟参戦）を消化する。
        決定論のため (due, seq) の順で処理する。"""
        t = self.tick_no
        due_wars = sorted([p for p in self._pending_wars if p["due"] <= t],
                          key=lambda p: (p["due"], p["seq"]))
        if due_wars:
            self._pending_wars = [p for p in self._pending_wars if p["due"] > t]
        for p in due_wars:
            a, b = p["a"], p["b"]
            na, nb = self.nations.get(a), self.nations.get(b)
            if na is None or nb is None or a in nb.at_war_with:
                continue
            if na.collapsed or nb.collapsed:
                continue
            tension = self._pair_tension(a, b)
            if tension < TC.WAR_TENSION_RELAPSE:
                self.event_log.emit(
                    t, "stand_down",
                    f"{na.name} と {nb.name} は緊張が退いたため動員を解除した",
                    targets=[a, b], parents=[p["ev"]],
                    data={"tension": round(tension, 3)},
                )
                continue
            self._start_war(a, b, tension, cause=p["ev"])

        due_ally = sorted([p for p in self._pending_alliance if p["due"] <= t],
                          key=lambda p: (p["due"], p["seq"]))
        if due_ally:
            self._pending_alliance = [p for p in self._pending_alliance if p["due"] > t]
        for p in due_ally:
            self._alliance_activation(p["a"], p["b"], p["war_ev"], only=p["x"],
                                      trust_at_decision=p.get("trust"))

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
                # 期待効果: 市場は物理的不足の前にニュースへ反応する
                comms = {r.commodity.value for r in self.spec.routes if cp.name in r.chokepoints}
                for c in comms:
                    self._fear[c] = min(TC.FEAR_CAP, self._fear[c] + TC.FEAR_JUMP)
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
                self.temp_effects.append(
                    TempEffect(self.tick_no + self._ticks_for(6.0 * TC.HOURS_PER_MONTH), nid, "food", 0.4))
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
        self._export_flow = {}
        for c in self._wants_total:
            self._wants_total[c] = 0.0
            self._blocked_wants[c] = 0.0
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
        self._clock_step()          # 実時間緩和: スロットル・恐怖プレミアム
        self._process_pending()     # 動員完了・同盟参戦の遅延消化
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
        # 次tickのリチャードソン反応用に今tick末の軍事力を記録
        self._mil_prev = {nid: n.military for nid, n in self.nations.items()}
        self._snapshot()

    # ------------------------------------------------------------- tech layer
    def _tech_step(self) -> None:
        """Paper-level innovations mature into prototypes, then diffuse to
        nations according to their absorptive (research) capacity).
        カタログの unlock_tick は「月」で定義されており、実時間に換算して判定する。"""
        t = self.tick_no
        fm = self._fm()
        hours_now = self._hours_now()
        for tech in CATALOG:
            if not self.tech_unlocked[tech.id] and hours_now >= tech.unlock_tick * TC.HOURS_PER_MONTH:
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
                if self.rng.random() < self._hazard(0.08 * self._research_capacity(nid)):
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
        # 宗教系技術の採用はイデオロギー圏の成立でもある（創発。割付ではない）
        if tech_id == "ai_religion":
            nat.ideology = "ai_cult"
        elif tech_id == "techno_nationalism":
            nat.ideology = "techno_nationalist"
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
        """Resolve import needs through routes; chokepoint closure throttles capacity.

        流量は月次レート×(1tickの月数)。封鎖は即時に輸送力を殺さない:
        航行中の船はまだ到着するので throttle は REROUTE_TAU で漸増する。"""
        t = self.tick_no
        fm = self._fm()
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
            want = need * route.share * fm * (1.3 if imp.budget.get("stockpile", 0) > 0.3 else 1.0)
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
            route_throttle = 0.0
            for cpn in route.chokepoints:
                cp = self.chokepoints.get(cpn)
                if cp and cp.throttle > 0.05:
                    capacity *= 1.0 - (1.0 - TC.CHOKE_MIN_CAPACITY) * cp.throttle
                    route_throttle = max(route_throttle, cp.throttle)
                    blocked.append(cpn)
            # 市場の裁定材料: この航路需要の何割が封鎖に曝されているか
            self._wants_total[route.commodity.value] += want
            self._blocked_wants[route.commodity.value] += want * route_throttle
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
                self._tick_throttled_note(route, blocked, capacity)
            # exporter earns, importer receives (flow already includes fm).
            # 輸出はGDP水準にではなく成長率に効かせる（macroで集計）:
            # 大口輸出国は最大+2.4%/年の成長ボーナス。水準加算だと
            # 資源輸出国が複利で爆発する
            self._export_flow[route.exporter] = self._export_flow.get(route.exporter, 0.0) + flow
            imp.stocks[route.commodity.value] += flow
            flow_val = flow * self.prices[route.commodity.value]
            self._ca_exports[route.exporter] = self._ca_exports.get(route.exporter, 0.0) + flow_val
            self._ca_imports[route.importer] = self._ca_imports.get(route.importer, 0.0) + flow_val
            failed = max(0.0, want - flow)
            if failed > 0:
                unmet[route.commodity.value] += failed

        return flows, unmet

    def _tick_throttled_note(self, route, blocked, capacity) -> None:
        """封鎖された航路の通知。高頻度時計では毎時間鳴らさない（週次）。"""
        key = (route.importer, route.exporter, route.commodity.value, tuple(blocked))
        now = self._hours_now()
        last = self._tt_last.get(key)
        if last is not None and now - last < TC.EVENT_HOURLY_GATE:
            return
        self._tt_last[key] = now
        imp, exp = self.nations[route.importer], self.nations[route.exporter]
        ev = self.event_log.emit(
            self.tick_no, "trade_throttled",
            f"{imp.name}←{exp.name} の{route.commodity.value}航路、{','.join(blocked)} 封鎖で輸送力激減",
            targets=[route.importer, route.exporter],
            parents=[self._cp_cause[n] for n in blocked if n in self._cp_cause],
            data={"routes": route.model_dump(), "capacity": round(capacity, 3)},
        )
        self._tick_throttled.append(ev.id)

    # ----------------------------------------------------------------- market
    def _market(self, supply, flows, unmet: dict[str, float]) -> None:
        t = self.tick_no
        self.last_prices = dict(self.prices)
        ref_day = self._price_ref(TC.SPIKE_WINDOW_H)
        a_price = self._alpha(TC.PRICE_TAU)
        for c in Commodity:
            world_demand = len(self.nations) * CONSUMPTION[c.value]
            world_supply = sum(supply[nid][c.value] for nid in self.nations)
            scarcity = max(0.0, world_demand - world_supply) / world_demand      # persistent level
            # 遮断の強度は「航路需要に対するfailure率」で測る。世界需要で割ると
            # 地域危機が全部薄まってしまう（16カ国でも176カ国でも同じ問題）。
            routed = self._wants_total[c.value]
            shock = min(1.0, unmet[c.value] / routed) if routed > 1e-9 else 0.0
            block_share = min(1.0, self._blocked_wants[c.value] / routed) if routed > 1e-9 else 0.0
            # 期待効果: 封鎖が続く限りリスクプレミアムは床を持つ
            fear_eff = max(self._fear[c.value], TC.FEAR_JUMP * block_share)
            target = (1.0 + 1.5 * scarcity + 2.0 * shock) * (1.0 + fear_eff)
            if self.wars and c is Commodity.ENERGY:
                target *= 1.15
            self.prices[c.value] = min(4.0, max(0.5, (1.0 - a_price) * self.prices[c.value] + a_price * target))
            # 急騰判定は「1日前比」で（高頻度時計で毎tick鳴らさない）
            ref = ref_day.get(c.value, self.last_prices[c.value])
            now = self._hours_now()
            if (self.prices[c.value] / max(0.01, ref) > TC.SPIKE_RATIO
                    and now - self._spike_last.get(c.value, -1e9) >= TC.SPIKE_WINDOW_H):
                self._spike_last[c.value] = now
                self.event_log.emit(
                    t, "price_spike",
                    f"{c.value} の国際価格が急騰 ({ref:.2f}→{self.prices[c.value]:.2f})",
                    parents=list(self._tick_throttled),
                    data={"commodity": c.value, "from": round(ref, 3), "to": self.prices[c.value]},
                )
        self._price_hist.append((self._hours_now(), dict(self.prices)))
        if len(self._price_hist) > 4000:
            del self._price_hist[:2000]

    # ------------------------------------------------------------- consumption
    CAUSAL_TYPES = ("trade_throttled", "disinfo", "god_intervention", "sanction",
                    "threat", "war_start", "price_spike", "shortage",
                    "mobilization", "stand_down")

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
        fm = self._fm()
        for nid in sorted(self.nations):
            nat = self.nations[nid]
            if nat.collapsed:
                nat.collapse_ticks = max(0, nat.collapse_ticks - 1)
                if nat.collapse_ticks == 0:
                    nat.collapsed = False
                    nat.stability = 35.0
                continue
            for c in Commodity:
                nat.stocks[c.value] += supply[nid][c.value] * fm
                use = CONSUMPTION[c.value] * fm * (0.85 if (nat.rationing and c is Commodity.FOOD) else 1.0)
                nat.stocks[c.value] -= use
                if nat.stocks[c.value] < 0:
                    deficit = -nat.stocks[c.value]
                    nat.stocks[c.value] = 0.0
                    # 深刻度 = max(瞬時の不足率, 慢性化ランプ(上限0.3))。
                    # 全供給断は即座に致命的(不足率1.0)、慢性的な部分不足は
                    # 月を重ねるほど深く刺さるが、急性と同じにはならない。
                    key = (nid, c.value)
                    self._shortage_since[key] = self._shortage_since.get(key, 0.0) + fm
                    severity = max(min(1.0, deficit / max(use, 1e-9)),
                                   min(TC.CHRONIC_SHORTAGE_CAP, self._shortage_since[key]))
                    stab_hit = SHORTAGE_STABILITY_HIT[c.value] * severity * fm
                    if nat.regime == "autocracy":
                        stab_hit *= 0.8   # 抑圧機構が社会的不満を緩衝する
                    nat.stability -= stab_hit
                    self._shortages[nid] = self._shortages.get(nid, 0.0) + severity * fm
                    # 0.3を上回って横切った瞬間に一度だけ通知する
                    if severity >= 0.3 > self._last_sev.get(key, 0.0):
                        self.event_log.emit(
                            t, "shortage",
                            f"{nat.name} で {c.value} が深刻な不足。備蓄底をつき社会不安が拡大",
                            actor=nid, targets=[nid],
                            parents=self._causal_parents(nid),
                            data={"commodity": c.value, "severity": round(severity, 2)},
                        )
                    self._last_sev[key] = severity
                elif nat.stocks[c.value] > 0.05:
                    self._shortage_since.pop((nid, c.value), None)
                    self._last_sev.pop((nid, c.value), None)

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
        memory = self._bilateral_memory(nid)
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
            last_decisions=self._decision_history.get(nid, []),
            memory=memory,
        )

    MEMORY_TYPES = ("threat", "sanction", "alliance_formed", "alliance_activation",
                    "trade_pact", "war_start", "war_end", "peace_settlement",
                    "arms_control", "collective_sanction", "disinfo")

    def _bilateral_memory(self, nid: str, limit: int = 20) -> list[dict]:
        """この国が当事者である双方向の外交・紛争エピソード（直近順）。
        「過去の会話と経緯」の記憶: 相手が誰で何をしたか/されたか。
        窓は実時間で定義する（直近5年）— 時計モードによらず政府は歳月で覚える。"""
        cutoff = self.tick_no - self._ticks_for(60.0 * TC.HOURS_PER_MONTH)
        out: list[dict] = []
        for rec in reversed(self.event_log.records):
            if rec.tick < cutoff:
                break
            if rec.type not in self.MEMORY_TYPES:
                continue
            if rec.actor != nid and nid not in rec.targets:
                continue
            others = [x for x in ([rec.actor] if rec.actor else []) + rec.targets if x != nid]
            if not others:
                continue
            out.append({
                "tick": rec.tick, "with": sorted(set(others)),
                "event": rec.type, "text": rec.text,
                "i_acted": rec.actor == nid,
            })
            if len(out) >= limit:
                break
        return out

    def _decide(self) -> dict[str, Decisions]:
        """国家の意思決定。decision_every_hours が設定された世界では、
        決定点と決定点の間は前回の決定（ standing policy ）を継続適用する。
        政府は毎時間閣議を開かない。"""
        now = self._hours_now()
        if self._cached_decisions is not None and self._dec_every is not None \
                and now < self._next_dec_hour - 1e-9:
            self._decisions_fresh = False
            return self._cached_decisions
        elapsed = max(self.hpt, now - self._last_dec_hour) if self._last_dec_hour > 0 else self.hpt
        out: dict[str, Decisions] = {}
        for nid in sorted(self.nations):
            policy = self.policies.get(nid) or self.policies.get("*")
            view = self.nation_view(nid)
            out[nid] = policy.decide(view)
        self._cached_decisions = out
        self._decisions_fresh = True
        self._dec_elapsed_hours = elapsed
        self._last_dec_hour = now
        if self._dec_every:
            self._next_dec_hour = (int(now // self._dec_every) + 1) * self._dec_every
        return out

    def _apply_decisions(self, decisions: dict[str, Decisions]) -> None:
        t = self.tick_no
        # 段階的効果（信頼改善・貿易協定等）は「今回の決定周期が何ヶ月分か」で効く
        dm = self._dec_elapsed_hours / TC.HOURS_PER_MONTH
        fresh = self._decisions_fresh
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
            if fresh:
                hist = self._decision_history.setdefault(nid, [])
                hist.append({"tick": t, **self._last_decision[nid]})
                # 政策史は実時間で保持する: 直近24ヶ月(上限12件)。
                # 時計モード(週次閣議でも月次でも)によらない
                cutoff = t - self._ticks_for(24.0 * TC.HOURS_PER_MONTH)
                hist[:] = [h for h in hist if h["tick"] >= cutoff][-12:]
            if nat.propaganda and not d.propaganda:
                nat.propaganda = False
            elif d.propaganda:
                nat.propaganda = True
                nat.approval = min(100.0, nat.approval + 3.0 * dm)
                nat.paranoia = min(1.0, nat.paranoia + 0.01 * dm)
            if fresh:
                self.event_log.emit(
                    t, "policy_shift",
                    f"{nat.name}: {d.rationale}",
                    actor=nid, targets=[nid],
                    data={"posture": d.military_posture, "rationing": d.rationing,
                          "propaganda": d.propaganda, "budget": d.budget},
                )

        # diplomacy, in two passes so offers see a consistent world.
        # 外交行動は決定点でのみ発生する（standing policy の再適用ではない）。
        if not fresh:
            return
        for nid in sorted(decisions):
            nat, d = self.nations[nid], decisions[nid]
            for act in d.diplomacy:
                other = self.nations.get(act.target)
                if other is None or other.id == nid:
                    continue
                if act.kind == "improve":
                    nat.trust[act.target] = min(100.0, nat.trust[act.target] + 4.0 * dm)
                    other.trust[nid] = min(100.0, other.trust[nid] + 2.0 * dm)
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
                    nat.trust[act.target] = min(100.0, nat.trust[act.target] + 3.0 * dm)
                    other.trust[nid] = min(100.0, other.trust[nid] + 3.0 * dm)

    # ---------------------------------------------------------------- conflict
    def _conflict(self) -> None:
        t = self.tick_no
        fm = self._fm()
        # ongoing wars: attrition（軍事消耗・疲弊は月次レートを実時間で）。
        # 戦争はスカラーではなく強度を持つ: 軍事偏重と期間で限定→総力戦へ
        # エスカレーションし、消耗・経済損失・人的被害が強度でスケールする
        for a, b in list(self.wars):
            na, nb = self.nations[a], self.nations[b]
            inten = self._war_intensity.get((a, b), 1.0)
            inten = min(3.0, inten + 0.03 * fm * (na.doctrine_militarism + nb.doctrine_militarism))
            self._war_intensity[(a, b)] = inten
            dmg_a = (2.0 + self.rng.random() * 3.0) * fm * inten
            dmg_b = (2.0 + self.rng.random() * 3.0) * fm * inten
            na.military -= dmg_b
            nb.military -= dmg_a
            # 民主政体は人的被害に敏感（疲弊が強度で増幅）
            sens_a = 1.2 if na.regime == "democracy" else 1.0
            sens_b = 1.2 if nb.regime == "democracy" else 1.0
            na.war_exhaustion += 4.0 * fm * inten * sens_a
            nb.war_exhaustion += 4.0 * fm * inten * sens_b
            for n, other_pop in ((na, "a"), (nb, "b")):
                n.gdp *= 1.0 - 0.003 * fm * inten
                cas = 0.001 * inten * fm * n.population_m * 0.01   # 人口の~0.001%/月@強度1
                n.population_m = max(0.1, n.population_m - cas)
                self._war_casualties[n.id] = self._war_casualties.get(n.id, 0.0) + cas
            # 報復性が高い政府は疲弊に耐えて戦い続ける（降伏閾値が伸びる）
            lim_a = 40.0 * (1.0 + 0.5 * na.doctrine_vengeance)
            lim_b = 40.0 * (1.0 + 0.5 * nb.doctrine_vengeance)
            # 交渉による終戦（Fearon型）: 力の不均衡と疲弊が深いほど講和が成立す
            # る — 消耗衰亡とは別の終わり方
            gap = abs(na.military - nb.military) / max(1.0, na.military + nb.military)
            p_settle = (0.10 + 0.15 * gap
                        + 0.002 * (na.war_exhaustion + nb.war_exhaustion)
                        + 0.05 * (inten - 1.0))
            if self.rng.random() < self._hazard(p_settle):
                self.wars.remove((a, b))
                self._war_intensity.pop((a, b), None)
                na.at_war_with.remove(b)
                nb.at_war_with.remove(a)
                na.trust[b] = min(100.0, na.trust.get(b, 0.0) + 5.0)
                nb.trust[a] = min(100.0, nb.trust.get(a, 0.0) + 5.0)
                self.event_log.emit(
                    t, "peace_settlement",
                    f"{na.name} と {nb.name} が交渉で講和（力の差と疲弊が合意を生んだ）",
                    targets=[a, b],
                    data={"negotiated": True, "power_gap": round(gap, 3)},
                )
                continue
            # 軍備管理: 核保有国同士の消耗戦は条約で凍結されうる
            both_nuke = "nuclear" in na.factors and "nuclear" in nb.factors
            if both_nuke and na.war_exhaustion > 12 and nb.war_exhaustion > 12 \
                    and self.rng.random() < self._hazard(0.12):
                self.wars.remove((a, b))
                self._war_intensity.pop((a, b), None)
                na.at_war_with.remove(b)
                nb.at_war_with.remove(a)
                for n in (na, nb):
                    n.military *= 0.8
                    n.war_exhaustion = max(0.0, n.war_exhaustion - 10.0)
                na.trust[b] = min(100.0, na.trust.get(b, 0.0) + 8.0)
                nb.trust[a] = min(100.0, nb.trust.get(a, 0.0) + 8.0)
                self.event_log.emit(
                    t, "arms_control",
                    f"{na.name} と {nb.name} が軍備管理条約を締結し戦争を凍結（軍縮と信頼回復）",
                    targets=[a, b], data={"military_cut": 0.2},
                )
                continue
            if na.war_exhaustion > lim_a or nb.war_exhaustion > lim_b \
                    or self.rng.random() < self._hazard(0.05):
                self.wars.remove((a, b))
                self._war_intensity.pop((a, b), None)
                na.at_war_with.remove(b)
                nb.at_war_with.remove(a)
                self.event_log.emit(
                    t, "war_end", f"{na.name} と {nb.name} の戦争が終結（疲弊）",
                    targets=[a, b], data={"exhaustion_a": na.war_exhaustion, "exhaustion_b": nb.war_exhaustion},
                )
            continue

        # new skirmishes from tension — ただし即時開戦しない:
        # 緊張が閾値を超えると「動員」が始まり、実時間の所要時間
        # （~4-30日、最頻10日）を経て初めて開戦判定が走る。その間に緊張が
        # 引けば動員は解除される（stand_down）。
        ids = sorted(self.nations)
        pending_pairs = {(p["a"], p["b"]) for p in self._pending_wars} | \
                        {(p["b"], p["a"]) for p in self._pending_wars}
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if b in self.nations[a].at_war_with:
                    continue
                na, nb = self.nations[a], self.nations[b]
                if na.collapsed or nb.collapsed:
                    continue
                if (a, b) in pending_pairs:
                    continue
                tension = self._pair_tension(a, b)
                det = self._deterrence(a, b) or self._deterrence(b, a)
                if det is not None:
                    tension *= det
                if tension > 0.55 and self.rng.random() < self._hazard(tension - 0.55):
                    self._enqueue_mobilization(a, b, tension)
                    pending_pairs.add((a, b))
                    pending_pairs.add((b, a))

    def _pair_tension(self, a: str, b: str) -> float:
        na, nb = self.nations[a], self.nations[b]
        rivalry_bonus = 0.15 if self._resource_dispute(a, b) else 0.0
        # 思想項: 修正主義が緊張を煽り、軍事偏重が它を増幅し、
        # 危機許容度（挑発に耐える度合い）が緊張を下げる
        doctrinal = (0.20 * max(na.doctrine_revisionism, nb.doctrine_revisionism)
                     + 0.10 * (na.doctrine_militarism + nb.doctrine_militarism) * 0.5
                     - 0.12 * (na.doctrine_risk + nb.doctrine_risk) * 0.5)
        # イデオロギー摩擦: 異なる圏の間は緊張が、同じ圏の内側は結束が効く
        if na.ideology != "secular" and nb.ideology != "secular":
            doctrinal += -0.06 if na.ideology == nb.ideology else 0.12
        # 民主的平和（実証的規則性）: 民主政体同士は武力紛争に至りにくい
        if na.regime == "democracy" and nb.regime == "democracy":
            doctrinal -= 0.12
        return (
            0.5 * (na.aggression + nb.aggression) * self.god.ai_aggression * 0.5
            + max(0.0, -na.trust.get(b, 0.0)) / 150.0
            + 0.1 * (na.paranoia + nb.paranoia)
            + rivalry_bonus
            + doctrinal
        )

    def _enqueue_mobilization(self, a: str, b: str, tension: float) -> None:
        """開戦への梯子: 動員は実時間がかかる。所要時間は三角形分布で決める。"""
        t = self.tick_no
        hours = self.rng.triangular(TC.MOBILIZE_MIN_H, TC.MOBILIZE_MAX_H, TC.MOBILIZE_MODE_H)
        due = t + self._ticks_for(hours)
        na, nb = self.nations[a], self.nations[b]
        ev = self.event_log.emit(
            t, "mobilization",
            f"{na.name} と {nb.name} の緊張が臨界を超え、双方が動員を開始（開戦まで最短 {TC.MOBILIZE_MIN_H:.0f}時間）",
            targets=[a, b],
            parents=[r.id for r in self.event_log.records[-10:]
                     if r.type in ("threat", "sanction", "shortage", "disinfo")
                     and (r.actor in (a, b) or a in r.targets or b in r.targets)],
            data={"tension": round(tension, 3), "eta_hours": round(hours, 1)},
        )
        self._seq += 1
        self._pending_wars.append({"a": a, "b": b, "due": due, "seq": self._seq, "ev": ev.id})

    def _start_war(self, a: str, b: str, tension: float, cause: Optional[str] = None) -> None:
        t = self.tick_no
        na, nb = self.nations[a], self.nations[b]
        self.wars.append((a, b))
        na.at_war_with.append(b)
        nb.at_war_with.append(a)
        self._war_intensity[(a, b)] = 1.0      # 限定戦争として開始
        parents = [cause] if cause else []
        parents += [r.id for r in self.event_log.records[-10:]
                    if r.type in ("threat", "sanction", "shortage", "disinfo", "mobilization")
                    and (r.actor in (a, b) or a in r.targets or b in r.targets)]
        ideological = (na.ideology != "secular" and nb.ideology != "secular"
                       and na.ideology != nb.ideology)
        self.event_log.emit(
            t, "war_start",
            (f"{na.name} と {nb.name} の間で武力衝突が勃発"
             + ("（イデオロギー圏の対立が背景）" if ideological else "")),
            targets=[a, b], parents=parents,
            data={"tension": round(tension, 3), "ideological": ideological},
        )
        # 相互防衛: 両側の同盟国が協議の末、条約を履行するか（遅延あり）
        wev = self.event_log.records[-1]
        self._schedule_alliance(b, a, wev)
        self._schedule_alliance(a, b, wev)

    def _schedule_alliance(self, a: str, b: str, war_ev) -> None:
        """bの同盟国は即座でなく、協議(~1日-1週間)の後に参戦を決める。"""
        for x in sorted(self.nations):
            if x in (a, b) or a in self.nations[x].at_war_with:
                continue
            xnat = self.nations[x]
            if b not in xnat.alliances or xnat.collapsed:
                continue
            trust = xnat.trust.get(b, 0.0)
            if trust < 35.0:
                continue
            hours = self.rng.uniform(TC.ALLIANCE_MIN_H, TC.ALLIANCE_MAX_H)
            self._seq += 1
            self._pending_alliance.append({
                "a": a, "b": b, "x": x, "trust": trust,
                "due": self.tick_no + self._ticks_for(hours),
                "seq": self._seq, "war_ev": war_ev,
            })

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
        pass-through + god's world rate hike.
        自国通貨建て債務が厚い国は通貨発行で返済できるため、信用リスク
        プレミアムの吹き上がりが抑えられる（主要国がデフォルトしない理由）。"""
        premium = (100.0 - nat.credibility) / 100.0 * 0.10 * (1.0 - 0.7 * nat.local_debt_share)
        infl_pass = min(0.15, max(0.0, nat.inflation - 0.05) * 2.0)
        return float(min(0.60, max(0.02, 0.02 + premium + infl_pass + self.god.world_rate_hike)))

    def _fiscal_step(self, nid: str, nat) -> None:
        t = self.tick_no
        fm = self._fm()
        at_war = bool(nat.at_war_with)
        mil = nat.budget.get("military", 0.2)
        wel = nat.budget.get("welfare", 0.3)
        # fiscal flows (fraction of GDP) — annual rates scaled by elapsed time
        revenue = self.TAX_RATE * self._fy()
        spending = (self.BASE_SPEND + 0.30 * mil * (2.0 if at_war else 1.0) + 0.10 * wel) * self._fy()
        rate = self._bond_rate(nat)
        interest = (nat.debt_gdp / 100.0) * rate * self._fy()
        deficit = spending + interest - revenue
        nat.debt_gdp = max(0.0, nat.debt_gdp + deficit * 100.0)

        # 自国通貨建て債務（現実の校正）: 石油危機のような貿易ショックで
        # 主要国がデフォルトしないのは、自国通貨で借りているからである。
        # 金利負担の強制力は外貨建て分にのみ働き、自国通貨分の赤字は
        # 通貨発行（インフレ）で吸収される
        eff_interest = interest * (1.0 - 0.8 * nat.local_debt_share)
        if deficit > 0 and nat.debt_gdp > 120.0:
            nat.inflation = min(1.0, nat.inflation
                                + 0.5 * deficit * nat.local_debt_share)

        # credibility dynamics (high debt alone erodes credit only slowly:
        # credible high-debt states like Japan must stay serviceable)
        nat.credibility = min(100.0, nat.credibility + 1.5 * fm)
        if nat.debt_gdp > 160.0:
            nat.credibility -= 2.5 * fm
        if nat.inflation > 0.10:
            nat.credibility -= 2.0 * fm
        nat.credibility = max(0.0, nat.credibility)
        if nat.default_cooldown > 0:
            nat.default_cooldown -= 1
            return

        # sovereign default check（月次ハザードを実時間に変換して判定）。
        # 外貨準備が厚い間は防衛できる — 破綻は「利払い負担×準備枯渇」の複合
        if eff_interest > self.DEFAULT_SAFE:
            forced = eff_interest > self.DEFAULT_FORCE
            p = 1.0 if forced else 0.05 + (eff_interest - self.DEFAULT_SAFE) * 15.0
            if nat.fx_reserves >= 2.0:
                p *= 0.35          # 準備防衛が効いている
                nat.fx_reserves -= eff_interest * 40.0   # 防衛コストは準備を削る
            if self.rng.random() < self._hazard(p):
                self._sovereign_default(nid, nat, rate)

    def _sovereign_default(self, nid: str, nat, rate: float) -> None:
        t = self.tick_no
        nat.defaults += 1
        nat.default_cooldown = self._ticks_for(12.0 * TC.HOURS_PER_MONTH)  # restructuring moratorium
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

    def _alliance_activation(self, a: str, b: str, war_ev, only: Optional[str] = None,
                             trust_at_decision: Optional[float] = None) -> None:
        """相互防衛: bの同盟国が信頼に応じて参戦する（連鎖の深さは1に制限）。
        only=None なら即時に全候補を判定（互換用）。only指定ならその1国のみ。"""
        t = self.tick_no
        for x in sorted(self.nations):
            if only is not None and x != only:
                continue
            if x in (a, b) or a in self.nations[x].at_war_with:
                continue
            xnat = self.nations[x]
            if b not in xnat.alliances or xnat.collapsed:
                continue
            trust = xnat.trust.get(b, 0.0)
            if trust_at_decision is not None:
                # 協議時に下した判断を優先しつつ、現在の信頼も条件とする
                if min(trust, trust_at_decision) < 35.0:
                    continue
            elif trust < 35.0:
                continue
            # 同盟遵守度: 条約は信任の関数でもある（高遵守国ほど履行する）
            p_act = 0.4 * (trust / 100.0) * xnat.doctrine_treaty_fidelity
            if self.rng.random() < p_act:
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
        """戦略因子の解決: policyのdoctrine表明に従い取得進捗/放棄を遷移させる。
        acquisition_ticks は「月」単位の所要期間。"""
        t = self.tick_no
        fm = self._fm()
        for nid in sorted(self.nations):
            nat = self.nations[nid]
            if nat.collapsed:
                continue
            for fid, spec in FACTORS_BY_ID.items():
                holds = fid in nat.factors
                doctrine = nat.doctrines.get(fid, "hold")
                if not holds and doctrine == "pursue" and self._factor_prereq_ok(nid, spec):
                    nat.factor_progress[fid] = nat.factor_progress.get(fid, 0.0) + 100.0 / spec.acquisition_ticks * fm
                    nat.gdp *= 1.0 - spec.pursuit_cost_gdp * fm
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
                    self._abandon_votes[key] = self._abandon_votes.get(key, 0.0) + self._dec_elapsed_hours
                    if self._abandon_votes[key] >= 3.0 * TC.HOURS_PER_MONTH:
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
                        nat.factor_progress[fid] = max(0.0, nat.factor_progress[fid] - 100.0 / (spec.acquisition_ticks * 2) * fm)
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
        """a→bの開戦意欲への抑止係数。None=抑止なし。
        攻撃側(a)の核態勢が抑止の効きを変える: counterforce（核は使えると
        信じる態勢）は抑止を侵食し、NFU（不先使用）は安定を強める。"""
        spec = FACTORS_BY_ID.get("nuclear")
        if not spec:
            return None
        posture_mult = {"counterforce": 0.75, "mad": 1.0, "nfu": 1.25}.get(
            self.nations[a].nuclear_posture, 1.0)
        a_holds = "nuclear" in self.nations[a].factors
        b_holds = "nuclear" in self.nations[b].factors
        if a_holds and b_holds:
            return min(1.0, spec.deterrence_mutual * posture_mult)
        if b_holds and not a_holds:
            return min(1.0, spec.deterrence_vs_nonholder * posture_mult)
        # 核傘: 保護国の抑止を係数付きで継承する
        umb = FACTORS_BY_ID.get("nuclear_umbrella")
        if umb and "nuclear_umbrella" in self.nations[b].factors and not a_holds:
            return min(1.0, spec.deterrence_vs_nonholder * (1.0 + umb.umbrella_deterrence) / 2.0 * posture_mult)
        return None

    def _macro_update(self) -> None:
        t = self.tick_no
        fm = self._fm()
        fy = self._fy()
        ref_month = self._price_ref(TC.HOURS_PER_MONTH)
        for nid in sorted(self.nations):
            nat = self.nations[nid]
            if nat.collapsed:
                continue
            spec = self._specs[nid]
            at_war_now = bool(nat.at_war_with)
            # inflation from import price exposure（通貨安は輸入インフレを増幅）。
            # pass-throughは「1ヶ月前の価格比」で測る（毎tick比ではない）。
            # 輸入ウェイトは全商品の依存度の和だが、CPIに占める輸入の上限
            # (0.35)で正規化する — 単純和は二重計上になり、食料危機が
            # インフレ死亡らせんに化ける。
            weights: dict[Commodity, float] = {}
            for c in Commodity:
                dep = self._import_dependency(nid, c)
                if dep > 0:
                    weights[c] = 0.25 * dep
            wsum = sum(weights.values())
            infl_delta = 0.0
            if wsum > 0.0:
                scale = min(1.0, IMPORT_INFLATION_CAP / wsum)
                infl_delta = sum(
                    w * scale * (self.prices[c.value] / max(0.01, ref_month.get(c.value, self.prices[c.value])) - 1.0)
                    for c, w in weights.items())
                infl_delta *= 1.0 / max(0.7, nat.fx)
            a_infl = self._alpha(TC.INFLATION_TAU)
            nat.inflation = max(-0.05, min(1.0, (1.0 - a_infl) * nat.inflation + a_infl * 0.02 + infl_delta))
            # growth — 年率として複利で刻む。輸出フローは成長ボーナスとして
            # 効かせる（大口輸出国で最大+2.4%/年: 資源ブームの表現）
            finance_units = sum(1 for r in self.nation_resources[nid] if r is ResourceKind.FINANCE)
            export_flow_m = self._export_flow.get(nid, 0.0) / max(fm, 1e-9)
            growth = (0.02 + 0.002 * finance_units - nat.inflation * 0.6
                      + 0.003 * min(8.0, export_flow_m))
            # --- 労働: 失業率（生産ギャップ・戦争・福祉が決める） ---
            welfare_share = bud0 = nat.budget.get("welfare", 0.3)
            shortage_hits = self._shortages.get(nid, 0.0)
            u_target = (5.0 + max(0.0, 0.02 - growth) * 160.0 + (8.0 if at_war_now else 0.0)
                        + 5.0 * min(1.5, shortage_hits / 2.0)
                        - min(4.0, 6.0 * welfare_share))
            a_unemp = self._alpha(TC.UNEMPLOYMENT_TAU)
            nat.unemployment = min(45.0, max(2.0, nat.unemployment + (u_target - nat.unemployment) * a_unemp))
            growth -= max(0.0, nat.unemployment - 10.0) * 0.001          # 失業は生産を蝕む
            # --- 人口（年率） ---
            nat.population_m *= (1.0 + spec.population_growth) ** fy * (1.0 - (0.001 if at_war_now else 0.0) * fm)
            # --- インフラ投資（補助金シェアが蓄積、戦争は毀損） ---
            nat.infra = min(1.25, max(0.5, nat.infra + 0.004 * (nat.budget.get("subsidy", 0.25) * 2.2 - 0.7) * fm - (0.006 * fm if at_war_now else 0.0)))
            # --- 為替: 年率のインフレ差を実時間で ---
            world_inf = sum(o.inflation for o in self.nations.values()) / len(self.nations)
            fx_sens = 0.6
            drain_mult = 1.0
            for fid in nat.factors:
                fs = FACTORS_BY_ID.get(fid)
                if fs:
                    fx_sens *= fs.fx_stabilize
                    drain_mult *= fs.reserves_drain_mult
            nat.fx = min(3.0, max(0.3, nat.fx * (1.0 + fx_sens * (world_inf - nat.inflation) * fy)))
            # --- 経常収支と外貨準備 ---
            exp_val = self._ca_exports.get(nid, 0.0)
            imp_val = self._ca_imports.get(nid, 0.0)
            nat.ca_last = (exp_val - imp_val) / max(fy, 1e-9)   # 年率換算で見える化
            nat.fx_reserves = min(36.0, max(0.0, nat.fx_reserves + (exp_val - imp_val) * 0.02 * drain_mult))
            if nat.fx_reserves < 1.0:
                # 外貨準備枯渇: 輸入能力が落ち、スタグフレーションと政治的圧力
                growth -= 0.01
                nat.stability = max(0.0, nat.stability - 1.5 * fm)
                now = self._hours_now()
                if now - self._fxwarn_last.get(nid, -1e9) >= TC.HOURS_PER_MONTH:
                    self._fxwarn_last[nid] = now
                    self.event_log.emit(
                        t, "fx_crisis",
                        f"{nat.name} の外貨準備が枯渇（{nat.fx_reserves:.1f}ヶ月分）。輸入が絞られる",
                        actor=nid, targets=[nid], data={"reserves": round(nat.fx_reserves, 2)},
                    )
            # --- イデオロギー摩擦: 異なる圏への信頼は徐々に削れる ---
            if nat.ideology != "secular":
                worst, worst_trust = None, 100.0
                for o, onat in self.nations.items():
                    if o == nid or onat.ideology in ("secular", nat.ideology):
                        continue
                    if nat.trust.get(o, 20.0) < worst_trust:
                        worst, worst_trust = o, nat.trust.get(o, 20.0)
                if worst is not None:
                    nat.trust[worst] = max(-100.0, nat.trust[worst] - 0.3 * fm)
            # --- 安全保障ジレンマ: 信頼の低い大国の軍事優位が攻撃性を煽る ---
            rival_max = 0.0
            for o, onat in self.nations.items():
                if o == nid or onat.collapsed or nat.trust.get(o, 20.0) >= 15.0:
                    continue
                rival_max = max(rival_max, onat.military)
            if rival_max > nat.military * 1.2:
                nat.aggression = min(0.95, nat.aggression + 0.004 * fm)
                nat.paranoia = min(0.95, nat.paranoia + 0.003 * fm)

            # --- CO2: 化石エネルギー生産 × (1-実効再生比率) ---
            techs = self._techs_of(nid)
            renew = max(spec.energy_renew,
                        0.50 if "fusion" in techs else 0.35 if "space_solar" in techs else spec.energy_renew)
            nat.renew_eff = renew
            fossil_units = sum(1 for r in self.nation_resources[nid] if r in (ResourceKind.OIL, ResourceKind.GAS))
            co2_flow = fossil_units * (1.0 - renew)
            nat.co2_cum += co2_flow * fm
            self.global_co2 += co2_flow * fm
            if nat.stocks["chips"] <= 0.05:
                growth -= 0.01
                nat.military = max(0.0, nat.military - 1.0 * fm)
            if nat.stocks["space"] <= 0.05:
                # 軌道資産を失うと偵察・通信能力が落ち、軍事力が漸減する
                nat.military = max(0.0, nat.military - 1.5 * fm)
            bud = nat.budget
            mil_mult = self._tech_military_mult(nid)
            for fid in nat.factors:
                fspec = FACTORS_BY_ID.get(fid)
                if fspec:
                    mil_mult *= fspec.military_mult
            # リチャードソン軍拰方程数: 敵性大国の軍備増強に軍事偏重が反応する
            # （行動-反応の軍拡競争。敵の増加分に比例して自国の軍拡が加速する）
            rival_surge = 0.0
            for o, onat in self.nations.items():
                if o == nid or onat.collapsed or nat.trust.get(o, 20.0) >= 15.0:
                    continue
                rival_surge = max(rival_surge,
                                  onat.military - self._mil_prev.get(o, onat.military))
            richardson = 1.0 + nat.doctrine_militarism * min(1.0, rival_surge / 5.0)
            nat.military = min(150.0, nat.military + (2.0 * bud.get("military", 0.2)) * mil_mult * richardson * fm - (0.5 * fm if nid in [x for w in self.wars for x in w] else 0.0))
            nat.gdp *= (1.0 + growth) ** fy
            # --- 内戦・反乱: 統治崩壊領域（安定<15）で不平等/失業が不和を増幅 ---
            if nat.insurgency_cooldown > 0:
                nat.insurgency_cooldown -= 1
            elif nat.stability < 15.0:
                grievance = ((1.0 - nat.stability / 15.0)
                             * (0.5 + max(0.0, spec.gini - 0.40) * 3.0
                                + max(0.0, nat.unemployment - 12.0) * 0.02))
                if nat.regime == "autocracy":
                    grievance *= 1.3   # 抑圧は不平を地表から隠し、地下で増幅する
                if self.rng.random() < self._hazard(0.08 * grievance):
                    nat.insurgency_cooldown = self._ticks_for(12.0 * TC.HOURS_PER_MONTH)
                    nat.military *= 0.85
                    nat.stability = max(0.0, nat.stability - 6.0)
                    self.event_log.emit(
                        t, "insurgency",
                        f"{nat.name} で武装反乱が勃発（不安定と不平等の複合）。軍は鎮圧に割かれる",
                        actor=nid, targets=[nid],
                        parents=self._causal_parents(nid),
                        data={"grievance": round(grievance, 3), "gini": spec.gini},
                    )
            # stability & approval（月次レートを実時間で）
            t_stab, t_appr = self._tech_socio_drifts(nid)
            drift = 0.25 * (55.0 - nat.stability) * fm
            welfare = 3.0 * bud.get("welfare", 0.3) * fm
            gini_drag = max(0.0, spec.gini - 0.40) * 30.0 * fm     # 高不平等は社会を疲弊させる
            edu_lift = (spec.education - 0.5) * 0.8 * fm
            unemp_drag = max(0.0, nat.unemployment - 8.0) * 0.15 * fm
            nat.stability = max(0.0, min(100.0, nat.stability + drift + welfare - nat.inflation * 25.0 * fm - nat.war_exhaustion * 0.05 * fm - gini_drag - unemp_drag + t_stab * fm))
            nat.approval = max(0.0, min(100.0, nat.approval + (0.2 * (50.0 - nat.approval) + (1.0 if bud.get("welfare", 0) > 0.35 else -0.5) - unemp_drag * 0.5 + edu_lift + t_appr) * fm))
            nat.war_exhaustion = max(0.0, nat.war_exhaustion - 0.5 * fm)
            # ---------------------------------------------------- 選挙(民主政体)
            if nat.regime == "democracy":
                if nat.next_election < 0:
                    # 初回は政体確認から24-48ヶ月以内に設定(分散)
                    nat.next_election = t + self._ticks_for(
                        TC.HOURS_PER_MONTH * (12 + (hash(nid) % 25)))
                elif t >= nat.next_election:
                    nat.next_election = t + self._ticks_for(48.0 * TC.HOURS_PER_MONTH)
                    if nat.approval < 45.0:
                        # 政権交代: 新政権は公約で福祉を優先し、外交路線をリセット
                        nat.approval = min(100.0, nat.approval + 12.0)
                        nat.stability = min(100.0, nat.stability + 3.0)
                        nat.aggression = nat.base_aggression
                        nat.paranoia = nat.base_paranoia
                        bud = nat.budget
                        nat.budget = {"military": max(0.05, bud.get("military", 0.2) - 0.08),
                                      "welfare": min(0.6, bud.get("welfare", 0.3) + 0.12),
                                      "stockpile": bud.get("stockpile", 0.2),
                                      "subsidy": bud.get("subsidy", 0.3)}
                        self.event_log.emit(
                            t, "election_turnover",
                            f"{nat.name} で政権交代（不支持の与党が敗北）。新政権は福祉公約で出直す",
                            actor=nid, targets=[nid], data={"approval_before": round(nat.approval - 12.0, 1)},
                        )
                    else:
                        nat.approval = max(0.0, nat.approval - 5.0)   # 再選後の逆風
                        self.event_log.emit(
                            t, "election",
                            f"{nat.name} で与党が再選（政策的継続）",
                            actor=nid, targets=[nid], data={},
                        )
            # ---------------------------------------------------- fiscal block
            self._fiscal_step(nid, nat)
            # collapse check（不安定が実時間で継続した場合）
            if nat.stability < 12.0:
                nat.collapse_ticks += 1
                if nat.collapse_ticks >= self._collapse_need_ticks and not nat.collapsed:
                    nat.collapsed = True
                    nat.collapse_ticks = self._recover_ticks
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
                # 思想・ドクトリン（観測・UIから見える）
                "doctrine_risk": round(nat.doctrine_risk, 2),
                "doctrine_militarism": round(nat.doctrine_militarism, 2),
                "doctrine_revisionism": round(nat.doctrine_revisionism, 2),
                "doctrine_vengeance": round(nat.doctrine_vengeance, 2),
                "doctrine_treaty_fidelity": round(nat.doctrine_treaty_fidelity, 2),
                "nuclear_posture": nat.nuclear_posture,
                "ideology": nat.ideology,
                "regime": nat.regime,
                "next_election": nat.next_election,
                "war_casualties_m": round(self._war_casualties.get(nid, 0.0), 4),
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
            "war_casualties_m": round(sum(self._war_casualties.values()), 4),
        }
        snap = {
            "type": "tick", "tick": t, "hours": round((t + 1) * self.hpt, 1),
            "nations": nations_out,
            "prices": {k: round(v, 4) for k, v in self.prices.items()},
            "chokepoints": {name: cp.closed for name, cp in sorted(self.chokepoints.items())},
            "metrics": metrics,
            "events": [e.model_dump() for e in tick_events],
            "news": [e.text for e in tick_events if e.type in
                     ("war_start", "war_end", "collapse", "sanction", "alliance_formed",
                      "price_spike", "shortage", "disinfo", "god_intervention", "threat",
                      "mobilization")],
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
