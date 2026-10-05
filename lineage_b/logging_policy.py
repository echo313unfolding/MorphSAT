"""Known randomized logging policy mu with recorded propensities (B0 gate 10;
B1 §5). One draw per step regardless of whether it randomizes."""

from __future__ import annotations

from lineage_b.params import ACTIONS, EPSILON


class LoggingPolicy:
    def __init__(self, rng, active: bool = True, epsilon: float = EPSILON):
        self.rng, self.active, self.eps = rng, active, epsilon

    def propensities(self, proposal: str):
        alts = [a for a in ACTIONS if a != proposal]
        p = {proposal: 1 - self.eps}
        p.update({a: self.eps / len(alts) for a in alts})
        return p

    def choose(self, proposal: str, randomizable: bool):
        u = self.rng.random()
        if not (self.active and randomizable):
            return proposal, 1.0, False
        if u < 1 - self.eps:
            return proposal, 1 - self.eps, True
        alts = [a for a in ACTIONS if a != proposal]
        i = min(int((u - (1 - self.eps)) / (self.eps / len(alts))), len(alts) - 1)
        return alts[i], self.eps / len(alts), True
