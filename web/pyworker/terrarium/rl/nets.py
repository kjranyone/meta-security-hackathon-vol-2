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


def _act_from_outputs(rng, out: dict, *, fine: bool, deterministic: bool) -> dict:
    """3ネット共通のact本体。サンプリング順序(budget→posture→ration→propa→外交)は
    全クラスで厳密に同一 — rng消費順の保存=訓練再現のbit等価のため。
    deterministic経路は値が独立なので内部順序の正規化は観測不能。"""
    z_b = out["budget_logits"]
    dl = out.get("diplo_logits", np.zeros(0))
    if deterministic:
        logp = 0.0
        if fine:
            action = {"budget_levels": [int(np.argmax(z_b[a * 5:(a + 1) * 5])) for a in range(4)]}
        else:
            action = {"budget_idx": int(np.argmax(z_b))}
        p = int(np.argmax(out["posture_logits"]))
        r = 1 if out["ration_logit"] > 0 else 0
        g = 1 if out["propa_logit"] > 0 else 0
        for i, name in enumerate(("diplo_improve", "diplo_sanction", "diplo_threaten")):
            if i < len(dl):
                action[name] = 1 if float(dl[i]) > 0 else 0
    else:
        logp = 0.0
        if fine:
            lv = []
            for a in range(4):
                za = z_b[a * 5:(a + 1) * 5]
                k = int(rng.choice(5, p=_softmax(za)))
                lv.append(k)
                logp += _log_softmax(za)[k]
            action = {"budget_levels": lv}
        else:
            b = int(rng.choice(len(z_b), p=_softmax(z_b)))
            action = {"budget_idx": b}
            logp += _log_softmax(z_b)[b]
        p = int(rng.choice(3, p=_softmax(out["posture_logits"])))
        logp += _log_softmax(out["posture_logits"])[p]
        r = int(rng.random() < _sigmoid(out["ration_logit"]))
        g = int(rng.random() < _sigmoid(out["propa_logit"]))
        logp += _bern_logp(out["ration_logit"], r) + _bern_logp(out["propa_logit"], g)
        for i, name in enumerate(("diplo_improve", "diplo_sanction", "diplo_threaten")):
            if i < len(dl):
                k = int(rng.random() < _sigmoid(float(dl[i])))
                action[name] = k
                logp += _bern_logp(float(dl[i]), k)
    return {
        **action, "posture_idx": p, "rationing": r, "propaganda": g,
        "logp": logp, "value": out["value"], "out": out,
    }


def _he_init(fan_in: int, fan_out: int, rng: np.random.Generator) -> np.ndarray:
    x = rng.normal(0.0, 1.0, (fan_in, fan_out))
    return x * np.sqrt(2.0 / fan_in)


