# Lineage B0 — Tank/Valve Simulator Validity: Preregistration v1.1 (FROZEN FOR IMPLEMENTATION)

Status: **frozen.** v1.0 candidate `c57185c` amended per the user's
2026-10-05 structural edits (§12). No Lineage B code existed at freeze.
Scope: public GitHub lineage of `14689b7`. Builds on scoping
`965ec90` / v1.1 (B-U1–B-U7). Branch `claude/lineage-b-prereg`.

**B0 makes no adaptive-learning or feedback-policy claim.** Its only output
is a frozen simulator plus validity receipts. B1 stays unfrozen until B0
passes. B0 may expose facts that legitimately change B1 wording or validity.

Standing inputs (`1fe9b0a`): `upstream_id` / `declared_upstream` is
provenance metadata only. Controls get their own scrutiny; the A4V shuffle
sham failed to destroy dependence.

## 1. Separation (invariant)

```
Z_t      hidden evaluator state          evaluator only
X_t      agent-visible delivered records sensors + channel → agent
Ô_{t+1}  frozen probabilistic prediction committed BEFORE T runs
O_{t+1}  subsequent sensor observations  delivered through the channel
```

| Module | Side | May import (besides stdlib/numpy) |
|---|---|---|
| `lineage_b/params.py` | shared constants | — |
| `lineage_b/world.py`, `sensors.py`, `channel.py` | evaluator | params |
| `lineage_b/obs.py`, `receipts.py`, `events.py` | shared types | params |
| `lineage_b/agent/*` | agent | `lineage_b.params`, `obs`, `receipts`, `events`, `lineage_b.agent.*`, `morphsat.terminal_authority` |
| `lineage_b/harness.py`, `logging_policy.py`, `evaluate.py`, `ref.py` | evaluator | all |

`params.py` holds only public nominal constants: tank geometry, nominal
physics, sensor specifications, bins, costs. Fault assignments and seeds are
**not** in `params.py`. They live in `world`/`harness` and are
evaluator-only.

## 2. Hidden state Z_t

| Component | Domain |
|---|---|
| level `h` | [0, H_max] m |
| inflow `q_in` | AR(1) `q_in' = q̄ + φ(q_in − q̄) + η`, η ~ N(0, σ_η²), clipped at 0 |
| valve position `u` | {0, .25, .5, .75, 1}; actual = commanded (no valve fault in v1) |
| leak `ℓ` | {none, slow, fast}; onset hazard per step; repair after a true-positive inspection |
| sensor / ADC fault states | frozen per condition (§6) |

## 3. Transition T (explicit Euler, exact discrete form)

```
q_out  = Cv · u · sqrt(max(h, 0))
q_leak = k(ℓ) · sqrt(max(h, 0))
h_raw  = h + (dt / A) · (q_in − q_out − q_leak) + w,   w ~ N(0, σ_w²)
h'     = clip(h_raw, 0, H_max)
spill  = A · max(h_raw − H_max, 0) / dt;   shortfall = A · max(−h_raw, 0) / dt   (both recorded)
```

The valve update is applied before the flow computation for the step: the
action at t sets `u_{t+1}`, used in the t → t+1 flow. `open` = +0.25 and
`close` = −0.25 (clipped to [0, 1]); `hold` and `inspect` leave `u`
unchanged.

## 4. Inspection

`inspect` at t yields an agent-visible record at t+1: `LEAK_FOUND` or
`NO_LEAK`. Errors: miss `e_m`, false alarm `e_f`. A true positive (leak
present and `LEAK_FOUND`) repairs the leak `R_rep` steps later.

## 5. Sensors and channel

| Sensor | declared_upstream | Model |
|---|---|---|
| L1 | ADC_A | `h + ε_A + ε_1` |
| L2 | ADC_A | `h + ε_A + ε_2` (same ε_A draw as L1) |
| L3 | ADC_B | `h + ε_3` |
| F | FEED_F | `q_out(t) + ε_F`, where q_out(t) = Cv·u_t·√h_t |
| P | ADC_C | `9.81 · h + ε_P` (kPa) |
| L4 (C3 only) | relay:L1 | exact copy of L1's value, distinct `sensor_id` |

