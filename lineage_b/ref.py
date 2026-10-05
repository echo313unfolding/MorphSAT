"""REF-S evaluator-side reference sensor model (B0 §10): true fault and error
parameters and the ADC_A covariance; same observations and timing; never
sees hidden h. Used only for the gate-17 pilot and as the B1 closure
denominator."""

from __future__ import annotations

import numpy as np

from lineage_b.agent.predictor import W, g_and_var
from lineage_b.params import NOMINAL_SIGMA, SIGMA_A, SIGMA_L12, T_F


class RefSensorModel:
    def __init__(self, condition: str):
        self.condition = condition

    def params(self, s: str, g: int):
        if s == "L4":
            return None                                  # known relay copy of L1
        b, sig = 0.0, NOMINAL_SIGMA[s]
        if g >= T_F:
            c = self.condition
            if c == "C1" and s == "L3":
                return None                              # known stuck
            if c == "C2" and s in ("L1", "L2"):
                b = 0.15
            if c == "C3" and s == "L1":
                b = min(0.002 * (g - T_F), 0.3)
            if c == "C4" and s == "P":
                sig = 5 * sig
            if c == "C4" and s == "F":
                b = 0.02
        return b, sig

    def loglik(self, fresh, u, g):
        ll = np.zeros(len(g_and_var("L1", u)[0]))
        joint = {"L1", "L2"} <= set(fresh)
        for s, y in fresh.items():
            if joint and s in ("L1", "L2"):
                continue
            p = self.params(s, g)
            if p is None:
                continue
            gq, wv = g_and_var(s, u)
            var = p[1] ** 2 + wv
            ll += -0.5 * (y - gq - p[0]) ** 2 / var - 0.5 * np.log(var)
        if joint:
            h, _ = g_and_var("L1", u)
            v = W * W / 12
            S = np.array([[SIGMA_A ** 2 + SIGMA_L12 ** 2 + v, SIGMA_A ** 2 + v],
                          [SIGMA_A ** 2 + v, SIGMA_A ** 2 + SIGMA_L12 ** 2 + v]])
            Si = np.linalg.inv(S)
            r1 = fresh["L1"] - h - self.params("L1", g)[0]
            r2 = fresh["L2"] - h - self.params("L2", g)[0]
            ll += -0.5 * (Si[0, 0] * r1 * r1 + 2 * Si[0, 1] * r1 * r2 + Si[1, 1] * r2 * r2) \
                - 0.5 * np.log(np.linalg.det(S))
        return ll

    def update(self, *a, **k):
        raise RuntimeError("REF-S does not learn")

    def theta_hash(self) -> str:
        return "REF-S:" + self.condition
