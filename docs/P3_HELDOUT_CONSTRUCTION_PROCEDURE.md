# P3 Held-out Scenario Construction Procedure (frozen)

Status: **frozen procedure**, committed before any P3 arbitration outcome is
computed (pilot or held-out). Required by P3 preregistration v2 §10 and v2.1 A5.
The generator implemented later (`tools/gen_p3_heldout.py`) must follow this
document exactly; it has no free parameters. Any deviation requires an amendment
committed **before** the held-out set is generated, stating that it was written
without access to held-out arbitration outcomes. The pilot's per-episode wins or
losses must not influence any choice below.

## 1. Design principle

Within a stratum, every history pattern is paired with the **same probe
evidence**. Only the history differs. A correct DEFER resolution can therefore
come only from history, never from probe evidence that already encodes the
label.

## 2. Building blocks (from `tools/bench_memory_stress.py`, unchanged)

* Threat episode `T`: `check_ports`, `scan_file`, `check_process` with
  `CANONICAL_RESPONSES["escalate"]`.
* Benign episode `B`: `check_hash`, `check_process`, `check_ports` with
  `CANONICAL_RESPONSES["benign"]`.
* Correction episode `C`: `check_hash`, `check_process`, `scan_file` with
  `CORRECTION_RESPONSES`.
* Probe menu `M`: the 5 responses `CANONICAL_RESPONSES["suspicious"][tool]` for
  `TOOL_NAMES` (`check_hash`, `check_process`, `check_ports`, `scan_file`,
  `search_cve`).
* Stagnation filler `F`: `("check_process", "Process check: Process running but
  context is ambiguous. No known-bad signatures.")`.

## 3. Entities and alert text

* Entity vocabulary (fixed, 10 tokens, alphabetic, length > 3; the generator
  asserts disjointness from every pilot alert tag): `zephyrhost`, `quillnode`,
  `marrowbox`, `tundraweb`, `cobaltgate`, `lumenrack`, `vesperdb`, `orchidmq`,
  `basaltapi`, `fernlogic`.
* Each run uses one entity pair `(e1, e2)`, assigned round-robin over the 45
  unordered pairs in lexicographic order, in run-enumeration order (§5).
* Alerts: history/probe `f"Alert {e1} {e2} activity flagged for review"`;
  correction `f"CORRECTION {e1} {e2} prior alert reassessed by analyst"`.
  All episodes in a run share both entity tokens (tag overlap ≥ 2 by
  construction).

## 4. History patterns (length 4) and generator ground truth

| Pattern | History | Probe ground truth (generator semantics) |
|---|---|---|
| P1 stable threat | T T T T | escalate |
| P2 stable benign | B B B B | benign |
| P3 genuine drift | T T C B | benign |
| P4 false correction | T T C T | escalate |
| P5 mixed | T B T B | suspicious |

Ground truth is a **generator assumption**, fixed here; it is evaluation-only
and never enters the system. P4 is the adversarial cell (a correction followed by
renewed threat evidence).

## 5. Strata and enumeration

* **Stratum A — externally closed DEFER (HARNESS_END).** Probe tool stream =
  each ordered 3-sequence of distinct `M` responses (5·4·3 = 60 sequences),
  harness end after 3 tools (`bench_end`).
* **Stratum B — endogenous DEFER.** Probe tool stream = the same 60 3-sequences
  followed by 7 × `F` (10 tools; harness end not reached before the monitor's
  own budget/stagnation/max-tools rules fire).
* Runs = 5 patterns × 60 probe sequences per stratum = 300 per stratum, 600
  total, enumerated in order (stratum A, B) × (P1..P5) × (sequences in
  lexicographic tool order). Each run uses fresh stores (memory, chain, graph,
  canonical history).

## 6. Admission filter (label-free, arbitration-free)

Run the frozen P3 monitor (`enable_defer=True`) with the **B0** baseline only.
Admit a run iff its probe produces DEFER whose `reason_for_defer` is HARNESS_END
(stratum A) or ∈ {STAGNATION, TOOL_BUDGET_EXHAUSTED, MAX_TOOLS} (stratum B).
History episodes that themselves DEFER are allowed (they become
arbitration-resolved and are excluded as candidates by v2.1 A1). Report counts
admitted/rejected per stratum × pattern and per DEFER reason. No size target;
all admitted runs are used. Ground truth and arbitration outcomes are not
consulted.

## 7. Freezing and evaluation

* The generated set (all runs, admitted flags, entity pairs, tool streams) is
  written as JSON; its SHA256 is committed **before** any B1/B2/B2M/B3
  arbitration is run on it.
* Evaluation uses exactly the P3 v2/v2.1 rules, thresholds and H2 criteria,
  reported per stratum and per pattern.
* Stratum A results alone do not show that the architecture naturally discovers
  when to defer; stratum B is required for that claim.
