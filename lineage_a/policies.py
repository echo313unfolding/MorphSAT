"""Frozen policies (prereg v1.0 §6, v1.1 §5, v1.3 Amendment 2).

Policies see ONLY ObservationRecord fields. Thresholds k=2 and share 0.75
are frozen design parameters inherited from P3. Output: ACCEPT | REJECT |
ABSTAIN (ACCEPT = believe the correction's direction).
"""

from __future__ import annotations

import hashlib
from typing import Callable, Dict, Sequence

from lineage_a.records import ObservationRecord

K = 2
SHARE = 0.75
ACCEPT, REJECT, ABSTAIN = "ACCEPT", "REJECT", "ABSTAIN"


def _corr(records):
    return next(r for r in records if r.is_correction)


def _post(records):
    c = _corr(records)
    return [r for r in records if r.order > c.order]


def _vote(records, c_dir: str) -> str:
    counts: Dict[str, int] = {}
    for r in records:
        counts[r.direction] = counts.get(r.direction, 0) + 1
    if not counts:
        return ABSTAIN
    top, n = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    if n >= K and n / sum(counts.values()) >= SHARE:
        return ACCEPT if top == c_dir else REJECT
    return ABSTAIN


def a1_majority(records: Sequence[ObservationRecord]) -> str:
    return _vote(records, _corr(records).direction)


def a2_recency(records: Sequence[ObservationRecord]) -> str:
    last = max(records, key=lambda r: r.order)
    return ACCEPT if last.direction == _corr(records).direction else REJECT


def a3a_unconditional(records: Sequence[ObservationRecord]) -> str:
    return ACCEPT


def a3b_frozen_b3(records: Sequence[ObservationRecord]) -> str:
    c = _corr(records)
    kept = [r for r in records if not (r.order < c.order and r.direction != c.direction)]
    return _vote(kept, c.direction)


def _gated(support: int, contradict: int) -> str:
    if support >= K and contradict == 0:
        return ACCEPT
    if contradict >= K and support == 0:
        return REJECT
    return ABSTAIN


def a4_corroboration(records: Sequence[ObservationRecord]) -> str:
    c = _corr(records)
    post = _post(records)
    return _gated(sum(r.direction == c.direction for r in post),
                  sum(r.direction != c.direction for r in post))


def a5_independent(records: Sequence[ObservationRecord]) -> str:
    c = _corr(records)
    post = [r for r in _post(records) if r.upstream_id != c.upstream_id]
    return _gated(len({r.upstream_id for r in post if r.direction == c.direction}),
                  len({r.upstream_id for r in post if r.direction != c.direction}))


def a5n_naive(records: Sequence[ObservationRecord]) -> str:
    c = _corr(records)
    post = [r for r in _post(records) if r.source_id != c.source_id]
    return _gated(len({r.source_id for r in post if r.direction == c.direction}),
                  len({r.source_id for r in post if r.direction != c.direction}))


def s1_count_sham(records: Sequence[ObservationRecord]) -> str:
    return ACCEPT if len(_post(records)) >= K else ABSTAIN


def shuffle_ids(pid: str, records: Sequence[ObservationRecord]):
    """Frozen S2 rule (v1.1 §5): permute (source_id, upstream_id) pairs of
    non-correction records by sha256(f"{pid}|{order}") ranking."""
    non = sorted((r for r in records if not r.is_correction), key=lambda r: r.order)
    pairs = [(r.source_id, r.upstream_id) for r in non]
    ranked = sorted(non, key=lambda r: hashlib.sha256(f"{pid}|{r.order}".encode("utf-8")).hexdigest())
    new_ids = {r.order: pairs[i] for i, r in enumerate(ranked)}
    out = []
    for r in records:
        if r.is_correction:
            out.append(r)
        else:
            s, u = new_ids[r.order]
            out.append(ObservationRecord(r.order, r.direction, s, u, False))
    return tuple(out)


def s2_shuffle_sham(records: Sequence[ObservationRecord], pid: str) -> str:
    return a5_independent(shuffle_ids(pid, records))


def s3_always_abstain(records) -> str:
    return ABSTAIN


def s4_never_accept(records) -> str:
    return REJECT


POLICIES: Dict[str, Callable] = {
    "A1": a1_majority, "A2": a2_recency, "A3a": a3a_unconditional,
    "A3b": a3b_frozen_b3, "A4": a4_corroboration, "A5": a5_independent,
    "A5n": a5n_naive, "S1": s1_count_sham, "S3": s3_always_abstain,
    "S4": s4_never_accept,
}
