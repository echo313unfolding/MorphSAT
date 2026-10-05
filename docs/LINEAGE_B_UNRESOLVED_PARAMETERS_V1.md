# Lineage B0/B1 — Unresolved Parameters (proposed defaults; for the user's decision)

Nothing here is frozen. Values are proposals chosen for plausibility and
internal consistency, not tuned on any outcome. Nothing has been run.

## A. Structural choices (decide first; they change the design)

| ID | Choice | Proposed | Alternative |
|---|---|---|---|
| S1 | G1 definition | same-time leave-one-out consensus (strongest non-grounded competitor; Dawid–Skene spirit) | self-consistency against the agent's own posterior history (weaker; partly self-confirming) |
| S2 | Learning protocol | common-log learning under μ, then frozen-θ on-policy evaluation (arms differ only by update rule) | online learning, with each arm acting under its own ε-randomized policy |
| S3 | θ persistence | within a deployment (across its episodes), reset between deployments | within an episode only |
| S4 | Learned object | per-sensor `(b_i, σ_i)` only; controller fixed | also learn pathway weights (needs reward-based bandit learning; closer to U1) |
| S5 | Event type | new frozen `ControlDecisionEvent` in `lineage_b/` (semantics mirror v4) | reuse `morphsat.decision_event` v4 (its fields are P3-specific) |
| S6 | REF-S (true sensor model, evaluator-side) | include, as closure denominator | omit; use REF-Z only |
| S7 | Declared provenance | truthful in v1 | include laundering (deferred) |
| S8 | Missingness | MCAR in v1 | MNAR stress test |
| S9 | Added gates 2b, 13–17 | include | drop any |
| S10 | Valve faults | none in v1 (actual u = commanded u) | add a stuck-valve condition |

## B. Simulator parameters (B0)

| Parameter | Proposed |
|---|---|
| Tank area A, height H_max, setpoint h* | 1.0 m², 2.0 m, 1.0 m |
| dt | 1 step |
| Inflow AR(1): q̄, φ, σ_η | 0.05, 0.9, 0.003 (m³/step) |
| Valve coefficient Cv; valve positions | 0.1; {0, .25, .5, .75, 1}, ±0.25 per action |
| Leak k(slow), k(fast); onset hazard; P(slow given onset) | 0.01, 0.03; 0.002/step; 0.7 |
| Process noise σ_w | 0.002 m |
| Inspection miss / false alarm; repair delay R_rep | 0.10 / 0.05; 5 steps |
| Unsafe region U | h > 1.8 or h < 0.2 |
| Warning (hazard) bands | [1.6, 1.8) high; (0.2, 0.4] low |
| Interlock thresholds h_IL^hi / h_IL^lo | 1.7 / 0.3 |
| σ_A (shared ADC), σ_1 = σ_2, σ_3 | 0.01, 0.01, 0.014 m |
| σ_P, σ_F | 0.196 kPa (≈ 0.02 m), 0.003 m³/step |
| Prediction bins | level 0–2.0 m by 0.02; P 0–19.62 kPa by 0.196; F 0–0.15 by 0.003; plus under/overflow bins |
| D_max (PENDING → MISSING) | 3 steps |
| Transport redelivery probability | 0.02, all conditions |
| Fault onset t_f | learning episode 1, step 50 |
| C1 | L3 stuck at its value at onset |
| C2 | ADC_A bias b_A = +0.15 m |
| C3 | L1 drift +0.002 m/step, saturating at +0.3 m; alias L4 |
| C4 | P noise ×5; F bias +0.02 m³/step |
| C5 | L3 delay ~ Geom(mean 2); dropout L1/L2 0.10, P 0.30 |
| Gate tolerances | 1e-12 (mass balance); ±3 SE (correlations); χ² p ≥ 0.001 (propensities); κ = 0.05 nats (gate 13) |
| Root seeds | B0: 20261005; pilot and B1: spawned disjoint children, hashes committed |

## C. Agent and experiment parameters (B1)

| Parameter | Proposed |
|---|---|
| Filter grid | h 100 bins × q_in 11 bins × ℓ 3 |
| θ0; learning rates η_b, η_σ; σ_min | nominal; 0.02, 0.02; 0.25 × nominal σ |
| Controller τ_I; inspection cooldown R_cool | 0.3; 10 steps |
| Costs c_U, c_D, c_I, c_M, c_L, c_S | 100, 10, 2, 0.1, 200 per m³, 200 per m³ |
| Episode length T; E_L; E_E | 200; 5; 5 |
| μ exploration ε | 0.2 (each alternative 0.0667) |
| Closure minimum effect of interest | 0.10 of `J_G0 − J_REF-S` |
| δ_safe | unsafe-transition rate +0.0005/step; false-safe rate +0.005/step (absolute) |
| δ_null | 2% of mean J_G0 in C0 |
| Bootstrap | 10,000 resamples, stratified by condition, frozen seed |
| N per condition | from the gate-17 pilot (B1 §7), cap N_max = 200 |
| OPE ridge λ; cross-fitting | 1.0; 2 folds by deployment |
