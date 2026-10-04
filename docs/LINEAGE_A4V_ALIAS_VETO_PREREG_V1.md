# Lineage A follow-up — A4V Upstream-Alias Veto: Preregistration v1.0 (CANDIDATE FOR FREEZE)

Status: **candidate; not frozen until the user approves §13.** No A4V code
exists and no A4V outcome has been computed. Scope: public GitHub lineage of
`14689b7`. Branch `claude/lineage-a4v`, forked from `claude/lineage-a-impl`
at `39766cc`. The Lineage A branch and its commits (`0c7847a`, `9929b31`,
`38f29e3`, `39766cc`) are not modified.

Lineage: Lineage A prereg v1.0 `965ec90` → v1.1 `6be2821` → v1.2 `c90e008` →
v1.3 `0c7847a`; results `39766cc` (`docs/LINEAGE_A_RESULTS.md`, primary claim
not supported). This document tests the one positive Lineage A finding.

**Carried-forward disclosure (verbatim from the Lineage A report):** "I
deleted the uncommitted validation receipt from the crashed run before
re-running. The re-run gave identical validation output." This happened after
posterior validation and before any policy outcome existed. It is not
recorded in `docs/LINEAGE_A_RESULTS.md`; it is recorded here (see §13 Q4).

## 1. Hypothesis

> **H-V:** Can upstream-aware provenance work as a targeted veto without
> becoming the decision rule?

Operationally: A4 vs A4V = A4 plus one provenance guard, everything else held
fixed. The guard is useful authority information if it blocks A4 acceptances
that are **disproportionately wrong**. If it blocks correct and incorrect
acceptances at roughly the same rate, the upstream signal detects dependence
but is not useful authority information, and this path closes.

Not tested here: whether A4V is better than A1/A2/A3b or any other policy
(the Lineage A A5 claim ladder does not apply); cross-episode trust (deferred
as a separate lineage); MorphSAT integration; anything about self-models or
strange loops.

## 2. Held fixed (byte-identical to `39766cc`)

* `lineage_a/records.py`, `generator.py`, `world.py`, `policies.py`,
  `corollary.py`, `evaluate.py`: not edited. The implementation adds new
  modules only; the run checks `git diff 39766cc -- <these files>` is empty
  and records their sha256 in the receipt.
* Pattern families FAM-G (248), FAM-T (54), FAM-I (20); `pattern_set_sha256`
  must equal the Lineage A receipt's value.
* The 24 environments; the exact posterior; v1.3 within-cell Z weights;
  families weighted equally (FAM-G, FAM-T primary); impossible patterns
  weight 0.
* A4 exactly as frozen: post-correction record counts, `support ≥ K = 2` and
  `contradict = 0` → ACCEPT; `contradict ≥ 2` and `support = 0` → REJECT;
  else ABSTAIN.

The known coverage limitation (coverage set by the pattern mix) is carried
forward unchanged and stays disclosed.

## 3. Policy A4V

Let `c` = the correction record. Over post-correction records with
`direction = c.direction` ("supporting records"):

* `n_src` = number of distinct `source_id` values, excluding `c.source_id`
  (the frozen A5n projection);
* `n_up` = number of distinct `upstream_id` values, excluding `c.upstream_id`
  (the frozen A5 projection).

**Alias veto fires** iff all three hold:

1. `A4(records) = ACCEPT`;
2. `n_src ≥ K` (apparent multi-source support passes the frozen count);
3. `n_up < K` (the same support projected to independent upstreams fails it).

**A4V(records) = ABSTAIN if the veto fires, else A4(records).**

Correction to the request text: A4 uses `support ≥ 2, contradict = 0`, not
the `k = 2, share 0.75` vote; the 0.75 share applies to A1/A3b only. Because
A4 acceptance already implies zero contradicting post records, the share
condition holds trivially for A4, so the projection uses A4's own `K = 2`.

### 3.1 Invariants (unit tests; must hold before any outcome is computed)

* I1 `A4V(p) ∈ {A4(p), ABSTAIN}` for every pattern.
* I2 `A4V(p) ≠ A4(p)` ⇒ `A4(p) = ACCEPT` and the veto condition holds.
* I3 Veto condition false ⇒ `A4V(p) = A4(p)` (non-alias cases unchanged).
* I4 A4V never creates an ACCEPT or a REJECT and never flips direction.
* I5 `K` is imported from `lineage_a.policies`; no new threshold exists.
* I6 No-oracle AST check (same forbidden set as Lineage A) on the new policy
  module; it may not import `lineage_a.world` or `lineage_a.evaluate`.

## 4. Comparators

