"""
kv_chain_cas.py — Token-ID-indexed, SHAKE-chained content-addressable KV cache.

Two cryptographic guarantees, decoupled:
  1. ANCHOR (cache key)     = SHAKE256(prev_anchor || layer || pos || token_id)
                              -> identifies "which token prefix is this?"
                              -> avalanche: 1-bit token change = totally different anchor
  2. INTEGRITY (receipt)    = SHAKE256("KVI:" || K || V)
                              -> verifies "are the K/V values intact?"
                              -> detects tampering on read

Storage: dict[anchor] -> CacheEntry. Lossless on hit. Receipted.
Chain audit: every entry's anchor must equal derive_anchor(prev_anchor, ...).

Slot in the memory tier story:
  hot in-pass        -> PolarQuant / helix-kv (lossy, fast)
  warm exact recall  -> THIS (lossless on hit, cross-session, receipted)
  long-term symbolic -> codon SSM (bounded, auditable, cross-model)
"""

import hashlib
import numpy as np
from dataclasses import dataclass
from typing import Optional

ANCHOR_BYTES = 32       # 256-bit anchors -> ~2^128 collision resistance
INTEGRITY_BYTES = 32


def derive_anchor(prev_anchor: bytes, layer_idx: int, pos: int, token_id: int,
                  model_fp: bytes = b"") -> bytes:
    """Chain a new anchor: SHAKE256(prev || model_fp || layer || pos || token_id)."""
    h = hashlib.shake_256()
    h.update(prev_anchor)
    h.update(model_fp)
    h.update(layer_idx.to_bytes(2, "big"))
    h.update(pos.to_bytes(4, "big"))
    h.update(token_id.to_bytes(4, "big"))
    return h.digest(ANCHOR_BYTES)


def integrity_hash(k: np.ndarray, v: np.ndarray) -> bytes:
    """Receipt over K/V tensor bytes."""
    h = hashlib.shake_256()
    h.update(b"KVI:")
    h.update(k.tobytes())
    h.update(v.tobytes())
    return h.digest(INTEGRITY_BYTES)


class IntegrityError(Exception):
    pass


@dataclass
class CacheEntry:
    anchor: bytes
    prev_anchor: bytes
    layer: int
    pos: int
    token_id: int
    k: np.ndarray
    v: np.ndarray
    kv_integrity: bytes


class ChainedKVCache:
    """Content-addressable KV cache with SHAKE-chained anchors.

    The anchor IS the attention identity:
      - Same anchor = cryptographic proof of shared computation history
      - No radix tree, no prefix metadata — just 32 bytes per position
      - Triple duty: cache key + attention identity + audit trail
    """

    GENESIS = b"\x00" * ANCHOR_BYTES

    def __init__(self, num_layers: int, model_fingerprint: bytes = b"default-model"):
        self.num_layers = num_layers
        self.model_fp = hashlib.shake_256(model_fingerprint).digest(16)
        self.store: dict[bytes, CacheEntry] = {}

    def insert(self, layer: int, pos: int, token_id: int, prev_anchor: bytes,
               k: np.ndarray, v: np.ndarray) -> bytes:
        anchor = derive_anchor(prev_anchor, layer, pos, token_id, self.model_fp)
        entry = CacheEntry(
            anchor=anchor, prev_anchor=prev_anchor,
            layer=layer, pos=pos, token_id=token_id,
            k=k.copy(), v=v.copy(),
            kv_integrity=integrity_hash(k, v),
        )
        self.store[anchor] = entry
        return anchor

    def lookup(self, anchor: bytes) -> Optional[CacheEntry]:
        """Read with integrity verification. Raises IntegrityError on tamper."""
        entry = self.store.get(anchor)
        if entry is None:
            return None
        if integrity_hash(entry.k, entry.v) != entry.kv_integrity:
            raise IntegrityError(
                f"Tamper detected at anchor {entry.anchor.hex()[:16]}... "
                f"(layer={entry.layer}, pos={entry.pos}, tok={entry.token_id})"
            )
        return entry

    def find_longest_prefix(self, layer: int, token_seq: list[int]) -> tuple[int, bytes]:
        """Walk chain from genesis; return (matched_length, last_matching_anchor)."""
        anchor = self.GENESIS
        matched = 0
        for pos, tok in enumerate(token_seq):
            candidate = derive_anchor(anchor, layer, pos, tok, self.model_fp)
            if candidate in self.store:
                anchor = candidate
                matched += 1
            else:
                break
        return matched, anchor

    def store_sequence(self, layer: int, tokens: list[int],
                       k_per_pos: np.ndarray, v_per_pos: np.ndarray) -> bytes:
        anchor = self.GENESIS
        for pos, tok in enumerate(tokens):
            anchor = self.insert(layer, pos, tok, anchor,
                                 k_per_pos[pos], v_per_pos[pos])
        return anchor

    def chain_audit(self) -> tuple[int, int]:
        """Verify every entry's anchor derives correctly. Returns (pass, fail)."""
        ok = bad = 0
        for anchor, entry in self.store.items():
            expected = derive_anchor(entry.prev_anchor, entry.layer,
                                     entry.pos, entry.token_id, self.model_fp)
            if expected == anchor:
                ok += 1
            else:
                bad += 1
        return ok, bad

    def model_fingerprint_gate(self, other_fingerprint: bytes) -> bool:
        """Verify a model fingerprint matches this cache's namespace."""
        other_fp = hashlib.shake_256(other_fingerprint).digest(16)
        return other_fp == self.model_fp


