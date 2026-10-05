"""Frozen authority layer and thin adapter over the unchanged
morphsat.terminal_authority (B0 §8, gate 12)."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from morphsat.terminal_authority import resolve_terminal_authority
from lineage_b.obs import Record
from lineage_b.params import D_MAX, IL_HI, IL_LO, LEVEL_IL


def latest_values(records: Dict[tuple, Record], t: int) -> Dict[str, Optional[float]]:
    out = {}
    for s in LEVEL_IL:
        cands = [r for r in records.values() if r.sensor_id == s and t - D_MAX <= r.measured_at <= t]
        out[s] = max(cands, key=lambda r: (r.measured_at, r.seq)).value if cands else None
    return out


def monitor(records: Dict[tuple, Record], t: int) -> Tuple[str, Optional[str], bool, str]:
    """(action, direction, terminal, path). Never reads theta or belief."""
    v = latest_values(records, t)
    vals = [x for x in v.values() if x is not None]
    if len(LEVEL_IL) - len(vals) >= 2:
        return "ABSTAIN", None, True, "terminal_abstain"
    if sum(x >= IL_HI for x in vals) >= 2:
        return "COMMIT", "open", True, "interlock"
    if sum(x <= IL_LO for x in vals) >= 2:
        return "COMMIT", "close", True, "interlock"
    return "DEFER", None, False, "arbitration"


def resolve(mon: Tuple[str, Optional[str], bool, str], proposal: Optional[str]):
    """Return (final_action, resolved_by). The proposal is submitted only on DEFER."""
    action, direction, terminal, path = mon
    if action == "DEFER":
        if proposal == "inspect":
            r = resolve_terminal_authority("DEFER", None, False, "ABSTAIN", None, "arbitration")
        else:
            r = resolve_terminal_authority("DEFER", None, False, "COMMIT", proposal, "arbitration")
    else:
        r = resolve_terminal_authority(action, direction, terminal)
    final = "inspect" if r.final_action == "ABSTAIN" else r.final_direction
    if r.final_action == "DEFER" or final is None:
        raise RuntimeError("unresolved decision")
    return final, r.applied_source
