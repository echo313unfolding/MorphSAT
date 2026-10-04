"""Record and pattern types (prereg v1.1 §4, v1.3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple

BENIGN, THREAT = "benign", "threat"


def opposite(d: str) -> str:
    return THREAT if d == BENIGN else BENIGN


@dataclass(frozen=True)
class ObservationRecord:
    order: int
    direction: str          # benign | threat
    source_id: str          # apparent identity
    upstream_id: str        # true origin
    is_correction: bool = False


@dataclass(frozen=True)
class DeclaredRecord:
    """What a declared-origin system (Corollary model) can see: no upstream_id."""
    order: int
    direction: str
    source_id: str
    is_correction: bool = False


def declared_view(records) -> Tuple[DeclaredRecord, ...]:
    return tuple(DeclaredRecord(r.order, r.direction, r.source_id, r.is_correction)
                 for r in records)


@dataclass(frozen=True)
class Pattern:
    pid: str                                  # opaque identifier
    family: str                               # FAM-G | FAM-T (evaluation only)
    cell: str                                 # structure cell (evaluation only)
    records: Tuple[ObservationRecord, ...]    # the ONLY policy-visible content
    meta: Dict[str, object] = field(default_factory=dict, hash=False, compare=False)

    @property
    def correction(self) -> ObservationRecord:
        return next(r for r in self.records if r.is_correction)
