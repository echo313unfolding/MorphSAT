# P3 — DEFER → ARBITRATION: Design and Preregistration (v1 — SUPERSEDED)

> **Superseded by `docs/P3_DEFER_ARBITRATION_PREREG_V2.md`. Do not implement v1.**

Status: **DESIGN ONLY — not implemented.** Base: `claude/p2d-docs` @ `ae3130d`
(public GitHub lineage of `14689b7`). This document is the preregistration; any
change to a rule or threshold after the first P3 run requires a new version of
this document and both results must be reported.

**Designer disclosure.** The author of this design knows the benchmark family
intents (family names such as `wrong_correction`, `hard_abstain_required`).
Per-episode labels were NOT used to choose any rule below. The DEFER mapping and
history-eligibility table were computed from monitor internals and prior
canonical outcomes only. Rules were fixed from semantic/safety principles before
any arbitration outcome was computed. Predicted resolutions were deliberately
NOT computed.

---

## 1. State semantics

| State | Meaning | Final? | Who may resolve it |
|---|---|---|---|
| CONTINUE | ordinary evidence acquisition | no | monitor |
| COMMIT(d) | sufficient evidence for a substantive verdict | **terminal** | nobody (P2B invariant) |
| DEFER | local controller cannot commit; authorized arbitration may inspect additional history/evidence | **never final** | **arbitration only** |
| ABSTAIN | the authorized decision process cannot reach sufficient confidence | **terminal** | nobody |
| SWARM_CALL / HANDOFF | external escalation; currently resolves as ABSTAIN; 0 benchmark occurrences | terminal | unchanged (characterize separately) |

Invariants (enforced in code and tests):

1. History/QUBO/Echo never alter COMMIT. 2. Never alter ABSTAIN.
3. Arbitration is entered **only** from DEFER; no other stage may resolve DEFER.
4. Arbitration that does not meet the preregistered criterion yields **ABSTAIN**.
5. `final_action ∈ {COMMIT, ABSTAIN}` always; a final DEFER is a violation.
   DEFER is never scored as benign/suspicious/escalate.
6. Ground truth is evaluation-only. 7. No scenario/oracle field enters arbitration.
8. Every arbitration result cites the history record refs it used and excluded.
9. E10 observables remain dead (existing negative-control tests extended to P3).
10. Records whose outcome was itself produced by arbitration are excluded from
    arbitration retrieval (no self-reinforcement), in P3.

DEFER latches the **local** controller (`terminal_latched = True`: no more
evidence acquisition) but DEFER ∉ `TERMINAL_AUTHORITY_ACTIONS`, so it is not a
final decision.

## 2. Current-state → DEFER mapping rule (R1)

Derived from existing monitor semantics, not from scores:

> **R1.** In dual-boundary mode, when the monitor reaches the end of its
> authorized local evidence — harness end while still CONTINUE (an explicit
> request for more evidence), investigation budget exhausted, max tools, or
> stagnation/loop — and the evidence balance is strictly **inside** the continue
> zone `(-commit_safe_boundary, commit_threat_boundary)` **and**
> `contradiction < contradiction_gate`, emit **DEFER** instead of ABSTAIN.

Code locus: `ShadowMonitor._force_commit`, dual-boundary in-zone branch (the
branch that today sets `abstain_due_to_uncertainty = True`). `reason_for_defer` ∈
{`harness_end_in_zone`, `budget_exhausted_in_zone`, `stagnation_in_zone`,
`max_tools_in_zone`} from the existing `reason` argument.

Explicitly **not** DEFER in P3 (stay terminal ABSTAIN):

* contradiction ABSTAIN (`min(t,s) ≥ contradiction_gate`): live evidence is
  strong both ways; adjudicating it with history is a different hypothesis (P3b).
  Current benchmark occurrences: 0.
* SWARM_CALL: external escalation, not local insufficiency. Occurrences: 0.
* single-boundary mode: has no continue zone; unchanged.

