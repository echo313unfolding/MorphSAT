# Lineage B — Grounded Causal Feedback: Scoping v1.1 (DRAFT)

Status: **scoping only** — revision of `docs/LINEAGE_B_GROUNDED_FEEDBACK_SCOPING.md`
(`965ec90`, preserved). No simulator, no implementation, no preregistered
outcome experiment. Everything in v1 stands unless amended. Biology remains
design inspiration only.

## 1. Fixed scoping decisions

| ID | Decision |
|---|---|
| B-U1 | First simulator is a **physical tank/valve** world (not cybersecurity): clean separation of hidden state, action, physical transition and observation. |
| B-U2 | A **pathway** is a fixed routing/arbitration policy — not trainable weights or latent representations. |
| B-U3 | Predictions are **probabilistic next-observation distributions** `p(O_{t+1} | O_{≤t}, A_t)` (categorical over frozen bins per sensor), so proper scoring rules apply. |
| B-U4 | Delayed and missing observations are explicit states with distributions fixed in the eventual preregistration. **A missing observation is never treated as success.** |
| B-U5 | Primary selective-feedback design: a **known randomized logging policy** with recorded action propensities, enabling principled off-policy evaluation (inverse-propensity / doubly robust; Dudík, Langford & Li 2011). |
| B-U6 | **Nonadaptive, frozen** sensor corruption first. Adaptive adversaries are a later stress test. |
| B-U7 | Scale set later by a power/sensitivity analysis, after simulator mechanics are frozen. |

## 2. Required separation (invariant)

```
hidden evaluator state  Z_t          (evaluation only)
   ≠ agent observation   X_t          (sensor readings available before acting)
   ≠ frozen prediction   Ô_{t+1}      (hashed before the transition runs)
   ≠ subsequent sensor observation O_{t+1}
```

No component may read across these boundaries in the forbidden direction
(agent ← Z, prediction ← O_{t+1}, pathway → its own receipt).

## 3. Tank/valve world (sketch for the eventual preregistration)

* **Hidden state Z_t:** tank level, true inflow, outlet valve position, and a
  hidden fault (e.g. leak ∈ {none, slow, fast}) with a frozen onset process.
* **Actions A_t:** open / hold / close the outlet valve; request inspection
  (maps to deferral). Mapped from MorphSAT outcomes; COMMIT/ABSTAIN terminal
  authority preserved.
* **Transition T(Z_t, A_t):** discrete-time mass balance with process noise;
  the chosen action changes future level/flow, so consequences depend on it.
* **Sensors:** at least two level sensors sharing one upstream ADC (dependent),
  one independent level sensor, one flow sensor, one pressure sensor; each with
  frozen reliability and frozen corruption (e.g. stuck-at, bias, dropout).
* **Delay/censoring:** per-sensor delay and dropout; explicit `MISSING` /
  `DELAYED(d)`.

## 4. Provenance dependency on Lineage A

Lineage A's `source_id` / `upstream_id` schema and dependence accounting are
adopted as the **canonical provenance schema**; Lineage B generalizes the
single `upstream_id` into a **sensor dependency graph** (shared ADCs, shared
feeds). Independence weighting in B uses upstream-graph connectivity, never
apparent sensor ids alone. B's preregistration waits for A's result; if A
finds no benefit for independence-aware corroboration, B's independence
hypothesis is revisited before preregistration.

## 5. Unchanged from v1

Invariants 1–9, `PredictionReceipt` schema (written by the evaluator layer,
prediction hash committed before transition), candidate update rules U0–U3,
evaluation machinery (Gneiting & Raftery 2007; Dawid & Skene 1979; Dudík,
Langford & Li 2011), and the A→B overlap map.

## 6. Prior art

As in Lineage A v1.1 §8 (2026 provenance-laundering preprints, verified by
the reviewer; relevant preprints, not established conclusions).
