# P3 Held-out Closure Result

Dataset: `receipts/p3_heldout/heldout_dataset.json` (sha256 `e0570348…0a52bc`,
frozen `6d5cf8d`), generated once by `tools/gen_p3_heldout.py` (`3b16371`,
exact realization of `ca394ff`, audit `docs/P3_HELDOUT_GENERATOR_AUDIT.md`).
Runner `032d12a`, committed before arbitration. Receipt: `receipts/p3_heldout/p3_heldout_results_20261004T192559Z.json`. Frozen P3 code
`53c825b` unchanged. No parameter tuned after outcomes. Scope: public GitHub
lineage of `14689b7`.

## Admission (label-free, B0-only)

600/600 runs admitted in all 9 modes. Stratum A: 300 HARNESS_END. Stratum B:
300 **TOOL_BUDGET_EXHAUSTED** (endogenous). All 2,400 history episodes
COMMIT naturally. U7 (admitted but not deferred under another baseline): 0.

## Closure question — matched P3 (genuine correction) vs P4 (false correction), identical probe evidence

| Baseline | Stratum A pairs: correct / wrong / tie | Stratum B | Discriminates |
|---|---|---|---|
| B0 | 0 / 0 / 60 | 0 / 0 / 60 | no |
| B1 | 60 / 0 / 0 | 60 / 0 / 0 | **yes** |
| B2 | 60 / 0 / 0 | 60 / 0 / 0 | **yes** |
| B2M | 24 / 12 / 24 | 23 / 10 / 27 | no |
| **B3** | 0 / 0 / 60 | 0 / 0 / 60 | **no** |

All 9 modes identical. Results match the analytic expectation stated in the
audit before generation.

## Fixed interpretation applied

* **B3 does not discriminate** genuine from false correction in either
  stratum. Per the pre-fixed rule: **causal provenance/supersession is
  insufficient for correction validity in this architecture; the
  causal-history line is CLOSED for this harness.**
  * P3: supersession removes both pre-correction threat records → 2 benign
    votes → blocked by the frozen benign guard (probe balance > 0) → ABSTAIN.
  * P4: supersession removes the first two threat records → 1 benign
    (correction) vs 1 escalate (post-correction) → share 0.5 → ABSTAIN.
* **B1 and B2 discriminate (60/60 correct direction, 0 wrong, both strata).**
  Per the rule this does **not** promote H2/H3. The discriminating observable is
  the **count of directional history records without causal interpretation**:
  P3 = 2 escalate / 2 benign (share 0.5 → ABSTAIN); P4 = 3 escalate / 1 benign
  (share 0.75 → COMMIT escalate). The extra escalate vote is the
  post-correction episode's outcome/evidence lean. B1 (evidence lean only)
  equals B2 (canonical outcomes), so the signal is generic historical
  evidence, not the agent's own decisions and not provenance.
  * Candidate separate experiment (not run, not preregistered): whether
    *post-correction confirmation evidence* (renewed threat evidence after a
    correction) is a reliable correction-validity signal — e.g. vary the
    number/position of post-correction episodes with probe evidence held fixed.
* **B2M** (noncausal mask) is mixed in both directions (12 and 10 wrong-direction
  pairs) — removing records by chance does not discriminate.

## Per-cell outcomes (Mode A; strata identical in pattern)

| Pattern (GT) | B0 | B1 = B2 | B2M (A / B) | B3 |
|---|---|---|---|---|
| P1 stable threat (escalate) | ABSTAIN 60 | escalate 60 ✓ | escalate 60 ✓ | escalate 60 ✓ |
| P2 stable benign (benign) | ABSTAIN 60 | ABSTAIN 60 | ABSTAIN 60 | ABSTAIN 60 |
| P3 genuine drift (benign) | ABSTAIN 60 | ABSTAIN 60 | escalate 20/16 ✗, ABSTAIN rest | ABSTAIN 60 |
| P4 false correction (escalate) | ABSTAIN 60 | escalate 60 ✓ | escalate 32/29 ✓, ABSTAIN rest | ABSTAIN 60 |
| P5 mixed (suspicious) | ABSTAIN 60 | ABSTAIN 60 | ABSTAIN 60 | ABSTAIN 60 |

false_safe = 0 for every baseline, cell and mode. As disclosed in the audit,
the frozen benign guard makes benign resolution impossible on this probe menu,
so P2/P3 can at best ABSTAIN.

## Status

* Causal-history (B3/provenance) line: **closed for this harness.**
* Not promoted: H2, H3, own-vs-foreign, self-model, strange loop.
* Null and negative results preserved (`53c825b` pilot; this closure result).
