"""Immutable decision and feedback records (B0 §9, gates 9 and 19)."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from lineage_b.receipts import canonical


def _hash(d: Dict[str, Any]) -> str:
    d = {k: v for k, v in d.items() if k != "canonical_hash"}
    return hashlib.sha256(canonical(d).encode()).hexdigest()


@dataclass(frozen=True)
class ControlDecisionEvent:
    deployment: str
    episode: int
    t: int
    arm: str
    belief: Dict[str, float]               # mean_h, sd_h, p_leak, digest
    monitor_action: str
    monitor_direction: Optional[str]
    terminal: bool
    authority_path: str                    # interlock | terminal_abstain | arbitration
    controller_reason: Dict[str, Any]      # expected cost per candidate, inspect trigger
    proposal: Optional[str]
    final_action: str
    resolved_by: str
    theta_hash: str
    receipt_hash: str
    propensity: float
    randomized: bool
    visible_digest: str
    canonical_hash: str = ""

    def __post_init__(self):
        object.__setattr__(self, "canonical_hash", _hash(asdict(self)))


@dataclass(frozen=True)
class FeedbackRecord:
    deployment: str
    episode: int
    sensor_id: str
    seq: int
    measured_at: int
    delivered_at: int
    receipt_key: Tuple[int, int]
    receipt_hash: str
    decision_ref: str                      # canonical_hash of the decision that preceded the receipt
    observed: float
    provenance: Dict[str, str]
    residual: float
    log_score: float
    brier: float
    theta_before_hash: str
    theta_after_hash: str
    update_applied: bool
    canonical_hash: str = ""

    def __post_init__(self):
        object.__setattr__(self, "canonical_hash", _hash(asdict(self)))


class AppendOnlyStore:
    def __init__(self):
        self._items: List[Any] = []

    def append(self, item) -> None:
        self._items.append(item)

    def items(self) -> Tuple[Any, ...]:
        return tuple(self._items)

    def digest(self) -> str:
        return hashlib.sha256("".join(i.canonical_hash for i in self._items).encode()).hexdigest()

    def verify(self) -> bool:
        return all(i.canonical_hash == _hash(asdict(i)) for i in self._items)
