# Lineage A4V — Run 1 aborted at validity check 5 (2026-10-05)

Implementation `6f2a51c`, prereg v1.1 `0b44c16`. Receipt:
`receipts/lineage_a4v/a4v_ABORTED_20261005T010534Z.json` (validity checks
only; no claim, no non-null metrics).

## What happened

Checks 1–4 and 6 passed. Posterior validation reproduced Lineage A exactly.
Frozen files were unchanged. 39 tests passed. Structural counts matched §5,
and A4 reproduced the Lineage A receipt (max diff 0.0). Check 5 (E2 null
identity, `|R − 1| ≤ 1e-9` for A4V and A4V-S in the 4 `ρ = 0, α = 0` envs)
**failed**: max `|R − 1|` = 0.061. The runner stopped. `run()` had computed
all environments in memory, but the claim and non-null metrics were neither
printed nor written. The diagnosis below used null environments only.

## Diagnosis (null envs only)

| Env (ρ=0, α=0) | A4V FAM-G | A4V FAM-T | A4V pooled | A4V-S FAM-G | A4V-S FAM-T | A4V-S pooled |
|---|---|---|---|---|---|---|
| r=0.7, π=0.2 | 1.0 | 1.0 | 0.9895 | 0.8867 | 1.2042 | 0.9452 |
| r=0.7, π=0.5 | 1.0 | 1.0 | 0.9939 | 1.0 | 1.2437 | 1.0430 |
| r=0.9, π=0.2 | 1.0 | 1.0 | 0.9810 | 0.8542 | 1.4117 | 0.9484 |
| r=0.9, π=0.5 | 1.0 | 1.0 | 0.9897 | 1.0 | 1.4215 | 1.0614 |

Two derivation errors in prereg §5 E2, both mine:

1. **A4V's identity holds per family, not pooled.** Within FAM-G and within
   FAM-T, `R(A4V) = 1` exactly, as derived. The primary weighting pools the
   two families (½ each) before forming the ratio. The veto removes a
   different share of A4 accepts in each family, and the families have
   different A4 error rates. The pooled ratio is therefore not 1
   (aggregation / Simpson-type effect). Implementation is correct.
2. **A4V-S has no identity at all.** The sham's veto set is not
   composition-balanced: which shuffled patterns collapse onto one upstream
   depends on `n_pre` and `n_post`. So in null envs its R reflects pattern
   composition alone (0.85–1.42 per family). That composition-only
   discrimination is exactly the baseline V2 compares against, so V2 is
   unaffected in meaning.

## Status

Run invalid as specified. No criterion was evaluated. An amendment is
required before re-running (proposed to the user; not applied).
