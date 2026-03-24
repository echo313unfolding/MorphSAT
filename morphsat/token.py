"""
MorphSAT Token Adjacency Scoring
=================================

Soft constraint scoring over token sequences.

MorphSAT enforces soft constraints on token adjacency:
- Which tokens can follow which (lane-based rules)
- Position-aware masking (``pos_mod4`` for rhythmic structure)
- Soft penalties rather than hard masks, with cosine-annealed temperature

Lane structure (4 lanes)::

    Lane 0 (ENTITY)   -- Nouns / objects
    Lane 1 (ACTION)   -- Verbs
    Lane 2 (QUALITY)  -- Adjectives / modifiers
    Lane 3 (RELATION) -- Prepositions / connectors

Default adjacency rules enforce natural sequential flow::

    ENTITY   -> ACTION or QUALITY
    ACTION   -> QUALITY, RELATION, or ENTITY
    QUALITY  -> RELATION, ENTITY, or ACTION
    RELATION -> ENTITY or ACTION
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np


# Default adjacency rules based on 4-lane semantic structure
# Format: lane -> list of preferred next lanes
DEFAULT_LANE_ADJACENCY: Dict[int, List[int]] = {
    0: [1, 2],      # ENTITY   -> ACTION or QUALITY
    1: [2, 3, 0],   # ACTION   -> QUALITY, RELATION, or ENTITY
    2: [3, 0, 1],   # QUALITY  -> RELATION, ENTITY, or ACTION
    3: [0, 1],      # RELATION -> ENTITY or ACTION
}

# Lane names for reference
LANE_NAMES: List[str] = ["ENTITY", "ACTION", "QUALITY", "RELATION"]


class MorphSATScorer:
    """Token adjacency constraint scorer.

    Applies soft penalties to tokens that violate adjacency rules,
    respecting the 4-lane semantic structure.

    Args:
        morph_table: Optional dict with adjacency rules.
            Keys: ``mode`` (``"simple"`` | ``"prev+pos"`` | ``"lane"``),
            ``adj`` (adjacency mappings), ``default`` (``"all"`` | ``"deny"``).
        sat_T0: Initial temperature for annealing.
        sat_Tmin: Minimum temperature.
        steps_anneal: Steps to reach minimum temperature.
        soft_lambda: Soft penalty magnitude.
    """

    def __init__(
        self,
        morph_table: Optional[Dict[str, Any]] = None,
        sat_T0: float = 1.0,
        sat_Tmin: float = 0.5,
        steps_anneal: int = 200,
        soft_lambda: float = 4.0,
    ):
        self.mt = morph_table
        self.T0 = sat_T0
        self.Tmin = sat_Tmin
        self.N = max(1, steps_anneal)
        self.soft_lambda = soft_lambda
        self.step = 0

    def _allowed_set(
        self, last_token: int, pos_mod4: int, vocab_size: int
    ) -> Optional[List[int]]:
        """Get allowed token indices for ``(prev_token, position_mod4)``.

        Returns ``None`` to allow all tokens, or a list of allowed indices.
        """
        if self.mt is None:
            return self._lane_based_allowed(last_token, pos_mod4, vocab_size)

        mode = self.mt.get("mode", "simple")

        if mode == "prev+pos":
            key = f"{int(last_token)}:{int(pos_mod4)}"
            allowed = self.mt.get("adj", {}).get(key)
            if allowed is None:
                return None if self.mt.get("default", "all") == "all" else []
            return allowed

        if mode == "lane":
            return self._lane_based_allowed(last_token, pos_mod4, vocab_size)

        # Simple mode: just check prev token
        allowed = self.mt.get(str(int(last_token)))
        if allowed is None and self.mt.get("default", "all") == "all":
            return None
        return allowed or []

    def _lane_based_allowed(
        self, last_token: int, pos_mod4: int, vocab_size: int
    ) -> Optional[List[int]]:
        """Lane-based adjacency using 4-lane structure.

        The lane structure creates natural sequential flow when adjacency
        is respected.
        """
        last_lane = last_token % 4
        preferred_lanes = DEFAULT_LANE_ADJACENCY.get(last_lane, [0, 1, 2, 3])
        current_lane = pos_mod4

        if current_lane in preferred_lanes:
            return None

        # Current lane not preferred -- still allow, but score() applies soft penalty
        return None

    def score(
        self,
        prev_token: Optional[str],
        next_token: str,
        prev_idx: Optional[int],
        next_idx: int,
        position: int,
    ) -> float:
        """Score a token transition.

        Args:
            prev_token: Previous token word (or ``None`` if first).
            next_token: Next token word.
            prev_idx: Previous token base index.
            next_idx: Next token base index.
            position: Current position in sequence.

        Returns:
            Score multiplier (``1.0`` = full score, ``< 1.0`` = penalized).

        Note:
            Lane is determined by **position** (``pos % 4``), not by base index.
        """
        if position == 0:
            return 1.0  # No constraint on first token

        prev_lane = (position - 1) % 4
        curr_lane = position % 4

        preferred = DEFAULT_LANE_ADJACENCY.get(prev_lane, [0, 1, 2, 3])

        if curr_lane in preferred:
            return 1.0

        # Apply soft penalty for non-preferred transition
        T = self.temperature()
        self.step += 1
        return math.exp(-self.soft_lambda / T)

    def mask_scores(
        self,
        scores: np.ndarray,
        last_token_idx: Optional[int],
        pos_mod4: int,
    ) -> np.ndarray:
        """Apply soft penalties to a score array.

        Args:
            scores: Array of shape ``[vocab_size]`` with token scores.
            last_token_idx: Previous token index or ``None``.
            pos_mod4: Current position mod 4.

        Returns:
            Modified scores with penalties applied.
        """
        if self.mt is None and last_token_idx is None:
            return scores

        vocab_size = len(scores)
        allowed = self._allowed_set(
            last_token_idx if last_token_idx is not None else 0,
            pos_mod4,
            vocab_size,
        )

        if allowed is None:
            # All allowed -- apply lane-based soft penalties
            if last_token_idx is not None:
                prev_lane = last_token_idx % 4
                preferred = DEFAULT_LANE_ADJACENCY.get(prev_lane, [0, 1, 2, 3])
                curr_lane = pos_mod4

                if curr_lane not in preferred:
                    T = self.temperature()
                    scores = scores - self.soft_lambda / T

            self.step += 1
            return scores

        # Hard constraints from morph_table
        mask = np.full_like(scores, -self.soft_lambda)
        mask[allowed] = 0.0
        T = self.temperature()
        self.step += 1
        return (scores + mask) / T

    def temperature(self) -> float:
        """Cosine annealing from ``T0`` to ``Tmin``."""
        x = min(1.0, self.step / self.N)
        return self.Tmin + 0.5 * (self.T0 - self.Tmin) * (1 + math.cos(math.pi * (1 - x)))

    def reset(self) -> None:
        """Reset step counter for new sequence."""
        self.step = 0


def load_morph_table(path: Optional[Union[str, Path]]) -> Optional[Dict[str, Any]]:
    """Load morph table from a JSON file.

    Expected format::

        {
            "mode": "lane" | "simple" | "prev+pos",
            "default": "all" | "deny",
            "adj": { ... }
        }
    """
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    with open(p, "r") as f:
        return json.load(f)


def create_default_morph_table() -> Dict[str, Any]:
    """Create a default morph table using 4-lane adjacency.

    Encodes natural sequential structure:
    ENTITY -> ACTION -> QUALITY -> RELATION -> ENTITY ...
    """
    return {
        "mode": "lane",
        "default": "all",
        "lane_adjacency": DEFAULT_LANE_ADJACENCY,
        "lane_names": LANE_NAMES,
        "description": "Default 4-lane semantic adjacency",
    }


def score_token_sequence(
    tokens: List[str],
    indices: List[int],
    scorer: Optional[MorphSATScorer] = None,
) -> List[Dict[str, Any]]:
    """Score a complete token sequence.

    Args:
        tokens: List of token words.
        indices: List of base indices.
        scorer: :class:`MorphSATScorer` instance (creates default if ``None``).

    Returns:
        List of dicts with scoring info for each token.
    """
    if scorer is None:
        scorer = MorphSATScorer()
    scorer.reset()

    results: List[Dict[str, Any]] = []
    prev_idx: Optional[int] = None

    for pos, (token, idx) in enumerate(zip(tokens, indices)):
        sc = scorer.score(
            prev_token=tokens[pos - 1] if pos > 0 else None,
            next_token=token,
            prev_idx=prev_idx,
            next_idx=idx,
            position=pos,
        )

        lane = pos % 4
        results.append({
            "pos": pos,
            "token": token,
            "base_idx": idx,
            "lane": lane,
            "lane_name": LANE_NAMES[lane],
            "score": sc,
            "penalized": sc < 1.0,
        })

        prev_idx = idx

    return results
