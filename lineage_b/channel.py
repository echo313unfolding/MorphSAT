"""Delivery channel: delay, MCAR dropout, transport redelivery, relay alias
(B0 §5). EVALUATOR ONLY."""

from __future__ import annotations

import math
from typing import Dict, List

from lineage_b.obs import Record
from lineage_b.params import DECLARED_UPSTREAM, REDELIVERY_P, T_F


def channel_params(sensor: str, condition: str, g: int):
    """(drop probability, geometric delay p or None) for a measurement at g."""
    if condition == "C5" and g >= T_F:
        if sensor == "L3":
            return 0.0, 0.5
        if sensor in ("L1", "L2"):
            return 0.10, None
        if sensor == "P":
            return 0.30, None
    return 0.0, None


class Channel:
    def __init__(self, rng, condition: str):
        self.rng = rng
        self.condition = condition
        self.pending: List[Record] = []
        self.seq: Dict[str, int] = {}
        self.dropped: List[tuple] = []

    def _seq(self, s):
        self.seq[s] = self.seq.get(s, -1) + 1
        return self.seq[s]

    def push(self, t: int, g: int, readings: Dict[str, float]):
        for s in ("L1", "L2", "L3", "F", "P"):
            u_drop, u_delay, u_red = self.rng["ch_" + s].random(3)   # fixed draws
            seq = self._seq(s)
            p_drop, p_geo = channel_params(s, self.condition, g)
            if u_drop < p_drop:
                self.dropped.append((s, seq, t))
                continue
            d = 0 if p_geo is None else max(1, math.ceil(math.log(1 - u_delay) / math.log(1 - p_geo)))
            rec = Record(s, seq, t, t + d, float(readings[s]), DECLARED_UPSTREAM[s])
            self.pending.append(rec)
            if u_red < REDELIVERY_P:
                self.pending.append(Record(s, seq, t, t + d + 1, float(readings[s]), DECLARED_UPSTREAM[s]))
            if s == "L1" and self.condition == "C3" and g >= T_F:
                self.pending.append(Record("L4", self._seq("L4"), t, t + d, float(readings[s]),
                                           DECLARED_UPSTREAM["L4"]))

    def push_inspection(self, measured_at: int, report: str):
        self.pending.append(Record("INSPECT", self._seq("INSPECT"), measured_at, measured_at + 1,
                                   report, DECLARED_UPSTREAM["INSPECT"]))

    def deliver(self, t: int) -> List[Record]:
        out = [r for r in self.pending if r.delivered_at == t]
        self.pending = [r for r in self.pending if r.delivered_at != t]
        return sorted(out, key=lambda r: (r.sensor_id, r.seq, r.delivered_at))