| Name | Role | Definition |
|---|---|---|
| A4 | reference | as frozen |
| A4V | primary | §3 |
| A4V-S | sham (primary criterion V2) | A4 on the original records; veto condition evaluated on `shuffle_ids(pid, records)` (frozen S2 shuffle). A4 is id-blind, so only the veto set changes. |
| A4V-W | diagnostic only | veto iff `A4 = ACCEPT ∧ n_up < K` (drops condition 2, so it also blocks A4 acceptances resting on repeats of one source or of the correction's own source) |

A4V-W is not part of the claim. It answers whether the residual A4
weakness that A4V deliberately leaves alone (repeats) matters. Remove it if
you want strictly one new variable (§13 Q3).

## 5. Facts fixed before outcomes (structural; no posterior computed)

These counts came from records alone (generator plus frozen policy
functions, no world import). They are disclosed because they shape
interpretation.

| Family | A4 accepts | A4V vetoes | A4V-W vetoes | A4V-S vetoes |
|---|---|---|---|---|
| FAM-G (248) | 80 | 32 (B-corr 16, B-oth 16) | 64 (+A-corr 16, A-oth 16) | 20 |
| FAM-T (54) | 18 | 6 (shared-upstream 6) | 12 (+repeated 6) | 2 |
| FAM-I (20) | 20 | 8 (B-corr 4, B-oth 4) | 16 | 4 |

Identities that follow from the definitions and the frozen world model.
They are **not evidence** for H-V:

* **E1 Weak safety by construction.** A veto only turns ACCEPT into ABSTAIN,
  so A4V ≤ A4 on `false_safe`, `ICA` and `mc_failures` in every environment.
  These are reported for magnitude only.
* **E2 Null-environment identity.** In the four `ρ = 0, α = 0` environments,
  upstream labels do not enter the likelihood. Each vetoed structure (B-corr,
  B-oth, shared-upstream) has a retained twin with the same `(n_pre, n_post,
  c)` grid and an identical posterior. So the discrimination ratio is
  `R = 1` there for A4V and A4V-S. This is checked as an implementation
  validity test (tolerance 1e-9), not as a result.
* **E3 Direction is built in.** For `ρ > 0`, copies sharing an upstream carry
  less evidence. For `α > 0`, U_c aliases may be adversarial. Either way
  vetoed patterns have lower `q`, so `R ≥ 1` is expected in all non-null
  environments. The open question is **magnitude and cost**, not direction.
  B-oth vetoes depend on `ρ` only (the adversary controls U_c, not U_x);
  B-corr vetoes depend on `ρ` and `α`.

## 6. Metrics (per environment; primary weighting; then macro over envs)

All quantities use the existing `aggregate()` outputs for A4 and A4V:

* Incorrect accepts prevented `ΔICA = ICA(A4) − ICA(A4V)`.
* Correct accepts sacrificed `ΔCCA = CCA(A4) − CCA(A4V)`.
* `Δcoverage = coverage(A4) − coverage(A4V) = ΔICA + ΔCCA`.
* **Veto precision** `= ΔICA / (ΔICA + ΔCCA)`, compared against the A4
  accept error base rate `ICA(A4) / (ICA(A4) + CCA(A4))`.
* **Discrimination ratio** `R = (ΔICA / ICA(A4)) / (ΔCCA / CCA(A4))`. This
  is the rate wrong acceptances are blocked divided by the rate correct ones
  are blocked; `R = 1` means a random veto of the same mass. Edge cases:
  `ΔCCA = 0 < ΔICA` → `R = +∞`; `ΔICA = ΔCCA = 0` (veto never fires) →
  `R = 1`.
* `false_safe`, `mc_failures`, `selective_risk`, `coverage` for A4, A4V,
  A4V-S and A4V-W.

## 7. Primary decision rule (frozen)

Non-null stratum **N̄** = the 20 environments with `ρ > 0` or `α > 0`. The
null stratum (4 envs) is excluded from criteria per E2. The threshold
convention reuses Lineage A's 75%: **15 of 20**.

| | Criterion | Pass |
|---|---|---|
| V1 | Discrimination: `R(A4V) ≥ 2` | ≥ 15/20 envs in N̄ |
| V2 | Specificity: `R(A4V) > R(A4V-S)` (strict, EPS = 1e-12) | ≥ 15/20 envs in N̄ |
| V3 | Risk: `selective_risk(A4V) < selective_risk(A4) − EPS` | ≥ 15/20 envs in N̄ |

Outcome mapping (fixed now):

* **V1 ∧ V2 ∧ V3 → Supported.** The alias veto removes disproportionately
  wrong A4 acceptances, specifically because of upstream assignment, and
  lowers A4's selective risk while leaving non-alias decisions unchanged
  (I3).
* **¬V1 → Closed: detector, not authority information.** Blocks right and
  wrong at comparable rates.
* **V1 ∧ ¬V2 → Closed: not upstream-specific.** Shuffled ids discriminate
  as well, so the effect is pattern composition, not provenance.
* **V1 ∧ V2 ∧ ¬V3 → Not supported as an authority guard.** It discriminates
  but does not lower risk at A4's operating point. Reported as such, with no
  rescue analysis.

`R ≥ 2` is a design choice, not derived. See §13 Q1.

## 8. Diagnostics (reported; not part of the claim)

* Coverage bands 0.05 / 0.10 / 0.20, preserved from Lineage A. Per env:
  `Δcoverage ≤ band` and A4V `false_safe`, `ICA`, `selective_risk` each
  `≤` A4's. By E1 this reduces to the coverage and risk conditions.
* Veto-subtype split: corr-alias (all supporting upstreams = U_c; B-corr)
  vs other-alias (B-oth, FAM-T shared-upstream). Report `R`, precision and
  ΔICA/ΔCCA for each.
* Strata: null (4), dependence-only `ρ > 0, α = 0` (8), attack `α = 0.3`
  (12, split `ρ = 0` / `ρ > 0`).
* Per family (FAM-G, FAM-T, FAM-I); unweighted-over-possible-patterns
  secondary weighting.
* A4V-W: same metrics, plus the share of A4 acceptances with `n_up < K` that
  A4V leaves un-vetoed (residual dependence).
* Macro table of A4V and A4V-S beside the Lineage A policies, for context
  only.

## 9. Validity checks (run order; any failure stops the run)

1. Re-run `validate_posterior()` with the frozen seed and draws; it must
   pass, and its output is compared with the Lineage A validation receipt.
2. Frozen-file check (§2) and `pattern_set_sha256` match.
3. Invariants I1–I6 (unit tests).
4. Structural counts in §5 reproduce exactly.
5. E2 null identity: `|R − 1| ≤ 1e-9` in all four null envs for A4V and
   A4V-S.
6. A4's per-env metrics reproduce the Lineage A receipt values (tolerance
   1e-12).

