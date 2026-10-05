"""Hidden world Z and transition T (B0 §2–§4, §6). EVALUATOR ONLY."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Optional

import numpy as np

from lineage_b.params import (A, CV, DT, DU, H_MAX, INSPECT_FA, INSPECT_MISS, K_LEAK,
                              LEAK_HAZARD, P_SLOW, PHI, Q_BAR, R_REP, SIGMA_ETA, SIGMA_W)

STREAMS = ("inflow", "process", "leak", "eps_A", "eps_1", "eps_2", "eps_3", "eps_F",
           "eps_P", "inspection", "ch_L1", "ch_L2", "ch_L3", "ch_F", "ch_P", "init")

CONDITIONS = ("C0", "C1", "C2", "C3", "C4", "C5")


def make_streams(seed_seq: np.random.SeedSequence) -> Dict[str, np.random.Generator]:
    children = seed_seq.spawn(len(STREAMS))
    return {name: np.random.default_rng(c) for name, c in zip(STREAMS, children)}


@dataclass
class FaultState:
    """Deployment-level fault regime (persists across episodes)."""
    condition: str
    stuck_value: Optional[float] = None


@dataclass
class Z:
    h: float
    q_in: float
    u: float
    leak: str
    repair_at: Optional[int]
    t: int
    g: int                      # deployment-global step (fault timing)


class TransitionError(RuntimeError):
    pass


class World:
    def __init__(self, streams, faults: FaultState, episode: int, g0: int,
                 receipts, noise: bool = True, h0: Optional[float] = None,
                 u0: float = 0.5, q0: float = Q_BAR):
        self.rng = streams
        self.faults = faults
        self.episode = episode
        self.noise = noise
        self.receipts = receipts
        init = self.rng["init"].normal()
        h = h0 if h0 is not None else 1.0 + (0.05 * init if noise else 0.0)
        self.z = Z(h=h, q_in=q0, u=u0, leak="none", repair_at=None, t=0, g=g0)
        self.last_flows: Dict[str, float] = {}
        self.inspection_report: Optional[tuple] = None
        self.transition_clock = []

    def step(self, action: str, commitment: Optional[str]) -> Z:
        """Apply A_t. Requires the prediction receipt for (episode, t+1) to be
        committed first (gate 8)."""
        z = self.z
        key = (self.episode, z.t + 1)
        if self.receipts is not None:
            if commitment is None or self.receipts.hash_of(key) != commitment:
                raise TransitionError(f"no committed receipt for {key}")
            commit_clock = self.receipts.clock_of(key)
            clock = self.receipts.tick()
            if not commit_clock < clock:
                raise TransitionError("commit clock not before transition clock")
            self.transition_clock.append((key, commit_clock, clock))
        # fixed draws per step (common random numbers)
        eta = self.rng["inflow"].normal()
        w = self.rng["process"].normal()
        u_on, u_type = self.rng["leak"].random(2)
        u_insp = self.rng["inspection"].random()

        u_new = min(1.0, max(0.0, z.u + (DU if action == "open" else -DU if action == "close" else 0.0)))
        sq = math.sqrt(max(z.h, 0.0))
        q_out = CV * u_new * sq
        q_leak = K_LEAK[z.leak] * sq
        h_raw = z.h + (DT / A) * (z.q_in - q_out - q_leak) + (SIGMA_W * w if self.noise else 0.0)
        h_new = min(max(h_raw, 0.0), H_MAX)
        spill = A * max(h_raw - H_MAX, 0.0) / DT
        shortfall = A * max(-h_raw, 0.0) / DT
        q_new = max(0.0, Q_BAR + PHI * (z.q_in - Q_BAR) + (SIGMA_ETA * eta if self.noise else 0.0))

        self.inspection_report = None
        repair_at = z.repair_at
        if action == "inspect":
            if z.leak != "none":
                found = u_insp >= INSPECT_MISS
                if found and repair_at is None:
                    repair_at = z.t + R_REP
            else:
                found = u_insp < INSPECT_FA
            self.inspection_report = (z.t, "LEAK_FOUND" if found else "NO_LEAK")

        leak = z.leak
        if repair_at is not None and z.t + 1 >= repair_at:
            leak, repair_at = "none", None
        elif leak == "none" and u_on < LEAK_HAZARD:
            leak = "slow" if u_type < P_SLOW else "fast"

        self.last_flows = {"q_in": z.q_in, "q_out": q_out, "q_leak": q_leak, "spill": spill,
                           "shortfall": shortfall, "h_raw": h_raw, "u_new": u_new}
        self.z = Z(h=h_new, q_in=q_new, u=u_new, leak=leak, repair_at=repair_at,
                   t=z.t + 1, g=z.g + 1)
        return self.z
