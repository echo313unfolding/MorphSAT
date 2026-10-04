"""External-artifact comparators C1/C2 (prereg v1.3 Amendment 1).

Models gabe-santana/corollary@3c25939 (kernel.assert_, _confidence,
_premise_confidence, _credit_confirmation; ledger.reliability;
trust default tool prior; resolvers.PreferHigherConfidence margin 0).
Sees ONLY the declared view (order, direction, source_id, is_correction).
Declared origin = source_id. The artifact's weakness is preserved.
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from lineage_a.records import DeclaredRecord

P0 = 0.95            # Corollary TrustPolicy default for kind "tool"
PRIOR_WEIGHT = 10.0  # Corollary TrustLedger default
ACCEPT, REJECT = "ACCEPT", "REJECT"


def _run(records: Sequence[DeclaredRecord], credit: bool):
    supporters: Dict[str, List[str]] = {}    # value -> sources (declared origin == source)
    created: Dict[str, int] = {}             # value -> order of first assertion
    correct: Dict[str, int] = {}
    total: Dict[str, int] = {}
    for rec in sorted(records, key=lambda r: r.order):
        v, s = rec.direction, rec.source_id
        if v not in supporters:
            supporters[v] = [s]
            created[v] = rec.order
            continue
        if s in supporters[v]:
            continue                                     # repeat: replaces, no credit
        others = [o for o in supporters[v] if o != s]   # different declared origin
        supporters[v].append(s)
        if credit and others:
            for src in others + [s]:
                correct[src] = correct.get(src, 0) + 1
                total[src] = total.get(src, 0) + 1

    def reliability(src: str) -> float:
        t = total.get(src, 0)
        if t == 0:
            return P0
        return (P0 * PRIOR_WEIGHT + correct.get(src, 0)) / (PRIOR_WEIGHT + t)

    conf = {}
    for v, srcs in supporters.items():
        doubt = 1.0
        for src in srcs:                                 # one origin group per source
            doubt *= 1.0 - reliability(src)
        conf[v] = 1.0 - doubt
    return conf, created, {s: reliability(s) for srcs in supporters.values() for s in srcs}


def _decide(records, credit: bool) -> Tuple[str, Dict[str, float]]:
    conf, created, rel = _run(records, credit)
    c_dir = next(r.direction for r in records if r.is_correction)
    if len(conf) == 1:
        belief = next(iter(conf))
    else:
        belief = sorted(conf, key=lambda v: (conf[v], created[v]), reverse=True)[0]
    return (ACCEPT if belief == c_dir else REJECT), rel


def c1_declared_origin(records: Sequence[DeclaredRecord]) -> str:
    return _decide(records, credit=False)[0]


def c2_agreement_credit(records: Sequence[DeclaredRecord]) -> str:
    return _decide(records, credit=True)[0]


def c2_reliabilities(records: Sequence[DeclaredRecord]) -> Dict[str, float]:
    """Diagnostic D3: final per-source reliability under C2."""
    return _decide(records, credit=True)[1]
