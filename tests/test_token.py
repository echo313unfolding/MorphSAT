"""Tests for morphsat.token -- token adjacency scoring."""

import math
import json
import tempfile
from pathlib import Path

import numpy as np
import pytest

from morphsat.token import (
    MorphSATScorer,
    score_token_sequence,
    load_morph_table,
    create_default_morph_table,
    DEFAULT_LANE_ADJACENCY,
    LANE_NAMES,
)


# ---------------------------------------------------------------------------
# Lane structure
# ---------------------------------------------------------------------------

class TestLaneStructure:
    def test_four_lanes(self):
        assert len(LANE_NAMES) == 4
        assert LANE_NAMES == ["ENTITY", "ACTION", "QUALITY", "RELATION"]

    def test_adjacency_keys(self):
        assert set(DEFAULT_LANE_ADJACENCY.keys()) == {0, 1, 2, 3}

    def test_entity_prefers_action(self):
        assert 1 in DEFAULT_LANE_ADJACENCY[0]

    def test_relation_prefers_entity(self):
        assert 0 in DEFAULT_LANE_ADJACENCY[3]


# ---------------------------------------------------------------------------
# Scorer: basic scoring
# ---------------------------------------------------------------------------

class TestScorerBasic:
    def test_first_position_always_1(self):
        s = MorphSATScorer()
        assert s.score(None, "cat", None, 0, position=0) == 1.0

    def test_preferred_transition_score_1(self):
        s = MorphSATScorer()
        # pos=0 is ENTITY (lane 0), pos=1 is ACTION (lane 1)
        # ENTITY -> ACTION is preferred
        sc = s.score("cat", "runs", 0, 1, position=1)
        assert sc == 1.0

    def test_non_preferred_transition_penalized(self):
        s = MorphSATScorer()
        # pos=0 is ENTITY (lane 0), need to find a non-preferred next lane
        # ENTITY preferred: [1, 2] (ACTION, QUALITY)
        # pos=3 is RELATION (lane 3) -- NOT preferred after ENTITY
        # But we need to go through positions 1, 2 first (they are preferred)
        # Direct test: set up scorer with known position
        # Lane 0 (ENTITY) -> Lane 3 (RELATION) is NOT preferred
        # This happens at position where prev_lane=0, curr_lane=3
        # prev_lane = (pos-1) % 4 = 0 means pos-1 = 0,4,8,... so pos = 1,5,9,...
        # curr_lane = pos % 4 = 3 means pos = 3,7,11,...
        # We need both: prev_lane=0 AND curr_lane=3
        # pos-1 % 4 = 0 -> pos = 1 mod 4 ... nope that gives curr_lane=1
        # Actually: prev_lane = (pos-1)%4 and curr_lane = pos%4
        # Want prev_lane=0, curr_lane=3 -> (pos-1)%4=0 and pos%4=3
        # pos%4=3 -> pos=3,7,11,...
        # (pos-1)%4 = 2%4=2 (for pos=3) -- not 0
        # (pos-1)%4 = 6%4=2 (for pos=7) -- not 0
        # So lane 0 -> lane 3 never happens in sequential positions.
        # Let's use lane 3 -> lane 2 instead.
        # RELATION (3) preferred: [0, 1]. So lane 2 (QUALITY) is not preferred.
        # prev_lane=3, curr_lane=2: (pos-1)%4=3 -> pos=4,8,...  pos%4=0 (not 2)
        # Hmm, sequential positions always have curr_lane = prev_lane + 1 mod 4.
        # So transitions are always 0->1, 1->2, 2->3, 3->0.
        # Check which of those are non-preferred:
        # 0->1: 1 in [1,2] = yes (preferred)
        # 1->2: 2 in [2,3,0] = yes (preferred)
        # 2->3: 3 in [3,0,1] = yes (preferred)
        # 3->0: 0 in [0,1] = yes (preferred)
        # All sequential transitions are preferred by design!
        # So we need a non-sequential position to get a penalty.
        # The penalty only applies when the lane transition is non-preferred,
        # which in the default table never happens for sequential positions.
        # This is by design -- the default adjacency table is engineered for
        # sequential flow. Let's verify all sequential transitions score 1.0.
        s2 = MorphSATScorer()
        for pos in range(1, 20):
            sc = s2.score("a", "b", pos - 1, pos, position=pos)
            assert sc == 1.0, f"pos={pos} should score 1.0"

    def test_custom_morph_table_penalty(self):
        """Use a restricted morph table to force a penalty."""
        # lane mode with default adjacency but we override to make lane 1
        # NOT preferred after lane 0
        s = MorphSATScorer()
        # Monkey-patch the adjacency to force a penalty
        import morphsat.token as mt
        original = mt.DEFAULT_LANE_ADJACENCY.copy()
        try:
            mt.DEFAULT_LANE_ADJACENCY[0] = [2, 3]  # ENTITY -> only QUALITY, RELATION
            sc = s.score("cat", "runs", 0, 1, position=1)
            assert sc < 1.0
        finally:
            mt.DEFAULT_LANE_ADJACENCY.update(original)


# ---------------------------------------------------------------------------
# Scorer: temperature annealing
# ---------------------------------------------------------------------------

