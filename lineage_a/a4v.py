"""A4V upstream-alias veto (A4V prereg v1.1 §3–§4).

Sees ONLY ObservationRecord fields. Reuses frozen K, A4 and the S2 shuffle;
introduces no threshold. A veto can only turn an A4 ACCEPT into ABSTAIN.
"""

from __future__ import annotations

from typing import Sequence, Tuple

from lineage_a.policies import ABSTAIN, ACCEPT, K, a4_corroboration, shuffle_ids
from lineage_a.records import ObservationRecord


def alias_counts(records: Sequence[ObservationRecord]) -> Tuple[int, int]:
    """(n_src, n_up) over post-correction records supporting the correction,
    excluding the correction's own source_id / upstream_id respectively."""
    c = next(r for r in records if r.is_correction)
    sup = [r for r in records if r.order > c.order and r.direction == c.direction]
    return (len({r.source_id for r in sup if r.source_id != c.source_id}),
            len({r.upstream_id for r in sup if r.upstream_id != c.upstream_id}))


def alias_veto_fires(records: Sequence[ObservationRecord]) -> bool:
    if a4_corroboration(records) != ACCEPT:
        return False
    n_src, n_up = alias_counts(records)
    return n_src >= K and n_up < K


def a4v(records: Sequence[ObservationRecord]) -> str:
    return ABSTAIN if alias_veto_fires(records) else a4_corroboration(records)


def a4v_shuffle_sham(records: Sequence[ObservationRecord], pid: str) -> str:
    """A4 on the original records; veto evaluated on frozen-shuffled ids."""
    base = a4_corroboration(records)
    return ABSTAIN if alias_veto_fires(shuffle_ids(pid, records)) else base


def a4v_wide(records: Sequence[ObservationRecord]) -> str:
    """Diagnostic only: veto any A4 ACCEPT with < K independent upstreams."""
    base = a4_corroboration(records)
    return ABSTAIN if base == ACCEPT and alias_counts(records)[1] < K else base


def a4v_corr_alias(records: Sequence[ObservationRecord]) -> str:
    """Subtype decomposition (§8): veto only when no supporting upstream
    other than the correction's (n_up = 0)."""
    return ABSTAIN if alias_veto_fires(records) and alias_counts(records)[1] == 0 \
        else a4_corroboration(records)


def a4v_other_alias(records: Sequence[ObservationRecord]) -> str:
    """Subtype decomposition (§8): veto only when support collapses onto one
    non-correction upstream (n_up = 1)."""
    return ABSTAIN if alias_veto_fires(records) and alias_counts(records)[1] == 1 \
        else a4_corroboration(records)
