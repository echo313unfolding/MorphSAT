"""
Terminal authority (P2B, decision D1 = A2).
============================================

Invariant:

    If the monitor has reached a terminal COMMIT or terminal ABSTAIN,
    downstream stages (QUBO, CorrectionEcho, ...) may be evaluated and
    recorded for provenance, but MUST NOT replace the emitted terminal
    result.

    monitor_terminal and monitor_action in {COMMIT, ABSTAIN}
        => final_action == monitor_action
           and final_direction == monitor_direction

For ABSTAIN the monitor direction is None and stays None: no substantive
direction is fabricated to satisfy a schema.

A downstream proposal that agrees with the monitor is not an override
attempt. A disagreeing proposal is an attempt; if the monitor is terminal
it is blocked and preserved as provenance (attempted_*), never erased.

SWARM_CALL resolves as action ABSTAIN in ShadowMonitor and is therefore
covered by the ABSTAIN rule; its semantics are not redesigned here.

P3 (prereg v2/v2.1): DEFER is nonterminal. It may be resolved ONLY by a
proposal whose source is ``arbitration``, and only to COMMIT or ABSTAIN.
Any other proposal on DEFER is blocked (provenance kept) and the result stays
DEFER, which the caller must then send to arbitration; a final DEFER is an
invariant violation. Arbitration on a terminal COMMIT/ABSTAIN fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

TERMINAL_AUTHORITY_ACTIONS = frozenset({"COMMIT", "ABSTAIN"})
ARBITRATION_SOURCE = "arbitration"
ARBITRATION_OUTCOMES = frozenset({"COMMIT", "ABSTAIN"})


@dataclass(frozen=True)
class AuthorityResult:
    final_action: str
    final_direction: Optional[str]
    applied_source: str               # stage whose output became final ("none" = monitor)
    attempted: bool                   # a downstream stage proposed something different
    attempted_source: str             # "none" if no attempt
    attempted_action: Optional[str]
    attempted_direction: Optional[str]
    blocked_by_terminal: bool


def resolve_terminal_authority(
    monitor_action: str,
    monitor_direction: Optional[str],
    monitor_terminal: bool,
    proposed_action: Optional[str] = None,
    proposed_direction: Optional[str] = None,
    proposed_source: str = "none",
) -> AuthorityResult:
    """Decide the emitted result given the monitor result and one proposal."""
    monitor_result = (monitor_action, monitor_direction)

    if proposed_source == ARBITRATION_SOURCE and monitor_action != "DEFER":
        raise ValueError(
            f"arbitration may only resolve DEFER, not {monitor_action}")

    if monitor_action == "DEFER":
        if proposed_source == ARBITRATION_SOURCE:
            if proposed_action not in ARBITRATION_OUTCOMES:
                raise ValueError(
                    f"arbitration must yield COMMIT or ABSTAIN, got {proposed_action}")
            if proposed_action == "ABSTAIN" and proposed_direction is not None:
                raise ValueError("ABSTAIN carries no direction")
            if proposed_action == "COMMIT" and proposed_direction is None:
                raise ValueError("COMMIT requires a direction")
            return AuthorityResult(proposed_action, proposed_direction,
                                   ARBITRATION_SOURCE, False, "none", None,
                                   None, False)
        if proposed_source == "none":
            return AuthorityResult("DEFER", None, "none", False, "none",
                                   None, None, False)
        # Non-arbitration proposal on DEFER: blocked, decision stays open.
        return AuthorityResult("DEFER", None, "none", True, proposed_source,
                               proposed_action, proposed_direction, True)

    if proposed_source == "none":
        return AuthorityResult(monitor_action, monitor_direction, "none",
                               False, "none", None, None, False)

    if (proposed_action, proposed_direction) == monitor_result:
        # Agreement: the downstream stage assigned the same result.
        return AuthorityResult(monitor_action, monitor_direction,
                               proposed_source, False, "none", None, None,
                               False)

    if monitor_terminal and monitor_action in TERMINAL_AUTHORITY_ACTIONS:
        return AuthorityResult(monitor_action, monitor_direction, "none",
                               True, proposed_source, proposed_action,
                               proposed_direction, True)

    return AuthorityResult(proposed_action, proposed_direction,
                           proposed_source, True, proposed_source,
                           proposed_action, proposed_direction, False)
