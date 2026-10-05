# Lineage A4V Results — Upstream-Alias Veto on A4

Preregistration: v1.0 candidate `5010996` → v1.1 `0b44c16` (frozen) →
v1.2 `f69ff08` (validity amendment after run 1 aborted, `8486875`).
Implementation `6f2a51c` + v1.2 changes `db1fb06`, committed before the
re-run. Receipts: `receipts/lineage_a4v/a4v_results_20261005T011637Z.json`, `receipts/lineage_a4v/posterior_validation_20261005T011637Z.json`,
`receipts/lineage_a4v/a4v_ABORTED_20261005T010534Z.json` (run 1).
Scope: public GitHub lineage of `14689b7`. Run once from v1.2; nothing
changed after outcomes.

**Ceiling:** a generator-internal mechanism test and cost characterization,
not evidence about real-world epistemic independence.

## Validity (all passed)

1. Posterior validation reproduced Lineage A exactly (1,245 checks, 0
   failures, max diff 0.078).
2. Frozen Lineage A files byte-identical to `39766cc`; pattern-set hash
   matches.
3. 39 tests pass (A4V invariants I1–I6 + Lineage A).
4. Structural veto counts match prereg §5.
5. Null identity (v1.2): `R(A4V) = 1` within FAM-G, FAM-T and FAM-I in all
   four `ρ = 0, α = 0` envs (max deviation 6e-15). Pooled null `R` =
   0.981–0.994 (mixture effect, reported, not fixed).
6. A4 reproduces the Lineage A receipt exactly (max diff 0.0).

## Verdict

| | Criterion | Result | Pass |
|---|---|---|---|
| V1 | `R(A4V) ≥ 2` | **0 / 20** (R = 1.14–1.38) | **no** |
| V2 | `R(A4V) > R(A4V-S)` | **0 / 20** | **no** (see caveat below) |
| V3 | selective risk below A4 | 15 / 20 | yes |

**CLOSED: detector, not authority information (V1 fails).** The alias veto
blocks wrong A4 acceptances only 1.14–1.38× as often as correct ones, far
below the 2× minimum practical discrimination threshold. The closure rests
on V1 alone, which needs no sham.

## Cost characterization (non-null, 20 envs)

* Coverage falls from 0.479 to 0.31–0.35 (Δcoverage 0.134–0.169), about
  30% of A4's decisions. Coverage bands: 0.05 → 0/20, 0.10 → 0/20,
  0.20 → 15/20.
* BCR 0.008–0.68, macro 0.23 (equal-cost reference 1). By weighted mass the
  veto sacrifices about 4.4 correct acceptances per incorrect acceptance
  prevented.
* By construction it is weakly safer. Under attack with `ρ > 0`, MC
  failures fall from 0.034–0.080 (A4) to 0.017–0.044 (A4V).
* V3's 15/20 comes from all 12 attack envs plus 3/8 dependence-only envs.
  Selective risk rises in the other 5 and in all 4 null envs.

## What happened (diagnostics; preregistered as non-claim, §8)

* **`R(A4V) = R(A4V-W)` exactly in every env (to 3e-15).** In this
  generator, `source_id` never enters the likelihood. Each vetoed B-type
  pattern (several source ids, one upstream) has a likelihood-identical
  A-type twin (one source repeated, same upstream), and the wide veto
  catches both. So "multiple apparent sources" carries no information
  beyond the upstream projection. The narrow veto is the wide veto at half
  the mass, with identical discrimination.
* **The signal sits in one subtype.** Corr-alias vetoes, where support
  collapses onto the correction's own upstream (B-corr), reach `R ≥ 2` in
  18/20 non-null envs (R 1.58–5.21; macro BCR 0.24–0.73). Other-alias
  vetoes (B-oth, shared-upstream) have `R < 1` in 20/20 non-null envs
  (0.04–0.94). They remove acceptances that are *better* than the remaining
  pool, which still contains correction self-corroboration. Pooling the two
  dilutes the corr-alias signal to 1.14–1.38. **This split is post hoc
  within a preregistered diagnostic.** It is hypothesis-generating only and
  not a rescue of the closed claim.
* **Caveat on V2:** all 22 sham vetoes are a **strict subset** of the real
  A4V veto set (16 B-corr, 4 B-oth with `n_pre = 0`, 2 shared-upstream).
  The frozen within-pattern shuffle cannot break U_c aliasing when few or
  no differently-sourced records exist to swap with. So the sham did not
  destroy dependence. It selected a corr-alias-enriched subset of true
  aliases, which is why its R is higher. V2 fails as specified, but its
  planned reading ("not specific to true upstream structure") is **not**
  supported by the mechanism. The verdict does not depend on V2.
* **Inherited-control flag (not re-analysed):** Lineage A's S2 sham uses
  the same frozen shuffle. It may likewise preserve dependence in some
  patterns, which bears on reading Lineage A criterion 4. Recorded here;
  Lineage A results are unchanged.

## Macro (equal weight over 24 envs, context only)

| Policy | Sel. risk | Coverage | false_safe | ICA | MC |
|---|---|---|---|---|---|
| A4 | 0.140 | 0.479 | 0.034 | 0.053 | 0.0288 |
| A4V | 0.129 | 0.329 | 0.021 | 0.029 | 0.0152 |
| A4V-S (sham) | 0.123 | 0.394 | 0.024 | 0.035 | 0.0173 |
| A4V-W (diag.) | 0.099 | 0.179 | 0.009 | 0.005 | 0.0016 |
| A4V-corr (diag.) | 0.120 | 0.423 | 0.025 | 0.037 | 0.0181 |
| A4V-oth (diag.) | 0.152 | 0.385 | 0.030 | 0.045 | 0.0258 |

## Consequence (per prereg §12)

* Close this path. Lineage B proceeds with `upstream_id` as **metadata
  only**, not as a control signal.
* Open, untested, would need its own preregistration and fresh data: a
  correction-self-corroboration guard (the corr-alias subtype). Its signal
  here is partly guaranteed by the generator's adversary, which controls
  exactly U_c (T1), and its BCR stayed below the equal-cost reference.
* A sham that actually destroys dependence (cross-pattern reassignment)
  would be needed before any future specificity claim.
