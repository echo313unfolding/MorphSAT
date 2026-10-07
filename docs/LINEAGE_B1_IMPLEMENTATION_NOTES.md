# Lineage B1 — Implementation Notes (§15 step b)

> **Superseded where they differ by the binding pre-execution amendment v1.5.1
> (`docs/LINEAGE_B1_PREREG_V1_5_1_AMENDMENT.md`, `f4f5990`).** The
> implementation-level choices below are now fixed by that amendment.
> Corrections made in the corrective commit after `2206373`:
> * the sham construction is now the maximum-mismatch permutation;
> * G1 uses a pre-batch θ snapshot, and all learning arms use a canonical
>   batch order;
> * learning-phase provenance (`G0-logging` behavior events and
>   BehaviorDecisionRecord);
> * stage A/B sham barrier;
> * one-shot STARTED receipts;
> * post-sizing code freeze;
> * outcome-mapping precedence;
> * the time-to-detection diagnostic is removed.
>
> The "Foreseeable risk" section is resolved by amendment §1: SV3 stays at
> 0.80, and failure is now only possible when the action marginal makes 80%
> unattainable.

Prereg: B1 v1.5, sizing-design frozen at `2473c2a`. This commit implements
B1. **Nothing has been executed on the validation, sizing or confirmatory
roots.** No §7b validation, no sizing, no N, no confirmatory freeze.

## Files (all new; no existing file modified)

| File | Side | Content |
|---|---|---|
| `lineage_b/agent/arms.py` | agent | G1 consensus reference, G2 receipt reference, G2-S sham block, G3 `DependencyModel`; `B1Agent` (subclass of the frozen `core.Agent`) |
| `lineage_b/b1_seeds.py` | evaluator | the three reserved roots, opened only with runner tokens; frozen bootstrap seed; seed-list hash |
| `lineage_b/b1_protocol.py` | evaluator | §1 protocol per deployment: pass 1 (log), pass 2 (lockstep learning), frozen-θ evaluation, REF-Z, per-arm metrics, SV inputs, OPE data |
| `lineage_b/b1_stats.py` | evaluator | frozen constants, χ² constant-integrity check, stratified paired percentile bootstrap, P0/F1–F6, outcome mapping, blinded sizing |
| `lineage_b/b1_analysis.py` | evaluator | confirmatory table, SV aggregation, §9 diagnostics, OPE (IPS/DM/DR) |
| `lineage_b/b1_validation.py` | evaluator | §7b: V0 + adapted gates 7, 11, 12 for G1/G2/G3/G2-S |
| `lineage_b/b1_runctl.py` | evaluator | clean-tree check, source fingerprint, receipt writing |
| `lineage_b/b1_frozen.py` | — | N / seed-list hash / sizing receipt, all `None` until the confirmatory freeze |
| `tools/run_lineage_b1_validation.py`, `..._sizing.py`, `..._confirmatory.py` | runners | §7b, §7a, §15 h |
| `tests/test_lineage_b1_static.py` | tests | 15 synthetic unit tests: no world, no reserved root |

**Unchanged:**
* `lineage_b/agent/predictor.py` (byte-identical to `94f4f11`);
* `morphsat/terminal_authority.py`;
* every B0 module, gate, receipt, test and doc.

## Structural guarantees

* **G2-S sham isolation.** The sham action is used in exactly one place:
  `B1Agent.commit_prediction` computes a second, separate `payload["sham"]`
  block from `predict(B, u_after(u, sham))`. The belief carried forward, the
  receipt's `action`, the executed world action and every authority input
  use the true action. During learning the world is stepped only with the
  logged action. During evaluation G2-S runs with `updater=None`, so the
  sham path is inactive.
* **G3 dependency metadata.** It is used only inside
  `DependencyModel.assimilate` (joint likelihood, relay collapse) and in
  G3's learning. `arms.py` imports nothing from authority, world, sensors or
  the harness (unit test plus gate-12 check). The monitor, interlock and
  terminal-abstain paths stay the frozen, θ-blind B0 code.
* **Seed families.** `deployment_seeds` / `bootstrap_rng` raise unless given
  the family's runner token. The sizing runner additionally refuses to start
  without a PASSED §7b receipt for the identical source fingerprint, and
  refuses if any sizing receipt already exists (one-shot). The confirmatory
  runner refuses until `b1_frozen.py` is filled and its seed-list hash
  matches.
* **Sizing blinding.** Per-deployment metrics live only in the runner's
  memory. The receipt is whitelisted to n_s, variances, UCLs, N_q,
  N_required, N, status, V0, SV and the source fingerprint. Progress output
  prints counts only.

## Implementation choices the frozen text did not pin down (for review before sizing)

1. **Two-pass learning phase.** G2-S's derangement gives each DEFER step
   the logged action at the next hash rank, possibly a later step.
   * Pass 1: G0 at θ0 plus μ generate the log.
   * Pass 2: the same world is re-executed from the same seeds, with the
     logged actions. All learning arms observe the identical stream, and
     each commits its receipt before every transition through a lockstep
     barrier that requires all arms' commitments.
   * Pass 2 asserts that it reproduces pass 1's stream and levels exactly,
     and aborts otherwise.
