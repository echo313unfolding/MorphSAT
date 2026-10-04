# Lineage A — Correction Authority: Preregistration v1 (DRAFT FOR REVIEW)

Status: **draft preregistration; not approved; not implemented.** New lineage,
independent of the closed causal-history line (`53c825b`, `15d03fd`,
`0a7a744`). Nothing here reopens H2/H3. Scope: public GitHub lineage of
`14689b7`.

**Origin, stated honestly.** The P3 held-out run showed B1/B2 separating
genuine from false corrections, but that separation is **confounded**:
post-correction direction and total directional count differed together. This
lineage does not treat that result as evidence. It asks a new question with
the confound designed out.

## 1. Primary question

Under controlled history structure, does **independent post-correction
corroboration** provide a safer and/or more useful basis for correction
authority than majority, recency, or unconditional supersession?

## 2. Design principle: avoid circular ground truth

If ground truth were assigned as "a correction is valid iff later evidence
supports it", corroboration-gated policies would win by construction. Instead:

* Ground truth is a **hidden variable of a frozen generative world model**
  (§4). Observation patterns are evidence about it, not definitions of it.
* The world model has parameters the policies do not know. Policies are
  evaluated across a **frozen grid of environments** (§4.3), including ones
  where corroboration-style rules are expected to be *wrong* (e.g. repeated
  readings that really are independent). Claims are about robustness across
  the grid, never about a single assumed world.
* Policy thresholds are **design parameters**. No measured P(accept | n)
  response curve is claimed for deterministic policies.

## 3. Unit of evaluation (policy level)

One **pattern** = an ordered sequence of observation records around exactly
one correction event, plus a query: "after this history, should the correction
be accepted, rejected, or should the system abstain?"

Records (extending P3 `HistoryRecord` with explicit provenance):

```
ObservationRecord
  order            int
  direction        benign | threat
  source_id        str      # explicit provenance (NEW)
  upstream_id      str      # shared-upstream identity (NEW; == source_id unless copied)
  is_correction    bool     # exactly one record per pattern
```

Policies see only these fields. No scenario label, family name, environment
parameter, or ground truth is visible to any policy (enforced by schema and
an AST test, as in P3).

Rationale for policy level (rather than full MorphSAT monitor runs): it
isolates the authority rule from the monitor and the benign guard, which in
the P3 held-out made benign resolution impossible. Integration into
arbitration is a later, separately preregistered step (see §12, U1).

## 4. Generative world model (frozen)

### 4.1 Hidden variables (evaluation-only)

* `x_pre ∈ {benign, threat}`, prior 0.5 each — true state before the
  correction.
* `D ~ Bernoulli(π_drift)` — a real change occurs at the correction time;
  `x_post = ¬x_pre if D else x_pre`.
* `A ~ Bernoulli(α)` — the correction's source is adversarial.
* The correction claims `c`. **The correction is valid iff `x_post == c`.**

### 4.2 Observation likelihoods

* Honest independent source reporting the state at its time (pre-correction
  records report `x_pre`, post-correction records report `x_post`): correct
  with probability `r`, flipped with probability `1 − r`, independently.
* Honest correction source: reports `x_post` as `c` with the same
  reliability `r`.
* Adversarial correction source: always asserts `c`; all of its other records
  (repeats) also assert `c` (likelihood 1 for the observed claims).
* **Repeated records from one upstream source**: with repeat correlation
  `ρ = 1` they share one noise draw (perfect copies); with `ρ = 0` each repeat
  is an independent re-measurement.

### 4.3 Environment grid (frozen; 16 environments)

| Parameter | Levels | Why |
|---|---|---|
| `r` (honest source reliability) | 0.7, 0.9 | weak vs strong sensors |
| `π_drift` (prior that a correction is genuine) | 0.2, 0.5 | rare vs common real change |
| `ρ` (repeat correlation) | 1.0, 0.0 | copies vs genuine re-measurement — independence-aware rules should **lose** when ρ = 0 |
| `α` (adversarial correction source) | 0.0, 0.3 | no attacker vs manufactured-corroboration attacker |

### 4.4 Evaluation by exact posterior

For each pattern and environment, `q = P(correction valid | pattern, θ)` is
computed exactly by enumerating `(x_pre, D, A)` and multiplying record
likelihoods (copies counted once when `ρ = 1`). A policy decision then yields
expected outcomes deterministically (§7). Primary evaluation uses no sampling
noise; a seeded Monte-Carlo sample (10,000 draws per environment) is a
secondary check of the posterior code only.

## 5. Generator: controlled pattern families (frozen)

