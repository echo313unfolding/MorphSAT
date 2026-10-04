# P3 — DEFER → ARBITRATION: Preregistration v2.1 (amendment)

Status: **amendment to v2** (`docs/P3_DEFER_ARBITRATION_PREREG_V2.md`, commit
`e4bc7d9`, preserved unchanged). Everything in v2 stands except where amended
below. Written and committed **before** any P3 implementation or arbitration
outcome computation. Scope: public GitHub lineage of `14689b7`.

Kept unchanged from v2: DEFER nonterminal semantics (`local_acquisition_closed`
vs `decision_terminal`); COMMIT/ABSTAIN terminal authority; raw balance
definition; `wc_04` balance exactly `0.0` and its `≤ 0` treatment; threshold
table; asymmetric benign guard; claim ladder; safety and selective metrics; H2
pass/falsification criteria; E10 dead; no self-model/strange-loop claim;
own-vs-foreign deferred.

---

## A1 — Representation-independent candidates and eligibility (replaces v2 §4)

For each ArbitrationRequest at DEFER event with run order *i*:

1. **Candidates** — records in the same run (one benchmark family sequence)
   with `order < i`, `tag_overlap(alert_tags) ≥ 2`, and
   `resolved_by ≠ arbitration`. Every DEFER episode is resolved by arbitration
   in every baseline (B0 included), so this exclusion is identical across
   baselines.
2. **Slots** — the ≤ 5 most recent candidates by `order`. **Identical for B0's
   counterfactual, B1, B2, B2M, B3.**
3. **History-eligible** ⇔ ≥ 2 slots. No canonical action/outcome is consulted.
4. **Projection** (independently per baseline) of each slot into a directional
   vote or uncertainty:
   * B1: slot episode's contemporaneous evidence lean (t − s of its final
     monitor scores): `> 0` → `escalate`, `< 0` → `benign`, `= 0` → uncertainty.
   * B2 / B2M / B3: slot's canonical outcome: COMMIT(d) → vote d; ABSTAIN →
     uncertainty.
5. Arbitration criterion unchanged: ≥ 2 directional votes, share ≥ 0.75
   (denominator = directional votes + uncertainty among active slots), benign
   guard. A baseline whose projection yields < 2 directional votes ABSTAINS.

**Recomputed eligibility (label-free, outcome-free; from order and alert tags
only):** **6 / 19** — `spdo_07` (slots spdo_02–06), `drift_05` (drift_00–04),
`drift_06` (drift_00–04), `stale_03` (stale_00–02), `wc_04` (wc_00–03),
`wc_05` (wc_00–03). For transparency: without the `resolved_by ≠ arbitration`
exclusion the count would be 7 (adding `sgd_06`, whose only other candidate
`sgd_03` is itself a DEFER episode). The count is the same 6 as v2 but is now
derived without canonical information, and the slot contents of `drift_06` and
`wc_05` differ from v2 (earlier DEFER episodes excluded).

The v2 disclosure that B1 sees canonical slot roles is **withdrawn**: B1 no
longer receives any canonical information.

## A2 — Temporal semantics: store visibility vs request validity (amends v2 §6)

* **History store** may physically contain records with `order ≥ i` (replay,
  tests). Retrieval for event *i* filters `order < i`; such records are
  **invisible**. Appending future records to the store must not change a past
  request or result.
* **ArbitrationRequest** may contain only refs with `order < i`. A
  current/future ref in `candidate_refs` (or any slot) → **hard error (fail
  closed)**.
* **Causal edges:** `supersedes` is written at the correction record's
  creation and may only point to records with smaller `order` (forward
  reference → error at write). B3 may use an edge only if both endpoints are in
  the request's slot set and both precede *i*; `resolved_by` is fixed at write.
* Required tests: (1) future record appended to store → result unchanged;
  (2) future record injected into a request → error; (3) forward `supersedes`
  → error; (4) prefix invariance (run truncated at *i* gives identical result).

## A3 — Explicit DEFER reason whitelist (replaces v2 §2 table)

| `_force_commit` reason | Classification | DEFER-capable in P3 |
|---|---|---|
| `bench_end` | HARNESS_END | **yes** |
| `investigate_budget` | TOOL_BUDGET_EXHAUSTED | **yes** |
| `safe_distance_budget` | TOOL_BUDGET_EXHAUSTED | **yes** |
| `max_tools_reached` | MAX_TOOLS | **yes** |
| `loop_in_normal` | STAGNATION | **yes** |
| `investigate_no_progress` | STAGNATION | **yes** |
| `terminal_state` | defensive fallback | no (ABSTAIN) |
| `max_turns_no_verdict` (LLM benches) | recognized external end | no (ABSTAIN) |
| `adversarial_test_end` | recognized external end | no (ABSTAIN) |
| `cr_test_end` | recognized external end | no (ABSTAIN) |
| `compliance_test_end` | recognized external end | no (ABSTAIN) |
| anything else | **unknown** | **no** — existing non-DEFER behavior; reason recorded as `unrecognized_defer_reason` |

Enabling any further reason requires preregistration v3.

## A4 — Sham-mask diagnostic B2M (new; diagnostic only)

* Information: identical to B2 (canonical outcomes of the same slots; no causal
  links).
* Capacity matching: for each request, let *k* = number of slots B3 excludes by
  supersession. B2M masks exactly *k* slots.
* **Noncausal mask rule (frozen):** rank the request's slots by
  `sha256(f"{target_family}/{target_scenario_id}|{slot_family}/{slot_scenario_id}")`
  (hex digest, ascending, UTF-8); mask the first *k*. This uses only episode
  identifiers — no labels, outcomes, correctness, order, tags, or B3's identity
  of superseded records. A recency rule (mask oldest) was deliberately **not**
  chosen because supersession correlates with age, which would make the sham
  partly causal.
* If *k* = 0, B2M = B2.
* B2M is **not** part of the H2 criterion. Interpretation if B3 > B2:
  B3 ≈ B2M → benefit may come from reducing active memory; B3 > B2M → stronger
  evidence that causally identifying which history to suppress matters.

## A5 — Held-out construction strata

The held-out construction procedure
(`docs/P3_HELDOUT_CONSTRUCTION_PROCEDURE.md`) is committed separately, before
any P3 outcome computation, and contains two strata: **A — externally closed
DEFER** (HARNESS_END) and **B — endogenous DEFER** (STAGNATION,
TOOL_BUDGET_EXHAUSTED, MAX_TOOLS, produced naturally by the frozen rules).

This pilot is dominated by HARNESS_END (18/19 DEFERs; 5/6 eligible requests;
`wc_04` is the only endogenous eligible case). **A positive pilot on externally
closed cases is not evidence that the architecture naturally discovers when to
defer.**

## Output order for the P3 run

Per baseline (B0, B1, B2, B2M, B3), stratified HARNESS_END vs other: every
metric in v2 §9; H0/H1/H2 verdicts by the v2 criteria; B2M diagnostic reported
beside B3; per-request table (slots, projections, exclusions, result, cited
refs) — ground truth joined only at evaluation time.