Gated by a new `enable_defer` flag (default **False** → all existing behavior
and receipts unchanged).

## 3. Episodes that R1 maps to DEFER (computed at P2D, no labels)

R1 selects **19 episodes, identical in all 9 modes and in all 21 tool-sequence
seeds tried (0–19, 42)** — i.e. exactly the current ABSTAIN set; all 19 are
in-zone uncertainty (18 harness-end, 1 stagnation), 0 contradiction, 0 swarm.
Effective N = **19 distinct episodes**.

History eligibility (prior canonical outcomes in the same run with alert-tag
overlap ≥ 2; labels not consulted):

| Episode | prior relevant | directional prior (final outcomes) | balance t−s |
|---|---|---|---|
| spdo_07 | 7 | benign 5, escalate 2 | +0.237 |
| drift_05 | 5 | escalate 4, benign 1 | −0.238 |
| drift_06 | 6 | escalate 4, benign 1 (+1 abstain) | +0.062 |
| stale_03 | 3 | escalate 2, benign 1 | −0.302 |
| wc_04 | 4 | escalate 3, benign 1 | 0.000 |
| wc_05 | 5 | escalate 3, benign 1 (+1 abstain) | −0.103 |
| ldc_03, sgd_03, poison_03, poison_07, abstain_00–07, sgd_06 | 0–2 | < 2 directional | — |

At most **6 / 19** DEFER episodes can be history-resolved under the
`min_directional_support = 2` criterion; the other 13 must end ABSTAIN in every
baseline.

## 4. Schemas

```
HistoryRecord                      # canonical history store entry (no evaluation fields)
  outcome_ref, order (episode index within run), alert_tags, evidence_signature,
  final_action, final_direction, evidence_lean (sign of t−s: benign|escalate|neutral),
  provenance: { override_source, attempted_override_source,
                correction_detected (system evidence category 'correction'),
                supersedes: [outcome_ref], resolved_by: monitor|arbitration }

ArbitrationRequest
  request_id, episode_id
  decision_prefix: { monitor_action=DEFER, posture, threat, safety, balance,
                     contradiction, zone bounds }
  evidence_signature, alert_tags, reason_for_defer
  permitted_source: B0|B1|B2|B3
  candidate_refs: [outcome_ref]     # retrieved before policy
  policy: { k_max: 5, min_tag_overlap: 2, min_directional_support: 2,
            min_share: 0.75,
            benign_requires_balance_le_0: true,
            benign_requires_no_live_threat_category: true }
  request_hash                      # canonical hash of the above

ArbitrationResult
  action: COMMIT | ABSTAIN, direction (None for ABSTAIN)
  records_used: [outcome_ref], records_excluded: [{ref, reason}]
  support: { n_directional, n_uncertain, votes{dir:n}, share }
  criterion_met, backend (B0..B3), reason
  result_hash = canonical_hash(request_hash + result fields)
```

**Policy (identical for every baseline; only the record source differs).**
Retrieve the most recent ≤ `k_max` prior records with tag overlap ≥ 2 (excluding
`resolved_by = arbitration`). Directional votes = records with a COMMIT
direction (B1: evidence lean); ABSTAIN/neutral count as uncertainty mass.
`share = top_votes / (n_directional + n_uncertain)`. COMMIT(top) iff
`n_directional ≥ 2` and `share ≥ 0.75`; **asymmetric safety:** a `benign`
resolution additionally requires live balance ≤ 0 and **no** live
threat-category evidence (any `THREAT_SIGNALS` category) in the current
signature. Otherwise ABSTAIN. These thresholds are fixed from the existing
`min_tag_overlap = 2` convention and a conservative ¾ majority; they are not
fitted.

DecisionEvent v4 adds: `defer` {reason_for_defer}, `arbitration_request`,
`arbitration_result`, `override_source = "arbitration"` when applied.

## 5. Baselines (same retrieval rule, same k_max, same policy)

