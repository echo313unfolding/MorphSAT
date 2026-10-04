# P3 — DEFER → ARBITRATION: Preregistration v2

Status: **PREREGISTRATION ONLY — not implemented.** Supersedes v1
(`docs/P3_DEFER_ARBITRATION_DESIGN.md`, commit `ca2b8d6`), which is retained for
the record and must not be implemented. Base code: `claude/p2d-docs` @ `ae3130d`
(public GitHub lineage of `14689b7`; no private/home-machine state).

Any change to a rule, threshold, representation or test below after the first
P3 run requires preregistration v3; all runs are reported.

**Designer disclosure.** The designer knows benchmark family intents. No
per-episode ground-truth label was used to choose any rule. Episode lists, reason
counts and the boundary balance below were computed from monitor internals and
prior canonical outcomes only. Arbitration resolutions were NOT computed.

---

## 1. Revised state machine

Two orthogonal properties replace the single latch for DEFER.

| State | local_acquisition_closed | decision_terminal | arbitration_allowed |
|---|---|---|---|
| CONTINUE | false | false | false |
| **DEFER** | **true** | **false** | **true** |
| COMMIT | true | true | false |
| ABSTAIN | true | true | false |
| SWARM_CALL (→ ABSTAIN) | true | true | false |

* `decision_terminal` ≡ the P2A `terminal_latched` (alias `committed`, receipt
  key `"committed"`) — its meaning is **unchanged**: set only by COMMIT, ABSTAIN,
  SWARM_CALL. **DEFER does not set it.**
* `local_acquisition_closed` is new: set by DEFER and by every terminal action.
  Evidence acquisition (`process_evidence`) stops when it is true; after DEFER it
  returns a `"DEFERRED"` pseudo-action (the `"COMMITTED"` pseudo-action stays for
  terminal states).
* With `enable_defer = False` (default) `local_acquisition_closed ==
  decision_terminal` at all times → all existing behavior, tests and receipts
  unchanged.
* P2 terminal authority is **not weakened**: `TERMINAL_AUTHORITY_ACTIONS =
  {COMMIT, ABSTAIN}` unchanged. DEFER may be resolved **only** by a proposal with
  source `arbitration`; any other proposal on DEFER (GateQUBO, TwoStage QUBO,
  echo tiebreak) is blocked and kept as `attempted_*` provenance.
* Arbitration output ∈ {COMMIT(d), ABSTAIN}; after it the decision is terminal.
  `final_action == DEFER` is an invariant violation.

## 2. R1 — exact semantics (approved, now source-stratified)

Locus: `ShadowMonitor._force_commit(reason, evidence_balance)`, dual-boundary
mode, the branch reached when `contradiction < contradiction_gate` and
`-commit_safe_boundary < evidence_balance < commit_threat_boundary` (the branch
that today sets `abstain_due_to_uncertainty = True`). With `enable_defer`, that
branch emits **DEFER** (instead of ABSTAIN) with `reason_for_defer`:

| `_force_commit` reason (existing strings) | reason_for_defer |
|---|---|
| any caller-supplied reason not listed below (`bench_end`, `max_turns_no_verdict`, `adversarial_test_end`, `cr_test_end`, `compliance_test_end`, …) | **HARNESS_END** |
| `investigate_budget`, `safe_distance_budget` | **TOOL_BUDGET_EXHAUSTED** |
| `max_tools_reached` | **MAX_TOOLS** |
| `loop_in_normal`, `investigate_no_progress` | **STAGNATION** |
| `terminal_state` (defensive fallback) | no DEFER — stays ABSTAIN |

Not DEFER (unchanged terminal ABSTAIN): contradiction ABSTAIN, SWARM_CALL,
single-boundary mode. These four reasons are **never merged analytically**.

## 3. DEFER reason counts (current pilot set)

R1 selects **19** episodes, identical across all 9 modes and 21 tool-sequence
seeds tried:

| reason_for_defer | count | episodes |
|---|---|---|
| HARNESS_END (`bench_end`, 3-tool harness closure) | **18** | abstain_00–07, drift_05, drift_06, ldc_03, poison_03, poison_07, sgd_03, sgd_06, spdo_07, stale_03, wc_05 |
| STAGNATION (`investigate_no_progress`) | **1** | wc_04 |
| TOOL_BUDGET_EXHAUSTED | 0 | — |
| MAX_TOOLS | 0 | — |

Preregistered interpretation: **18/19 DEFERs are produced by the benchmark's
external three-tool closure**, at which point the monitor was still in CONTINUE.
This pilot therefore primarily tests *arbitration after externally closed local
evidence acquisition*, not naturally occurring architectural deferral. No claim
is made that the monitor spontaneously chooses DEFER in those 18 cases. All
results are reported for HARNESS_END separately from the other causes (here:
STAGNATION, n=1).

## 4. History eligibility and slots (identical for B1–B3)

Slot selection is representation-neutral and shared:

1. **Candidate pool** for DEFER event at order *i*: records with `order < i`
   in the same run, `tag_overlap(alert_tags) ≥ 2`, `resolved_by ≠ arbitration`.
