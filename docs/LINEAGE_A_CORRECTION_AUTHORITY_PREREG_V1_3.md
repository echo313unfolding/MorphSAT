# Lineage A — Correction Authority: Preregistration v1.3 (FROZEN FOR IMPLEMENTATION)

Status: **amendment to v1.2** (`docs/LINEAGE_A_CORRECTION_AUTHORITY_PREREG_V1_2.md`,
`c90e008`, preserved). v1.0–v1.2 stand except as amended here. Frozen before
any Lineage A code or outcome. Scope: public GitHub lineage of `14689b7`.

**The v1.2 primary claim rule is unchanged.** A5 is judged only against the
v1.2 comparator set C = {A1, A2, A3a, A3b, A4, A5n} and shams S1/S2, with the
same 18/24 thresholds. Nothing below is a requirement A5 must meet.

## Amendment 1 — External-artifact comparators C1 and C2 (secondary, diagnostic)

**Provenance of this addition:** added from the pre-implementation artifact
scan recorded at `f0b4b63` (`docs/ADJACENT_WORK_PROTOCOL.md` §7), modelling
the public implementation `gabe-santana/corollary` at commit `3c25939`. The
artifact's weakness is preserved, not fixed.

Purpose: does the independence-aware mechanism resist a failure mode present
in an existing public implementation?

### Shared modelling (C1 and C2)

Faithful to Corollary's mechanism (`kernel.py` `assert_`, `_confidence`,
`_premise_confidence`, `_credit_confirmation`; `ledger.py`; `trust.py`;
`resolvers.PreferHigherConfidence`):

* **Visible input:** a *declared view* of each record — `order`, `direction`,
  `source_id`, `is_correction`. **No `upstream_id`.** Declared origin =
  `source_id`. This models Corollary's default where origin is not declared
  separately (it defaults to the justification's own identity); Corollary with
  correctly declared true origins would behave like an upstream-aware rule and
  is **not** what C1/C2 model.
* One belief key with values `{benign, threat}`. Each record is a premise
  assertion `(value = direction, source = "tool:" + source_id)`. The
  correction is asserted as an ordinary premise (no `supersede=True`; forced
  supersession is already represented by A3a). No retractions occur.
* **Repeats:** a record from a source that already justifies the same value
  replaces its earlier justification (not new evidence, no credit).
* Prior per source `p0 = 0.95` (Corollary's default for kind `tool`); ledger
  `prior_weight W = 10`; no memory half-life; freshness 1.
* `reliability(s) = (p0·W + correct_s) / (W + total_s)`, equal to `p0` when the
  source has no recorded outcomes.
* `conf(v) = 1 − Π_{origin groups g supporting v} (1 − max_{j∈g} reliability(source_j))`
  (noisy-OR over declared origins).
* **Decision (PreferHigherConfidence, margin 0):** if only one value has
  support, belief = that value. If both, belief = the value with higher
  `conf`; exact ties go to the value whose belief was first created later
  (newest). ACCEPT if belief = `c`, else REJECT. C1/C2 never abstain.

### C1 — declared-origin corroboration

The shared model with the trust ledger **never updated** (all reliabilities
stay `p0`).

### C2 — agreement-credited trust

C1 plus Corollary's agreement credit, applied in record order:

1. Process records in increasing `order`.
2. For a record asserting value `v` by source `s`:
   * if no record has yet asserted `v`: create the belief (no credit);
   * else if `s` already justifies `v`: repeat (replace, no credit);
   * else (a *confirming* assertion): add `s`; let `others` = sources already
     justifying `v` whose declared origin ≠ `s`'s. If `others` is non-empty,
     record one **correct** outcome for each source in `others` and one for
     `s`.
3. After all records, compute `conf` with the updated reliabilities and decide.

"Agreement" is agreement among agent-visible records only. No evaluation
label, hidden state or environment parameter enters any update. The ledger is
fresh for each pattern (cross-pattern accumulation would only strengthen the
effect; not modelled).

### Diagnostic questions (reported, never part of the A5 claim)

* **D1** In B-corr and A-corr patterns of `α = 0.3` environments: MC failures
  and ICA of C1 and C2 vs A5.
* **D2** C2 − C1 (ICA, false_safe, MC failures): the isolated effect of
  agreement-credited trust (circular reinforcement).
* **D3** Mean final reliability of sources that share the correction's
  upstream (B-corr) vs independent sources (C), under C2: trust inflation.

## Amendment 2 — Implementation details frozen (clarifications, not changes)

* **Epoch latent readings.** The upstream latent reading of v1.1 §3 is per
  `(upstream_id, epoch)`, with epoch ∈ {pre, post} relative to the correction.
  This is needed when one upstream contributes records on both sides of the
  correction (FAM-T). Records copy their epoch's latent with probability `ρ`.
  The correction belongs to (`U_c`, post).
* **Record ordering.** FAM-G: pre records, correction, post records. FAM-T:
  the two `d_pre` records, then the `j` early `c`-agreeing records,
  correction, then the `b − j` late records.
* **Identifiers.** Correction `S_c`/`U_c`; pre `S_p{i}`/`U_p{i}`;
  "other" source `S_x`/`U_x`; distinct alias ids `S_q{i}`; independent
  upstreams `U_q{i}`; FAM-T groups `S_x`/`U_x` (d_pre) and `S_y`/`U_y`
  (`c`-agreeing).
* **Policy details.**
  * A1 counts all records, the correction included.
  * A3b has no slot limit at policy level: the correction excludes every
    earlier record whose direction ≠ `c`, then the A1 rule applies.
  * A4/A5/A5n count post-correction records (order > correction) and apply the
    "none contradict" condition in their own counting unit (records, distinct
    upstreams, distinct source ids). A5 and A5n exclude the correction's own
    upstream / source id respectively.
  * S1: ACCEPT iff ≥ 2 post-correction records exist, else ABSTAIN.
  * REF: ACCEPT if `q > 0.5`, REJECT if `q < 0.5`, ABSTAIN at 0.5.
* **Weighting (clarifies v1.1 §6.1).** Within an environment, a pattern's
  weight is the probability of its post-correction directions given its
  structure cell (the pattern with post-direction removed), normalized over
  the direction variants present in that cell. Cells are weighted equally.
  FAM-G and FAM-T are weighted equally; FAM-I is reported separately (it is a
  subset of FAM-G). Reason: raw marginal likelihoods are not comparable across
  patterns of different lengths.
* **Zero coverage.** The selective risk of a policy with zero coverage is
  defined as 0.
* **Posterior validation.** Seeded Monte Carlo, 10,000 draws per
  (environment, validation cell), for at least 6 cells spanning all source
  structures. Pass if |empirical − exact| ≤ 3·SE + 0.005 for every direction
  pattern with ≥ 200 matches. Primary results are not read until this passes.

## Amendment 3 — Required tests (before any evaluation)

* C1/C2 receive only the declared view; a runtime test passes records without
  an `upstream_id` attribute, and an AST test asserts the comparator module
  never references `upstream_id`.
* C2's credit rule matches the artifact's semantics on hand-built cases
  (repeat → no credit; first assertion → no credit; confirmation → credit to
  the asserter and every different-origin supporter).
* The no-oracle AST check covers all policy modules (no `x_pre`, `drift`,
  `adversarial`, `q`, `env`, `family`, `label`, `ground_truth`).
* The shuffle sham preserves count, directions, order, correction placement
  and marginal id counts.
