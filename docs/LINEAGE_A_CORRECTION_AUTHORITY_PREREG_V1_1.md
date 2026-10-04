# Lineage A — Correction Authority: Preregistration v1.1 (DRAFT FOR REVIEW)

Status: **revision of v1** (`docs/LINEAGE_A_CORRECTION_AUTHORITY_PREREG_V1.md`,
commit `965ec90`, preserved unchanged). Not approved; not implemented.
Everything in v1 stands unless amended here. Scope: public GitHub lineage of
`14689b7`. Independent of the closed causal-history line.

Summary of changes from v1: risk–coverage claim rule (§6); policy-level
evaluation fixed (§2); 24-environment grid with partial dependence (§3);
`source_id` ≠ `upstream_id` with three-way FAM-I (§4); binary abstraction
stated (§2); P3 thresholds inherited (§5); macro aggregation (§6.1);
frozen shuffle sham (§5); corrected prior-art position (§8).

## 1. Question and claimed contribution (narrowed)

Under controlled temporal histories, does **independent post-correction
corroboration** provide a safer basis for **correction / belief-revision
authority** than majority, recency or unconditional supersession, without
buying safety by collapsing coverage?

**No novelty is claimed** for origin-bound authority, independence-aware
corroboration, or manufactured-corroboration defenses; these are studied in
contemporary preprints (§8). The possible contribution is narrower: applying
these ideas to *correction authority* under controlled temporal structure,
comparing them in risk–coverage space, and later (separately) integrating a
surviving rule with MorphSAT's terminal decision semantics.

## 2. Fixed scoping decisions

* **Policy-level evaluation only (U1).** No MorphSAT monitor in v1.1.
  Integration is a later experiment, only if a policy-level effect survives.
* **Binary direction (U4).** `benign` / `threat` is an **experimental
  abstraction** for this isolated study. It does not redefine or replace
  MorphSAT's `suspicious` state.

## 3. World model and environment grid (amends v1 §4)

Hidden variables unchanged from v1: `x_pre` (prior 0.5), drift
`D ~ Bernoulli(π_drift)`, `x_post`, adversarial correction source
`A ~ Bernoulli(α)`; correction valid iff `x_post == c`.

**Upstream dependence model (replaces v1 §4.2 repeat model).** Every record
has an `upstream_id`. Each upstream group produces one latent reading of the
true state at its time (correct with probability `r`). Each record in the
group equals that latent reading with probability `ρ`, and otherwise is an
independent reading with reliability `r`. A record whose upstream is unique
is simply an independent reading. With `A = 1`, every record whose upstream is
the correction's upstream asserts `c` (likelihood 1 if it asserts `c`,
otherwise 0). Exact posteriors enumerate `(x_pre, D, A)` and each upstream
group's latent reading.

**Grid (U2): 24 environments.**

| Parameter | Levels |
|---|---|
| `r` | 0.7, 0.9 |
| `π_drift` | 0.2, 0.5 |
| `ρ` | 0, 0.5, 1 |
| `α` | 0, 0.3 |

## 4. Provenance schema and generator (amends v1 §3, §5)

```
ObservationRecord
  order          int
  direction      benign | threat
  source_id      str     # apparent source identity
  upstream_id    str     # true origin; distinct source_ids may share one
  is_correction  bool
```

**Distinct `source_id`s are never treated as independent evidence by
themselves.** Independence is defined only by distinct `upstream_id`s.

Post-correction source structures (used in FAM-G and FAM-I):

| Code | Structure | Example (n = 3) |
|---|---|---|
| A-corr | same source as the correction, repeated | `S_c, S_c, S_c` (upstream `U_c`) |
| B-corr | distinct source_ids sharing the correction's upstream | `S_1, S_2, S_3`, all upstream `U_c` |
| A-oth | one other source, repeated | `S_x, S_x, S_x` (upstream `U_x`) |
| B-oth | distinct source_ids sharing one other upstream | `S_1, S_2, S_3`, all upstream `U_x` |
| C | genuinely independent | `S_1, S_2, S_3`, upstreams `U_1, U_2, U_3` |

* **FAM-G:** `n_pre ∈ {0..3}` (independent sources) × `c` (2) × [`n_post = 0`,
  or `n_post ∈ {1, 2, 3}` × post-direction (2) × structure (5)] =
  4 × 2 × 31 = **248 patterns**.
* **FAM-T:** unchanged from v1 (18 patterns; only placement differs).
* **FAM-I:** `n_pre = 2`; `n_post ∈ {2, 3}`, all supporting; `c` (2) ×
  structure (5) = **20 patterns**. Within an (`n_post`, `c`) cell only source
  structure differs. A-corr / B-corr are the manufactured-corroboration cases;
  B-corr is the "many ids, one origin" attack.

## 5. Policies (amends v1 §6)

Inherited thresholds (U5): `k = 2`, vote share `≥ 0.75` — **frozen design
parameters inherited from P3, not inferred constants.**

v1 policies A1, A2, A3a, A3b, A4, A5, S1, S3, S4 and the evaluation-only REF
are kept. A5 counts **distinct `upstream_id`s** among post-correction
records, excluding the correction's own upstream. Added comparator:

* **A5n (naive independence)** — as A5 but counting distinct `source_id`s.
  Included to show whether apparent-identity counting is fooled by B-corr.

