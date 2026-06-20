"""
Receipt Chain — Layer 1 Tests

Tests the immutable provenance spine:
1. Canonical hash stability
2. Single block creation
3. Multi-block chain linking
4. Tamper detection (receipt, block hash, chain order)
5. Receipt inclusion proof
6. Persistence (save/load roundtrip)
7. Empty block rejection
8. Chain verification after reload
9. find_receipt across blocks
10. Head hash tracks latest block
"""

import json
import os
import tempfile

import pytest

from morphsat.receipt_chain import (
    ReceiptChain,
    ReceiptBlock,
    GENESIS_HASH,
    canonical_hash,
    canonical_json,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def chain_path():
    """Temp file for chain storage."""
    tmp = tempfile.mktemp(suffix=".json")
    yield tmp
    if os.path.exists(tmp):
        os.unlink(tmp)


@pytest.fixture
def chain(chain_path):
    """Fresh empty chain."""
    return ReceiptChain(chain_path)


def make_receipt(tag: str, score: float = 0.5) -> dict:
    """Create a minimal test receipt."""
    return {
        "gate_version": "v7_shadow_monitor",
        "tag": tag,
        "threat_score": score,
        "safety_score": 1.0 - score,
    }


# ---------------------------------------------------------------------------
# 1. Canonical hash stability
# ---------------------------------------------------------------------------

class TestCanonicalHash:

    def test_same_content_same_hash(self):
        """Identical dicts produce identical hashes."""
        a = {"b": 2, "a": 1}
        b = {"a": 1, "b": 2}
        assert canonical_hash(a) == canonical_hash(b)

    def test_canonical_json_deterministic(self):
        """Key order doesn't affect canonical JSON."""
        a = canonical_json({"z": 1, "a": 2})
        b = canonical_json({"a": 2, "z": 1})
        assert a == b

    def test_different_content_different_hash(self):
        """Different dicts produce different hashes."""
        assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})

    def test_nested_dict_stability(self):
        """Nested structures hash consistently."""
        d = {"outer": {"inner": [1, 2, 3], "key": "val"}}
        h1 = canonical_hash(d)
        h2 = canonical_hash(d)
        assert h1 == h2


# ---------------------------------------------------------------------------
# 2-3. Block creation and chain linking
# ---------------------------------------------------------------------------

class TestBlockCreation:

    def test_single_block(self, chain):
        """One receipt → one block."""
        r = make_receipt("r1")
        chain.append_receipt(r)
        block = chain.close_block()

        assert block is not None
        assert block.block_number == 0
        assert block.previous_hash == GENESIS_HASH
        assert len(block.receipt_hashes) == 1
        assert block.block_hash != ""
        assert block.verify()

    def test_multi_receipt_block(self, chain):
        """Multiple receipts in one block."""
        for i in range(5):
            chain.append_receipt(make_receipt(f"r{i}"))
        block = chain.close_block()

        assert len(block.receipt_hashes) == 5
        assert block.verify()

    def test_multi_block_chain(self, chain):
        """Two blocks link correctly."""
        chain.append_receipt(make_receipt("r1"))
        b0 = chain.close_block()

        chain.append_receipt(make_receipt("r2"))
        b1 = chain.close_block()

        assert b1.previous_hash == b0.block_hash
        assert b1.block_number == 1
        assert chain.height == 2
        assert chain.verify()

    def test_three_block_chain(self, chain):
        """Three blocks — full chain verification."""
        for i in range(3):
            chain.append_receipt(make_receipt(f"block{i}_r1"))
            chain.append_receipt(make_receipt(f"block{i}_r2"))
            chain.close_block()

        assert chain.height == 3
        assert chain.total_receipts == 6
        assert chain.verify()

    def test_empty_close_returns_none(self, chain):
        """Closing with no pending receipts returns None."""
        result = chain.close_block()
        assert result is None
        assert chain.height == 0


# ---------------------------------------------------------------------------
# 4. Tamper detection
# ---------------------------------------------------------------------------

