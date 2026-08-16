"""Tiny numpy neural net: MLP trunk with actor-critic heads + Adam.

No deep-learning framework: the tactical policy is small by design so that
training runs on any CPU, keeps the repo dependency-light, and stays
bit-reproducible for the hackathon's replay requirements.

Heads:
  budget    : 6-way softmax over budget presets (balanced/fortress/welfare/hoard/market/siege)
  posture   : 3-way softmax (defensive/neutral/aggressive)
  rationing : Bernoulli
  propaganda: Bernoulli
  value     : scalar state-value baseline
"""
from __future__ import annotations

import numpy as np

POSTURES = ["defensive", "neutral", "aggressive"]
BUDGET_PRESETS = [
    {"military": 0.20, "welfare": 0.30, "stockpile": 0.20, "subsidy": 0.30},  # balanced
    {"military": 0.50, "welfare": 0.20, "stockpile": 0.20, "subsidy": 0.10},  # fortress
    {"military": 0.10, "welfare": 0.50, "stockpile": 0.15, "subsidy": 0.25},  # welfare
    {"military": 0.10, "welfare": 0.15, "stockpile": 0.60, "subsidy": 0.15},  # hoard
    {"military": 0.10, "welfare": 0.20, "stockpile": 0.10, "subsidy": 0.60},  # market
    {"military": 0.45, "welfare": 0.35, "stockpile": 0.15, "subsidy": 0.05},  # siege
]


def _he_init(fan_in: int, fan_out: int, rng: np.random.Generator) -> np.ndarray:
    x = rng.normal(0.0, 1.0, (fan_in, fan_out))
    return x * np.sqrt(2.0 / fan_in)


class PolicyNet:
    def __init__(self, obs_dim: int, hidden: int = 64, seed: int = 0):
        self.rng = np.random.default_rng(seed)
        self.W1 = _he_init(obs_dim, hidden, self.rng)
        self.b1 = np.zeros(hidden)
        self.Wb = _he_init(hidden, len(BUDGET_PRESETS), self.rng)  # budget head
        self.bb = np.zeros(len(BUDGET_PRESETS))
        self.Wp = _he_init(hidden, 3, self.rng)     # posture head
        self.bp = np.zeros(3)
        self.Wr = _he_init(hidden, 1, self.rng)     # rationing (bernoulli)
        self.br = np.zeros(1)
        self.Wg = _he_init(hidden, 1, self.rng)     # propaganda (bernoulli)
        self.bg = np.zeros(1)
        self.Wv = _he_init(hidden, 1, self.rng)     # value head
        self.bv = np.zeros(1)
        self.params = [self.W1, self.b1, self.Wb, self.bb, self.Wp, self.bp,
                       self.Wr, self.br, self.Wg, self.bg, self.Wv, self.bv]
        self._m = [np.zeros_like(p) for p in self.params]
        self._v = [np.zeros_like(p) for p in self.params]
        self._t = 0
        self._cache: dict[str, np.ndarray] = {}

    # ---------------------------------------------------------------- forward
    def forward(self, obs: np.ndarray) -> dict[str, np.ndarray]:
        h = np.tanh(obs @ self.W1 + self.b1)
        self._cache = {"obs": obs, "h": h}
        return {
            "budget_logits": h @ self.Wb + self.bb,
            "posture_logits": h @ self.Wp + self.bp,
            "ration_logit": float((h @ self.Wr + self.br)[0]),
            "propa_logit": float((h @ self.Wg + self.bg)[0]),
            "value": float((h @ self.Wv + self.bv)[0]),
        }

    # ---------------------------------------------------------------- actions
    def act(self, obs: np.ndarray, deterministic: bool = False) -> dict:
        out = self.forward(obs)
        if deterministic:
            b = int(np.argmax(out["budget_logits"]))
            p = int(np.argmax(out["posture_logits"]))
            r = 1 if out["ration_logit"] > 0 else 0
            g = 1 if out["propa_logit"] > 0 else 0
            logp = 0.0
        else:
            b = int(self.rng.choice(len(BUDGET_PRESETS), p=_softmax(out["budget_logits"])))
            p = int(self.rng.choice(3, p=_softmax(out["posture_logits"])))
            r = int(self.rng.random() < _sigmoid(out["ration_logit"]))
            g = int(self.rng.random() < _sigmoid(out["propa_logit"]))
            logp = (_log_softmax(out["budget_logits"])[b]
                    + _log_softmax(out["posture_logits"])[p]
                    + _bern_logp(out["ration_logit"], r)
                    + _bern_logp(out["propa_logit"], g))
        return {
            "budget_idx": b, "posture_idx": p, "rationing": r, "propaganda": g,
            "logp": logp, "value": out["value"], "out": out,
        }

    # ------------------------------------------------------------ backward/A2C
    def update(self, obs: np.ndarray, action: dict, advantage: float,
               ret: float, lr: float = 3e-3, entropy_coef: float = 0.01) -> dict:
        """Single-step actor-critic update (REINFORCE with baseline + entropy)."""
        out = self.forward(obs)
        h = self._cache["h"]
        dW = {k: np.zeros_like(v) for k, v in
              [("W1", self.W1), ("b1", self.b1), ("Wb", self.Wb), ("bb", self.bb),
               ("Wp", self.Wp), ("bp", self.bp), ("Wr", self.Wr), ("br", self.br),
               ("Wg", self.Wg), ("bg", self.bg), ("Wv", self.Wv), ("bv", self.bv)]}

        # policy gradients (negative-loss direction)
        pg_budget = -advantage * _softmax_grad_neglog(out["budget_logits"], action["budget_idx"])
        pg_posture = -advantage * _softmax_grad_neglog(out["posture_logits"], action["posture_idx"])
        # d/dlogit of -log p(a) for bernoulli: a - sigmoid(logit)
        pg_rat = -advantage * (action["rationing"] - _sigmoid(out["ration_logit"]))
        pg_prop = -advantage * (action["propaganda"] - _sigmoid(out["propa_logit"]))

        # entropy gradients (encourage exploration): d/dz of -H
        ent_b = _entropy_grad_softmax(out["budget_logits"])
        ent_p = _entropy_grad_softmax(out["posture_logits"])
        ent_r = _entropy_grad_bern(out["ration_logit"])
        ent_g = _entropy_grad_bern(out["propa_logit"])
        gB = pg_budget - entropy_coef * ent_b
        gP = pg_posture - entropy_coef * ent_p
        gR = pg_rat - entropy_coef * ent_r
        gG = pg_prop - entropy_coef * ent_g

        # value gradient: ascend -(0.5*(v - ret)^2), i.e. move v toward ret
        gV = np.array([ret - out["value"]])

        dW["Wb"] += np.outer(h, gB); dW["bb"] += gB
        dW["Wp"] += np.outer(h, gP); dW["bp"] += gP
        dW["Wr"] += np.outer(h, [gR]); dW["br"] += np.array([gR])
        dW["Wg"] += np.outer(h, [gG]); dW["bg"] += np.array([gG])
        dW["Wv"] += np.outer(h, gV);  dW["bv"] += gV

        dh = (gB @ self.Wb.T + gP @ self.Wp.T + gR * self.Wr[:, 0]
              + gG * self.Wg[:, 0] + gV * self.Wv[:, 0])
        dz = dh * (1.0 - h ** 2)     # tanh'
        dW["W1"] += np.outer(obs, dz); dW["b1"] += dz

        # Adam ascent (grad of objective = -loss)
        self._t += 1
        grads = [dW["W1"], dW["b1"], dW["Wb"], dW["bb"], dW["Wp"], dW["bp"],
                 dW["Wr"], dW["br"], dW["Wg"], dW["bg"], dW["Wv"], dW["bv"]]
        for i, (p, g) in enumerate(zip(self.params, grads)):
            self._m[i] = 0.9 * self._m[i] + 0.1 * g
            self._v[i] = 0.999 * self._v[i] + 0.001 * g * g
            mhat = self._m[i] / (1 - 0.9 ** self._t)
            vhat = self._v[i] / (1 - 0.999 ** self._t)
            p += lr * mhat / (np.sqrt(vhat) + 1e-8)
        return {}

    # ------------------------------------------------------------------- io
    def save(self, path) -> None:
        np.savez(path, obs_dim=np.array([self.W1.shape[0]]),
                 **{f"p{i}": p for i, p in enumerate(self.params)})

    @classmethod
    def load(cls, path) -> "PolicyNet":
        data = np.load(path)
        obs_dim = int(data["obs_dim"][0])
        net = cls(obs_dim=obs_dim, seed=0)
        for i in range(len(net.params)):
            net.params[i][...] = data[f"p{i}"]
        return net