Every record carries `sensor_id`, `seq`, `measured_at`, `delivered_at`,
`value` (float, or None = dropped), and `declared_upstream`.

**Channel.**
* Per-sensor delay (frozen distribution).
* MCAR dropout.
* Transport redelivery: the same `(sensor_id, seq)` is delivered a second
  time 1 step later.

**Agent-visible status per (sensor, measured_at):**
* `VALUE`;
* `PENDING` (age ≤ D_max, not received);
* `MISSING` (age > D_max, not received).

The agent cannot distinguish a drop from a long delay.

**RNG.**
* Independent `numpy.random.SeedSequence` substreams: inflow, process,
  leak, ε_A, ε_1, ε_2, ε_3, ε_F, ε_P, inspection, channel per sensor, and
  the logging policy.
* Each substream draws a **fixed number of variates per step regardless of
  action or state**, so exogenous noise is common across arms.

## 6. Conditions (one stationary sensor-fault regime per deployment)

A deployment has a **stationary** sensor/fault regime after onset `t_f`.
What persists across its episodes is sensor calibration. Cross-regime
poisoning and persistence are deferred.

| ID | Faults (from `t_f`) |
|---|---|
| C0 | none |
| C1 | L3 stuck at its reading at `t_f` |
| C2 | ADC_A bias +0.15 m (L1 and L2) |
| C3 | L1 drift +0.002 m/step, saturating at +0.3 m; relay alias L4 = copy of L1 |
| C4 | P noise ×5; F bias +0.02 |
| C5 | L3 delay ~ Geom(p = 0.5) on {1, 2, …} (mean 2 steps; a delay beyond D_max shows as MISSING until it arrives late); dropout L1/L2 0.10, P 0.30; no value faults |

The leak process runs in all conditions.

## 7. Frozen nominal predictor (invariant; user edit 3)

