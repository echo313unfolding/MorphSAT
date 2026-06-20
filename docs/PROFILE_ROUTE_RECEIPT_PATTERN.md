# Profile-Route-Receipt: The Shared Architecture Pattern

## The Pattern

Across three independent subsystems built on this box — HXQ (tensor compression),
MorphSAT (safety governance), and Crystal Vault (compressed execution) — the same
control skeleton emerged:

```
state profile → route selection → specialized backend → bounded execution → deterministic receipt
```

This was not designed top-down. It converged independently in each domain because
the same engineering problem kept recurring: heterogeneous inputs require different
processing paths, and the routing decision must be auditable.

## The Pattern in Each Domain

### 1. HXQ / Hydra Router

**Problem:** Different tensors have different compression tolerances. A single
codec path is brittle — attention Q/K projections are fragile, MLP weights are
robust, embeddings must be exact.

```
tensor W
  → profile: kurtosis, std, cosine under each codec, tensor type, layer position
  → route:   HydraRouter selects Head (EXACT / AFFINE6 / AFFINE5 / AFFINE4 / AFFINE3)
  → backend: per-group affine quantization at selected bit width
  → execute: Triton VQ gather-matmul / GGML mmvq / C++ fused (Level 2: zero materialization)
  → receipt: cosine, bpw, max_abs_error, mean_abs_error, policy, reason codes
```

**Code:** `helix_substrate/hydra_router.py` — `TensorProfile` → `HydraRouter.route()` → `CompressionPlan`
**Tests:** 19/19. **Models shipped:** 7 models, 5 architecture types, all PASS affine g128.

### 2. MorphSAT / TwoStageGate

**Problem:** Different evidence states require different decision processes. Clear
threats need fast threshold logic. Ambiguous, conflicting, or post-correction cases
need deeper arbitration.

```
decision state
  → profile: threat_score, safety_score, novelty, correction_trace, contradiction_count, memory_conflict
  → route:   TwoStageGate selects path (threshold / QUBO / abstain / correction echo)
  → backend: threshold logic for clear cases, QUBO arbitration for ambiguous
  → execute: verdict under MorphSAT authority boundary
  → receipt: CDR chain — replay any episode through any mode, compare outcomes
```

**Code:** `morphsat/two_stage_gate.py`, `morphsat/correction_echo.py`, `tools/trace_splitmemory_cdr.py`
**Tests:** 321/321. **Key result:** Mode M = 98.6%, false_safe = 0%.

**Critical finding (CDR replay, v8.5):** SplitMemory's value was routing (operator
selection), not verdict generation. old_guy_helped = 0/72 episodes. The memory
changed which decision process ran, not what that process decided. CorrectionEcho
made this mechanism explicit and receipted.

### 3. Crystal Vault / Ghost Runtime

**Problem:** A compressed artifact should not require full decompression before the
runtime can make routing or classification decisions about it.

```
encoded body (compressed tensor / shard)
  → profile: GlyphDAR scans body WITHOUT opening it → Shadow (transition_entropy,
             markov_order, index_autocorr) → Ghost (inferred role, route, resources)
  → route:   Ghost pre-routes to Hydra head or execution path
  → backend: ExecutableShard.eval_encoded() — kernel reads encoded symbols directly
  → execute: Level 2 (zero persistent materialization, hardware translation boundary)
  → receipt: ShardReceipt — materialized_weight_bytes, encoded_ops_executed, state_path
```

**Code:** `cell-runtime/src/cell/vault_shard.py` — `Shadow` → `Ghost` → `ExecutableShard` → `ShardReceipt`
**Tests:** 52/52. **Key result:** Ghost classifies tensor role at 73.3% (8.1x random),
predicts execution behavior at R^2 = 0.818, pre-routes for Hydra at 53.8% cleared
with precision = 0.955.

## The Mediating Variable Discovery

The MorphSAT CDR replay produced the cleanest example of why this pattern matters.

Before CDR: the assumption was that memory (SplitMemory) improved verdicts directly.
After CDR: memory improved routing, and routing improved verdicts.

```
Before:   memory → better verdict                    (assumed, wrong)
After:    memory → routing signal → QUBO path → better verdict  (proven)
```

The memory was a mediating variable for route selection, not a direct cause of
better outcomes. CorrectionEcho replaced SplitMemory by making the routing
mechanism explicit: correction receipt → short-lived echo marker → next similar
episode gets QUBO routing.