class TestTamperDetection:

    def test_tampered_receipt_hash_breaks_block(self, chain):
        """Modifying a receipt hash inside a block breaks verification."""
        chain.append_receipt(make_receipt("r1"))
        chain.append_receipt(make_receipt("r2"))
        block = chain.close_block()

        # Tamper: replace first receipt hash
        chain.blocks[0].receipt_hashes[0] = "deadbeef" * 8
        assert not chain.blocks[0].verify()
        assert not chain.verify()

    def test_tampered_block_hash_breaks_chain(self, chain):
        """Modifying a block's stored hash breaks verification."""
        chain.append_receipt(make_receipt("r1"))
        chain.close_block()

        chain.blocks[0].block_hash = "cafebabe" * 8
        assert not chain.verify()

    def test_swapped_blocks_break_chain(self, chain):
        """Reordering blocks breaks the chain link."""
        chain.append_receipt(make_receipt("r1"))
        chain.close_block()
        chain.append_receipt(make_receipt("r2"))
        chain.close_block()

        # Swap block numbers
        chain.blocks[0], chain.blocks[1] = chain.blocks[1], chain.blocks[0]
        assert not chain.verify()

    def test_tampered_previous_hash_breaks_chain(self, chain):
        """Changing previous_hash in block 1 breaks the link."""
        chain.append_receipt(make_receipt("r1"))
        chain.close_block()
        chain.append_receipt(make_receipt("r2"))
        chain.close_block()

        chain.blocks[1].previous_hash = "0" * 64
        assert not chain.blocks[1].verify()
        assert not chain.verify()


# ---------------------------------------------------------------------------
# 5. Receipt inclusion proof
# ---------------------------------------------------------------------------

class TestReceiptInclusion:

    def test_receipt_in_block(self, chain):
        """verify_receipt_in_block confirms a receipt is in the right block."""
        r1 = make_receipt("r1")
        r2 = make_receipt("r2")
        chain.append_receipt(r1)
        chain.close_block()
        chain.append_receipt(r2)
        chain.close_block()

        assert chain.verify_receipt_in_block(r1, 0)
        assert not chain.verify_receipt_in_block(r1, 1)
        assert chain.verify_receipt_in_block(r2, 1)
        assert not chain.verify_receipt_in_block(r2, 0)

    def test_unknown_receipt_not_found(self, chain):
        """A receipt not in any block is not found."""
        chain.append_receipt(make_receipt("r1"))
        chain.close_block()

        unknown = make_receipt("never_added")
        assert not chain.verify_receipt_in_block(unknown, 0)

    def test_invalid_block_number(self, chain):
        """Out-of-range block number returns False."""
        chain.append_receipt(make_receipt("r1"))
        chain.close_block()

        assert not chain.verify_receipt_in_block(make_receipt("r1"), 5)
        assert not chain.verify_receipt_in_block(make_receipt("r1"), -1)


# ---------------------------------------------------------------------------
# 6. Persistence
# ---------------------------------------------------------------------------

class TestPersistence:

    def test_save_load_roundtrip(self, chain_path):
        """Chain survives save → reload → verify."""
        chain1 = ReceiptChain(chain_path)
        r1 = make_receipt("r1")
        r2 = make_receipt("r2")
        chain1.append_receipt(r1)
        chain1.close_block()
        chain1.append_receipt(r2)
        chain1.close_block()

        # Reload from disk
        chain2 = ReceiptChain(chain_path)
        assert chain2.height == 2
        assert chain2.total_receipts == 2
        assert chain2.verify()
        assert chain2.head_hash == chain1.head_hash

        # Receipt proofs still work after reload
        assert chain2.verify_receipt_in_block(r1, 0)
        assert chain2.verify_receipt_in_block(r2, 1)

    def test_fresh_chain_on_missing_file(self):
        """Non-existent path starts a fresh chain."""
        chain = ReceiptChain("/tmp/nonexistent_morphsat_chain_test.json")
        assert chain.height == 0
        assert chain.head_hash == GENESIS_HASH

    def test_corrupted_file_starts_fresh(self, chain_path):
        """Corrupted JSON file doesn't crash — starts fresh."""
        with open(chain_path, "w") as f:
            f.write("not valid json {{{")

        chain = ReceiptChain(chain_path)
        assert chain.height == 0


# ---------------------------------------------------------------------------
# 7-8. find_receipt and head_hash
# ---------------------------------------------------------------------------