Directions are specified explicitly per pattern. `d_pre = ¬c` (a correction
contradicts the prior belief). Correction direction `c ∈ {benign, threat}`
in every family (benign corrections are the safety-critical downgrades).

**FAM-G (full factorial).**
* pre-correction count `n_pre ∈ {0, 1, 2, 3}`, all `d_pre`, distinct
  independent sources;
* `c ∈ {benign, threat}`;
* post-correction count `n_post ∈ {0, 1, 2, 3}`;
* post-correction direction ∈ {support (= c), contradict (= d_pre)};
* post-correction sources ∈ {independent-distinct, one-other-source-repeated,
  correction-source-repeated}.
* Size: 4 × 2 × (1 + 3·2·3) = **152 patterns**.

**FAM-T (temporal placement; equal totals).** Two `d_pre` records before the
correction; `b ∈ {1, 2, 3}` records agreeing with `c`, of which `j ∈ {0..b}`
are placed **before** the correction and `b − j` after; all distinct
independent sources; `c ∈ {benign, threat}`. **Within a (b, c) cell only
temporal placement differs.** Size: (2 + 3 + 4) × 2 = **18 patterns**.

**FAM-I (independence; equal direction and count).** `n_pre = 2`;
`n_post ∈ {2, 3}`, all supporting; post sources ∈ {independent-distinct,
one-other-source-repeated, correction-source-repeated}; `c ∈ {benign, threat}`.
**Within an (n_post, c) cell only source independence differs.** Size:
**12 patterns** (a named subset of FAM-G, reported separately). This is the
explicit N-repeats-of-one-source vs N-independent-sources test.

Source identifiers are opaque (`s0, s1, …`); upstream identity equals the
source id except for repeats, which share the repeated source's upstream id.

## 6. Policies (frozen; thresholds reused from P3, not fitted)

Each policy outputs ACCEPT (belief = `c`), REJECT (belief = `d_pre`) or
ABSTAIN. `k = 2` and share `0.75` are the frozen P3 values.

| ID | Policy | Rule |
|---|---|---|
| A1 | Majority | All directional records including the correction; ACCEPT/REJECT if the top direction has ≥ 2 votes and share ≥ 0.75, else ABSTAIN |
| A2 | Pure recency | Direction of the most recent record (the correction if none follow) |
| A3a | Unconditional supersession | Always ACCEPT |
| A3b | Frozen MorphSAT B3 | Correction excludes earlier opposite records, then the A1 vote rule (continuity with P3; benign guard **not** applied at policy level) |
| A4 | Corroboration-gated supersession | ACCEPT if ≥ k post-correction records support `c` and none contradict; REJECT if ≥ k contradict and none support; else ABSTAIN |
| A5 | Independence-aware corroboration | As A4, counting **distinct upstream ids**, excluding the correction's own upstream, among post-correction records |

Controls and shams:

| ID | Control | Purpose |
|---|---|---|
| S1 | Direction-blind count sham | ACCEPT iff ≥ k post-correction records exist, whatever their direction (tests "later records" vs "supporting records") |
| S2 | Upstream-shuffled A5 | A5 with upstream ids permuted by frozen rule `sha256(f"{pattern_id}|{order}")` ranking (destroys true independence structure, keeps the multiset of ids) |
| S3 | Always ABSTAIN | coverage floor |
| S4 | Never accept corrections (always REJECT) | safety-biased floor |
| REF | Bayes reference (evaluation-only) | accepts iff `q > 0.5`, using environment parameters; **not a policy**, reported only as headroom |

## 7. Outcomes (per policy × environment × family)

With `q` = posterior validity and `t_post` = P(x_post = threat | pattern, θ):

* correct correction acceptance (CCA) = Σ q over ACCEPTs
* incorrect correction acceptance (ICA) = Σ (1 − q) over ACCEPTs
* correct correction rejection (CCR) = Σ (1 − q) over REJECTs
* incorrect correction rejection (ICR) = Σ q over REJECTs
* **selective risk** = (ICA + ICR) / (number of non-ABSTAIN decisions)
* **coverage** = non-ABSTAIN decisions / patterns
* **false_safe** = Σ t_post over decisions whose belief is benign
* **manufactured-corroboration failures** = Σ P(A = 1 ∧ invalid | pattern)
  over ACCEPTs, in α = 0.3 environments
* each reported unweighted (patterns equal) and weighted by the pattern's
  marginal likelihood under θ, normalized within its structural family

## 8. Hypotheses and decision rules (fixed in advance)

