# Lineage A4V — Preregistration v1.2 (FROZEN; amendment to v1.1)

Status: **amendment to v1.1** (`docs/LINEAGE_A4V_ALIAS_VETO_PREREG_V1.md`,
`0b44c16`, preserved unedited). v1.1 stands except as amended here.
Approved by the user 2026-10-05, after run 1 aborted
(`docs/LINEAGE_A4V_RUN1_ABORT.md`, `8486875`).

## Audit trail

1. v1.1 §5 E2 predicted an exact null identity, `R = 1` under the pooled
   primary weighting, for both A4V and the shuffle sham A4V-S in the four
   `ρ = 0, α = 0` environments. §9 check 5 tested it.
2. The preregistered validity check rejected that prediction. The runner
   stopped before any claim was emitted. No claim or non-null metric was
   printed or written.
3. Only the four excluded `ρ = 0, α = 0` environments were inspected.
4. The inspection showed:
   * A4V has an exact within-family null identity (`R = 1.0` in FAM-G and
     in FAM-T separately).
   * Pooling the families breaks the exact identity through family mixture
     (pooled `R` = 0.981–0.994). This is a Simpson/mixture-style aggregation
     effect from different veto prevalence and base error rates across
     families.
   * The shuffled sham has no expected identity. Deterministic reassignment
     selects different pattern compositions, so its null `R` reflects
     composition alone (0.85–1.42 per family).
5. v1.2 corrects only those invalid validity assumptions (Amendment 1).
6. No primary `R` definition, pooling, V1/V2/V3 threshold, generator, veto
   or non-null environment changed. The frozen pooled primary weighting and
   all V1–V3 rules remain unchanged because no defect was found in those
   definitions.
7. The run is restarted once from this frozen amended preregistration.

Separately, Amendment 2 removes a hard cost cutoff added in v1.1. It is not
a consequence of run 1.

## Amendment 1 — Null-control validity check (replaces v1.1 §5 E2 and §9 check 5)

* **E2 (corrected):** in the four `ρ = 0, α = 0` environments, upstream
  dependence carries no information. So the real alias veto has no
  within-family discriminatory advantage: `R(A4V) = 1` separately within
  each applicable family (FAM-G, FAM-T, FAM-I).
* **Check 5 (corrected):** `|R(A4V) − 1| ≤ 1e-9` within FAM-G, FAM-T and
  FAM-I in each of the four null environments. Failure stops the run.
* The pooled null deviation is documented as a mixture effect. It is
  reported, not "fixed".
* **The sham identity requirement is dropped.** A4V-S is a composition-
  preserving, dependence-destroying control. Its null behaviour, driven by
  which pattern structures the deterministic permutation catches, is part
  of what V2 controls for. Its null `R` is reported as a diagnostic.

## Amendment 2 — BCR has no cutoff (amends v1.1 §6 and §7)

* The v1.1 rule "macro BCR over N̄ below 1 ⇒ 'operationally useful'
  withheld" is **removed**. `BCR = 1` breaks even only if a wrong acceptance
  and a lost correct acceptance cost the same, which has not been
  established. `BCR = 1` is reported only as the **equal-cost reference
  point**, never as a pass/fail criterion.
* "Operationally useful" is withheld only under the coverage condition
  frozen in v1.1: the 0.20 coverage band fails in more than 5 of the 20 N̄
  environments. No further cost threshold is added.
* Still reported: BCR, correct accepts sacrificed, incorrect accepts
  prevented, Δcoverage, the 0.05/0.10/0.20 bands, and selective risk.

## Implementation consequence

Changes to `tools/run_lineage_a4v.py` (check 5 per family) and
`lineage_a/evaluate_a4v.py` (withholding rule, plus null `R` per family as a
diagnostic) are committed after this document and before the re-run. No
other code changes.
