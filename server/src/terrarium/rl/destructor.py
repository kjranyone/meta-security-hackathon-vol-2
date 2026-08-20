"""破壊神AI（イースターエッグ）: 強化学習で「世界を破壊する」神を訓練する。

GodEnv: エージェントは毎tick 神カードから1枚を選べる。報酬は世界へのダメージ
（GDP下落・新規デフォルト・開戦・崩壊）。訓練済み重みは models/destructor.npz。
神の玉座で "hakai" とタイプすると 破壊AIが神権を握る（終末モード）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from ..sim.engine import Engine
from ..sim.interventions import Intervention, Scenario
from ..agents.heuristic import HeuristicPolicy
from ..world.presets import load_preset

SERVER_ROOT = Path(__file__).resolve().parents[3]

OBS_DIM = 12
N_CARDS = 8
CARD_NAMES = ["利上げ", "封鎖ホルムズ", "封鎖マラッカ", "封鎖台湾海峡",
              "災害(最弱国)", "資源破壊(最大産油国)", "技術禁止", "様子見"]


class DestructorNet:
    """小さなMLP: world観測 → カード選択(8) + 価値。numpy実装（決定論・軽量）。"""

    def __init__(self, obs_dim: int = OBS_DIM, n_actions: int = N_CARDS, seed: int = 0, hidden: int = 64):
        rng = np.random.default_rng(seed)
        self.obs_dim, self.n_actions = obs_dim, n_actions
        self.W1 = rng.normal(0, 0.3, (obs_dim, hidden))
        self.b1 = np.zeros(hidden)
        self.W2 = rng.normal(0, 0.3, (hidden, hidden))
        self.b2 = np.zeros(hidden)
        self.Wp = rng.normal(0, 0.1, (hidden, n_actions))
        self.bp = np.zeros(n_actions)
        self.Wv = rng.normal(0, 0.1, (hidden, 1))
        self.bv = np.zeros(1)
        self._adam = {k: {"m": np.zeros_like(v), "v": np.zeros_like(v), "t": 0}
                      for k, v in self._params().items()}

    def _params(self):
        return {"W1": self.W1, "b1": self.b1, "W2": self.W2, "b2": self.b2,
                "Wp": self.Wp, "bp": self.bp, "Wv": self.Wv, "bv": self.bv}

    def forward(self, x):
        h = np.tanh(x @ self.W1 + self.b1)
        h2 = np.tanh(h @ self.W2 + self.b2)
        return h2 @ self.Wp + self.bp, h2 @ self.Wv + self.bv, h2

    def act(self, obs, deterministic: bool = False):
        logits, value, _ = self.forward(obs)
        if deterministic:
            a = int(np.argmax(logits))
        else:
            p = np.exp(logits - logits.max())
            p /= p.sum()
            a = int(np.random.choice(len(p), p=p))
        return {"card": a, "value": float(value[0])}

    def update(self, obs, action, adv, ret, lr=1e-3, entropy_coef=0.01):
        logits, value, h = self.forward(obs)
        p = np.exp(logits - logits.max()); p /= p.sum()
        pg = -p.copy(); pg[action["card"]] += 1.0          # d logπ/da
        glogits = pg * adv
        gv = np.array([ret - value[0]])
        grads = {
            "Wp": np.outer(h, glogits), "bp": glogits,
            "Wv": np.outer(h, gv), "bv": gv,
            "W2": np.outer(np.tanh(h @ self.W2 + self.b2) * 0 + 1, np.zeros(1)) if False else None,
        }
        # 手書き逆伝播（2層tanh）
        dh2 = self.Wp @ glogits + (self.Wv @ gv)
        dz2 = dh2 * (1 - np.tanh(h @ self.W2 + self.b2) ** 2)
        grads["W2"] = np.outer(h, dz2); grads["b2"] = dz2
        dh = self.W2 @ dz2
        dz = dh * (1 - np.tanh(obs @ self.W1 + self.b1) ** 2)
        grads["W1"] = np.outer(obs, dz); grads["b1"] = dz
        grads = {k: g for k, g in grads.items() if g is not None}
        # entropy bonus
        ent = -np.sum(p * np.log(p + 1e-9))
        grads["bp"] = grads["bp"] - entropy_coef * p
        # Adam
        for k, g in grads.items():
            s = self._adam[k]
            s["t"] += 1
            s["m"] = 0.9 * s["m"] + 0.1 * g
            s["v"] = 0.999 * s["v"] + 0.001 * g * g
            mh = s["m"] / (1 - 0.9 ** s["t"])
            vh = s["v"] / (1 - 0.999 ** s["t"])
            setattr(self, k, getattr(self, k) + lr * mh / (np.sqrt(vh) + 1e-8))
        return float(ent)

    def save(self, path):
        np.savez(path, **{k: v for k, v in self._params().items()})

    @classmethod
    def load(cls, path):
        d = np.load(path)
        net = cls()
        for k in net._params():
            setattr(net, k, d[k])
        return net


def obs_of(eng: Engine) -> np.ndarray:
    m = eng.snapshots[-1]["metrics"] if eng.snapshots else {}
    gdp = m.get("world_gdp", 100.0)
    return np.array([
        eng.prices["energy"] / 2.0, eng.prices["food"] / 2.0, eng.prices["chips"] / 2.0,
        eng.prices["minerals"] / 2.0, eng.prices["space"] / 2.0,
        np.log10(max(gdp, 1.0)) / 3.0,
        m.get("mean_stability", 55.0) / 100.0,
        m.get("wars", 0) / 5.0,
        m.get("defaults", 0) / 10.0,
        m.get("collapsed", 0) / 5.0,
        min(eng.tick_no / 36.0, 1.0),
        eng.god.trade_efficiency - 1.0,
    ], dtype=np.float32)


def card_to_intervention(eng: Engine, card: int) -> Intervention | None:
    t = eng.tick_no
    if card == 0:
        return Intervention(tick=t, type="rate_hike", params={"value": 0.05})
    if card == 1:
        return Intervention(tick=t, type="close_chokepoint",
                            params={"chokepoint": "Strait of Hormuz", "duration": 6})
    if card == 2:
        return Intervention(tick=t, type="close_chokepoint",
                            params={"chokepoint": "Strait of Malacca", "duration": 6})
    if card == 3:
        return Intervention(tick=t, type="close_chokepoint",
                            params={"chokepoint": "Taiwan Strait", "duration": 6})
    if card == 4:
        nid = min(eng.nations, key=lambda n: eng.nations[n].stability)
        return Intervention(tick=t, type="disaster", params={"nation": nid, "kind": "drought"})
    if card == 5:
        nid = max(eng.nations, key=lambda n: sum(
            1 for r in eng.nation_resources[n] if r.value in ("oil", "gas")))
        return Intervention(tick=t, type="destroy_resource", params={"nation": nid, "resource": "oil"})
    if card == 6:
        from ..world.tech import CATALOG
        avail = [t2.id for t2 in CATALOG if eng.tick_no <= t2.unlock_tick + 6]
        tech = avail[min(len(avail) - 1, eng.tick_no // 6)]
        return Intervention(tick=t, type="ban_tech", params={"tech": tech})
    return None  # 様子見


class GodEnv:
    """破壊AIの環境内シミュレーション（神カード選択→1tick→ダメージ報酬）。"""

    def __init__(self, preset="earth", seed=42, horizon=36):
        self.preset, self.seed, self.horizon = preset, seed, horizon

    def _build(self):
        spec = load_preset(self.preset)
        pol = {ns.id: HeuristicPolicy() for ns in spec.nations}
        eng = Engine(spec, pol, seed=self.seed, out_dir=None)
        eng.tick_no = 0
        return eng

    def run_episode(self, net: DestructorNet, train: bool, gamma=0.97):
        eng = self._build()
        prev = {"gdp": 100.0, "defaults": 0, "wars": 0, "collapsed": 0}
        traj, total = [], 0.0
        for t in range(self.horizon):
            obs = obs_of(eng)
            act = net.act(obs, deterministic=not train)
            iv = card_to_intervention(eng, act["card"])
            if iv:
                eng.apply_intervention(iv)
            eng.step()
            m = eng.snapshots[-1]["metrics"]
            gdp = m["world_gdp"]
            reward = ((prev["gdp"] - gdp) / max(prev["gdp"], 1.0) * 100.0
                      + 2.0 * (m["defaults"] - prev["defaults"])
                      + 3.0 * (m["wars"] - prev["wars"])
                      + 5.0 * (m["collapsed"] - prev["collapsed"]))
            prev = {"gdp": gdp, "defaults": m["defaults"],
                    "wars": m["wars"], "collapsed": m["collapsed"]}
            traj.append((obs, act, reward * 0.1))
            total += reward
        if train:
            returns, G = [], 0.0
            for _, _, r in reversed(traj):
                G = r + gamma * G
                returns.append(G)
            returns.reverse()
            advs = [G - a["value"] for (_, a, _), G in zip(traj, returns)]
            mu, sg = float(np.mean(advs)), float(np.std(advs)) + 1e-6
            for (o, a, _), G_, adv in zip(traj, returns, advs):
                net.update(o, a, (adv - mu) / sg, G_)
        return total


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Train the destructor god (easter egg)")
    ap.add_argument("--preset", default="earth")
    ap.add_argument("--episodes", type=int, default=400)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    out = Path(args.out) if args.out else SERVER_ROOT / "models" / "destructor.npz"
    net = DestructorNet(seed=args.seed)
    env = GodEnv(args.preset, seed=args.seed)
    base = env.run_episode(net, train=False)
    print(f"[destructor] episode 0 damage={base:.2f}")
    for ep in range(1, args.episodes + 1):
        d = env.run_episode(net, train=True)
        if ep % 50 == 0:
            print(f"[destructor] episode {ep} damage={d:.2f}")
    net.save(out)
    final = env.run_episode(net, train=False)
    print(f"[destructor] saved {out} | damage {base:.2f} -> {final:.2f} ({final-base:+.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
