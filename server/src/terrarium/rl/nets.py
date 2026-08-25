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
    def __init__(self, obs_dim: int, hidden: int = 64, seed: int = 0, fine: bool = False):
        self.rng = np.random.default_rng(seed)
        self.fine = fine
        # fine=True: 予算は4軸×5水準の微調整（625通り）。False: 従来の6プリセット
        self._n_budget = 4 * 5 if fine else len(BUDGET_PRESETS)
        self.W1 = _he_init(obs_dim, hidden, self.rng)
        self.b1 = np.zeros(hidden)
        self.Wb = _he_init(hidden, self._n_budget, self.rng)  # budget head (fine: 4x5)
        self.bb = np.zeros(self._n_budget)
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
        z_b = out["budget_logits"]
        if deterministic:
            r = 1 if out["ration_logit"] > 0 else 0
            g = 1 if out["propa_logit"] > 0 else 0
            logp = 0.0
            p = int(np.argmax(out["posture_logits"]))
            if self.fine:
                action = {"budget_levels": [int(np.argmax(z_b[a * 5:(a + 1) * 5])) for a in range(4)]}
            else:
                action = {"budget_idx": int(np.argmax(z_b))}
        else:
            logp = 0.0
            if self.fine:
                lv = []
                for a in range(4):
                    za = z_b[a * 5:(a + 1) * 5]
                    k = int(self.rng.choice(5, p=_softmax(za)))
                    lv.append(k)
                    logp += _log_softmax(za)[k]
                action = {"budget_levels": lv}
            else:
                b = int(self.rng.choice(len(z_b), p=_softmax(z_b)))
                action = {"budget_idx": b}
                logp += _log_softmax(z_b)[b]
            p = int(self.rng.choice(3, p=_softmax(out["posture_logits"])))
            logp += _log_softmax(out["posture_logits"])[p]
            r = int(self.rng.random() < _sigmoid(out["ration_logit"]))
            g = int(self.rng.random() < _sigmoid(out["propa_logit"]))
            logp += _bern_logp(out["ration_logit"], r) + _bern_logp(out["propa_logit"], g)
        return {
            **action, "posture_idx": p, "rationing": r, "propaganda": g,
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
        if self.fine:
            pg_budget = np.zeros_like(out["budget_logits"])
            for a in range(4):
                za = out["budget_logits"][a * 5:(a + 1) * 5]
                pg_budget[a * 5:(a + 1) * 5] = -advantage * _softmax_grad_neglog(
                    za, action["budget_levels"][a])
        else:
            pg_budget = -advantage * _softmax_grad_neglog(out["budget_logits"], action["budget_idx"])
        pg_posture = -advantage * _softmax_grad_neglog(out["posture_logits"], action["posture_idx"])
        # d/dlogit of -log p(a) for bernoulli: a - sigmoid(logit)
        pg_rat = -advantage * (action["rationing"] - _sigmoid(out["ration_logit"]))
        pg_prop = -advantage * (action["propaganda"] - _sigmoid(out["propa_logit"]))

        # entropy gradients (encourage exploration): d/dz of -H
        if self.fine:
            ent_b = np.zeros_like(out["budget_logits"])
            for a in range(4):
                ent_b[a * 5:(a + 1) * 5] = _entropy_grad_softmax(
                    out["budget_logits"][a * 5:(a + 1) * 5])
        else:
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

    def imitate(self, obs: np.ndarray, budget_idx: int, posture_idx: int,
                rationing: int, propaganda: int, lr: float = 2e-3) -> None:
        """行動クローニング: 教師行動への交差エントロピーの1ステップ（A2Cの
        policy-gradient経路を advantage=1・教師行動・entropyなしで流す）。"""
        out = self.forward(obs)
        h = self._cache["h"]
        gB = _softmax_grad_neglog(out["budget_logits"], budget_idx)
        gP = _softmax_grad_neglog(out["posture_logits"], posture_idx)
        gR = float(rationing) - _sigmoid(out["ration_logit"])
        gG = float(propaganda) - _sigmoid(out["propa_logit"])
        dW = {k: np.zeros_like(v) for k, v in
              [("W1", self.W1), ("b1", self.b1), ("Wb", self.Wb), ("bb", self.bb),
               ("Wp", self.Wp), ("bp", self.bp), ("Wr", self.Wr), ("br", self.br),
               ("Wg", self.Wg), ("bg", self.bg)]}
        dW["Wb"] += np.outer(h, gB); dW["bb"] += gB
        dW["Wp"] += np.outer(h, gP); dW["bp"] += gP
        dW["Wr"] += np.outer(h, [gR]); dW["br"] += np.array([gR])
        dW["Wg"] += np.outer(h, [gG]); dW["bg"] += np.array([gG])
        dh = gB @ self.Wb.T + gP @ self.Wp.T + gR * self.Wr[:, 0] + gG * self.Wg[:, 0]
        dz = dh * (1.0 - h ** 2)
        dW["W1"] += np.outer(obs, dz); dW["b1"] += dz
        grads = [dW["W1"], dW["b1"], dW["Wb"], dW["bb"], dW["Wp"], dW["bp"],
                 dW["Wr"], dW["br"], dW["Wg"], dW["bg"]]
        params = [self.W1, self.b1, self.Wb, self.bb, self.Wp, self.bp,
                  self.Wr, self.br, self.Wg, self.bg]
        for i, (pp, g) in enumerate(zip(params, grads)):
            pp -= lr * g     # 確率的勾配降下（CE最小化）

    # ------------------------------------------------------------------- io
    def save(self, path) -> None:
        np.savez(path, obs_dim=np.array([self.W1.shape[0]]),
                 fine=np.array([1 if self.fine else 0]),
                 **{f"p{i}": p for i, p in enumerate(self.params)})

    @classmethod
    def load(cls, path) -> "PolicyNet":
        data = np.load(path)
        obs_dim = int(data["obs_dim"][0])
        fine = bool(int(data["fine"][0])) if "fine" in data.files else False
        net = cls(obs_dim=obs_dim, seed=0, fine=fine)
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


class RecurrentPolicyNet:
    """GRU株+actor-critic頭の再帰型戦術AI（LSTM相当の時系列統合）。

    MLP版は毎tickの観測を独立に写像する（マルコフ前提）。再帰版は隠れ状態hが
    エピソードを通じて過去の観測・行動・報酬の影響を保持する — 「傾向の変化」
    「危機の積み重ね」を自力で統合できる高度な推論の素地。
    訓練は各エピソード終了後に系列を再計算して打ち切り長16のBPTTを回す。
    """

    def __init__(self, obs_dim: int, hidden: int = 64, seed: int = 0):
        self.rng = np.random.default_rng(seed)
        self.obs_dim, self.hidden = obs_dim, hidden
        H = hidden
        self.Wz = _he_init(obs_dim, H, self.rng); self.Uz = _he_init(H, H, self.rng) * 0.1; self.bz = np.zeros(H)
        self.Wr_ = _he_init(obs_dim, H, self.rng); self.Ur_ = _he_init(H, H, self.rng) * 0.1; self.br_ = np.zeros(H)
        self.Wn = _he_init(obs_dim, H, self.rng); self.Un = _he_init(H, H, self.rng) * 0.1; self.bn = np.zeros(H)
        self.Wb = _he_init(H, len(BUDGET_PRESETS), self.rng); self.bb = np.zeros(len(BUDGET_PRESETS))
        self.Wp = _he_init(H, 3, self.rng); self.bp = np.zeros(3)
        self.Wq = _he_init(H, 1, self.rng); self.bq = np.zeros(1)   # rationing
        self.Wc = _he_init(H, 1, self.rng); self.bc = np.zeros(1)   # propaganda
        self.Wv = _he_init(H, 1, self.rng); self.bv = np.zeros(1)
        self.params = [self.Wz, self.Uz, self.bz, self.Wr_, self.Ur_, self.br_,
                       self.Wn, self.Un, self.bn,
                       self.Wb, self.bb, self.Wp, self.bp, self.Wq, self.bq,
                       self.Wc, self.bc, self.Wv, self.bv]
        self._m = [np.zeros_like(p) for p in self.params]
        self._v = [np.zeros_like(p) for p in self.params]
        self._t = 0
        self._h = np.zeros(H)          # 実行時のローリング隠れ状態

    # ---------------------------------------------------------------- runtime
    def reset_state(self) -> None:
        self._h = np.zeros(self.hidden)

    def _cell(self, x: np.ndarray, h_prev: np.ndarray):
        a_z = x @ self.Wz + h_prev @ self.Uz + self.bz
        z = _sigmoid_vec(a_z)
        a_r = x @ self.Wr_ + h_prev @ self.Ur_ + self.br_
        r = _sigmoid_vec(a_r)
        a_n = x @ self.Wn + (r * h_prev) @ self.Un + self.bn
        n = np.tanh(a_n)
        h = (1.0 - z) * h_prev + z * n
        return z, r, n, h

    def forward_h(self, x: np.ndarray, h_prev: np.ndarray) -> np.ndarray:
        return self._cell(x, h_prev)[3]

    def act(self, obs: np.ndarray, deterministic: bool = False) -> dict:
        z, r, n, h = self._cell(obs, self._h)
        self._h = h
        budget_logits = h @ self.Wb + self.bb
        posture_logits = h @ self.Wp + self.bp
        ration_logit = float((h @ self.Wq + self.bq)[0])
        propa_logit = float((h @ self.Wc + self.bc)[0])
        value = float((h @ self.Wv + self.bv)[0])
        if deterministic:
            b = int(np.argmax(budget_logits)); p = int(np.argmax(posture_logits))
            q = 1 if ration_logit > 0 else 0; c = 1 if propa_logit > 0 else 0
            logp = 0.0
        else:
            b = int(self.rng.choice(len(BUDGET_PRESETS), p=_softmax(budget_logits)))
            p = int(self.rng.choice(3, p=_softmax(posture_logits)))
            q = int(self.rng.random() < _sigmoid(ration_logit))
            c = int(self.rng.random() < _sigmoid(propa_logit))
            logp = (_log_softmax(budget_logits)[b] + _log_softmax(posture_logits)[p]
                    + _bern_logp(ration_logit, q) + _bern_logp(propa_logit, c))
        return {"budget_idx": b, "posture_idx": p, "rationing": q, "propaganda": c,
                "logp": logp, "value": value}

    # -------------------------------------------------------- training (BPTT)
    def update_sequence(self, obs_list, act_list, advs, rets, lr: float = 1e-3,
                        entropy_coef: float = 0.005, bptt_len: int = 16) -> None:
        T = len(obs_list)
        if T == 0:
            return
        # forward over the episode from h0 = 0
        hs = []
        cache = []
        h = np.zeros(self.hidden)
        for x in obs_list:
            a_z = x @ self.Wz + h @ self.Uz + self.bz
            zz = _sigmoid_vec(a_z)
            a_r = x @ self.Wr_ + h @ self.Ur_ + self.br_
            rr = _sigmoid_vec(a_r)
            a_n = x @ self.Wn + (rr * h) @ self.Un + self.bn
            nn = np.tanh(a_n)
            h_new = (1.0 - zz) * h + zz * nn
            cache.append((x, h, zz, rr, nn, a_z, a_r, a_n))
            hs.append(h_new)
            h = h_new
        # grads
        gW = [np.zeros_like(p) for p in self.params]
        dh_next = np.zeros(self.hidden)
        for t in range(T - 1, -1, -1):
            if (T - 1 - t) >= bptt_len:
                dh_next = np.zeros(self.hidden)   # truncate
            x, h_prev, zz, rr, nn, a_z, a_r, a_n = cache[t]
            hh = hs[t]
            adv, ret = advs[t], rets[t]
            budget_logits = hh @ self.Wb + self.bb
            posture_logits = hh @ self.Wp + self.bp
            ration_logit = float((hh @ self.Wq + self.bq)[0])
            propa_logit = float((hh @ self.Wc + self.bc)[0])
            value = float((hh @ self.Wv + self.bv)[0])
            a = act_list[t]
            gB = -adv * _softmax_grad_neglog(budget_logits, a["budget_idx"]) \
                - entropy_coef * _entropy_grad_softmax(budget_logits)
            gP = -adv * _softmax_grad_neglog(posture_logits, a["posture_idx"]) \
                - entropy_coef * _entropy_grad_softmax(posture_logits)
            gQ = -adv * (a["rationing"] - _sigmoid(ration_logit)) \
                - entropy_coef * _entropy_grad_bern(ration_logit)
            gC = -adv * (a["propaganda"] - _sigmoid(propa_logit)) \
                - entropy_coef * _entropy_grad_bern(propa_logit)
            gV = np.array([ret - value])
            _acc(gW, 9, np.outer(hh, gB)); _acc(gW, 10, gB)
            _acc(gW, 11, np.outer(hh, gP)); _acc(gW, 12, gP)
            _acc(gW, 13, np.outer(hh, [gQ])); _acc(gW, 14, np.array([gQ]))
            _acc(gW, 15, np.outer(hh, [gC])); _acc(gW, 16, np.array([gC]))
            _acc(gW, 17, np.outer(hh, gV)); _acc(gW, 18, gV)
            dh = (gB @ self.Wb.T + gP @ self.Wp.T + gQ * self.Wq[:, 0]
                  + gC * self.Wc[:, 0] + gV * self.Wv[:, 0]) + dh_next
            # GRU逆伝播: h = (1-z)*h_prev + z*n
            dz = dh * (nn - h_prev)                      # dh ⊙ d h/dz
            da_z = dz * zz * (1.0 - zz)
            dn = dh * zz * (1.0 - nn ** 2)
            dh_prev = (1.0 - zz) * dh + self.Uz.T @ da_z
            da_r = (self.Un.T @ dn) * h_prev * rr * (1.0 - rr)
            dh_prev += rr * (self.Un.T @ dn) + self.Ur_.T @ da_r
            _acc(gW, 6, np.outer(x, dn)); _acc(gW, 7, np.outer(rr * h_prev, dn)); _acc(gW, 8, dn)
            _acc(gW, 3, np.outer(x, da_r)); _acc(gW, 4, np.outer(h_prev, da_r)); _acc(gW, 5, da_r)
            _acc(gW, 0, np.outer(x, da_z)); _acc(gW, 1, np.outer(h_prev, da_z)); _acc(gW, 2, da_z)
            dh_next = dh_prev
        # Adam ascent
        self._t += 1
        for i, (p, g) in enumerate(zip(self.params, gW)):
            self._m[i] = 0.9 * self._m[i] + 0.1 * g
            self._v[i] = 0.999 * self._v[i] + 0.001 * g * g
            mhat = self._m[i] / (1.0 - 0.9 ** self._t)
            vhat = self._v[i] / (1.0 - 0.999 ** self._t)
            p += lr * mhat / (np.sqrt(vhat) + 1e-8)

    # ------------------------------------------------------------------- io
    def save(self, path) -> None:
        np.savez(path, kind=np.array(["gru"]), obs_dim=np.array([self.obs_dim]),
                 **{f"p{i}": p for i, p in enumerate(self.params)})

    @classmethod
    def load(cls, path) -> "RecurrentPolicyNet":
        data = np.load(path)
        obs_dim = int(data["obs_dim"][0])
        net = cls(obs_dim=obs_dim, seed=0)
        for i in range(len(net.params)):
            net.params[i][...] = data[f"p{i}"]
        return net


def _acc(gW, i, g) -> None:
    gW[i] += g


def _sigmoid_vec(a: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(a, -30, 30)))


def load_net(path):
    """npzを読んでMLP/GRUを自動判別して復元する。"""
    data = np.load(path)
    if "kind" in data and str(data["kind"][0]) == "gru":
        return RecurrentPolicyNet.load(path)
    return PolicyNet.load(path)
