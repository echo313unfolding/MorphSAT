# P3 Held-out Generator Audit (committed before generation)

Generator: `tools/gen_p3_heldout.py`. Procedure: `docs/P3_HELDOUT_CONSTRUCTION_PROCEDURE.md`
@ `ca394ff`. Frozen P3 code: `53c825b` (branch `claude/p3-heldout` adds only the
generator, held-out runner, this audit and receipts; no change to arbitration,
thresholds, retrieval, B0/B1/B2/B2M/B3, benign guard, DEFER semantics,
authority or scoring). Purpose: **closure experiment**, not an H2 rescue.

Disclosure: the author knows the P3 pilot result (`53c825b`). No choice below
is resolved using it. Resolutions use only the frozen procedure text, the frozen
code, or pre-outcome frozen artifacts (the P3 pilot runner `eb3f6d3`, committed
before the pilot ran).

## 1. Parameter-by-parameter audit

| ca394ff § | Parameter | Generator realization | Match |
|---|---|---|---|
| §2 | T: `check_ports, scan_file, check_process` × `CANONICAL_RESPONSES["escalate"]` | `T_TOOLS`, `block_tools("T")` | exact |
| §2 | B: `check_hash, check_process, check_ports` × `["benign"]` | `B_TOOLS` | exact |
| §2 | C: `check_hash, check_process, scan_file` × `CORRECTION_RESPONSES` | `C_TOOLS` | exact |
| §2 | M: `CANONICAL_RESPONSES["suspicious"][tool]`, 5 tools | `probe_sequences()` | exact |
| §2 | F: `("check_process", "Process check: Process running but context is ambiguous. No known-bad signatures.")` | `FILLER` | exact (byte-identical string) |
| §3 | 10 entity tokens | `ENTITIES` | exact |
| §3 | disjointness assertion vs pilot tags | `assert` in `build_runs()` (passes: no collision) | exact |
| §3 | 45 unordered pairs, lexicographic, round-robin in enumeration order | `itertools.combinations(sorted(...), 2)`, index `k % 45` | exact |
| §3 | alert templates | `ALERT`, `CORRECTION_ALERT` | exact |
| §4 | P1–P5 histories and ground truth | `PATTERNS` | exact |
| §5 | stratum A: 60 ordered 3-sequences, harness end after 3 (`bench_end`) | permutations of 3 of 5; bench forces `bench_end` | exact |
| §5 | stratum B: same 60 + 7 × F (10 tools) | `filler: 7` | exact |
| §5 | enumeration (A,B) × (P1..P5) × sequences; fresh stores per run | loop order; each run is its own bench family | exact |
| §6 | admission: frozen P3 monitor, `enable_defer=True`, B0; A ⇒ HARNESS_END; B ⇒ {STAGNATION, TOOL_BUDGET_EXHAUSTED, MAX_TOOLS} | `admit()` | exact |
| §6 | history DEFERs allowed (excluded as candidates by v2.1 A1) | no filtering on history | exact |
| §7 | dataset JSON written once; hash committed before B1–B3 | `__main__` prints sha256 | exact |

## 2. Underspecified items

| ID | Item | Material? | Resolution |
|---|---|---|---|
| U1 | Bench mode/components (SplitMemory, chain, graph, QUBO, echo) not named | **Potentially** (SplitMemory can alter monitor initialization across episodes in B/D/H/J) | Use the **pre-outcome frozen P3 runner convention** (`eb3f6d3`): all 9 modes, Mode A primary. Admission is computed **per mode**; each mode is evaluated on its own admitted set; all modes reported. Not derived from pilot outcomes. |
| U2 | "lexicographic tool order": `TOOL_NAMES` order vs sorted names | No — affects only enumeration order, hence only which inert entity pair a run receives (entities appear in no classifier keyword list and are compared only within a run) | Literal reading: sorted tool names. |
| U3 | `category` for history episodes (bench requires a value) | No — evaluation-only; not an input to admission, arbitration or the primary analysis | T→escalate, B→benign, C→benign; excluded from held-out metrics (probe-only reporting). |
| U4 | `has_correction_tools` | No — read only by the legacy echo path, which is disabled (canonical echo default) | Field omitted (no oracle field present). |
| U5 | Run/episode identifiers | No | `ho_{stratum}_{pattern}_{seq:02d}`, `_h{j}`, `_probe`. |
| U6 | Statistic for the closure question (posed after the pilot; not in ca394ff) | Analysis, not generation | Frozen in §3 below, before generation. |
| U7 | Probe admitted under B0 but not DEFER under another baseline (possible only via cross-episode SplitMemory feedback) | Reporting | Counted and reported; such probes are monitor-decided, not arbitrated. Cannot occur in Mode A (no cross-episode memory). |

No material choice remains unresolved by the procedure text or a pre-outcome
frozen artifact, so generation proceeds. If the reviewer rejects the U1
resolution, the dataset must be regenerated under an amendment.

**Structural property disclosed in advance (not an underspecification):** every
M response has threat ≥ safety, and every 3-sequence contains a response with
threat > safety, so every admitted probe has `balance > 0`. Under the frozen
benign guard, **no baseline can resolve any probe to `benign`.** Genuine-drift
(P3, ground truth benign) can therefore at best ABSTAIN. Discrimination between
P3 and P4 is possible only through COMMIT(escalate/suspicious) vs ABSTAIN.

## 3. Primary closure analysis (frozen before generation)

Question: can the information available to the frozen arbitration mechanism
distinguish genuine correction (P3) from false correction (P4) when probe
evidence is held constant?

For each mode, stratum and baseline, over **matched pairs** = probe sequence
indices admitted in both P3 and P4 (identical probe tool stream):

* score(out): COMMIT benign = −1; ABSTAIN = 0; COMMIT suspicious/escalate = +1.
* **correct-direction pair:** score(P4) > score(P3); **wrong-direction pair:**
  score(P4) < score(P3); **tie** otherwise.
* A baseline **discriminates** iff correct-direction pairs ≥ 1 and
  wrong-direction pairs = 0.
* For each discriminating baseline, identify the preregistered observable that
  differs between the matched P3 and P4 requests (slot projections, exclusions)
  and supplied the decision.

Fixed interpretation (from the reviewer's instruction):

* If **B3** (the causal-provenance/supersession baseline) does not
  discriminate, record that causal provenance/supersession is insufficient
  for correction validity in this architecture and **close the
  causal-history line for this harness**.
* If any baseline discriminates, do not promote H2/H3; name the observable and
  propose a separate experiment for that signal.

Also reported (procedure §7): all v2 §9 metrics per stratum × pattern ×
baseline (B0, B1, B2, B2M, B3), probe episodes only; admission counts per
stratum × pattern × reason; U7 counts.

## 4. Analytic expectation from the frozen code (stated before generation)

Derived from frozen rules and classifier outputs only (not from pilot
outcomes), assuming T/B/C history episodes commit their natural direction:

* P3 (T T C B): B3 excludes both T (superseded by C) → C, B benign 2/2 → benign
  guard blocks → ABSTAIN. B1/B2: 2–2 → ABSTAIN.
* P4 (T T C T): B3 excludes the first two T → C (benign), T (escalate) 1–1 →
  ABSTAIN. B1/B2: 3/4 escalate → COMMIT escalate.
* Expected: **B3 does not discriminate**; B1/B2 discriminate in the correct
  direction via the count of post-correction outcomes (a generic-evidence
  majority, not provenance). B2M depends on its hash mask.

The run tests this expectation; any deviation is reported, not explained away.
