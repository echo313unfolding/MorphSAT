"""
Correction Echo — short-lived routing marker after correction episodes.
=====================================================================

When a correction receipt is committed, the echo stores a marker with
the correction's entity tags. For the next N episodes, if a new alert
overlaps those tags, the echo fires: correction_related=True,
routing_triggered=True → TwoStageGate routes to QUBO.

The echo is not a verdict. It is a routing tap:
    "This pattern was recently corrected. Don't trust normal routing.
     Call the foreman meeting."

This replaces SplitMemory's implicit routing effect — the old guy's
reflex that said "this smells familiar, think harder" — with an
explicit, receipted, expiring graph-side marker.

Lineage:
    SplitMemory.lookup() → CDR trace → old_guy_helped=0/72 →
    real value was routing tap → CorrectionEcho (explicit version)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class EchoMarker:
    """A short-lived correction echo marker."""
    tags: Set[str]                    # entity tags from the correction episode
    created_at_episode: int           # episode index when created
    source_scenario_id: str           # which scenario triggered this
    outcome_before: str               # what the graph thought before correction
    outcome_after: str                # what the correction changed it to
    ttl: int                          # episodes remaining before expiry
    fired_count: int = 0              # how many times this echo triggered routing
    reinforced: bool = False          # set True when a later episode confirms


class CorrectionEcho:
    """Short-lived correction routing markers for ReceiptGraph.

    When a correction episode happens:
        1. Extract stable tags from the alert
        2. Store an EchoMarker with those tags and a TTL
        3. For the next N episodes, check new alerts against markers
        4. If tags overlap sufficiently → fire correction_related signal
        5. Marker expires after TTL or after reinforcement

    The echo does NOT decide verdicts. It only says:
        "Route this to QUBO because a recent correction touched similar ground."
    """

    def __init__(self, ttl: int = 5, min_tag_overlap: int = 2):
        self.ttl = ttl
        self.min_tag_overlap = min_tag_overlap
        self.markers: List[EchoMarker] = []
        self._episode_counter: int = 0

    def observe_episode(
        self,
        alert_text: str,
        scenario_id: str,
        is_correction: bool,
        outcome: str,
        prior_outcome: str = "unknown",
    ) -> None:
        """Called after each episode completes.

        If this episode is a correction, create a new echo marker.
        Always advances the episode counter and decays existing markers.
        """
        self._episode_counter += 1

        if is_correction:
            tags = self._extract_tags(alert_text)
            if tags:
                marker = EchoMarker(
                    tags=tags,
                    created_at_episode=self._episode_counter,
                    source_scenario_id=scenario_id,
                    outcome_before=prior_outcome,
                    outcome_after=outcome,
                    ttl=self.ttl,
                )
                self.markers.append(marker)

        # Decay all markers
        for marker in self.markers:
            if not marker.reinforced:
                marker.ttl -= 1

        # Remove expired markers
        self.markers = [m for m in self.markers if m.ttl > 0]

    def check(self, alert_text: str) -> Tuple[bool, Optional[EchoMarker]]:
        """Check if a new alert overlaps with any active correction echo.

        Returns (triggered, matching_marker).
        Does NOT modify state — this is a read-only probe.
        """
        if not self.markers:
            return False, None

        alert_tags = self._extract_tags(alert_text)
        if not alert_tags:
            return False, None

        best_marker = None
        best_overlap = 0

        for marker in self.markers:
            overlap = len(alert_tags & marker.tags)
            if overlap >= self.min_tag_overlap and overlap > best_overlap:
                best_overlap = overlap
                best_marker = marker

        if best_marker is not None:
            best_marker.fired_count += 1
            return True, best_marker

        return False, None

    def reinforce(self, marker: EchoMarker) -> None:
        """Mark a marker as reinforced (echo was useful).

        Reinforced markers don't decay — they persist until explicitly
        absorbed into the graph's permanent memory.
        """
        marker.reinforced = True

    @property
    def active_marker_count(self) -> int:
        return len(self.markers)

    @property
    def episode_count(self) -> int:
        return self._episode_counter

    def to_dict(self) -> Dict:
        """Serialize for receipt."""
        return {
            "episode_counter": self._episode_counter,
            "active_markers": len(self.markers),
            "markers": [
                {
                    "tags": sorted(m.tags),
                    "created_at_episode": m.created_at_episode,
                    "source_scenario_id": m.source_scenario_id,
                    "outcome_before": m.outcome_before,
                    "outcome_after": m.outcome_after,
                    "ttl": m.ttl,
                    "fired_count": m.fired_count,
                    "reinforced": m.reinforced,
                }
                for m in self.markers
            ],
        }

    @staticmethod
    def _extract_tags(text: str) -> Set[str]:
        """Extract stable entity tags from alert text.

        Same logic as graph_routing_signal: words > 3 chars, alpha, lowercase.
        """
        return {
            w.lower() for w in text.split()
            if len(w) > 3 and w.isalpha()
        }