**S2 upstream-shuffle sham (U8; frozen).** For a pattern with id `pid`:
take the non-correction records, rank them by
`sha256(f"{pid}|{order}")` (hex, ascending), and reassign their
`(source_id, upstream_id)` pairs, in original record order, to the records in
ranked order. The correction record keeps its own ids. This preserves record
count, directions, correction placement, temporal order and the marginal
counts of source and upstream ids, and destroys the true assignment of
dependence to records. S2 then applies A5.

## 6. Outcomes and claim rule (replaces v1 §7–§8)

Reported per policy and environment: selective risk, coverage, abstention
rate (= 1 − coverage), false_safe, CCA, ICA, CCR, ICR,
manufactured-corroboration (MC) failures; plus per-environment Pareto
frontiers over (selective risk, coverage).

### 6.1 Aggregation (U7)

* **Within each environment (primary):** likelihood-weighted expectation —
  each pattern weighted by its marginal probability under that environment,
  normalized within its family.
  * coverage = Σ w·decided; selective risk = Σ w·error / Σ w·decided.
* **Across environments:** equal macro-weight over the 24 environments.
* Unweighted pattern-level results: secondary diagnostics only.

### 6.2 Definitions

* **Pareto dominance:** X dominates Y in an environment iff
  `risk_X ≤ risk_Y` and `coverage_X ≥ coverage_Y`, with at least one strict.
* **Coverage-admissible comparison:** X's safety advantage over Y counts only
  if `coverage_X ≥ coverage_Y − 0.10` (absolute) in that environment.
  Otherwise the advantage is classed as **bought by abstention** and is
  excluded from support.
* Comparator set **C** = {A1, A2, A3a, A3b, A4, A5n}.

### 6.3 Primary claim rule (frozen before implementation)

"Independent post-correction corroboration (A5) is a safer basis for
correction authority" is **supported** iff all of the following hold:

1. **Non-domination:** A5 is not Pareto-dominated by any policy in C in
   ≥ 75% of environments.
2. **Useful dominance:** A5 Pareto-dominates at least one of {A1, A2, A3b} in
   ≥ 75% of environments.
3. **Coverage-admissible safety:** for each comparator in C, A5 has
   false_safe ≤ and ICA ≤ that comparator in ≥ 75% of environments,
   counting only coverage-admissible comparisons; an environment where the
   comparison is not admissible counts as a **failure** of this criterion.
4. **Manufactured corroboration:** in every environment with `α = 0.3` and
   `ρ ∈ {0.5, 1}`, A5 has fewer MC failures than A4 **and** than A5n, and in
   ≥ 75% of those environments fewer than S2.
5. **Shams:** A5 has lower selective risk than S1 and S2 at coverage-admissible
   levels in ≥ 75% of environments.

Otherwise **not supported**. All partial results, including environments
where A5 is dominated, are reported. A result whose safety advantage exists
only through substantially lower coverage is never reported as support.

### 6.4 Secondary hypotheses (reported, not part of the claim)

* HA-temporal (FAM-T): placement-sensitive rules vs placement-blind A1 in
  equal-total cells, in risk–coverage terms.
* HA-dependence (`ρ`): how A5's position in risk–coverage space changes from
  `ρ = 1` to `ρ = 0.5` to `ρ = 0` (A5 is expected to under-use evidence at
  `ρ = 0`).

## 7. Integrity controls

Unchanged from v1 §9 (no-oracle schema and AST checks; generator, evaluator
and policies committed and hashed before evaluation; pattern set hashed;
posterior code validated against a seeded Monte-Carlo sample; no change after
outcomes without a new preregistration version).

## 8. Prior art (replaces v1 §11)

Preprints below were verified by the reviewer (2026-10-04); this environment
could locate them via search but could not open arXiv (egress-blocked).
They are treated as **relevant preprints / prior art, not established
peer-reviewed conclusions.**

* Louck, Y. (2026). *Securing LLM-Agent Long-Term Memory Against Poisoning:
  Non-Malleable, Origin-Bound Authority with Machine-Checked Guarantees.*
  arXiv:2606.24322. Content- and derivation-lineage trust can be laundered,
  including via manufactured corroboration; proposes origin-bound authority
  and Sybil-resistant, corroboration-gated elevation. **Closest prior art to
  this lineage's independence component.**
* Xu, J. et al. (2026). *Memory Provenance Laundering in LLM Agents: A
  Non-Amplification Firewall for Persistent Memory.* arXiv:2607.29167.
  Memory consolidation can erase low-trust origins while retaining action
  authority; platform-maintained provenance with authority/risk controls.
* (2026). *Agent Memory Is a Surface for Endogenous Authorization
  Laundering.* arXiv:2609.01836. An agent's own memory updates can
  manufacture authority without an external attacker; source-backed
  permissions and bounded event sourcing reduce this at a utility cost.
* (2026). *From Agent Traces to Trust: A Survey of Evidence Tracing and
  Execution Provenance in LLM Agents.* arXiv:2606.04990. Identifies
  provenance-aware trust and recovery as open areas.
* Established machinery: Gneiting & Raftery (2007), JASA 102(477), 359–378
  (proper scoring rules); Dawid & Skene (1979), JRSS-C 28(1), 20–28 (observer
  error rates without true labels).

The P3 finding "lineage ≠ credibility" independently matches the failure class
these preprints describe as authority/provenance laundering. That convergence
is context, not a contribution claim.

## 9. Remaining open items

* Exact numerical tolerance for the absolute coverage margin (0.10) and the
  75% proportion — proposed, frozen once approved.
* Whether FAM-T should also vary source structure (currently independent
  only).