class TestChainQueries:

    def test_find_receipt_across_blocks(self, chain):
        """find_receipt locates the correct block for each receipt."""
        receipts = [make_receipt(f"r{i}", score=i * 0.1) for i in range(6)]

        # 3 receipts per block, 2 blocks
        for r in receipts[:3]:
            chain.append_receipt(r)
        chain.close_block()
        for r in receipts[3:]:
            chain.append_receipt(r)
        chain.close_block()

        assert chain.find_receipt(receipts[0]) == 0
        assert chain.find_receipt(receipts[2]) == 0
        assert chain.find_receipt(receipts[3]) == 1
        assert chain.find_receipt(receipts[5]) == 1
        assert chain.find_receipt(make_receipt("not_here")) is None

    def test_head_hash_tracks_latest(self, chain):
        """head_hash updates after each close_block."""
        assert chain.head_hash == GENESIS_HASH

        chain.append_receipt(make_receipt("r1"))
        b0 = chain.close_block()
        assert chain.head_hash == b0.block_hash

        chain.append_receipt(make_receipt("r2"))
        b1 = chain.close_block()
        assert chain.head_hash == b1.block_hash
        assert chain.head_hash != b0.block_hash

    def test_get_block(self, chain):
        """get_block returns correct block or None."""
        chain.append_receipt(make_receipt("r1"))
        chain.close_block()

        assert chain.get_block(0) is not None
        assert chain.get_block(0).block_number == 0
        assert chain.get_block(1) is None
        assert chain.get_block(-1) is None


# ---------------------------------------------------------------------------
# 9. to_dict export
# ---------------------------------------------------------------------------

class TestExport:

    def test_to_dict_structure(self, chain):
        """to_dict includes all required fields."""
        chain.append_receipt(make_receipt("r1"))
        chain.close_block()

        d = chain.to_dict()
        assert d["chain_version"] == "v1_linear"
        assert d["height"] == 1
        assert d["total_receipts"] == 1
        assert len(d["head_hash"]) == 64
        assert len(d["blocks"]) == 1
        assert d["blocks"][0]["block_number"] == 0


# ---------------------------------------------------------------------------
# 10. Integration: real MorphSAT receipt shape
# ---------------------------------------------------------------------------

class TestMorphSATIntegration:

    def test_shadow_monitor_receipt_shape(self, chain):
        """Chain works with realistic shadow monitor receipt payloads."""
        receipt = {
            "gate_version": "v7_shadow_monitor",
            "initial_novelty": 0.85,
            "initial_state": "orienting",
            "final_state": "commit_ready",
            "threat_score": 0.62,
            "safety_score": 0.15,
            "contradiction": 0.15,
            "committed": True,
            "final_action": "COMMIT",
            "final_direction": "escalate",
            "final_reason": "threat_boundary_crossed",
            "turns": 4,
            "total_tools": 4,
            "orient_tools": 1,
            "investigate_tools": 3,
            "posture_transitions": 3,
            "evidence_vector": [
                ("scan_yara", "threat"),
                ("check_baseline", "safe"),
                ("network_check", "threat"),
                ("process_tree", "threat"),
            ],
            "posture_trace": [
                {"turn": 0, "from": "normal", "to": "orienting",
                 "trigger": "novel"},
                {"turn": 1, "from": "orienting", "to": "investigating",
                 "trigger": "orient_budget_exhausted"},
                {"turn": 4, "from": "investigating", "to": "commit_ready",
                 "trigger": "threat_boundary_crossed"},
            ],
            "history": [],
            "memory_state": {
                "threat_patterns": 2,
                "tolerance_patterns": 1,
                "abstain_patterns": 0,
            },
        }

        h = chain.append_receipt(receipt)
        block = chain.close_block()

        assert len(h) == 64
        assert chain.verify()
        assert chain.verify_receipt_in_block(receipt, 0)
        assert chain.find_receipt(receipt) == 0

    def test_deterministic_replay(self, chain_path):
        """Same receipts in same order produce identical chain state."""
        receipts = [make_receipt(f"r{i}", score=i * 0.1) for i in range(10)]

        # Build chain 1
        c1 = ReceiptChain(chain_path + ".c1")
        for r in receipts[:5]:
            c1.append_receipt(r)
        c1.close_block()
        for r in receipts[5:]:
            c1.append_receipt(r)
        c1.close_block()

        # Build chain 2 with same receipts
        c2 = ReceiptChain(chain_path + ".c2")
        for r in receipts[:5]:
            c2.append_receipt(r)
        c2.close_block()
        for r in receipts[5:]:
            c2.append_receipt(r)
        c2.close_block()

        # Chains must be identical
        assert c1.head_hash == c2.head_hash
        assert c1.blocks[0].block_hash == c2.blocks[0].block_hash
        assert c1.blocks[1].block_hash == c2.blocks[1].block_hash

        # Cleanup
        for suffix in (".c1", ".c2"):
            p = chain_path + suffix
            if os.path.exists(p):
                os.unlink(p)