**The predictive model is identical and frozen across every agent arm
(G0–G3, G2-S).** It is a grid Bayes filter over (h, q_in, ℓ) =
100 × 11 × 3 cells, using:
* the §3 dynamics with **known nominal physics** (the published tank
  constants in `params.py`, equal to the simulator's values in v1);
* the agent's commanded valve position;
* the chosen action;
* the known sensor-model form `y = g(state) + b + N(0, σ²)`, with
  per-sensor `(b, σ)` supplied by the arm.

It may not use hidden h, hidden fault state, future observations, evaluator
labels or seeds. Its dynamics parameters are never fitted, least of all on
B1 seeds.

Documented simplifications:
* The filter assimilates only fresh records (`measured_at = t`). Late
  records are still scored against their receipt.
* Leak repair is modelled as: at `R_rep` steps after a `LEAK_FOUND`
  report, leak mass moves to `none`.
* G0–G2 assume conditional independence of sensors.

The predictor is not required to be perfect. Its errors are bounded and
characterized by gate 18.

## 8. Authority layer (frozen; arm-independent)

1. **Interlock → terminal COMMIT.** Uses the latest VALUE of L1, L2, L3
   with `measured_at ∈ [t − D_max, t]`; never θ. At least 2 readings
   ≥ 1.7 → COMMIT(open); at least 2 readings ≤ 0.3 → COMMIT(close).
2. **Terminal ABSTAIN.** At least 2 of L1–L3 have no VALUE in
   `[t − D_max, t]` → ABSTAIN, mapped to `inspect`.
3. **Otherwise DEFER → arbitration.** The controller proposes COMMIT(dir)
   or ABSTAIN. Its frozen rule:
   * if `P(ℓ ≠ none) ≥ 0.3` and there was no inspection in the last 10
     steps → ABSTAIN;
   * else `argmin_a` of
     `E[c_D (h_{t+1} − h*)² + c_U 1[h_{t+1} ∈ U]] + c_M 1[a ≠ hold]`
     over {open, hold, close}.

A thin adapter calls `morphsat.terminal_authority.resolve_terminal_authority`
unchanged. Directions are the strings `open`, `hold`, `close`; ABSTAIN maps
to `inspect`. The adapter adds no alternate override path (gate 12).

## 9. Records

* **ControlDecisionEvent** (new frozen type; user-approved S5). Fields:
  * deployment, episode, t, arm;
  * belief-before-action summary (posterior mean and sd of h,
    P(ℓ ≠ none), belief digest);
  * monitor action, terminal flag, authority path (interlock / terminal /
    arbitration) and controller reason (expected cost per candidate);
  * proposal, final action, `resolved_by`;
  * `theta_hash`, `receipt_hash`, propensity, visible digest,
    `canonical_hash`.

  The store is append-only.
* **PredictionReceipt.** Committed before T. Holds:
  * the per-sensor categorical over frozen bins;
  * the per-sensor latent predictive mean and variance of the measured
    quantity;
  * the action, `theta_hash` and belief digest.

  All of it sits under one hash, in a hash-chained store with a logical
  clock.
* **FeedbackRecord.** Written by the harness, never by the agent, when a
  VALUE for a receipted `(sensor, measured_at)` is first delivered. It
  stores, structurally, *(belief before action, action, reason, Ô, O,
  provenance, error, later update)*:
  * decision ref and receipt hash;
  * observed value and provenance;
  * per-sensor residual, log score and Brier score;
  * `theta_before_hash` / `theta_after_hash`, and whether an update was
    applied.

  Append-only. It is never rewritten when later evidence arrives.

## 10. Validity gates (all must pass; any failure stops B0)

| # | Gate | Test |
|---|---|---|
| 1 | Mass balance | With `w = 0`, `σ_η = 0`: `A·(h'−h) = dt·(q_in − q_out − q_leak − spill + shortfall)` within 1e-12, on fixtures: valve closed with inflow (linear rise), drain only, leak only, overflow, underflow |
| 2 | Deterministic replay | Same (seed, condition, action sequence) → identical hashes of the Z trajectory and the delivered stream; 3 seeds × 6 conditions |
| 2b | Common random numbers | Two different action sequences, one seed → identical exogenous variates, step for step |
| 3 | Actions change later state | Same state and seed: `open`×10 vs `close`×10 changes h at t+10 by ≥ 0.05 m |
| 4 | Shared-upstream dependence | corr(L1 err, L2 err) = 0.5 ± 3·SE over ≥ 20,000 steps (C0). Under C2, both L1 and L2 errors shift by +0.15 at the same steps |
| 5 | No accidental shared noise | Every pair other than (L1, L2) and (L1, L4): \|corr\| ≤ 3/√N. Distinct spawn keys per noise source |
| 6 | Missing/delayed explicit, never success | Status ∈ {VALUE, PENDING, MISSING}. An all-MISSING stream gives zero θ updates and no FeedbackRecords, and every skip is logged |
| 7 | Hidden state never agent-visible | (a) AST import rule (§1); (b) Observation/record types carry no hidden fields; (c) the agent replayed on a recorded stream while the harness holds a different hidden world gives identical decisions, receipts and θ hashes; (d) NaN-poisoned evaluator state leaves agent outputs unchanged |
| 8 | Receipts committed before transition | `world.step` raises without a matching commitment for (episode, t+1). The chain verifies. Commit clock < transition clock |
| 9 | DecisionEvents immutable | Frozen dataclass; mutation raises; the store is append-only; read-back hashes are equal after a full run with updates |
| 10 | Logging propensities correct | Propensities sum to 1. Empirical frequencies over 10⁵ draws per context class match them (χ² p ≥ 0.001). Interlock and terminal steps record propensity 1, flagged non-randomized |
| 11 | Updates affect only future lawful routing/arbitration | Perturbing records delivered after t leaves decisions ≤ t identical. Randomizing θ leaves interlock and terminal-ABSTAIN outputs identical |
| 12 | Terminal authority untouched | `morphsat/terminal_authority.py` byte-identical to `eb3f6d3` (its last frozen version). Every final action is produced by `resolve_terminal_authority`. On non-DEFER steps the adapter never submits an arbitration proposal, and a forced attempt raises |
| 13 | **Action sensitivity** (user edit 2) | From fixed admissible beliefs (h ∈ {0.5, 1.0, 1.5}, u = 0.5, C0 nominal θ), `KL(P(O_{t+1} \| open) ‖ P(O_{t+1} \| close)) ≥ 0.05` nats for L3 and for F at every listed belief. This proves actions matter to the predictor. The sham itself is validated in B1, not here |
| 14 | Transport duplicates count once | A redelivered `(sensor_id, seq)` is assimilated, scored and updated exactly once |
| 15 | Fault semantics | Each C1–C5 fault reproduces its specification from `t_f` (fixtures) |
| 16 | Evaluator metrics | Cost J, unsafe transitions and false-safe are correct on hand-built trajectories |
| 17 | G0 / REF-S variance pilot | G0 (θ0, μ off) and REF-S only, on pilot seeds disjoint from B1's: var(J) and mean J per condition, used **only** to set N (B1 §7). No G1/G2/G3/G2-S code runs |
| 18 | **Nominal predictor calibration** (user edit 3) | C0, μ behaviour, θ0, 20 deployments × 1 episode on B0 seeds. For each of L1, L2, L3, F, P: 90% central-interval coverage ∈ [0.85, 0.95] and 50% coverage ∈ [0.40, 0.60]. Mean log score and mean standardized residual are reported. If outside the range, B0 fails |
| 19 | FeedbackRecord integrity | Each record references an existing earlier receipt. Its scores recompute exactly from (receipt, observed value). Records are append-only. The agent module cannot write them |

**REF-S definition (user edit 4).** Same observations at the same times, the
same action space, authority layer and controller. It is told which sensors
are faulty and their true error parameters: bias, noise, stuck sensors
treated as uninformative, alias identity, and the shared ADC_A covariance.
It never sees hidden h or Z. Z stays evaluator-only, for scoring.

## 11. Frozen parameters

All values are as proposed in `docs/LINEAGE_B_UNRESOLVED_PARAMETERS_V1.md`
(`c57185c`), §B and the relevant §C rows, and are now frozen. Structural
choices:

| ID | Frozen choice |
|---|---|
| S1 | G1 = same-time leave-one-out consensus |
| S2 | Shared learning log, then frozen evaluation |
| S3 | Persistence within a stationary-regime deployment |
| S4 | Learn `(b, σ)` only |
| S5 | New ControlDecisionEvent |
| S6 | REF-S as constrained above |
| S7 | Truthful declared provenance |
| S8 | MCAR missingness |
| S9 | Gates as listed |
| S10 | No valve faults |

Nominal per-sensor σ for θ0: L1 = L2 = √(σ_A² + σ_i²) = 0.01414 m (the
marginal); L3 = 0.014; F = 0.003; P = 0.196 kPa.

Seeds:

| Purpose | Root |
|---|---|
| B0 gates | 20261005 |
| pilot | 20261006 |
| B1 | 20261007 |

Spawned children are disjoint, and their hashes are written to the
receipts.

## 12. Changes from candidate v1.0 (`c57185c`)

* Gate 13 replaced: the action-sensitivity gate replaces sham validation.
  Sham checks move to B1.
* Added §7, the frozen-predictor invariant, and gate 18, the C0
  calibration range.
* REF-S constrained to fault knowledge only, with the same information
  timing.
* Deployment = stationary regime; what persists is sensor calibration.
* FeedbackRecord added (§9), plus gate 19.
* Gate 12 reference corrected: `terminal_authority.py` was added after
  `14689b7`, so its frozen reference is `eb3f6d3`.
* All parameters frozen (§11).

## 13. Threats

* **T-B1** Designer-determined identifiability: B1 outcomes are conditional
  on these choices.
* **T-B2** MCAR missingness is easier than reality.
* **T-B3** Nominal physics equals the simulator's in v1. The only predictor
  mismatch comes from the §7 simplifications, the leak and sensor faults.