2. **Derangement key.** `sha256("<purpose>:<condition>:<deployment>|g")`,
   where g = episode·200 + t is the deployment-global step. At non-DEFER
   steps (interlock, terminal) no derangement is defined, and the sham
   equals the logged action.
3. **SV aggregation over the sizing (or confirmatory) set.**
   * SV1 and SV2 must hold in every deployment.
   * SV3 uses the pooled fraction of DEFER steps whose sham differs (≥ 0.80);
     the per-deployment minimum is also reported.
   * SV4 is the mean KL(genuine ‖ sham) over (step, sensor) pairs, for the
     sensors gate 13 tested (L3, F), on DEFER steps whose sham differs
     (≥ 0.05 nats).
4. **G1 same-time set** = every VALUE record the agent has seen with the same
   `measured_at`, including the current delivered batch, so the result does
   not depend on within-batch order.
   * Level-equivalent maps: levels `y − b`; pressure `(y − b)/9.81`; flow
     by a first-order inverse of `Cv·u·√h`, using the commanded valve
     position at `measured_at`. Flow is omitted when u = 0 or `y − b ≤ 0`.
   * L4 is treated as an ordinary sensor, since G1 has no dependency
     knowledge.
   * No update happens without at least one other sensor (logged).
5. **G3 parameterization** ("as G2, plus" shared τ² and a group bias).
   * Group = sensors sharing a non-relay `declared_upstream` (ADC_A: L1,
     L2).
   * Effective bias = group bias b_g + individual deviation d_i. With both
     members present, the effective-bias update equals G2's per-sensor rule
     (unit-tested).
   * τ² = max(0, EWMA of the residual cross-product − s²_ref);
     σ_i² = max(σ_min², v_i − s²_ref − τ²).
   * Initial τ² = 0, so G3 starts identical to G2.
   * A (group, step) slot updates once all members are present, or once it
     is older than D_MAX, or at the next episode's start.
   * Group-member FeedbackRecords carry `update_applied = False`; the slot
     update is logged separately.
   * Relay copies are dropped when their source is present, and used as the
     source otherwise.
6. **REF-Z.** Myopic expected one-step cost on the true Z_t over the
   process noise (20-point Gauss–Hermite), tie order hold/open/close/inspect.
   It runs through the same frozen authority layer as every arm (interlock
   and terminal-abstain from its delivered records). A myopic one-step
   objective never pays for inspection, so REF-Z will essentially never
   inspect.
7. **One-step cost** (OPE reward and REF-Z objective):
   `c_U·1[h_{t+1}∈U] + c_D(h_{t+1}−h*)² + c_I·1[inspect] + c_M·1[Δu≠0] + c_L·q_leak + c_S·spill`.
8. **Action error / coverage / selective risk** are evaluated on the arm's
   own evaluation DEFER steps against REF-Z's myopic action at the arm's own
   Z_t.
9. **Bootstrap seed** = SeedSequence(entropy = confirmatory root,
   spawn_key = (6, 0)), outside every (condition, deployment) key. One
   (10,000 × n_c) index draw per condition, reused for every quantity.
10. **Outcome-mapping precedence.**
    * The harm row (¬F4 ∨ ¬F5 ∨ ¬F6) is checked before the "F3 not
      isolated" row.
    * F1 ∧ ¬F2, which the frozen table does not list, is reported as "no
      ceiling claim".
11. **OPE details.**
    * Features: posterior mean and variance of h, P(ℓ ≠ none), u, and fresh
      flags for L1, L2, L3, F, P.
    * Ridge λ = 1.0 (frozen via B0 v1.1 §11 / unresolved-parameters §C),
      with an intercept, on raw features.
    * 2 folds by deployment-index parity within each condition.
    * Per-deployment DR CI uses a normal approximation.
    * Truth = an exact CRN counterfactual from a world snapshot.
12. **"Time to detection after t_f"** (§9, a diagnostic) is **not
    computed**: the prereg names it but defines no detection rule. θ
    trajectories are reported as end-of-episode θ hashes plus final θ
    values.
13. **Evaluation agents.**
    * G0 and REF-S use the frozen `core.Agent`, as in the B0 pilot.
    * Learners use `B1Agent` with `updater=None`, because G3 needs its relay
      bookkeeping; θ is asserted unchanged after evaluation.
14. **Confirmatory per-deployment records** are pickled to a user-given
    output directory, which is not committed.

## Foreseeable risk (structural; no outcome used)

**SV3 may fail by construction.** The derangement pairs each DEFER step
with another step's logged action. The chance that the sham equals the
logged action is therefore about Σ_a p_a² over μ's action marginal. If G0's
controller proposes `hold` on most DEFER steps (μ keeps it with probability
0.8), that sum can exceed 0.2. Then fewer than 80% of sham actions would
differ, and the frozen rule stops the sizing run as a sham-design failure.

I have not measured μ's action marginal; doing so needs a seeded run. The
§7b validation run does not compute SV. Whether to look at this risk before
spending the sizing set is your decision.

## Pre-commit execution (complete list)

* Compile and import of all new modules; pyflakes, installed outside the
  repo.
* 15 synthetic unit tests.
* One synthetic smoke check: each arm's agent methods on a fixed constant
  record stream (no world), plus the OPE analysis on arbitrary arrays.
  Crash and finiteness only; no arm compared.
* No world simulation, no logging-policy run, no reserved seed root, no
  receipt.
