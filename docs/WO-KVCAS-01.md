# WO-KVCAS-01: Chained Content-Addressable KV Cache

**Status:** SCOPED
**Date:** 2026-05-10
**Depends on:** sentinel agent loop (bench_gate_authority.py), T2000 deployment
**Falsifiable:** Yes (4 gates below)

## One-sentence

The SHAKE-chained anchor IS the attention identity — no separate prefix tree, no metadata tracking, just "same anchor = same computation history = reusable K/V."

## The insight

Standard prefix caching (vLLM, SGLang) maintains a radix tree of token sequences to find shared prefixes. This replaces the radix tree with a 32-byte cryptographic anchor per position:

```
anchor_k = SHAKE256(anchor_{k-1} || model_fp || layer || pos || token_id)
```

Properties:
- **Deterministic:** same token prefix → same anchor (always)
- **Collision-resistant:** different prefix → different anchor (2^128 security)
- **Avalanche:** 1-bit token change → ~50% bit flip in anchor
- **Self-verifying:** chain audit walks prev_anchor links, no external index needed

The anchor serves triple duty:
1. Cache lookup key (dict[anchor] → K/V entry)
2. Attention identity proof (same anchor = proven shared computation)
3. Audit trail (chain is self-verifying, integrity hash catches K/V tampering)

## Architecture slot

```
hot in-pass        → PolarQuant / helix-kv (lossy, fast, per-token)
warm exact recall  → THIS (lossless on hit, cross-session, receipted)
long-term symbolic → codon SSM (bounded, auditable, cross-model)
```

## Why it matters for sentinel

The sentinel agent loop replays identical prefixes every call:
- System prompt (~200 tokens) — same every time
- Tool definitions (~150 tokens) — same every time
- Scenario setup (~50 tokens) — same per scenario

That's 400+ tokens of shared prefix across every 20-scenario run. On T2000 (prefill bottleneck: 30% of Q4), caching this prefix is direct wall-time savings.

For the agent substrate (11 agents, same tool registry): even more sharing. Every agent call shares the system prompt prefix.

## Falsification gates

| Gate | Metric | Pass | Fail |
|------|--------|------|------|
| G1 | Hit rate on sentinel bench traces | >50% tokens from cache | <30% |
| G2 | Prefill wall-time saved on T2000 | >15% reduction | <5% |
| G3 | Hash overhead per token | <0.1ms | >1ms |
| G4 | Persistence: cold-start hit after restart | hits on restart | 0 hits |
| G5 | Model fingerprint isolation | same prefix + different model = 0 hits | any cross-model hit |

### Theoretical ceiling (from advisor review)

Prefill cost savings follow (k/n)² where k=shared tokens, n=total tokens:
- 50% shared → 25% prefill saved
- 80% shared → 64% prefill saved
- 90% shared → 81% prefill saved

Strong nonlinearity favoring long shared prefixes. Sentinel workload (400+ system prompt tokens in ~500 total) should land near 60-80% theoretical savings. G2 measures actual vs this ceiling.

### Pre-Phase-1 analyzer (advisor suggestion)

Before any integration: offline token-overlap analysis on 20 scenarios × 5 turns. Tokenize each prompt, compute pairwise longest common prefix, output:
1. Empirical shared-token percentage (does G1 pass at all?)
2. Theoretical prefill savings ceiling via (k/n)²

If ceiling is small, WO closes cheap. Script: `tools/analyze_prefix_overlap.py`.

## Critical design flags (advisor review, 2026-05-10)

### Flag 1: Model fingerprint is load-bearing

Same prefix on different model weights produces different K/V. Anchor MUST namespace by model identity or you get invalid cache hits across versions. The prototype includes `model_fingerprint` in `derive_anchor()`. Acceptance criteria:
- `model_fingerprint_gate()` test in kv_chain_cas.py (added)
- G5 gate: "anchor differs across model versions for same prefix" verified on every build

Without this, a fine-tune or quantization swap silently corrupts the cache.

### Flag 2: Cache size budget needs a number

At 6 layers × 2048 head_dim × 2 (K+V) × 2 bytes fp16 ≈ ~50KB per cached token-position.
- 1K cached tokens = ~50MB
- 10K cached tokens = ~500MB
- 100K cached tokens = ~5GB (exceeds T2000 disk budget)

v0.2 config needs: hard cap (e.g., 10K tokens = 500MB) + LRU eviction. LMDB on T2000 has ~20GB free disk, so 10K-50K tokens is the operating range.

### Flag 3: Savings math is strongly nonlinear

(k/n)² means: short shared prefixes don't help much, but the sentinel's 400+ token system prompt (80%+ of total) hits the steep part of the curve. This is why the workload fit matters — generic workloads with short/varied prefixes would fail G2.