# ------------------------------------------------------------------ helpers
def _softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max()
    e = np.exp(z)
    return e / e.sum()


def _log_softmax(z: np.ndarray) -> np.ndarray:
    return z - z.max() - np.log(np.exp(z - z.max()).sum())


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


def _bern_logp(logit: float, a: int) -> float:
    p = _sigmoid(logit)
    return float(np.log(p if a else 1.0 - p))


def _softmax_grad_neglog(z: np.ndarray, idx: int) -> np.ndarray:
    """d/dz of -log softmax(z)[idx] = softmax(z) - onehot(idx)"""
    return _softmax(z) - np.eye(len(z))[idx]


def _entropy_grad_softmax(z: np.ndarray) -> np.ndarray:
    """d/dz of -H where H = -sum p log p  =>  p * (log p + H) (ascended)"""
    p = _softmax(z)
    H = float(-(p * np.log(p + 1e-12)).sum())
    return p * (np.log(p + 1e-12) + H)


def _entropy_grad_bern(logit: float) -> float:
    """d/dlogit of -H for Bernoulli; H = -(p log p + q log q). dH/dp = log(q/p).
    dH/dlogit = p q log(q/p); grad ascent on -H uses -dH/dlogit... we return d(-H)/dlogit."""
    p = _sigmoid(logit)
    q = 1.0 - p
    H = -(p * np.log(p + 1e-12) + q * np.log(q + 1e-12))
    # numeric gradient fallback (simple, robust)
    eps = 1e-3
    H2 = -(_sigmoid(logit + eps) * np.log(_sigmoid(logit + eps) + 1e-12)
           + (1 - _sigmoid(logit + eps)) * np.log(1 - _sigmoid(logit + eps) + 1e-12))
    return float((H2 - H) / eps)
