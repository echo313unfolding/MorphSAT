"""Per-sensor (b, sigma) model and the matched update primitive (B1 §3; B0
infrastructure for gates 6, 11, 14, 19). G0 = no updater."""

from __future__ import annotations

import hashlib
import math
from typing import Dict, Optional

from lineage_b.agent import predictor
from lineage_b.params import ETA_B, ETA_S, NOMINAL_SIGMA, SIGMA_MIN_FRAC
from lineage_b.receipts import canonical


class SensorModel:
    """Conditionally independent Gaussian sensors (G0–G2 assumption)."""

    def __init__(self):
        self.b: Dict[str, float] = {}
        self.sigma: Dict[str, float] = {}
        self.v: Dict[str, Optional[float]] = {}
        for s in ("L1", "L2", "L3", "F", "P"):        # eager: theta_hash changes only on update
            self._ensure(s)

    def _ensure(self, s):
        if s not in self.sigma:
            self.b[s], self.sigma[s], self.v[s] = 0.0, NOMINAL_SIGMA[s], None

    def params(self, s: str, g: int):
        self._ensure(s)
        return self.b[s], self.sigma[s]

    def assimilate(self, B, fresh: Dict[str, float], u: float, g: int):
        """Sequential conditionally independent updates (v1.3 §1.4)."""
        return predictor.assimilate(B, fresh, u, lambda s: self.params(s, g))

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
