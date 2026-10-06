"""REF-S evaluator-side reference sensor model (B0 §10): true fault and error
parameters and the ADC_A covariance; same observations and timing; never
sees hidden h. Used only for the gate-17 pilot and as the B1 closure
denominator."""

from __future__ import annotations

import numpy as np

from lineage_b.agent import predictor
from lineage_b.params import NOMINAL_SIGMA, SIGMA_A, SIGMA_L12, T_F

JOINT_L12 = np.array([[SIGMA_A ** 2 + SIGMA_L12 ** 2, SIGMA_A ** 2],
                      [SIGMA_A ** 2, SIGMA_A ** 2 + SIGMA_L12 ** 2]])


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

    def assimilate(self, B, fresh, u, g):
        """Same machinery as the arms (v1.3 §1.4); joint L1/L2 update with the true
        ADC_A covariance when both are fresh; stuck sensors and L4 skipped via params."""
        return predictor.assimilate(B, fresh, u, lambda s: self.params(s, g), joint_l12=JOINT_L12)

    def update(self, *a, **k):
        raise RuntimeError("REF-S does not learn")

    def theta_hash(self) -> str:
        return "REF-S:" + self.condition