class PolicyNet:
    def __init__(self, obs_dim: int, hidden: int = 64, seed: int = 0, fine: bool = False,
                 diplomacy: bool = False, obs_sem: int = 2):
        """diplomacy=True は外交3頭(改善/制裁/脅迫)を有効化するが、
        不可逆的escalationへの探索が方策学習を一貫して壊すため既定は無効
        (SAH学習: 61次元+外交なし +6.0、外交あり -3.7)。外交行動は
        heuristic/LLM層が担う。実装と知見は残す(失敗の記録)。"""
        self.rng = np.random.default_rng(seed)
        self.fine = fine
        self.diplomacy = diplomacy
        self.obs_sem = obs_sem
        self._n_diplo = 3 if diplomacy else 0
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
        self.Wd = _he_init(hidden, self._n_diplo, self.rng) if diplomacy else np.zeros((hidden, 0))
        # 外交ヘッド: デフォルトは無効(学習阻害が実証されたため)。diplomacy=Trueで
        # 明示的に有効化 — 不可逆的escalationへの探索が方策を壊す(§失敗の記録)
        self.bd = np.full(self._n_diplo, -2.5) if diplomacy else np.zeros(0)
        self.params = [self.W1, self.b1, self.Wb, self.bb, self.Wp, self.bp,
                       self.Wr, self.br, self.Wg, self.bg, self.Wv, self.bv,
                       self.Wd, self.bd]
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
            "diplo_logits": (h @ self.Wd + self.bd) if self.diplomacy else np.zeros(0),
            "value": float((h @ self.Wv + self.bv)[0]),
        }

    # ---------------------------------------------------------------- actions
    def act(self, obs: np.ndarray, deterministic: bool = False) -> dict:
        return _act_from_outputs(self.rng, self.forward(obs),
                                 fine=self.fine, deterministic=deterministic)

    # ------------------------------------------------------------ backward/A2C
    def update(self, obs: np.ndarray, action: dict, advantage: float,
               ret: float, lr: float = 3e-3, entropy_coef: float = 0.01) -> dict:
        """Single-step actor-critic update (REINFORCE with baseline + entropy)."""
        out = self.forward(obs)
        h = self._cache["h"]
        dW = {k: np.zeros_like(v) for k, v in
              [("W1", self.W1), ("b1", self.b1), ("Wb", self.Wb), ("bb", self.bb),
               ("Wp", self.Wp), ("bp", self.bp), ("Wr", self.Wr), ("br", self.br),
               ("Wg", self.Wg), ("bg", self.bg), ("Wv", self.Wv), ("bv", self.bv),
               ("Wd", self.Wd), ("bd", self.bd)]}

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

        gD = np.zeros(self._n_diplo)
        if self.diplomacy:
            dl = out.get("diplo_logits", np.zeros(0))
            for i, name in enumerate(("diplo_improve", "diplo_sanction", "diplo_threaten")):
                if i < len(dl):
                    # 外交ヘッドにentropy正則をかけない(不可逆的escalationへの
                    # 探索奨励が学習を壊すため — 予算や姿勢と同じに扱わない)
                    gD[i] = -advantage * (action.get(name, 0) - _sigmoid(float(dl[i])))
            dW["Wd"] += np.outer(h, gD); dW["bd"] += gD
        dh = (gB @ self.Wb.T + gP @ self.Wp.T + gR * self.Wr[:, 0]
              + gG * self.Wg[:, 0] + gV * self.Wv[:, 0]
              + (self.Wd @ gD if self.diplomacy else 0.0))
        dz = dh * (1.0 - h ** 2)     # tanh'
        dW["W1"] += np.outer(obs, dz); dW["b1"] += dz

        # Adam ascent (grad of objective = -loss)
        self._t += 1
        grads = [dW["W1"], dW["b1"], dW["Wb"], dW["bb"], dW["Wp"], dW["bp"],
                 dW["Wr"], dW["br"], dW["Wg"], dW["bg"], dW["Wv"], dW["bv"],
                 dW["Wd"], dW["bd"]]
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
               ("Wg", self.Wg), ("bg", self.bg), ("Wd", self.Wd), ("bd", self.bd)]}
        dW["Wb"] += np.outer(h, gB); dW["bb"] += gB
        dW["Wp"] += np.outer(h, gP); dW["bp"] += gP
        dW["Wr"] += np.outer(h, [gR]); dW["br"] += np.array([gR])
        dW["Wg"] += np.outer(h, [gG]); dW["bg"] += np.array([gG])
        dh = gB @ self.Wb.T + gP @ self.Wp.T + gR * self.Wr[:, 0] + gG * self.Wg[:, 0]
        dz = dh * (1.0 - h ** 2)
        dW["W1"] += np.outer(obs, dz); dW["b1"] += dz
        grads = [dW[k] for k in ("W1", "b1", "Wb", "bb", "Wp", "bp", "Wr", "br", "Wg", "bg")]
        params = [self.W1, self.b1, self.Wb, self.bb, self.Wp, self.bp,
                  self.Wr, self.br, self.Wg, self.bg]
        for i, (pp, g) in enumerate(zip(params, grads)):
            pp -= lr * g     # 確率的勾配降下（CE最小化）

    # ------------------------------------------------------------------- io
    def save(self, path) -> None:
        np.savez(path, obs_dim=np.array([self.W1.shape[0]]),
                 hidden=np.array([self.W1.shape[1]]),
                 fine=np.array([1 if self.fine else 0]),
                 diplomacy=np.array([1 if self.diplomacy else 0]),
                 obs_sem=np.array([self.obs_sem]),
                 **{f"p{i}": p for i, p in enumerate(self.params)})

    @classmethod
    def load(cls, path) -> "PolicyNet":
        data = np.load(path)
        obs_dim = int(data["obs_dim"][0])
        hidden = int(data["hidden"][0]) if "hidden" in data.files else 64
        fine = bool(int(data["fine"][0])) if "fine" in data.files else False
        diplo = bool(int(data["diplomacy"][0])) if "diplomacy" in data.files else False
        # obs_semなしの旧npzは sem1（war_intensity/refugee次元が未配線=常に0）
        obs_sem = int(data["obs_sem"][0]) if "obs_sem" in data.files else 1
        net = cls(obs_dim=obs_dim, hidden=hidden, seed=0, fine=fine, diplomacy=diplo,
                  obs_sem=obs_sem)
        for i, param in enumerate(net.params):
            key = f"p{i}"
            if key in data.files:
                param[...] = data[key]
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

    def __init__(self, obs_dim: int, hidden: int = 64, seed: int = 0, obs_sem: int = 2):
        self.rng = np.random.default_rng(seed)
        self.obs_dim, self.hidden = obs_dim, hidden
        self.obs_sem = obs_sem
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
        out = {
            "budget_logits": h @ self.Wb + self.bb,
            "posture_logits": h @ self.Wp + self.bp,
            "ration_logit": float((h @ self.Wq + self.bq)[0]),
            "propa_logit": float((h @ self.Wc + self.bc)[0]),
            "value": float((h @ self.Wv + self.bv)[0]),
        }
        return _act_from_outputs(self.rng, out, fine=False, deterministic=deterministic)

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
                 obs_sem=np.array([self.obs_sem]),
                 **{f"p{i}": p for i, p in enumerate(self.params)})

    @classmethod
    def load(cls, path) -> "RecurrentPolicyNet":
        data = np.load(path)
        obs_dim = int(data["obs_dim"][0])
        obs_sem = int(data["obs_sem"][0]) if "obs_sem" in data.files else 1
        net = cls(obs_dim=obs_dim, seed=0, obs_sem=obs_sem)
        for i in range(len(net.params)):
            net.params[i][...] = data[f"p{i}"]
        return net


