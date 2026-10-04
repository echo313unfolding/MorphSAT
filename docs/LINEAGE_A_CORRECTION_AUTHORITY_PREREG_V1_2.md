# Lineage A — Correction Authority: Preregistration v1.2 (FREEZE CANDIDATE)

Status: **revision of v1.1** (`docs/LINEAGE_A_CORRECTION_AUTHORITY_PREREG_V1_1.md`,
`6be2821`, preserved). Everything in v1.1 stands except as amended here. Not
implemented. Scope: public GitHub lineage of `14689b7`.

Research question: **When should a correction be granted authority, and does
true source independence matter?**

## Amendment 1 — Primary claim rule uses the full risk–coverage relation

The 0.10 absolute coverage margin is **removed from the primary rule** (it
created an artificial cliff at 0.09 vs 0.11). The **75% environment
proportion is frozen** (= 18 of 24 environments).

Replaces v1.1 §6.2–§6.3. Definitions unchanged: Pareto dominance in an
environment = risk ≤ and coverage ≥, with at least one strict. Comparator set
C = {A1, A2, A3a, A3b, A4, A5n}.

"Independent post-correction corroboration (A5) is a safer basis for
correction authority" is **supported** iff all hold:

1. **Non-domination:** A5 is not Pareto-dominated by any policy in C in
   ≥ 18/24 environments.
2. **Frequent dominance:** A5 Pareto-dominates at least one of {A1, A2, A3b}
   in ≥ 18/24 environments.
3. **Manufactured corroboration:** in every environment with `α = 0.3` and
   `ρ ∈ {0.5, 1}`, A5 has fewer MC failures than A4 and than A5n, and fewer
   than S2 in ≥ 75% of those environments.
4. **Shams:** A5 is not Pareto-dominated by S1 or S2, and Pareto-dominates S2,
   in ≥ 18/24 environments.

Otherwise **not supported**.

**Coverage-loss diagnostics (reported, not part of the claim).** For each
comparator in C and each environment, report whether A5's false_safe, ICA and
selective-risk advantages survive at coverage loss
`ΔC = coverage_comp − coverage_A5` within each band: `ΔC ≤ 0.05`,
`ΔC ≤ 0.10`, `ΔC ≤ 0.20`. A safety advantage that appears only outside all
bands is labelled "abstention-driven" in the write-up, whatever the headline
verdict.

## Amendment 2 — FAM-T varies source structure

FAM-T keeps its temporal design (two `d_pre` records before the correction;
`b ∈ {1, 2, 3}` records agreeing with `c`, `j ∈ {0..b}` of them before the
correction) and now crosses it with source structure `s`, applied
symmetrically within each direction group:

| `s` | `d_pre` group | `c`-agreeing group |
|---|---|---|
| repeated | one source repeated (`S_x`, upstream `U_x`) | one other source repeated (`S_y`, `U_y`) |
| shared-upstream | distinct ids, all upstream `U_x` | distinct ids, all upstream `U_y` |
| independent | distinct ids and upstreams | distinct ids and upstreams |

Size: 18 × 3 = **54 patterns**. Within a (`b`, `c`, `s`) cell only temporal
placement differs. Within a (`b`, `c`, `j`) cell only source structure differs.
This separates *when evidence appeared* from *how independent it was*, e.g.
`T_A, T_A, T_A, C, B_A` vs `T_A, T_B, T_C, C, B_D` with identical timing.
(The `c`-agreeing groups never share the correction's upstream in FAM-T;
manufactured-corroboration structures stay in FAM-G and FAM-I.)

## Frozen on approval

75% (18/24) proportion · Pareto-primary claim rule · coverage bands
{0.05, 0.10, 0.20} as diagnostics only · FAM-G 248, FAM-T 54, FAM-I 20
patterns · all v1.1 policies, shams, grid, dependence model, aggregation and
integrity controls.

Lineage B remains scoping-only until Lineage A completes.