| ID | Record content | Purpose |
|---|---|---|
| **B0** | no records | must reproduce P2C finals exactly (sanity) |
| **B1** | capacity-matched **generic memory**: same matched prior episodes, but only their *live evidence lean* (observations), not decisions | H1: does any relevant memory help? |
| **B2** | canonical history, **provenance stripped**: same records' final directions as an unordered bag; no supersession, no recency | isolates outcome content |
| **B3** | canonical history, **provenance intact**: recency order + supersession (a later record with `correction_detected` on overlapping tags supersedes earlier opposite-direction records) | H2: does receipted causal history add value? |

Own-vs-foreign history (H3) is **not** run unless H2 survives.

## 6. Preregistered hypotheses and falsifiers

Definitions over the 19 DEFER episodes (seed 42 primary; seeds 0–19 reported but
they do not change the DEFER set): `correct_res` = DEFER→COMMIT(d) with d =
ground truth; `wrong_res` = DEFER→COMMIT(d) with d ≠ ground truth;
`net(B) = correct_res − wrong_res` (ABSTAIN counts 0). `net(B0) = 0` by
construction.

Validity (any failure invalidates the run): B0 finals identical to P2C;
terminal-invariant violations = 0; final DEFER = 0; E10 inversion leaves P3
outputs unchanged; AST check that arbitration code references no
`category`/`ground_truth`/`has_correction_tools`/scenario fields.

* **H0 (history irrelevant)** supported if `net(B3) ≤ 0`.
* **H1 (generic memory effect)** supported if `net(B1) > 0` and
  `net(B3) − net(B1) < 2`.
* **H2 (canonical-history effect)** supported iff ALL: `net(B3) ≥ net(B1) + 2`;
  `net(B3) ≥ net(B2) + 1`; `wrong_res(B3) ≤ wrong_res(B1)`;
  `false_safe(B3) = 0`; unsafe resolutions(B3) = 0.
* **Critical falsifier (preserved whatever happens):** if B3 cannot beat B1 by
  the margin above without increasing unsafe resolution, the
  causal-self-history direction is **unsupported in this harness**.
* **Power caveat:** at most 6 episodes are eligible. Even an H2 pass is
  *suggestive only* and must be replicated on a held-out scenario set authored
  without access to arbitration outcomes before any claim.
* **Stated risk (from family design, not labels):** supersession in B3 will
  prefer a later correction; where a correction is false, this can push toward
  benign. The asymmetric safety rule is the only guard; if it fails, `false_safe`
  > 0 falsifies H2 and is reported as such.

## 7. Safety metrics (reported per baseline, never collapsed)

defer count · defer→commit · defer→abstain · history-resolved count ·
wrong-history-resolution count · false_safe · resolutions against live evidence
lean · severity of resolution vs live lean (up/down) · terminal-invariant
violations (must be 0) · final-DEFER count (must be 0) · legacy accuracy (with
the caveat that ABSTAIN is scored `suspicious`, which rewards abstention on the 8
`hard_abstain_required` episodes) · committed-only accuracy · coverage.

## 8. Files that would change (implementation phase, after approval)

* `morphsat/shadow_monitor.py` — `enable_defer` flag, `ShadowState.DEFERRED`,
  DEFER branch in `_force_commit`.
* `morphsat/terminal_authority.py` — DEFER resolvable only by source
  `arbitration`; all other proposals on DEFER blocked.
* `morphsat/canonical_history.py` (new) — `HistoryRecord` store and capacity-matched
  generic memory store.
* `morphsat/arbitration.py` (new) — request/result schemas, policy, B0–B3 sources.
* `morphsat/history_projection.py` — arbitration provenance in projections.
* `morphsat/decision_event.py` — schema v4.
* `tools/bench_memory_stress.py` — `enable_defer` + `arbitration_baseline` flags.
* Tests (new): `test_defer_semantics.py`, `test_arbitration.py` (incl. no-oracle
  AST, E10 under P3, recursion exclusion, invariants); extended existing tests.
* `docs/DECISION_SEMANTICS.md` — DEFER section; `receipts/p3_*`.