class DeepPolicyNet:
    """多層MLP戦術AI(大規模蒸留用)。PolicyNetと同じ行動インターフェースを持ち、
    hiddenは層幅のリスト(例 [2048]*4 ≈ 12.7M params ≈ 51MB npz)。

    - trunk: tanh多層。BCはミニバッチ交差エントロピー+Adam、A2CはPolicyNetと
      同じ頭部勾配式を単一Adamで適用(train.run_episodeからそのまま呼べる)
    - save/loadはkind="deep"。load_netが自動判別するためRLPolicyから
      そのまま配備できる(obs_dim/obs_sem/act契約を維持)
    """

    def __init__(self, obs_dim: int, hidden=(512, 512), seed: int = 0, fine: bool = False,
                 diplomacy: bool = False, obs_sem: int = 2):
        if isinstance(hidden, int):
            hidden = [hidden]
        self.rng = np.random.default_rng(seed)
        self.hidden = list(hidden)
        self.obs_dim = obs_dim
        self.fine = fine
        self.diplomacy = diplomacy
        self.obs_sem = obs_sem
        self._n_diplo = 3 if diplomacy else 0
        self._n_budget = 4 * 5 if fine else len(BUDGET_PRESETS)
        dims = [obs_dim] + self.hidden
        self.Ws = [_he_init(dims[i], dims[i + 1], self.rng) for i in range(len(dims) - 1)]
        self.bs = [np.zeros(w) for w in self.hidden]
        top = self.hidden[-1]
        self.Wb = _he_init(top, self._n_budget, self.rng); self.bb = np.zeros(self._n_budget)
        self.Wp = _he_init(top, 3, self.rng); self.bp = np.zeros(3)
        self.Wr = _he_init(top, 1, self.rng); self.br = np.zeros(1)
        self.Wg = _he_init(top, 1, self.rng); self.bg = np.zeros(1)
        self.Wv = _he_init(top, 1, self.rng); self.bv = np.zeros(1)
        self.Wd = _he_init(top, self._n_diplo, self.rng) if diplomacy else np.zeros((top, 0))
        self.bd = np.full(self._n_diplo, -2.5) if diplomacy else np.zeros(0)
        self.params = [*self.Ws, *self.bs,
                       self.Wb, self.bb, self.Wp, self.bp,
                       self.Wr, self.br, self.Wg, self.bg,
                       self.Wv, self.bv, self.Wd, self.bd]
        self._m = [np.zeros_like(p) for p in self.params]
        self._v = [np.zeros_like(p) for p in self.params]
        self._t = 0
        self._adam_lr = 1e-3
        self._cache: dict = {}

    # ---------------------------------------------------------------- forward
    def _trunk(self, X: np.ndarray) -> list[np.ndarray]:
        """X: (B, obs_dim) or (obs_dim,) -> 各層激活のリスト(先頭は入力)。"""
        acts = [np.atleast_2d(X).astype(np.float64)]
        h = acts[0]
        for W, b in zip(self.Ws, self.bs):
            h = np.tanh(h @ W + b)
            acts.append(h)
        return acts

    def forward(self, obs: np.ndarray) -> dict:
        acts = self._trunk(obs)
        h = acts[-1][0]
        self._cache = {"acts": acts}
        return {
            "budget_logits": h @ self.Wb + self.bb,
            "posture_logits": h @ self.Wp + self.bp,
            "ration_logit": float((h @ self.Wr + self.br)[0]),
            "propa_logit": float((h @ self.Wg + self.bg)[0]),
            "diplo_logits": (h @ self.Wd + self.bd) if self.diplomacy else np.zeros(0),
            "value": float((h @ self.Wv + self.bv)[0]),
        }

    def _heads_forward(self, H: np.ndarray) -> dict:
        return {
            "budget_logits": H @ self.Wb + self.bb,
            "posture_logits": H @ self.Wp + self.bp,
            "ration_logit": (H @ self.Wr + self.br)[:, 0],
            "propa_logit": (H @ self.Wg + self.bg)[:, 0],
            "value": (H @ self.Wv + self.bv)[:, 0],
        }

    # ---------------------------------------------------------------- actions
    def act(self, obs: np.ndarray, deterministic: bool = False) -> dict:
        return _act_from_outputs(self.rng, self.forward(obs),
                                 fine=self.fine, deterministic=deterministic)

    # ------------------------------------------------------------ grad engine
    def _apply_adam(self, dirs: list[np.ndarray], ascend: bool) -> None:
        self._t += 1
        sign = 1.0 if ascend else -1.0
        # 勾配ノルム clipping(巨大ネットのBC/A2Cでの発振対策。閾値は緩く)
        gnorm = float(np.sqrt(sum(float(np.sum(g * g)) for g in dirs if g.size)))
        if gnorm > 10.0:
            scale = 10.0 / (gnorm + 1e-12)
            dirs = [g * scale for g in dirs]
        for i, (p, g) in enumerate(zip(self.params, dirs)):
            self._m[i] = 0.9 * self._m[i] + 0.1 * g
            self._v[i] = 0.999 * self._v[i] + 0.001 * g * g
            mhat = self._m[i] / (1.0 - 0.9 ** self._t)
            vhat = self._v[i] / (1.0 - 0.999 ** self._t)
            p += sign * self._adam_lr * mhat / (np.sqrt(vhat) + 1e-8)

    def _backward(self, acts: list[np.ndarray], gB, gP, gR, gG, gV, gD=None,
                  scale: float = 1.0) -> list[np.ndarray]:
        """頭部のdL/dz行列(B,n)から全パラメータの勾配を返す(バッチ和×scale=平均)。"""
        n_Ws = len(self.Ws)
        grads = [np.zeros_like(p) for p in self.params]
        top = acts[-1]
        grads[n_Ws * 2] = top.T @ gB * scale          # Wb
        grads[n_Ws * 2 + 1] = gB.sum(axis=0) * scale
        grads[n_Ws * 2 + 2] = top.T @ gP * scale
        grads[n_Ws * 2 + 3] = gP.sum(axis=0) * scale
        grads[n_Ws * 2 + 4] = (top.T @ gR).reshape(self.Wr.shape) * scale
        grads[n_Ws * 2 + 5] = np.array([gR.sum()]) * scale
        grads[n_Ws * 2 + 6] = (top.T @ gG).reshape(self.Wg.shape) * scale
        grads[n_Ws * 2 + 7] = np.array([gG.sum()]) * scale
        grads[n_Ws * 2 + 8] = (top.T @ gV).reshape(self.Wv.shape) * scale
        grads[n_Ws * 2 + 9] = np.array([gV.sum()]) * scale
        if self.diplomacy and gD is not None:
            grads[n_Ws * 2 + 10] = top.T @ gD * scale
            grads[n_Ws * 2 + 11] = gD.sum(axis=0) * scale
        dtop = (gB @ self.Wb.T + gP @ self.Wp.T
                + np.outer(gR, self.Wr[:, 0]) + np.outer(gG, self.Wg[:, 0])
                + np.outer(gV, self.Wv[:, 0])
                + ((gD @ self.Wd.T) if (self.diplomacy and gD is not None) else 0.0)) * scale
        dh = dtop
        for i in reversed(range(n_Ws)):
            dz = dh * (1.0 - acts[i + 1] ** 2)
            grads[i] = acts[i].T @ dz * scale
            grads[n_Ws + i] = dz.sum(axis=0) * scale
            dh = dz @ self.Ws[i].T
        return grads

    # ------------------------------------------------------------ batch BC
    def imitate_batch(self, batch: list[tuple], lr: float = 1e-3,
                      weights: np.ndarray | None = None,
                      soft_budget: np.ndarray | None = None) -> float:
        """ミニバッチ行動クローニング: 交差エントロピーの平均をAdamで降下。
        batch: [(obs, budget_idx, posture_idx, rationing, propaganda), ...]
        weights: サンプル重み(逆頻度等)。Noneなら均一。損失は重み付き平均。
        soft_budget: (B, 6)のsoft target分布(同一状態のk回教師サンプルの経験分布)。
        与えられた場合はone-hotの代わりに分布への交差エントロピー(KL+エントロピ項)。"""
        self._adam_lr = lr
        X = np.stack([b[0] for b in batch])
        tb = np.array([b[1] for b in batch])
        tp = np.array([b[2] for b in batch])
        tr = np.array([b[3] for b in batch], dtype=np.float64)
        tg = np.array([b[4] for b in batch], dtype=np.float64)
        acts = self._trunk(X)
        out = self._heads_forward(acts[-1])
        B = len(batch)
        P = _softmax_rows(out["budget_logits"])
        if soft_budget is not None:
            gB = P - soft_budget
        else:
            gB = P - np.eye(self._n_budget)[tb]
        gP = _softmax_rows(out["posture_logits"]) - np.eye(3)[tp]
        gR = _sigmoid_rows(out["ration_logit"]) - tr
        gG = _sigmoid_rows(out["propa_logit"]) - tg
        if weights is not None:
            w = np.asarray(weights, dtype=np.float64) / np.sum(weights)
            gB = gB * w[:, None]
            gP = gP * w[:, None]
            gR = gR * w
            gG = gG * w
        else:
            w = np.full(B, 1.0 / B)
        grads = self._backward(acts, gB, gP, gR, gG, np.zeros(B))
        self._apply_adam(grads, ascend=False)
        pp = _softmax_rows(out["posture_logits"])[np.arange(B), tp]
        pr = np.where(tr > 0, _sigmoid_rows(out["ration_logit"]), 1 - _sigmoid_rows(out["ration_logit"]))
        pg = np.where(tg > 0, _sigmoid_rows(out["propa_logit"]), 1 - _sigmoid_rows(out["propa_logit"]))
        # budget項: softなら分布への交差エントロピー、hardなら正解クラスのNLL
        if soft_budget is not None:
            pce = -(soft_budget * np.log(P + 1e-12)).sum(axis=1)
        else:
            pce = -np.log(P[np.arange(B), tb] + 1e-12)
        per = pce - np.log(pp + 1e-12) - np.log(pr + 1e-12) - np.log(pg + 1e-12)
        return float(np.sum(w * per))

    # ------------------------------------------------------------ backward/A2C
    def update(self, obs: np.ndarray, action: dict, advantage: float,
               ret: float, lr: float = 3e-4, entropy_coef: float = 0.01) -> dict:
        """PolicyNet.updateと同じ頭部勾配式の単一サンプルAdam(上昇)。"""
        self._adam_lr = lr
        out = self.forward(obs)
        acts = self._cache["acts"]
        if self.fine:
            gB = np.zeros((1, self._n_budget))
            for a in range(4):
                za = out["budget_logits"][a * 5:(a + 1) * 5]
                gB[0, a * 5:(a + 1) * 5] = (-advantage * _softmax_grad_neglog(za, action["budget_levels"][a])
                                            - entropy_coef * _entropy_grad_softmax(za))
        else:
            gB = np.array([(-advantage * _softmax_grad_neglog(out["budget_logits"], action["budget_idx"])
                            - entropy_coef * _entropy_grad_softmax(out["budget_logits"]))])
        gP = np.array([(-advantage * _softmax_grad_neglog(out["posture_logits"], action["posture_idx"])
                        - entropy_coef * _entropy_grad_softmax(out["posture_logits"]))])
        gR = np.array([-advantage * (action["rationing"] - _sigmoid(out["ration_logit"]))
                       - entropy_coef * _entropy_grad_bern(out["ration_logit"])])
        gG = np.array([-advantage * (action["propaganda"] - _sigmoid(out["propa_logit"]))
                       - entropy_coef * _entropy_grad_bern(out["propa_logit"])])
        gV = np.array([ret - out["value"]])
        gD = None
        if self.diplomacy:
            dl = out.get("diplo_logits", np.zeros(0))
            gD = np.zeros((1, self._n_diplo))
            for i, name in enumerate(("diplo_improve", "diplo_sanction", "diplo_threaten")):
                if i < len(dl):
                    gD[0, i] = -advantage * (action.get(name, 0) - _sigmoid(float(dl[i])))
        grads = self._backward(acts, gB, gP, gR, gG, gV, gD=gD)
        self._apply_adam(grads, ascend=True)
        return {}

    # ------------------------------------------------------------ batch PG
    def update_batch(self, batch: list[tuple], lr: float = 1e-4,
                     entropy_coef: float = 0.0, kl_coef: float = 0.0,
                     ref_budget_logits: np.ndarray | None = None) -> None:
        """バッチpolicy-gradient更新(エピソード蓄積用・KLアンカー対応)。
        batch: [(obs, action, advantage, ret), ...]
        kl_coef + ref_budget_logits: 凍結参照方策(ref)のbudgetロジット(B,6)に対する
        **分布KLの真の勾配**を罰則として加える(降下方向)。
        注意: RLHF流の「有効advantage = adv - β」はAdamのm̂/√v̂が勾配の
        一様スケールを消すため機能しない(実測: β=0/0.05/0.2が完全同一更新に
        なる)。KL勾配は方向を変えるのでAdam下でも有効。"""
        self._adam_lr = lr
        X = np.stack([b[0] for b in batch])
        acts = [b[1] for b in batch]
        advs = np.array([b[2] for b in batch], dtype=np.float64)
        rets = np.array([b[3] for b in batch], dtype=np.float64)
        acts_m = self._trunk(X)
        out = self._heads_forward(acts_m[-1])
        B = len(batch)
        P = _softmax_rows(out["budget_logits"])
        gB = np.zeros((B, self._n_budget))
        gP = np.zeros((B, 3))
        gR = np.zeros(B)
        gG = np.zeros(B)
        for i, a in enumerate(acts):
            adv = advs[i]
            if self.fine:
                for ax in range(4):
                    za = out["budget_logits"][i, ax * 5:(ax + 1) * 5]
                    gB[i, ax * 5:(ax + 1) * 5] = (
                        -adv * _softmax_grad_neglog(za, a["budget_levels"][ax])
                        - entropy_coef * _entropy_grad_softmax(za))
            else:
                gB[i] = (-adv * (P[i] - np.eye(self._n_budget)[a["budget_idx"]])
                         - entropy_coef * _entropy_grad_softmax(out["budget_logits"][i]))
            gP[i] = (-adv * _softmax_grad_neglog(out["posture_logits"][i], a["posture_idx"])
                     - entropy_coef * _entropy_grad_softmax(out["posture_logits"][i]))
            gR[i] = -adv * (a["rationing"] - _sigmoid(out["ration_logit"][i])) \
                - entropy_coef * _entropy_grad_bern(out["ration_logit"][i])
            gG[i] = -adv * (a["propaganda"] - _sigmoid(out["propa_logit"][i])) \
                - entropy_coef * _entropy_grad_bern(out["propa_logit"][i])
        # KL(π‖π_ref)の真の勾配(罰則=降下方向なので減算):
        # dKL/dz_j = p_j[(log p_j - log ρ_j) - KL]
        if kl_coef > 0.0 and ref_budget_logits is not None:
            R = _softmax_rows(ref_budget_logits)
            logP = np.log(P + 1e-12)
            logR = np.log(R + 1e-12)
            KL = (P * (logP - logR)).sum(axis=1)                    # (B,)
            dkl = P * ((logP - logR) - KL[:, None])                 # (B, C)
            gB = gB - kl_coef * dkl
        gV = out["value"] - rets
        grads = self._backward(acts_m, gB, gP, gR, gG, gV)
        self._apply_adam(grads, ascend=True)

    # ------------------------------------------------------------------- io
    def save(self, path) -> None:
        # float32で保存(容量半減: [2048]*4 ≈ 48.6MB。load時にfloat64へ昇格)
        np.savez(path, kind=np.array(["deep"]), obs_dim=np.array([self.obs_dim]),
                 hidden=np.array(self.hidden),
                 fine=np.array([1 if self.fine else 0]),
                 diplomacy=np.array([1 if self.diplomacy else 0]),
                 obs_sem=np.array([self.obs_sem]),
                 **{f"p{i}": p.astype(np.float32) for i, p in enumerate(self.params)})

    @classmethod
    def load(cls, path) -> "DeepPolicyNet":
        data = np.load(path)
        net = cls(obs_dim=int(data["obs_dim"][0]), hidden=list(data["hidden"]),
                  fine=bool(int(data["fine"][0])), diplomacy=bool(int(data["diplomacy"][0])),
                  obs_sem=int(data["obs_sem"][0]))
        for i, param in enumerate(net.params):
            key = f"p{i}"
            if key in data.files:
                param[...] = data[key]
        return net


def _acc(gW, i, g) -> None:
    gW[i] += g


def _softmax_rows(Z: np.ndarray) -> np.ndarray:
    Z = Z - Z.max(axis=1, keepdims=True)
    E = np.exp(Z)
    return E / E.sum(axis=1, keepdims=True)


def _sigmoid_rows(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


def _sigmoid_vec(a: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(a, -30, 30)))


def load_net(path):
    """npzを読んでMLP/GRU/多層MLPを自動判別して復元する。"""
    data = np.load(path)
    kind = str(data["kind"][0]) if "kind" in data.files else ""
    if kind == "gru":
        return RecurrentPolicyNet.load(path)
    if kind == "deep":
        return DeepPolicyNet.load(path)
    return PolicyNet.load(path)