This is the same mechanism as Hydra: kurtosis and cosine probe don't improve
compression directly — they improve the routing decision about which codec to use.

## Cognitive Architecture Translation

For researchers in cognitive architecture (Soar, ACT-R, appraisal theory):

| This Pattern | Cognitive Architecture Term |
|---|---|
| State profile | Appraisal (novelty, threat, relevance assessment) |
| Route selection | Strategy commitment (when to switch decision process) |
| Specialized backend | Task-specific operator / production rule |
| Bounded execution | Exogenous meta-management (external governor, not self-monitoring) |
| Deterministic receipt | Episodic memory trace (replayable, not reconstructed) |
| CorrectionEcho | Passive accumulation — micro-instance of Ohlsson's error correction |

The TwoStageGate is a concrete implementation of the strategy commitment problem:
when should a system abandon fast heuristic processing and switch to deliberative
reasoning? The answer in MorphSAT: when the evidence profile indicates ambiguity,
conflict, drift, or recent correction.

## Current Status (2026-06-20)

### Built and tested

| Component | Location | Tests | Status |
|---|---|---|---|
| Hydra Router | `helix_substrate/hydra_router.py` | 19/19 | Shipped, 7 models |
| TensorProfile + probes | `helix_substrate/hydra_router.py` + bench tools | receipted | 154 tensors x 7 strategies |
| TwoStageGate | `morphsat/two_stage_gate.py` | 321/321 | Tagged v8.5.2 |
| CorrectionEcho | `morphsat/correction_echo.py` | 321/321 | Contradiction defense proven |
| CDR replay | `tools/trace_splitmemory_cdr.py` | deterministic | old_guy_helped=0/82 |
| Crystal Vault shard | `cell-runtime/src/cell/vault_shard.py` | 52/52 | Phase 0-0.19 complete |
| Shadow/Ghost/GlyphDAR | same file | 217/217 total | 73.3% role, R^2=0.818 |
| VaultManifest | same file | 52/52 | Merkle hash, DAG, topo sort |

### Integration gaps — CLOSED

**Gap 1: Shadow → Hydra bridge — DONE.** `helix_substrate/ghost_bridge.py` bridges
Crystal Vault's Ghost signal into Hydra Router. `GhostPreRoute` predicts tensor
fragility from 4 encoded-body features (te, tr, mo, ac) and decides SKIP_PROBE
vs PROBE_REQUIRED. `HydraRouter.route_with_ghost()` uses Ghost pre-screening to
skip expensive codec probes when Ghost is confident. 25/25 tests.

**Gap 2: Residual contract — DONE.** `helix_substrate/residual_contract.py` profiles
the structure of codec damage (E = W - W_hat). `ResidualProfile` captures 12
structural features: rms, cosine, kurtosis, sparsity, ACF, spectral ratio,
SVD rank, channel concentration. `DamageType` classifies residuals as DISTRIBUTED,
CONCENTRATED, LOW_RANK, or STRUCTURED. `compare_codecs()` ranks heterogeneous
codecs by residual quality. `residual_routing_signal()` extracts routing-relevant
signals (codec_optimal, try_correction, correction_hint). 26/26 tests including
real-data VQ and affine comparison.

## The Scientific Claim

> Across compression and governance tasks, the common mechanism is not a universal
> solver but a profile-conditioned router. The system first characterizes the local
> structure of the substrate, then selects a specialized backend, and finally
> receipts the outcome for deterministic replay and correction.

This is not a framework. It is a pattern that emerged from engineering three
independent systems and noticing they converged on the same skeleton.

## Reproduction

All code is in the MorphSAT repository (`echo313unfolding/MorphSAT`) at tag
`v8.5.2-cdr-reproducibility`. Crystal Vault code is in `cell-runtime/`. Hydra
Router is in `helix-substrate/`.

```bash
# MorphSAT: full evidence chain
git clone https://github.com/echo313unfolding/MorphSAT.git
cd MorphSAT && git checkout v8.5.2-cdr-reproducibility
python3 -m pytest tests/ -q                          # 321 passed
python3 tools/trace_splitmemory_cdr.py               # old_guy_helped=0/82
python3 tools/bench_memory_stress.py --skip-replay   # M=95.1%, false_safe=0%
```