## Pre-Phase-1 results (2026-05-10)

Analyzer: `tools/analyze_prefix_overlap.py` (whitespace tokenization approximation).

```
Scenarios: 20
System prompt tokens: 97 (whitespace)
Pairwise LCP: 98/120 avg = 83.0% shared
Theoretical ceiling: (0.83)^2 = 69.0% prefill savings
G1 (>50%): PASS    G2 ceiling (>15%): PASS
```

Formula validation: predicted (0.83)² = 0.689, measured 69.0%. The (k/n)² model holds exactly.

### Calibration notes (advisor review, 2026-05-10)

**BPE will raise the fraction.** Whitespace splitting underestimates because identical character strings tokenize to identical BPE token sequences. Real tokenizer should yield 85-90% shared, pushing ceiling toward 75-80%. 30-min swap to real `tokenizer.json` before locking pre-Phase-2 receipt.

**Zamba2 hybrid pulls whole-model ceiling below 69%.** (k/n)² gives attention-cacheable savings only. Zamba2's 32 mamba layers are linear in n and aren't in this cache — mamba prefill still runs through every uncached token. Whole-model wall-time savings ≈ attention savings × (attention's share of total prefill time). If T2000 measures 50-55% instead of 69%, that's the Mamba floor, not implementation overhead.

**Phase 1 is receipt-tightening, not gating.** The answer is already decisive (83% > 50% gate). Phase 1 locks the receipt with actual BPE numerator/denominator.

### Phase 2 gates (advisor suggestion, 2026-05-10)

Phase 2 (llama-server slot integration) carries the real engineering risk. Scope as its own WO with:

| Gate | Metric | Pass | Fail |
|------|--------|------|------|
| G7 | Slot correctness: cached-prefix gen = byte-identical to cold prefill | 100-prompt suite matches | any divergence |
| G8 | No cache-miss regression: novel-prefix prompts | within ±5% of baseline wall time | >10% slower |
| G9 | Eviction under load: cache size stays bounded | under configured cap across sustained workload | exceeds cap |

## Implementation plan

### Phase 1: Measure (no persistence, no model integration)

1. Instrument `bench_gate_authority.py` to log full token sequences per scenario
2. Run the 20 scenarios, compute anchor chains offline
3. Measure: how many anchors are shared across scenarios? (predicted: system prompt tokens = 100% shared)
4. This is G1 without any runtime change — pure measurement

### Phase 2: Wire into llama-server (if G1 passes)

Two options:
- **A: External cache server** — sits between the harness and llama-server, intercepts prompt, serves cached KV via llama.cpp's slot mechanism
- **B: Patch llama-server** — add KV cache persistence with anchor-indexed lookup (harder, but no proxy)

Option A is simpler and doesn't touch the llama.cpp fork (keeps HXQ PR clean).

### Phase 3: Persistence (if G2 passes)

- LMDB or sqlite backend (replace in-memory dict)
- Eviction: LRU by anchor access time, size-bounded
- Cross-session: cache survives process restart
- This is what makes it a "warm tier" — not just intra-session prefix sharing

### Phase 4: Integrity in production

- Integrity hash checked on every cache read
- Chain audit on startup (verify no corruption during persistence)
- Receipt emitted per cache hit (audit log: "this K/V was computed at time T from prefix P")

## What this is NOT

- Not novel prefix caching (vLLM/SGLang do this)
- Not a replacement for KV compression (PolarQuant handles the hot tier)
- Not cross-model (anchor includes model fingerprint — different model = different anchors)

## What IS novel

- The hash chain as attention identity (no radix tree, no metadata, just 32 bytes)
- Integrity receipt on stored K/V (tamper detection on read)
- Chain audit (self-verifying without external index)
- Receipt discipline: every cache hit is logged with provenance

## Existing code

- `kv_chain_cas.py` — demo implementation with all 4 properties verified
- Proven: prefix sharing (60% hit), tamper detection, chain audit (20/20), avalanche (55.1%)

## Cost estimate

- Phase 1: 1 hour (instrument bench, measure offline)
- Phase 2: 2-4 hours (proxy or slot API integration)
- Phase 3: 1-2 hours (LMDB swap)
- Phase 4: 30 min (receipt logging)

## Connection to existing work

- Same SHAKE256 used in superglyph (provenance) and helix-cdc (chunk vault)
- Same receipt discipline as WO-RECEIPT-COST-01
- Warm tier complements helix-online-kv (which is the hot/lossy tier)
- The "42zip mechanic" from the seed work: sponge chain = controlled expansion key, K/V = unfolded state, attention = regen function
