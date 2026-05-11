# Recomputation-Gated Architecture (RGA)

**Status:** 4/4 instances validated (2026-05-11)
**Receipt:** `~/receipts/wo_recomp_04/recomp_gate_bench_20260511T035503Z.json`
**Origin:** EXPLORE mode synthesis across three independent systems (2026-05-10)

---

## The Thesis

Every privileged transition in a system that handles high-stakes decisions
should be gated by **independent recomputation**, not evaluation.

The distinction is load-bearing:

| | Evaluation | Recomputation |
|---|---|---|
| **Mechanism** | Review the work, judge quality | Produce ground truth independently, compare |
| **Bypassable?** | Yes — work can *appear* correct | No — verifier doesn't see the original claim |
| **Example** | Code review, reward model scoring | Hash verification, dual-agent independent verdict |
| **Failure mode** | Reviewer fooled by surface quality | Verifier disagrees — escalate |

**Evaluation** asks: "Does this look right?"
**Recomputation** asks: "Do I get the same answer independently?"

---

## Four Validated Instances

### Layer 1: Data — Hash Recomputation

**System:** hxq-solana on-chain claim verifier
**What's gated:** Promotion of compressed tensor assets from Candidate to Active
**Recomputation mechanism:** Independent party downloads off-chain artifact, computes SHA-256 and cosine similarity from scratch, compares to on-chain commitment
**Gate behavior:** MATCH → VERIFIED (promote). MISMATCH → DISPUTED (block).
**Receipt:** 75/75 localnet tests. `verify_claim.py` produces exit 0 (VERIFIED) or exit 2 (DISPUTED).
**Why it's recomputation, not evaluation:** The verifier never looks at the compressor's reasoning or intermediate state. It downloads the raw artifact and recomputes the hash. The compressor cannot fake a hash match — it would require producing a collision.

### Layer 2: Action — Tool-Count Recomputation

**System:** MorphSAT v8.3 early-verdict guard
**What's gated:** Verdict emission (benign/suspicious/escalate transition)
**Recomputation mechanism:** Monitor independently counts tool calls in the conversation. `MIN_TOOLS_BEFORE_VERDICT` rejects premature verdicts regardless of the agent's reasoning about sufficiency.
**Gate behavior:** Count >= threshold → allow verdict. Count < threshold → block, redirect to investigate.
**Receipt:** 100/100 on MorphSAT v8.3 benchmark. `supply_01` recovered (agent issued verdict after 1 tool call; guard forced 2nd tool call, monitor reached COMMIT with direction).
**Why it's recomputation, not evaluation:** The monitor doesn't evaluate whether the agent's investigation was *good enough* — it independently counts whether a minimum number of evidence-gathering actions occurred. The agent's self-report of "I have enough evidence" is not trusted.

### Layer 3: Fitness — Behavioral Recomputation

**System:** Specialist compute pool HXQ asset layer
**What's gated:** Routing of compressed model assets to production inference
**Recomputation mechanism:** Independent behavioral evaluation on held-out inputs. Asset claims fitness via tensor fidelity (cosine >= 0.998); routing additionally requires behavioral eval pass (25-task suite).
**Gate behavior:** Tensor fidelity PASS + behavioral eval PASS → promote to Active. Either FAIL → remain Candidate. Quarantine → block routing entirely.
**Receipt:** 153/153 tests.
**Why it's recomputation, not evaluation:** The evaluator doesn't review the compression method's reasoning about quality. It runs the compressed model on tasks independently and measures whether outputs match baseline. The compressor's training reports are not trusted.

### Layer 4: Reasoning — Conclusion Recomputation

**System:** MorphSAT v9 DualAgentGate (WO-RECOMP-04)
**What's gated:** Security verdict emission on ambiguous alerts
**Recomputation mechanism:** Second agent, same inputs, different prompt framing, produces its own verdict without seeing Agent A's output. Verdicts compared after both complete.
**Gate behavior:** AGREE → emit verdict (confidence = min of both). DISAGREE → escalate to human review.
**Receipt:** 4/4 gates PASS. 30% disagreement rate, 100% disagreement precision, 3 errors caught. `adv_fn_03`: Agent A wrong (0.95 conf), Agent B right — disagreement saved.

**Why it's recomputation, not evaluation:** Agent B never sees Agent A's output. It doesn't review Agent A's reasoning and decide if it's correct. It independently produces its own conclusion from the same raw inputs. The agreement check is structural, not judgmental.

**Key finding:** Prompt independence is sufficient. Same model, different framing = enough divergence to catch errors. The recomputation gate for reasoning doesn't require a different model — it requires a different perspective on the same evidence.

**Pre-flight finding:** Cost-gating is unsafe. Wrong answers had 0.95 confidence (highest in the set). Confidence does not predict error. Dual-agent must be unconditional for security verdicts.

---

## Biological Grounding: Cell Cycle Checkpoints

The pattern is structurally identical to cell cycle checkpoints in eukaryotic biology.

| Cell Biology | RGA |
|---|---|
| G1/S checkpoint | Data layer (hash verification before promotion) |
| G2/M checkpoint | Action layer (preconditions before state transition) |
| Spindle assembly checkpoint | Fitness layer (correct attachment before division) |
| DNA damage checkpoint | Reasoning layer (integrity before commitment) |

**ATM/ATR kinases** don't review the cell's *intention* to divide. They directly sense DNA double-strand breaks. **MAD/BUB proteins** don't evaluate the cell's *claim* of chromosome attachment. They detect mechanical tension at kinetochores.

Evolution converged on recomputation gates as the load-bearing primitive for high-stakes transitions because:
1. The cost of an undetected error cascades (one bad division → cancer)
2. Self-report from the system being gated is unreliable (damaged cells still signal "ready to divide")
3. Independent physical measurement is more expensive but unfakeable

