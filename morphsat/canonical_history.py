"""
Canonical history store (P3, preregistration v2 / v2.1).
=========================================================

Append-only store of the system's own canonical outcomes, one immutable
``HistoryRecord`` per episode, written AFTER that episode's stores were
written. Records carry no evaluation or scenario-label fields.

Temporal semantics (v2.1 A2):
    * the store may physically contain records later than a target event;
      ``candidates()`` makes them invisible (strict ``order < i``);
    * ``supersedes`` is computed at write time and may only point to earlier
      records of the same run (forward reference -> ValueError).

Candidate retrieval (v2.1 A1) is representation-independent: same run,
``order < i``, alert-tag overlap >= 2, ``resolved_by != "arbitration"``,
then the ``k_max`` most recent by order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional, Tuple

MIN_TAG_OVERLAP = 2
K_MAX = 5


def alert_tags(text: str) -> FrozenSet[str]:
    """Same tag rule as CorrectionEcho / graph routing: alpha words > 3 chars."""
    return frozenset(w.lower() for w in text.split() if len(w) > 3 and w.isalpha())


def evidence_lean(threat_score: float, safety_score: float) -> str:
    """Contemporaneous evidence lean from final monitor scores (B1 content)."""
    b = threat_score - safety_score
    return "escalate" if b > 0 else "benign" if b < 0 else "neutral"


@dataclass(frozen=True)
class HistoryRecord:
    outcome_ref: str
    run_id: str
    order: int
    episode_key: str                    # f"{family}/{scenario_id}" (identifier only)
    alert_tags: Tuple[str, ...]
    evidence_signature: Tuple[Tuple[str, str], ...]
    final_action: str                   # COMMIT | ABSTAIN (never DEFER)
    final_direction: Optional[str]
    evidence_lean: str                  # escalate | benign | neutral
    correction_detected: bool           # system evidence category "correction"
    supersedes: Tuple[str, ...]         # outcome_refs, computed at write time
    resolved_by: str                    # monitor | arbitration
    override_source: str = "none"


class CanonicalHistory:
    def __init__(self) -> None:
        self._records: List[HistoryRecord] = []
        self._by_ref: Dict[str, HistoryRecord] = {}

    def __len__(self) -> int:
        return len(self._records)

    @property
    def records(self) -> Tuple[HistoryRecord, ...]:
        return tuple(self._records)

    def get(self, ref: str) -> Optional[HistoryRecord]:
        return self._by_ref.get(ref)

    def compute_supersedes(self, run_id: str, order: int, tags: FrozenSet[str],
                           final_action: str, final_direction: Optional[str],
                           correction_detected: bool) -> Tuple[str, ...]:
        """Refs this record supersedes, knowable at its write time."""
        if not (correction_detected and final_action == "COMMIT"):
            return ()
        return tuple(
            r.outcome_ref for r in self._records
            if r.run_id == run_id and r.order < order
            and r.resolved_by != "arbitration"
            and r.final_action == "COMMIT"
            and r.final_direction != final_direction
            and len(tags & set(r.alert_tags)) >= MIN_TAG_OVERLAP)

    def append(self, record: HistoryRecord) -> None:
        if record.final_action not in ("COMMIT", "ABSTAIN"):
            raise ValueError(f"history records are final outcomes, got {record.final_action}")
        if record.outcome_ref in self._by_ref:
            raise ValueError("duplicate outcome_ref")
        for ref in record.supersedes:
            prior = self._by_ref.get(ref)
            if prior is None or prior.run_id != record.run_id or prior.order >= record.order:
                raise ValueError(f"supersedes forward/unknown reference: {ref}")
        self._records.append(record)
        self._by_ref[record.outcome_ref] = record

    def candidates(self, run_id: str, order: int, tags: FrozenSet[str],
                   k_max: int = K_MAX) -> Tuple[HistoryRecord, ...]:
        """Representation-independent slots for a request at ``order``."""
        pool = [r for r in self._records
                if r.run_id == run_id and r.order < order
                and r.resolved_by != "arbitration"
                and len(tags & set(r.alert_tags)) >= MIN_TAG_OVERLAP]
        pool.sort(key=lambda r: r.order)
        return tuple(pool[-k_max:]) if k_max > 0 else ()