* **HA-safety:** A4 and A5 have lower ICA and false_safe than A1, A2, A3a,
  A3b in every environment.
* **HA-temporal (FAM-T):** in equal-total cells, the policies that are
  sensitive to placement (A4, A5) have lower selective risk than
  placement-blind A1.
* **HA-independence (FAM-I):** in α = 0.3, ρ = 1 environments, A5 has fewer
  manufactured-corroboration failures than A4 and S2; in ρ = 0 environments,
  A5's coverage/accuracy cost relative to A4 is reported as the price of
  independence-awareness.

**Primary decision.** "Independent post-correction corroboration is a safer
basis for correction authority" is **supported** iff A5:

1. has false_safe ≤ every one of A1, A2, A3a, A3b in all 16 environments;
2. has ICA ≤ every one of them in all 16 environments;
3. has selective risk ≤ both A1 and A2 in ≥ 12 of 16 environments;
4. has fewer manufactured-corroboration failures than A4 in every
   α = 0.3, ρ = 1 environment;
5. beats S1 and S2 on selective risk in ≥ 12 of 16 environments (otherwise the
   effect is "having later records" or "having many ids", not independent
   support).

Otherwise **not supported**. Partial results are reported as they fall,
including environments where A5 is worse. The coverage cost of A4/A5
(abstention) is always reported next to any safety gain.

## 9. Integrity controls

* Policies receive only `ObservationRecord` fields (schema test; AST check for
  `x_pre`, `drift`, `adversarial`, `q`, `env`, `family`, `label`,
  `ground_truth`).
* Generator, posterior evaluator and policies are committed and hashed before
  the first evaluation; the pattern set is hashed before evaluation.
* Posterior code is validated against the Monte-Carlo sample before primary
  results are read.
* No threshold, grid level, family or policy is changed after outcomes are
  visible; any change requires prereg v2 and both runs are reported.

## 10. Expected properties disclosed in advance (not results)

* A3a has ICA = Σ(1 − q) by construction and maximal coverage.
* A1 is placement-blind by construction, so FAM-T can only separate it from
  placement-sensitive rules, not from itself.
* In ρ = 0 environments, deduplicating repeats discards real information, so
  A5 is expected to under-use evidence there. This is deliberate.

## 11. Related work (verification level stated)

* Strictly proper scoring rules — Gneiting, T. & Raftery, A. E. (2007).
  *Strictly proper scoring rules, prediction, and estimation.* JASA 102(477),
  359–378. (Bibliographic details verified via search.)
* Source reliability without ground truth — Dawid, A. P. & Skene, A. M.
  (1979). *Maximum likelihood estimation of observer error-rates using the EM
  algorithm.* JRSS-C 28(1), 20–28. (Verified via search.)
* Agent-memory provenance (2026). Located via search index only; **full text
  not accessed** (arXiv blocked by this environment's egress proxy). Cited as
  related, not relied upon:
  * Louck, Y. *Securing LLM-Agent Long-Term Memory Against Poisoning:
    Non-Malleable, Origin-Bound Authority with Machine-Checked Guarantees.*
    arXiv:2606.24322. Index summary: argues content- or lineage-based defenses
    are unsound under laundering and proposes origin-bound authority with
    Sybil-resistant, corroboration-gated elevation; lists manufactured
    corroboration as a laundering channel.
  * Xu, J. et al. *Memory Provenance Laundering in LLM Agents: A
    Non-Amplification Firewall for Persistent Memory.* arXiv:2607.29167.
  * *From Agent Traces to Trust: A Survey of Evidence Tracing and Execution
    Provenance in LLM Agents.* arXiv:2606.04990.

## 12. Unresolved design choices (for review before approval)

* **U1** Policy-level evaluation (proposed) vs full MorphSAT monitor runs.
* **U2** Environment grid levels (`r`, `π_drift`, `ρ`, `α`) — proposed values
  are conventional, not fitted; reviewer may prefer more levels.
* **U3** Adversary scope: only the correction's source can be adversarial.
  Should pre-correction or independent sources also be corruptible?
* **U4** Binary direction (benign/threat): MorphSAT's `suspicious` is folded
  into threat. Acceptable?
* **U5** Reuse of P3 thresholds (k = 2, share 0.75) vs separately chosen
  values — reuse is proposed to avoid new degrees of freedom.
* **U6** Decision-rule margins (12/16 environments) are judgment calls.
* **U7** Weighting: unweighted vs marginal-likelihood-weighted — both
  reported; which one is primary? (Proposed: unweighted primary.)
* **U8** S2 shuffle rule and whether additional shams are needed.