The same logic applies to AI systems:
1. A wrong security verdict cascades (undetected exfiltration)
2. Agent confidence is unreliable (0.95 conf on wrong answer)
3. Independent recomputation is 2x cost but catches real errors

---

## The Unifying Claim

These four instances were built independently over 6 weeks for different domains (blockchain provenance, agent constraint enforcement, model deployment safety, security triage). They were never designed as instances of a common pattern. The pattern was identified retrospectively via EXPLORE mode synthesis.

**The claim:** Recomputation-gated architecture is a coherent design philosophy for AI systems where:
- Privileged transitions have high stakes (promotion, deployment, verdict)
- The system being gated can produce confident-but-wrong outputs
- Ground truth is independently reproducible (hash, count, behavioral output, conclusion)

**What RGA is NOT:**
- Not a replacement for evaluation (both are needed; RGA gates transitions, evaluation provides signal)
- Not always applicable (requires independently reproducible ground truth)
- Not free (2x cost at reasoning layer; negligible at data/action layers)

---

## Where RGA Doesn't Apply (Boundaries)

Recomputation requires that the verifier can independently produce the correct answer. This holds for:
- Hashes (deterministic)
- Counts (deterministic)
- Behavioral outputs (reproducible given same model + inputs)
- Conclusions from evidence (reproducible given same inputs + different perspective)

It does NOT hold for:
- Aesthetic judgment (no ground truth to recompute against)
- Creative generation (multiple valid outputs)
- Preference alignment (subjective, not reproducible)

**Boundary finding from WO-RECOMP-04:** Even at the reasoning layer, both agents can be wrong the same way (`adv_fn_02`: both said "suspicious" when answer was "escalate"). Shared training data creates shared blind spots. Recomputation catches *divergent* errors but not *convergent* errors. This bounds the safety claim honestly: RGA detects ~30% of errors (the divergent ones) with 100% precision.

---

## Counterexample Search

Searched the full stack for privileged transitions NOT gated by independent recomputation:

| System | Transition | Gate Type | Result |
|---|---|---|---|
| helix-substrate file load | Load tensor from disk | Hash check (recomputation) | Confirms pattern |
| helix-kv match=true | Accept tensor as equivalent | Cosine recomputation | Confirms pattern |
| Born-compressed training | Accept training result | Independent re-eval (44x ratio) | Confirms pattern |
| PR #21412 validation | Accept contribution | Wasserstein recomputed by Zyphra | Confirms pattern |
| Tailscale auth | Allow connection | Signature verification (evaluation-style) | Partial counterexample |

**Tailscale** is the closest counterexample — key-based auth verifies a signature rather than recomputing a conclusion. But signature verification IS recomputation of a mathematical property (does this signature correspond to this public key?). The line between "evaluate" and "recompute" blurs at the cryptographic layer. This suggests the pattern may be even more general than initially framed.

No clean counterexample found. The pattern is load-bearing across the stack.

---

## Implications

### For AI Safety

Most current AI safety work operates in evaluation mode:
- RLHF reward models *evaluate* whether an output is good
- Constitutional AI *evaluates* whether an output violates principles
- Output filters *evaluate* whether text is harmful

RGA-style safety would look like:
- Second model *independently produces* the answer, gate on agreement
- Divergent conclusions → don't emit, escalate
- Cost: 2x inference. Benefit: catches confident-but-wrong outputs.

This is not currently a standard primitive in mainstream safety work. Possibly because it's expensive. But cell cycle checkpoints are expensive too, and they evolved anyway because the alternative was catastrophic.

### For System Design

Any system that emits high-stakes decisions from a single inference path should ask:
1. Can a second path independently produce the same answer?
2. If they disagree, is the disagreement signal useful?
3. Is the cost of 2x inference less than the cost of a wrong decision?

If all three are yes, add a recomputation gate.

### For This Stack Specifically

The four-layer coverage means:
- **Data integrity** is gated (hxq-solana)
- **Process integrity** is gated (MorphSAT FSA)
- **Deployment integrity** is gated (specialist compute)
- **Reasoning integrity** is gated (DualAgentGate)

The remaining ungated layer is **memory integrity** — can the codon SSM state be independently recomputed from the event stream? This is architecturally possible (replay events, compare final state) but not yet built. Predicted fifth instance.

---

## Receipts

| Instance | Receipt | Key Metric |
|---|---|---|
| Data (hxq-solana) | `~/hxq-solana/receipts/verify_claim_verified_20260510.json` | VERIFIED: hash match, cosine 0.999718 |
| Action (MorphSAT v8.3) | `~/receipts/morphsat_v83_early_verdict_guard/` | 100/100, supply_01 recovered |
| Fitness (specialist compute) | `~/receipts/specialist_compute_pool_hxq_shards_20260502T160000Z.json` | 153/153 tests |
| Reasoning (WO-RECOMP-04) | `~/receipts/wo_recomp_04/recomp_gate_bench_20260511T035503Z.json` | 4/4 gates, 100% precision |
| EXPLORE synthesis | `~/hxq-solana/receipts/explore_rga_proof_of_concept_20260510.json` | Pattern identified |

---

## Lineage

```
2026-04-28  specialist compute pool built (fitness gate)
2026-05-07  MorphSAT v8.3 ships (early-verdict guard = action gate)
2026-05-10  hxq-solana codec-aware (independent verifier = data gate)
2026-05-10  EXPLORE mode synthesis: three instances connected → RGA named
2026-05-11  WO-RECOMP-04 validates reasoning gate (4/4 PASS)
2026-05-11  Pre-flight: cost-gating unsafe (overconfident errors)
2026-05-11  MorphSAT v9 DualAgentGate committed (14/14 tests)
2026-05-11  This document written
```
