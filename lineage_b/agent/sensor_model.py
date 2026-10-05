"""Per-sensor (b, sigma) model and the matched update primitive (B1 §3; B0
infrastructure for gates 6, 11, 14, 19). G0 = no updater."""

from __future__ import annotations

import hashlib
import math
from typing import Dict, Optional

import numpy as np

from lineage_b.agent.predictor import g_and_var
from lineage_b.params import ETA_B, ETA_S, NOMINAL_SIGMA, SIGMA_MIN_FRAC
from lineage_b.receipts import canonical


class SensorModel:
    """Conditionally independent Gaussian sensors (G0–G2 assumption)."""

    def __init__(self):
        self.b: Dict[str, float] = {}
        self.sigma: Dict[str, float] = {}
        self.v: Dict[str, Optional[float]] = {}

    def _ensure(self, s):
        if s not in self.sigma:
            self.b[s], self.sigma[s], self.v[s] = 0.0, NOMINAL_SIGMA[s], None

    def params(self, s: str, g: int):
        self._ensure(s)
        return self.b[s], self.sigma[s]

    def loglik(self, fresh: Dict[str, float], u: float, g: int) -> np.ndarray:
        ll = 0.0
        for s, y in fresh.items():
            p = self.params(s, g)
            if p is None:
                continue
            b, sig = p
            gq, wv = g_and_var(s, u)
            var = sig ** 2 + wv
            ll = ll - 0.5 * (y - gq - b) ** 2 / var - 0.5 * np.log(var)
        return np.asarray(ll) * np.ones(len(g_and_var("L1", u)[0]))

    def update(self, s: str, residual: float, ref_var: float) -> None:
        self._ensure(s)
        b = self.b[s] + ETA_B * (residual - self.b[s])
        if self.v[s] is None:
            self.v[s] = NOMINAL_SIGMA[s] ** 2 + ref_var
        v = (1 - ETA_S) * self.v[s] + ETA_S * (residual - b) ** 2
        smin = SIGMA_MIN_FRAC * NOMINAL_SIGMA[s]
        self.b[s], self.v[s] = b, v
        self.sigma[s] = math.sqrt(max(smin ** 2, v - ref_var))

    def theta_hash(self) -> str:
        d = {s: [self.b[s], self.sigma[s], self.v[s]] for s in sorted(self.sigma)}
        return hashlib.sha256(canonical(d).encode()).hexdigest()
