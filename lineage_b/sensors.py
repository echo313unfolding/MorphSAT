"""Sensor measurements and frozen faults (B0 §5–§6). EVALUATOR ONLY."""

from __future__ import annotations

import math
from typing import Dict

from lineage_b.params import CV, P_GAIN, SIGMA_A, SIGMA_F, SIGMA_L12, SIGMA_L3, SIGMA_P, T_F
from lineage_b.world import FaultState, Z


def true_quantity(sensor: str, z: Z) -> float:
    if sensor in ("L1", "L2", "L3", "L4"):
        return z.h
    if sensor == "F":
        return CV * z.u * math.sqrt(max(z.h, 0.0))
    if sensor == "P":
        return P_GAIN * z.h
    raise ValueError(sensor)


def measure(z: Z, rng, faults: FaultState, noise: bool = True) -> Dict[str, float]:
    """One reading per base sensor at time t; fixed draws per step."""
    e = {k: rng[k].normal() for k in ("eps_A", "eps_1", "eps_2", "eps_3", "eps_F", "eps_P")}
    if not noise:
        e = {k: 0.0 for k in e}
    on = z.g >= T_F
    c = faults.condition
    eA = SIGMA_A * e["eps_A"]
    sP = SIGMA_P * (5.0 if (c == "C4" and on) else 1.0)
    v = {"L1": z.h + eA + SIGMA_L12 * e["eps_1"],
         "L2": z.h + eA + SIGMA_L12 * e["eps_2"],
         "L3": z.h + SIGMA_L3 * e["eps_3"],
         "F": true_quantity("F", z) + SIGMA_F * e["eps_F"],
         "P": true_quantity("P", z) + sP * e["eps_P"]}
    if on:
        if c == "C1":
            if faults.stuck_value is None:
                faults.stuck_value = v["L3"]
            v["L3"] = faults.stuck_value
        elif c == "C2":
            v["L1"] += 0.15
            v["L2"] += 0.15
        elif c == "C3":
            v["L1"] += min(0.002 * (z.g - T_F), 0.3)
        elif c == "C4":
            v["F"] += 0.02
    return v
