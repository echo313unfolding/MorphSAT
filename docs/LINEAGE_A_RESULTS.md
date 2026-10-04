# Lineage A Results — Correction Authority (policy level)

Preregistration: v1.0 `965ec90` → v1.1 `6be2821` → v1.2 `c90e008` → v1.3
`0c7847a`. Implementation frozen before running (`9929b31`); one pre-result
fix (`38f29e3`: zero-probability patterns crashed the first evaluation
*after* posterior validation passed and *before* any policy outcome was
computed; also added the preregistered unweighted diagnostic). Receipts:
`receipts/lineage_a/lineage_a_results_20261004T215503Z.json`, `receipts/lineage_a/posterior_validation_20261004T215503Z.json`. Scope: public GitHub lineage of `14689b7`. No threshold, rule,
grid or policy changed after outcomes.

## Validity

Posterior Monte-Carlo validation **passed**: 1,245 checks, 0 failures (max
absolute difference 0.078, within the 3·SE + 0.005 rule for its sample size).
Pattern counts: FAM-G 248, FAM-T 54, FAM-I 20. In the 12 environments with
`ρ = 1`, 48 patterns are impossible (perfect copies that disagree) and get
weight 0, as the frozen cell normalization implies.

## Primary verdict (v1.2 rule, unchanged by v1.3)

| Criterion | Result | Pass |
|---|---|---|
| 1 A5 not Pareto-dominated by C = {A1, A2, A3a, A3b, A4, A5n} | 23 / 24 envs | yes |
| 2 A5 Pareto-dominates A1, A2 or A3b | **0 / 24** | **no** |
| 3 MC failures < A4 and < A5n in all 8 attack envs; < S2 in ≥ 75% | 8/8, 8/8, 8/8 | yes |
| 4 not dominated by S1/S2 and dominates S2 | **0 / 24** | **no** |

**Not supported.** Independent post-correction corroboration (A5) is not shown
to be a better basis for correction authority in risk–coverage terms.

## Macro results (equal weight over 24 environments)

| Policy | Sel. risk | Coverage | false_safe | ICA | MC failures |
|---|---|---|---|---|---|
| A1 majority | 0.179 | 0.254 | 0.023 | 0.022 | 0.0130 |
| A2 recency | 0.185 | 1.000 | 0.092 | 0.156 | 0.0735 |
| A3a always accept | 0.256 | 1.000 | 0.128 | 0.256 | 0.1101 |
| A3b frozen B3 | 0.173 | 0.880 | 0.075 | 0.145 | 0.0688 |
| A4 corroboration | 0.140 | 0.479 | 0.034 | 0.053 | 0.0288 |
| **A5 independent** | **0.058** | **0.118** | **0.003** | **0.005** | **0.0016** |
| A5n naive ids | 0.124 | 0.299 | 0.018 | 0.029 | 0.0152 |
| S1 count sham | 0.256 | 0.479 | 0.061 | 0.123 | 0.0541 |
| S2 shuffle sham | 0.091 | 0.301 | 0.012 | 0.020 | 0.0078 |
| C1 declared origin | 0.220 | 1.000 | 0.110 | 0.130 | 0.0600 |
| C2 + agreement credit | 0.220 | 1.000 | 0.110 | 0.130 | 0.0600 |
| REF Bayes (eval only) | 0.173 | 0.988 | 0.086 | 0.130 | 0.0537 |

## What happened

* **A5 is the safest policy on every error measure, but decides on only ~12%
  of histories.** Its advantages are mostly abstention-driven. Coverage-band
  diagnostic: vs A1 and A5n, A5's safety/risk advantages survive only in the
  ΔC ≤ 0.20 band (24/24 and 23/24 envs); vs A2, A3a, A3b and A4, in no band.
  This is the P3 failure mode ("safe because it abstains"), which the frozen
  rule was designed to catch, and did.
* **Manufactured-corroboration resistance is real and large.** With an
  attacker and dependence, A5's MC failures (≈ 0.000–0.008) are an order of
  magnitude below A4 (0.04–0.08), A5n (0.02–0.04) and C1/C2 (0.09–0.15).
  Counting distinct upstreams, not apparent sources, is what blocks the
  "many ids, one origin" attack. A5n is fooled, as expected.
* **Independence information is worthless without dependence or attack.** In
  the four `ρ = 0, α = 0` environments the shuffle sham S2 Pareto-dominates
  A5 (and in one, A4 and A5n do too). When repeats are genuinely independent,
  destroying the upstream assignment costs nothing.
* **Coverage is largely set by the generator.** It is nearly constant across
  environments for every policy, because it depends on which histories the
  families contain (e.g. how many have ≥ 2 independent post-correction
  supporters), not on the world. Risk–coverage comparisons are therefore
  conditional on this pattern mix. This is a limitation of the design, stated
  here rather than discovered later.

## External-artifact diagnostics (secondary; not part of the claim)

* **D1 / C1:** Corollary-style declared-origin noisy-OR always decides, and has
  MC failures comparable to unconditional supersession (macro 0.060).
* **D2: C2 − C1 = 0 on every metric in every environment.** Agreement-credited
  trust changed no decision here, because each pattern starts a fresh ledger:
  one confirmation moves reliability only from 0.95 to ≈ 0.958, which is too
  small to flip any noisy-OR comparison. The positive-feedback loop needs trust
  carried across episodes, which v1.3 deliberately did not model.
* **D3:** under C2, sources that share the correction's upstream end with the
  same mean reliability as genuinely independent sources (0.958 both). The
  artifact grants aliases exactly the trust it grants independent evidence.

## Interpretation (narrow)

* Supported in this harness: counting **distinct origins** (not apparent ids)
  sharply reduces manufactured-corroboration acceptance.
* Not supported: that independence-gated correction authority is better
  overall. Under these frozen thresholds it buys safety with coverage and is
  Pareto-incomparable to simpler rules.
* Not tested: cross-episode trust accumulation (the C2 feedback loop); a
  coverage-preserving independence-aware rule; any MorphSAT integration.