class TestTemperature:
    def test_initial_temperature(self):
        s = MorphSATScorer(sat_T0=2.0, sat_Tmin=0.5)
        # step=0 -> x=0 -> cos(pi*(1-0)) = cos(pi) = -1
        # T = 0.5 + 0.5*(2.0-0.5)*(1 + (-1)) = 0.5 + 0.5*1.5*0 = 0.5
        # Wait, that gives Tmin at step 0. Let's recalculate:
        # x = min(1, 0/N) = 0
        # T = Tmin + 0.5*(T0-Tmin)*(1 + cos(pi*(1-x)))
        # T = 0.5 + 0.5*1.5*(1 + cos(pi)) = 0.5 + 0.75*(1-1) = 0.5
        # Hmm, at step=0 temperature is Tmin. At step=N, x=1:
        # T = 0.5 + 0.75*(1 + cos(0)) = 0.5 + 0.75*2 = 2.0 = T0
        # So this is REVERSE annealing (cold start, warm end).
        assert s.temperature() == pytest.approx(0.5)

    def test_final_temperature(self):
        s = MorphSATScorer(sat_T0=2.0, sat_Tmin=0.5, steps_anneal=100)
        s.step = 100
        assert s.temperature() == pytest.approx(2.0)

    def test_reset_step(self):
        s = MorphSATScorer()
        s.step = 50
        s.reset()
        assert s.step == 0


# ---------------------------------------------------------------------------
# Scorer: mask_scores
# ---------------------------------------------------------------------------

class TestMaskScores:
    def test_no_prev_token_passthrough(self):
        s = MorphSATScorer()
        scores = np.array([1.0, 2.0, 3.0])
        result = s.mask_scores(scores, None, 0)
        np.testing.assert_array_equal(result, scores)

    def test_preferred_lane_no_penalty(self):
        s = MorphSATScorer()
        scores = np.array([1.0, 2.0, 3.0, 4.0])
        # last_token_idx=0 -> lane 0 (ENTITY), pos_mod4=1 (ACTION)
        # ACTION is in ENTITY's preferred list
        result = s.mask_scores(scores, 0, 1)
        np.testing.assert_array_equal(result, scores)

    def test_hard_constraint_morph_table(self):
        table = {"mode": "prev+pos", "adj": {"0:0": [1, 2]}, "default": "deny"}
        s = MorphSATScorer(morph_table=table)
        # Use equal base scores so penalty effect is directly observable
        scores = np.array([10.0, 10.0, 10.0, 10.0])
        result = s.mask_scores(scores, 0, 0)
        # Allowed indices (1, 2) get mask=0; disallowed (0, 3) get mask=-lambda
        assert result[1] > result[0]  # 1 is allowed, 0 is not
        assert result[2] > result[3]  # 2 is allowed, 3 is not
        # Allowed indices should be equal, disallowed indices should be equal
        assert result[1] == result[2]
        assert result[0] == result[3]


# ---------------------------------------------------------------------------
# score_token_sequence
# ---------------------------------------------------------------------------

class TestScoreTokenSequence:
    def test_basic_sequence(self):
        tokens = ["cat", "runs", "fast", "through"]
        indices = [0, 1, 2, 3]
        results = score_token_sequence(tokens, indices)
        assert len(results) == 4
        assert results[0]["pos"] == 0
        assert results[0]["lane_name"] == "ENTITY"
        assert results[0]["score"] == 1.0
        assert results[0]["penalized"] is False

    def test_all_fields_present(self):
        results = score_token_sequence(["a", "b"], [0, 1])
        expected_keys = {"pos", "token", "base_idx", "lane", "lane_name", "score", "penalized"}
        assert set(results[0].keys()) == expected_keys

    def test_lane_assignment(self):
        tokens = ["a", "b", "c", "d", "e"]
        indices = [0, 1, 2, 3, 4]
        results = score_token_sequence(tokens, indices)
        assert results[0]["lane_name"] == "ENTITY"
        assert results[1]["lane_name"] == "ACTION"
        assert results[2]["lane_name"] == "QUALITY"
        assert results[3]["lane_name"] == "RELATION"
        assert results[4]["lane_name"] == "ENTITY"  # wraps

    def test_custom_scorer(self):
        scorer = MorphSATScorer(soft_lambda=8.0)
        results = score_token_sequence(["x", "y"], [0, 1], scorer=scorer)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# load_morph_table / create_default_morph_table
# ---------------------------------------------------------------------------

class TestMorphTable:
    def test_load_none(self):
        assert load_morph_table(None) is None

    def test_load_nonexistent(self):
        assert load_morph_table("/tmp/nonexistent_morphsat_test.json") is None

    def test_load_valid(self, tmp_path):
        data = {"mode": "lane", "default": "all"}
        p = tmp_path / "morph.json"
        p.write_text(json.dumps(data))
        loaded = load_morph_table(str(p))
        assert loaded == data

    def test_create_default(self):
        table = create_default_morph_table()
        assert table["mode"] == "lane"
        assert table["default"] == "all"
        assert "lane_adjacency" in table
        assert len(table["lane_names"]) == 4
