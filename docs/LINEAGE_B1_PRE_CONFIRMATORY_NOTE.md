# Lineage B1 — Pre-Confirmatory Interpretation Note (doc-only)

**Status: interpretation and operations note.**
* **Not an amendment.** It changes no hypothesis, arm, criterion, margin,
  analysis rule, sizing result, N or seed list, and no protected source.
* **Timing.** Written after the blinded §7a sizing completed and N was
  frozen, and **before** the confirmatory root 2026100514000 was opened. No
  confirmatory receipt exists.
* **Sources.** It is based only on design facts and on what the blinded
  sizing receipt contains: variances, UCLs and N_q, with no means or effect
  estimates.

References:
* sizing receipt `receipts/lineage_b1/b1_sizing_COMPLETED_20261011T020204Z.json`
  (sha256 `080d8cd4…dd381a`, root 2026100521000);
* freeze `82d347a` (N = 2350);
* amendments v1.5.1 – v1.6.3.

Independent review, from the receipt alone (no seeded execution):
* All 18 N_q values reproduce exactly from the receipt's variances, the
  frozen χ² constants, z = 1.96 and the frozen half-widths.
* The receipt is blinded.
* SV1–SV4 pass (SV3 = 1.0, SV4 = 0.605 nats).
* `b1_frozen.py` and the seed-list hash verify.
* `verify_post_sizing_freeze` passes.

## 1. Threat T8 — the exploration rate shapes what B1 measures

v1.6 raised the B1 learning-phase logging exploration rate to
`B1_LOGGING_EPSILON = 0.5`, so that SV3 could be satisfied. The decision was
taken before any outcome, from feasibility arithmetic. This is legitimate,
but it changes the experiment:
* About half of all learning-phase DEFER actions are now randomized, so the
  learning log contains much more action variation than a mostly-G0 policy
  would produce.
* G2 learns from action-conditioned prediction error, so it can exploit that
  variation. G1's same-time consensus ignores the action, so it gains nothing
  from it.
* Any G2-vs-G1 difference is therefore conditional on ε = 0.5. It must not be
  read as holding for other exploration rates, or for a log produced by a
  mostly greedy controller.

Neither the direction nor the size of this dependence is asserted in advance.
Reporting will state the ceiling claim as holding "under ε = 0.5 randomized
logging in the learning phase".

## 2. Threat T9 — F4's unsafe-transition component cannot detect harm here

In the sizing receipt, the sample variance of the per-deployment paired
difference in unsafe-transition rate is **exactly 0** for G2 − G1 and for
G2 − G0:
* in every fault condition C1–C5 (the pooled F4 quantities);
* in C5 alone (the F4-C5 quantities).

Their N_q values are 0.

That means no sizing deployment showed any between-arm difference in
unsafe-transition rate. A zero variance does not by itself show that the rates
were zero; it only shows they did not differ. Consequences:
* F4's unsafe-transition component is evaluated as frozen, but in this
  simulator it has essentially no ability to detect harm. A pass on it will
  **not** be cited as evidence of safety.
* Safety evidence in B1 rests on F4's **false-safe** component (and on F5 in
  C0).

## 3. N is set by a guard criterion, not the primary contrast

| Quantity | N_q |
|---|---|
| F1 (primary, pooled Δ12) | 280 |
| P0 | 673 |
| F2 | 637 |
| F3 | 228 |
| F4-C5 false-safe G2−G1 | 647 |
| F5 | 278 |
| F6, C1 / C2 / C3 / C4 / C5 | 1123 / 1702 / **2350** / 759 / 1048 |

N = 2350 comes from F6|C3: per-condition non-inferiority of G2 against G1 in
C3, under the conservative family-wise variance bound. That is the frozen rule
working as designed. The confirmatory run is about 8× larger than the primary
contrast alone would need; the extra size buys condition-level precision, not
primary-contrast power.

## 4. Operational notes for the one-shot confirmatory run

* **Size.** 6 conditions × 2350 = 14,100 deployment-conditions, all seven
  arms. Stage B also re-runs learning deterministically for OPE (v1.5.1 §6).
* **Benchmark.** Sizing attempt 2 (300 deployment-conditions, 5 arms, no G3,
  REF-Z or OPE) took about 4 h 18 m wall time. The confirmatory run is about
  47× the deployments with roughly 2–3× the work each, so it is likely
  **weeks** at sizing-run parallelism. This is an estimate, not a
  measurement.
* **One-shot.** Under the frozen run control, a crash after
  `b1_confirmatory_STARTED` consumes root 2026100514000, and there is no
  resume. Protected sources cannot change before the run either: the
  post-sizing freeze rejects any change. Mitigation must therefore be
  operational:
  * a stable machine with many cores (not the laptop);
  * enough disk for 2 × 14,100 per-deployment records;
  * `--outdir` outside the repository, empty, on durable storage;
  * no other workload competing for memory.
* **Receipt gap.** The sizing receipts do not record the worker count. Record
  it, together with the host, start time and command line, in the
  confirmatory launch notes, so throughput and timing can be interpreted.

## 5. What this note does not do

* It does not alter the outcome mapping.
* It does not add or remove a criterion.
* It does not reinterpret any result in advance.

T8 and T9 are disclosures added to B1's threat list (§10), to be carried into
the confirmatory report.
