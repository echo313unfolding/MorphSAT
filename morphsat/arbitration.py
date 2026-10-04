"""
DEFER arbitration (P3, preregistration v2 + v2.1).
===================================================

Entered ONLY from DEFER. Output is COMMIT(direction) or ABSTAIN, citing the
history records used and excluded. One shared policy; baselines differ only
in how the SAME slots are projected:

    B0   no history                         -> always ABSTAIN
    B1   slot evidence lean                 (no canonical information)
    B2   slot canonical outcome, ordered    (no causal links)
    B2M  B2 + noncausal hash mask of k slots (k = number B3 excludes)
    B3   B2 + supersession exclusion        (causal provenance)

Frozen policy (v2 §7): >= 2 directional votes; share >= 0.75 with
denominator = directional votes + uncertainty among active slots;
benign additionally requires balance <= 0.0 (raw floats, no epsilon) and no
current THREAT_SIGNALS category. No evaluation label is an input.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from morphsat.canonical_history import HistoryRecord, K_MAX
from morphsat.commit_gate import THREAT_SIGNALS
from morphsat.receipt_chain import canonical_hash

BASELINES = ("B0", "B1", "B2", "B2M", "B3")
MIN_DIRECTIONAL = 2
MIN_SHARE = 0.75
THREAT_CATEGORIES = frozenset(THREAT_SIGNALS)


@dataclass(frozen=True)
class ArbitrationRequest:
    run_id: str
    order: int
    target_key: str                       # f"{family}/{scenario_id}"
    episode_id: str
    baseline: str
    reason_for_defer: str
    threat_score: float                   # at DEFER emission
    safety_score: float
    contradiction: float
    evidence_signature: Tuple[Tuple[str, str], ...]
    alert_tags: Tuple[str, ...]
    slots: Tuple[HistoryRecord, ...]

    def validate(self) -> None:
        if self.baseline not in BASELINES:
            raise ValueError(f"unknown baseline {self.baseline}")
        if len(self.slots) > K_MAX:
            raise ValueError("too many slots")
        for r in self.slots:
            if r.run_id != self.run_id or r.order >= self.order:
                raise ValueError(f"future/foreign record in request: {r.outcome_ref}")
            if r.resolved_by == "arbitration":
                raise ValueError("arbitration-resolved record in request")

    @property
    def balance(self) -> float:
        return self.threat_score - self.safety_score

    def payload(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id, "order": self.order,
            "target_key": self.target_key, "episode_id": self.episode_id,
            "baseline": self.baseline, "reason_for_defer": self.reason_for_defer,
            "threat_score": round(self.threat_score, 6),
            "safety_score": round(self.safety_score, 6),
            "contradiction": round(self.contradiction, 6),
            "evidence_signature": [list(x) for x in self.evidence_signature],
            "alert_tags": list(self.alert_tags),
            "slot_refs": [r.outcome_ref for r in self.slots],
            "policy": {"min_directional": MIN_DIRECTIONAL, "min_share": MIN_SHARE,
                       "k_max": K_MAX},
        }

    @property
    def request_hash(self) -> str:
        return canonical_hash(self.payload())


@dataclass(frozen=True)
class ArbitrationResult:
    action: str                           # COMMIT | ABSTAIN
    direction: Optional[str]
    backend: str
    reason: str
    criterion_met: bool
    records_used: Tuple[str, ...]
    records_excluded: Tuple[Tuple[str, str], ...]   # (ref, reason)
    votes: Tuple[Tuple[str, int], ...]
    n_directional: int
    n_uncertain: int
    share: float
    request_hash: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["share"] = round(self.share, 6)
        d["result_hash"] = self.result_hash
        return d

    @property
    def result_hash(self) -> str:
        d = asdict(self)
        d["share"] = round(self.share, 6)
        return canonical_hash(d)


# ---------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------

def supersession_exclusions(slots: Tuple[HistoryRecord, ...]) -> List[str]:
    """B3: refs excluded because another slot in the SAME slot set supersedes them."""
    refs = {r.outcome_ref for r in slots}
    out = []
    for r in slots:
        if any(r.outcome_ref in c.supersedes and c.order > r.order
               for c in slots if c.outcome_ref in refs and c is not r):
            out.append(r.outcome_ref)
    return out


def sham_mask(target_key: str, slots: Tuple[HistoryRecord, ...], k: int) -> List[str]:
    """B2M: frozen noncausal mask — rank by sha256(target|slot key), mask first k."""
    if k <= 0:
        return []
    ranked = sorted(
        slots,
        key=lambda r: hashlib.sha256(
            f"{target_key}|{r.episode_key}".encode("utf-8")).hexdigest())
    return [r.outcome_ref for r in ranked[:k]]


def project(baseline: str, r: HistoryRecord) -> Optional[str]:
    """Directional vote for an active slot, or None for uncertainty."""
    if baseline == "B1":
        return None if r.evidence_lean == "neutral" else r.evidence_lean
    # B2 / B2M / B3: canonical outcome
    return r.final_direction if r.final_action == "COMMIT" else None


# ---------------------------------------------------------------------------
# Arbitration
# ---------------------------------------------------------------------------

def arbitrate(req: ArbitrationRequest) -> ArbitrationResult:
    req.validate()
    rh = req.request_hash

    def result(action, direction, reason, met, used, excluded, votes, nd, nu, share):
        return ArbitrationResult(action, direction, req.baseline, reason, met,
                                 tuple(used), tuple(excluded),
                                 tuple(sorted(votes.items())), nd, nu, share, rh)

    if req.baseline == "B0":
        return result("ABSTAIN", None, "B0: no history available", False,
                      [], [], {}, 0, 0, 0.0)
    if len(req.slots) < MIN_DIRECTIONAL:
        return result("ABSTAIN", None, "history-ineligible (< 2 candidate records)",
                      False, [], [], {}, 0, 0, 0.0)

    excluded: List[Tuple[str, str]] = []
    if req.baseline == "B3":
        excluded = [(ref, "superseded") for ref in supersession_exclusions(req.slots)]
    elif req.baseline == "B2M":
        k = len(supersession_exclusions(req.slots))
        excluded = [(ref, "sham_mask") for ref in sham_mask(req.target_key, req.slots, k)]
    ex_refs = {ref for ref, _ in excluded}
    active = [r for r in req.slots if r.outcome_ref not in ex_refs]

    votes: Dict[str, int] = {}
    n_uncertain = 0
    for r in active:
        v = project(req.baseline, r)
        if v is None:
            n_uncertain += 1
        else:
            votes[v] = votes.get(v, 0) + 1
    n_dir = sum(votes.values())
    used = [r.outcome_ref for r in active]
    if n_dir < MIN_DIRECTIONAL:
        return result("ABSTAIN", None, f"{n_dir} directional votes < {MIN_DIRECTIONAL}",
                      False, used, excluded, votes, n_dir, n_uncertain, 0.0)

    top = sorted(votes.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    share = top[1] / (n_dir + n_uncertain)
    if share < MIN_SHARE:
        return result("ABSTAIN", None, f"share {top[1]}/{n_dir + n_uncertain} < {MIN_SHARE}",
                      False, used, excluded, votes, n_dir, n_uncertain, share)

    direction = top[0]
    if direction == "benign":
        if not (req.balance <= 0.0):
            return result("ABSTAIN", None, f"benign guard: balance {req.balance!r} > 0",
                          False, used, excluded, votes, n_dir, n_uncertain, share)
        cats = {c for _, c in req.evidence_signature} & THREAT_CATEGORIES
        if cats:
            return result("ABSTAIN", None, f"benign guard: live threat evidence {sorted(cats)}",
                          False, used, excluded, votes, n_dir, n_uncertain, share)
    return result("COMMIT", direction,
                  f"{top[1]}/{n_dir + n_uncertain} votes for {direction}",
                  True, used, excluded, votes, n_dir, n_uncertain, share)
