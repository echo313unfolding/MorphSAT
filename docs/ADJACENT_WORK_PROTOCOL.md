# Adjacent-Work Protocol (scholarly + artifact scans)

Purpose: before any novelty claim or choice of next experiment, find **who
else is building or testing something structurally similar**, not only what
reached the scholarly publishing system. Adopted 2026-10-04.

## 1. Two scans, always

| Scholarly scan | Artifact scan |
|---|---|
| arXiv, Semantic Scholar, proceedings, journals, citation trails, established terminology | GitHub repos and code search, issues/discussions, experimental branches, release notes, benchmarks, Hugging Face model cards, PyPI packages, technical blogs |

## 2. Search by function, not by our names

Our terms (shadow, receipts, causal history, structural identity, DEFER) are
idiosyncratic. Query the mechanism, e.g.:

`agent memory supersede correction` · `belief revision llm runtime` ·
`truth maintenance agent` · `agent source trust independent corroboration` ·
`persistent memory contradiction provenance` · `agent memory causal edges` ·
`decision outcome reinforcement agent` · `provenance ledger agent` ·
`episodic control` · `self model agent routing`

## 3. Audit chain for each relevant artifact

README claim → implementation → tests → benchmarks → commit history.

Questions: What fields are stored? What writes them? What reads them? Does
provenance change behavior or is it only logged? Can a correction overwrite a
terminal/committed state? How are conflicts handled? Are sources actually
independent (identity vs origin)? Are results reproduced by tests? What failed
before the current design?

## 4. Overlap classification

* terminology overlap only
* mechanism overlap
* experimental-question overlap
* same mechanism, different application
* same hypothesis already tested
* potential complementary work
* stronger prior result that changes our plan

## 5. Evidence grades

| Grade | Meaning |
|---|---|
| E0 | README / description only |
| E1 | implementation inspected; behavior matches claim |
| E2 | tests exist and assert the claimed behavior |
| E3 | reproducible benchmark or evaluation with reported results |
| E4 | peer-reviewed or independently replicated |

A README is a lead, not evidence. No inference is made about authors'
affiliations or publication status.

## 6. Scan log

### 2026-10-04 — Lineage A (correction authority)

Scholarly: arXiv:2606.24322, arXiv:2607.29167, arXiv:2609.01836,
arXiv:2606.04990 (verified by reviewer; see Lineage A prereg v1.1 §8).

Artifact: see §7 (audits of `gabe-santana/corollary`,
`JingxuanC/causal-memory`, `esaradev/icarus-memory-infra`).

## 7. Artifact audits — 2026-10-04 (Lineage A)

Code-level, read-only audits of shallow clones (only the latest commit was
visible in each). Load-bearing claims were spot-checked against source.
Scope: what the code does, not the authors' intent.

### gabe-santana/corollary (commit 3c25939; Python, ~5k LOC, ~290 tests; v0.1.0a4)

* **Mechanism:** Doyle-style truth maintenance. Beliefs are immutable
  revisions with source and justifications; `retract()` relabels dependents;
  old revisions are kept.
* **Corroboration:** noisy-OR over **origin groups**
  (`kernel.py:1727-1746`). Origin is caller-declared and defaults to the
  justification's own id. Same-source repeats do not stack (tested:
  `tests/test_confidence.py:36-46`, `:328-334`).
* **Gaps relative to Lineage A:**
  * N distinct ids from one undeclared upstream inflate corroboration. Its
    docs state "Tools are trusted to be what they say".
  * Agreement is credited as correctness in the trust ledger
    (`_credit_confirmation`, `kernel.py:1781-1794`), which is circular.
  * Every retraction is accepted; there is no terminal decision state and no
    rule requiring post-correction confirmation.
* **No evaluation** of correction validity, manufactured corroboration, or
  coverage.
* **Grade E2. Overlap:** mechanism overlap and complementary. Not the same
  hypothesis; not a stronger prior result. Its declared-origin noisy-OR is the
  same idea as A5 when origins are true, and behaves like A5n when they are
  not.

### JingxuanC/causal-memory (commit a248f3b; Rust, ~52.6k LOC, 460 tests; v0.9.3)

* **Mechanism:** facts, temporal state, and decision→outcome causal edges
  (caused / enabled / prevented); retirement via `valid_to` and
  `superseded_by`.
* **Supersession:** newest or polarity-flip wins, with no credibility check
  on the superseding record.
* **Provenance:** confidence comes from a declared label (`user_feedback` →
  0.95, `memory/ops.rs:101-106`). There is no source-independence model.
* **Q-learning:** in consolidation the reward is the constant 1.0 for
  salience-protected edges (`consolidate/mod.rs:96-115`).
* **Frozen predictions:** counterfactual predictions are logged before
  outcomes, missing outcomes stay pending, and ambiguous ones are excluded
  (`store/write.rs:1003-1090`). The ledger does not feed routing.
* **Its own adversarial evaluation:** planted false edges were corrected
  92–100% of the time only when later contradicting records arrived, and
  **0% with no counter-evidence** (`docs/evaluations/adversarial-injection.md`,
  scenario D). The refuter also flagged 71% of true edges.
* **Grade E3** (LLM-judged benchmarks, not deterministically reproducible
  here). **Overlap:**
  * independent confirmation of "lineage ≠ credibility": complementary;
  * terminology overlap only for source independence;
  * partial mechanism overlap with Lineage B's frozen-prediction receipts
    (worth citing).

### esaradev/icarus-memory-infra (commit 6e34870; Python, ~2.4k LOC + tests; v0.3.0)

* **Mechanism:** superseded-not-deleted lifecycle with `superseded_by` links,
  but old records are edited in place (`__init__.py:236-245`).
* **Authority:** newest-wins with no credibility gating; "sourced" means
  evidence/display fields only; no independence or corroboration logic.
* **Briefing:** LLM synthesis with a template fallback.
* **Grade E2** (mechanics tests only). **Overlap:** terminology plus partial
  mechanism; complementary; does not change the plan.

### Net effect on Lineage A

No artifact tests our hypothesis: correction authority gated by true
(origin-level, not identity-level) post-correction independence, evaluated
in risk–coverage space under terminal semantics. Two adjacent findings
support the question's relevance:

* causal-memory's 0% correction without counter-evidence;
* Corollary's self-declared-origin and agreement-as-success trust ledger,
  which is a concrete manufactured-corroboration surface.

Candidate additions (not adopted without reviewer approval): a
Corollary-style agreement-credited trust policy as an additional comparator
or attack target.