## 10. Evidence status and threats (stated before outcomes)

* **T1 Near-tautology (most important).** The frozen world model *defines*
  shared upstream as reduced informativeness (copy probability `ρ`) plus
  adversarial control of U_c. A4V keys on exactly that structure. A positive
  result therefore shows that the veto **implements the generator's
  dependence semantics at the decision level with acceptable cost**. It does
  **not** show that `upstream_id` is meaningful in any real or grounded
  system. Only Lineage B, or real data, can test that.
* **T2 Same-world reanalysis.** A4V was proposed after the Lineage A
  aggregates (A4, A5, A5n) were public, and the world and patterns are
  deterministic and already known. This is a preregistered analysis of a
  post-hoc-motivated hypothesis on the same world. It is not a held-out
  test. A positive result is hypothesis-supporting, not confirmatory.
  Per-pattern Lineage A outcomes were never written to receipts, so A4V's
  numbers cannot be read off them.
* **T3 Threshold arbitrariness.** `R ≥ 2` and 15/20 are conventions. All
  per-env `R` values are reported so readers can apply their own.
* **T4 Pattern-mix dependence.** Veto mass and R depend on how many B-type
  structures the families contain. This is carried forward from Lineage A.
* **Literature.** No novelty claim is made, so no adjacent-work scan was
  run for this document. Pointer to scan before any external claim
  (unverified, not cited): source-dependence / copy-detection work in the
  truth-discovery literature.

## 11. Implementation plan (after freeze)

* `lineage_a/a4v.py` (new): `alias_counts`, `alias_veto_fires`, `a4v`,
  `a4v_shuffle_sham`, `a4v_wide`. Imports `K`, `a4_corroboration`,
  `shuffle_ids` from `lineage_a.policies`; no world/evaluate import.
* `lineage_a/evaluate_a4v.py` (new): reuses `fam_*`, `posterior`,
  `weights`, `uniform_weights`, `aggregate`, `validate_posterior` unchanged;
  computes §6–§8 and `claim_v()` per §7.
* `tools/run_lineage_a4v.py` (new): validity checks §9 in order, then the
  run; writes `receipts/lineage_a4v/…json`.
* `tests/test_lineage_a4v.py` (new): I1–I6, §5 counts, the A4V-S id-only
  property, and E2 (run inside the evaluation, since it needs posteriors).
* `docs/LINEAGE_A4V_RESULTS.md` after the run. No change to MorphSAT runtime
  code.

## 12. Downstream decision (fixed now)

* **Supported** → carry the upstream-alias guard into Lineage B as a
  **tested hypothesis**: B must measure whether its grounded dependence shows
  up under `upstream_id` labels (because of T1). It is not an assumed-good
  control.
* **Any closed or not-supported outcome** → close this path. Lineage B
  proceeds with `upstream_id` as metadata only.
* Lineage B implementation stays on hold until the A4V results are written.
  Cross-episode trust stays deferred as a separate lineage.

## 13. Decisions needed before freeze

* **Q1** `R ≥ 2` for V1: keep, or set another value (e.g. 1.5)?
* **Q2** Keep V2 (shuffle sham) as primary? Recommended: yes. It is the only
  criterion not settled in direction by E3.
* **Q3** Keep A4V-W as a diagnostic, or drop it for strict
  one-variable scope?
* **Q4** Also append an addendum to `docs/LINEAGE_A_RESULTS.md` (on this
  branch, as a new commit) recording the deleted crashed-run receipt?
