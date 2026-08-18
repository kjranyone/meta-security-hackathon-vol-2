"""Deterministic rule-based nation bots: baseline policy layer."""
from __future__ import annotations

from .base import Decisions, DiplomaticAction, NationView


def _shortage(view: NationView) -> list[str]:
    me = view.me
    return [c for c in ("energy", "food", "chips") if me.get("stocks", {}).get(c, 99) < 2.0]


class HeuristicPolicy:
    """Simple survival doctrine: stockpile scarce goods, punish untrusted rivals,
    rally military when threatened, ride out the rest."""

    def _doctrines(self, view: NationView) -> dict:
        """戦略因子のheuristic doctrine: 脅威を受けていれば追求、崩壊寸前なら放棄。"""
        out = {}
        for fid in ("nuclear", "export_control"):
            holds = fid in view.me.get("factors", [])
            if holds:
                out[fid] = "abandon" if view.me.get("stability", 50) < 25 else "hold"
            elif fid == "nuclear":
                threatened = bool(view.me.get("at_war_with")) or view.me.get("stability", 50) < 40
                out[fid] = "pursue" if threatened else "hold"
            else:  # export_control: 製裁を受けている・大国・戦時は加盟へ
                sanctioned = any(r.get("sanction") for r in view.relations.values())
                big = view.me.get("gdp", 0.0) > 1.0
                war = bool(view.me.get("at_war_with"))
                out[fid] = "pursue" if (sanctioned or big or war) else "hold"
        return out

    def decide(self, view: NationView) -> Decisions:
        me = view.me
        short = _shortage(view)
        at_war = bool(me.get("at_war_with"))
        stability = me.get("stability", 50.0)
        inflation = me.get("inflation", 0.02)
        aggression = me.get("aggression", 0.3)

        budget = {"military": 0.2, "welfare": 0.3, "stockpile": 0.2, "subsidy": 0.3}
        if short:
            budget["stockpile"] += 0.2
            budget["subsidy"] -= 0.1
        if at_war or aggression > 0.6:
            budget["military"] += 0.2
            budget["welfare"] -= 0.1
        if stability < 40 or inflation > 0.08:
            budget["welfare"] += 0.2
            budget["military"] -= 0.1
        # normalize to sum 1
        total = sum(max(v, 0.0) for v in budget.values())
        budget = {k: round(max(v, 0.0) / total, 3) for k, v in budget.items()}

        diplomacy: list[DiplomaticAction] = []
        for other, rel in view.relations.items():
            trust = rel.get("trust", 0.0)
            if rel.get("war"):
                continue
            if trust < -30 and rel.get("alliance") is False:
                diplomacy.append(DiplomaticAction(kind="sanction", target=other))
            elif trust > 40 and not rel.get("alliance"):
                diplomacy.append(DiplomaticAction(kind="alliance_offer", target=other))
            elif trust < -10 and aggression > 0.5:
                diplomacy.append(DiplomaticAction(kind="threaten", target=other))

        posture = "aggressive" if (at_war or aggression > 0.65) else ("defensive" if short else "neutral")
        rationing = "food" in short or "energy" in short
        propaganda = stability < 45

        drivers = []
        if short:
            drivers.append(f"shortage:{'+'.join(short)}")
        if at_war:
            drivers.append("at_war")
        if stability < 40:
            drivers.append("low_stability")
        rationale = "doctrine: survive and secure supply (" + (", ".join(drivers) or "steady state") + ")"

        return Decisions(
            budget=budget,
            diplomacy=diplomacy[:3],
            military_posture=posture,
            rationing=rationing,
            propaganda=propaganda,
            doctrines=self._doctrines(view),
            rationale=rationale,
        )