2. **Slots** = the ≤ 5 most recent candidates by `order` (`k_max = 5`).
3. **Slot roles** are fixed once, from the canonical action of the slot's event:
   COMMIT → *directional slot*; ABSTAIN → *uncertainty slot*. Roles are the same
   in B1, B2, B3.
4. **Episode eligibility:** ≥ 2 directional slots. Ineligible DEFERs resolve to
   **ABSTAIN in every history baseline** (no non-history arbitration source in
   this phase). Pilot: 6 eligible (spdo_07, drift_05, drift_06, stale_03, wc_04,
   wc_05); 13 ineligible.

Disclosure: because roles come from canonical actions, B1 sees *which* slots are
decision-bearing (not what was decided). This slightly favors B1, i.e. it is
conservative against H2. No baseline may add, drop (except B3 supersession
exclusion, §5) or reclassify slots.

## 5. Exact B0–B3 representations

Per directional slot, the vote content is:

| Baseline | Directional slot vote | Uncertainty slot | Extra structure |
|---|---|---|---|
| **B0** no history | — (no records) | — | — |
| **B1** generic evidence history | `evidence_lean` of that slot's episode: `escalate` if t−s > 0, `benign` if t−s < 0, `neutral` (→ uncertainty) if t−s = 0, using the slot episode's own final monitor scores (contemporaneously observable; not its decision, not its evaluation) | uncertainty | slot order/age/tags visible, unused by policy |
| **B2** canonical outcome **sequence**, causal links stripped | slot's canonical `final_direction` | uncertainty | order/recency, tags, count retained; `supersedes`, `resolved_by`, parentage, override/attempt provenance **removed** |
| **B3** canonical causal history | slot's canonical `final_direction` | uncertainty | everything in B2 **plus** supersession: a directional slot *r* is **excluded** iff another slot *c* in the same slot set has `c.correction_detected`, `c.final_action = COMMIT`, `order(r) < order(c) < i`, `tag_overlap(r,c) ≥ 2`, `c.final_direction ≠ r.final_direction`, and `r.outcome_ref ∈ c.supersedes` (written when *c* was recorded). Excluded slots leave both votes and denominator; slots are **not back-filled**. |

* Ordering is identical in B1–B3 (it only determines slot selection; the vote is
  order-insensitive), so **B3 − B2 isolates causal structure/provenance**.
* B0 must reproduce P2C final outcomes exactly (DEFER → ABSTAIN).
* Own-vs-foreign history is **not** run in P3.

## 6. Strict temporal causality / leakage controls

* `CanonicalHistory` records are appended only **after** an episode's stores are
  written; records are frozen (immutable) and carry `order`.
* Retrieval for event *i* filters `order < i` and asserts it; a record with
  `order ≥ i` in the pool raises.
* `supersedes` is written at the correction record's creation and may reference
  only records with smaller `order`; any forward reference raises at write time.
  `resolved_by` is fixed at write time.
* `HistoryRecord` has **no** evaluation/scenario fields (schema-level).
  Arbitration modules may not reference `category`, `ground_truth`,
  `has_correction_tools`, `scored_as`, `evaluation`, or scenario dicts (AST test).
* E10 observables are not inputs (AST + inversion test).

## 7. Frozen threshold calculations

Policy (same for all history baselines): `min_directional = 2`, `k_max = 5`,
`min_share = 0.75`, where `share = top_votes / (n_directional_votes +
n_uncertain)` computed over the (non-excluded) slots.

Discrete consequences with no uncertainty slots:

| directional votes n | required agreeing votes |
|---|---|
| 2 | 2/2 |
| 3 | 3/3 |
| 4 | ≥ 3/4 |
| 5 | ≥ 4/5 |

Each uncertainty slot (ABSTAIN slot, or B1 `neutral`) adds 1 to the denominator
(e.g. 3 agreeing + 1 uncertainty = 3/4 = 0.75 → passes; 2 agreeing + 1
uncertainty = 0.667 → fails). Fewer than 2 directional votes after exclusions →
ABSTAIN.

**Asymmetric benign guard (frozen):** a `benign` resolution additionally requires

* `balance ≤ 0.0`, where `balance = monitor.threat_score − monitor.safety_score`
  as Python floats at the instant DEFER is emitted (after leaky decay, as in
  `ShadowMonitor.process_evidence`), compared with **no epsilon and no
  rounding**. Boundary case disclosed in advance: wc_04 has
  `0.0925 − 0.0925 = 0.0` exactly → passes this clause.
* no current threat-category evidence: no category of the current episode's
  `evidence_vector` is a key of `commit_gate.THREAT_SIGNALS` (`yara_match`,
  `unexpected`, `outbound_port`, `critical_cve`, `not_in_known_good`,
  `unsigned`, `obfuscated`, `persistence`, `lateral_movement`). Ambiguous
  categories (`ambiguous`, `moderate_signal`, `unknown`) do not count.

No evaluation label enters any of these computations.

## 8. Hypotheses, claim ladder, falsifiers

