"""Agent-visible record types (B0 §5). Carries no hidden fields."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

VALUE, PENDING, MISSING = "VALUE", "PENDING", "MISSING"


@dataclass(frozen=True)
class Record:
    sensor_id: str
    seq: int
    measured_at: int
    delivered_at: int
    value: Union[float, str]
    declared_upstream: str

    @property
    def key(self):
        return (self.sensor_id, self.seq)