# ============================================================================
# Demonstration
# ============================================================================
if __name__ == "__main__":
    NUM_LAYERS = 4
    HEAD_DIM = 8

    cache = ChainedKVCache(num_layers=NUM_LAYERS,
                           model_fingerprint=b"demo-zamba2-1.2b")

    # Two sequences sharing a 3-token prefix
    seq_a = [101, 202, 303, 404, 505]   # "the cat sat on mat"
    seq_b = [101, 202, 303, 666, 777]   # "the cat sat under tree"

    rng = np.random.default_rng(42)

    print("=" * 64)
    print("INSERT SEQUENCE A — full prefill K/V cached")
    print("=" * 64)
    for layer in range(NUM_LAYERS):
        k = rng.standard_normal((len(seq_a), HEAD_DIM)).astype(np.float32)
        v = rng.standard_normal((len(seq_a), HEAD_DIM)).astype(np.float32)
        tip = cache.store_sequence(layer, seq_a, k, v)
        print(f"  layer {layer}  tip anchor: {tip.hex()[:32]}...")
    print(f"\n  CAS entries: {len(cache.store)}  (= {NUM_LAYERS} layers x {len(seq_a)} tokens)")

    print("\n" + "=" * 64)
    print("LOOKUP SEQUENCE B — shares first 3 tokens with A")
    print("=" * 64)
    total_hits = 0
    for layer in range(NUM_LAYERS):
        matched, anchor_at = cache.find_longest_prefix(layer, seq_b)
        total_hits += matched
        print(f"  layer {layer}  matched {matched}/{len(seq_b)} "
              f"-> resume fresh prefill from pos {matched}")
    print(f"\n  Total cache hits: {total_hits}/{NUM_LAYERS * len(seq_b)} "
          f"= {100 * total_hits / (NUM_LAYERS * len(seq_b)):.1f}%")

    # Naive prefill cost is O(n^2) per layer; cache hit elides the prefix attention
    n = len(seq_b)
    cached_pos = total_hits // NUM_LAYERS
    fresh_pos = n - cached_pos
    naive_cost = n * n * NUM_LAYERS
    cached_cost = (fresh_pos * (fresh_pos + 2 * cached_pos)) * NUM_LAYERS
    print(f"  Prefill work units: naive={naive_cost}  cached={cached_cost}  "
          f"saved={100*(1-cached_cost/naive_cost):.1f}%")

    print("\n" + "=" * 64)
    print("TAMPER TEST — flip one float in a stored K tensor, attempt read")
    print("=" * 64)
    victim_anchor = next(iter(cache.store.keys()))
    victim = cache.store[victim_anchor]
    print(f"  victim: layer={victim.layer} pos={victim.pos} tok={victim.token_id}")
    original = victim.k[0]
    victim.k[0] = 999.0
    try:
        cache.lookup(victim_anchor)
        print("  FAIL — no IntegrityError raised")
    except IntegrityError as e:
        print(f"  PASS — {e}")
    victim.k[0] = original  # restore for chain audit

    print("\n" + "=" * 64)
    print("CHAIN AUDIT — every anchor must derive from its declared prev_anchor")
    print("=" * 64)
    ok, bad = cache.chain_audit()
    print(f"  pass={ok}  fail={bad}  total={ok+bad}")
    assert bad == 0, "chain audit failed"

    print("\n" + "=" * 64)
    print("AVALANCHE CHECK — single-token change at pos 0, anchor divergence")
    print("=" * 64)
    a0 = derive_anchor(ChainedKVCache.GENESIS, 0, 0, 101, cache.model_fp)
    a1 = derive_anchor(ChainedKVCache.GENESIS, 0, 0, 102, cache.model_fp)
    diff_bits = sum(bin(b1 ^ b2).count("1") for b1, b2 in zip(a0, a1))
    print(f"  token 101 anchor: {a0.hex()[:32]}...")
    print(f"  token 102 anchor: {a1.hex()[:32]}...")
    print(f"  hamming distance: {diff_bits}/256 bits "
          f"({100*diff_bits/256:.1f}% — ideal ~50%)")

    print("\n" + "=" * 64)
    print("MODEL FINGERPRINT GATE — different model = different anchors")
    print("=" * 64)
    cache2 = ChainedKVCache(num_layers=NUM_LAYERS,
                            model_fingerprint=b"different-model-v2")
    a_same = derive_anchor(ChainedKVCache.GENESIS, 0, 0, 101, cache.model_fp)
    a_diff = derive_anchor(ChainedKVCache.GENESIS, 0, 0, 101, cache2.model_fp)
    print(f"  model A anchor: {a_same.hex()[:32]}...")
    print(f"  model B anchor: {a_diff.hex()[:32]}...")
    print(f"  same? {a_same == a_diff}  (must be False)")
    assert a_same != a_diff, "model fingerprint gate failed"
    print("  PASS — same prefix, different model = different anchor")

    print("\nall checks passed.")