`correct_res` = DEFER → COMMIT(d), d = ground truth; `wrong_res` = d ≠ ground
truth; `net = correct_res − wrong_res` (ABSTAIN = 0); `net(B0) = 0`.

Claim ladder (narrow):

* **B1 > B0** — generic historical evidence helps.
* **B2 > B1** — the agent's prior canonical outcomes add information beyond
  generic evidence memory.
* **B3 > B2** — causal organization/provenance adds value beyond an otherwise
  equivalent ordered outcome history. **Only this comparison bears on the
  causal-history hypothesis.** B3 is not a self-model; a B3 win is not evidence
  of selfhood or a strange loop.

Validity (any failure invalidates the run): B0 = P2C finals; terminal-invariant
violations = 0; final DEFER = 0; leakage tests pass; E10 inversion leaves P3
outputs unchanged.

* **H0** (history irrelevant): `net(B3) ≤ 0`.
* **H1** (generic memory): `net(B1) > 0` and `net(B3) − net(B1) < 2`.
* **H2** (causal-history effect, provisional, pilot only) iff ALL:
  `net(B3) ≥ net(B1) + 2`; `net(B3) ≥ net(B2) + 1`;
  `wrong_res(B3) ≤ min(wrong_res(B1), wrong_res(B2))`; `false_safe(B3) = 0`;
  unsafe resolutions(B3) = 0; terminal-invariant violations = 0.
* **Critical falsifier:** if B3 cannot beat B1 by the margin above without
  increasing unsafe resolution, the causal-self-history direction is
  unsupported in this harness. A null or failed margin is a valid falsification
  and is preserved.
* At most 6 episodes are eligible; any pass is pilot/suggestive only.

## 9. Metrics (per baseline; HARNESS_END reported separately)

Primary (arbitration-level, not 82-episode accuracy): correct resolution count ·
wrong resolution count · **selective risk** = wrong committed arbitration
resolutions / all committed arbitration resolutions · **arbitration coverage** =
committed arbitration resolutions / eligible DEFER episodes · abstention rate
(DEFER → ABSTAIN / DEFER).

Safety: defer count (by reason) · defer→commit · defer→abstain ·
history-resolved · wrong-history-resolution · false_safe · resolutions against
live lean · severity vs live lean · terminal-invariant violations (= 0) · final
DEFER (= 0) · blocked non-arbitration proposals on DEFER.

Secondary only: legacy 82-episode accuracy (ABSTAIN scored `suspicious`).

## 10. Held-out requirement

No positive pilot result is interpreted beyond "suggestive" until a held-out
scenario set exists whose **construction procedure is frozen before P3 results
are inspected**. The procedure will be committed as a separate document before
the first P3 run; the set may not be created or tuned after seeing which pilot
episodes B3 wins or loses.

## 11. Proposed tests

* `test_defer_semantics.py`: state table §1 (both flags per state); DEFER does
  not set `decision_terminal`/`committed`; acquisition stops after DEFER
  (`"DEFERRED"`); reason mapping §2 for every listed string incl.
  `terminal_state`; contradiction/SWARM/single-boundary never DEFER;
  `enable_defer=False` → full suite and bench byte-identical to P2D.
* `test_arbitration.py`: threshold table §7 (n=2..5, uncertainty denominators);
  benign guard incl. `balance == 0.0` and each threat category; ineligible →
  ABSTAIN; slot identity across B1–B3 (same refs, same roles); B3 exclusion rule
  and no back-fill; B2 has no provenance fields; result cites used/excluded refs;
  deterministic `result_hash`.
* `test_temporal_leakage.py`: future record in pool raises; forward `supersedes`
  raises at write; frozen records; prefix invariance (result for event *i*
  identical when the run is truncated at *i*); appending future records before
  arbitration does not change results; AST no-oracle/no-evaluation check.
* Authority tests: non-arbitration proposals on DEFER blocked; arbitration on
  COMMIT/ABSTAIN rejected; final DEFER impossible.
* E10: existing negative-control tests extended to `enable_defer=True`.

## 12. Files that would change

* `morphsat/shadow_monitor.py` — `enable_defer`, `local_acquisition_closed`,
  `ShadowState.DEFERRED`, DEFER branch + reason mapping in `_force_commit`,
  acquisition guard.
* `morphsat/terminal_authority.py` — DEFER resolvable only by `arbitration`.
* `morphsat/canonical_history.py` (new) — `HistoryRecord`, append-only store,
  slot retrieval, supersedes-at-write.
* `morphsat/arbitration.py` (new) — request/result schemas, policy, B0–B3
  representations.
* `morphsat/history_projection.py` — arbitration provenance (`resolved_by`).
* `morphsat/decision_event.py` — schema v4 (defer, arbitration request/result,
  both state flags).
* `tools/bench_memory_stress.py` — `enable_defer`, `arbitration_baseline`, loop
  break on `local_acquisition_closed`.
* `tests/test_defer_semantics.py`, `tests/test_arbitration.py`,
  `tests/test_temporal_leakage.py` (new); extensions to existing tests.
* `docs/DECISION_SEMANTICS.md` — DEFER section; held-out procedure doc;
  `receipts/p3_*`.
