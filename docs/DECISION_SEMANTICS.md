# MorphSAT Decision Semantics and Claim Status

Scope: public GitHub lineage `14689b7` → P1 `1524506` → P2A `275b946` →
P2B `0cf5fba` → P2C `7478602`. Nothing here describes private or unpushed work.
Receipts: `receipts/phase2_5_freeze/`, `receipts/p1_decision_event/`,
`receipts/p2_terminal_authority/`.

## 1. Primary finding (P2C)

> Canonical history exists but has **no lawful causal effect on final decisions**
> in the memory-stress harness. All modes (A, B, C, D, H, J, K, L, M) converge to
> **76/82**, false_safe 0. Earlier history-related gains were produced by
> post-terminal arbitration and contaminated CorrectionEcho semantics.

Supporting facts:

* At `14689b7`, A/B/C/D/J/K/L all scored 76/82: SplitMemory and ReceiptGraph
  produced **no net final-outcome benefit**. Only CorrectionEcho (Mode M, 78/82)
  changed net behavior.
* Mode M's +3 came entirely from the echo tiebreak converting **terminal ABSTAIN**
  into `benign` (`drift_05`, `drift_06`, `stale_03`); its −1 was a committed
  `escalate` downgraded to `suspicious` by QUBO acting on an echo-injected memory
  (`wc_03`). Echo provenance was partly oracle-derived (`has_correction_tools`)
  and hard-coded (`outcome_before = "escalate"`, fabricated for `ldc_06`) — C7.
* In this harness the monitor is **always terminal before downstream stages run**
  (natural terminal, or `_force_commit("bench_end")` at 3 tools). Every downstream
  effect on outcomes was therefore a post-terminal override.

## 2. Terminal semantics (since P2B)

| Action | Meaning | Terminal | Downstream may change it |
|---|---|---|---|
| CONTINUE | gather more evidence | no | — |
| COMMIT(direction) | substantive verdict | **yes** | **no** |
| ABSTAIN | insufficient grounds; direction is `None` | **yes** | **no** |
| SWARM_CALL | resolves as ABSTAIN (0 occurrences in the benchmark) | yes | no |

* `terminal_latched` (alias `committed`; receipt key `"committed"`) is set by ANY
  terminal action — it does not mean "a verdict was committed" (P2A).
* `morphsat/terminal_authority.py`: downstream stages (GateQUBO, TwoStageGate QUBO,
  CorrectionEcho tiebreak) only **propose**. A disagreeing proposal on a terminal
  result is **blocked** and kept as provenance (`attempted_*`). Applied overrides
  at P2C: 0 in all modes; attempts: H 27, J 3, M 4.
* The bench scores ABSTAIN as `suspicious` (`hard_abstain_required` expects
  `suspicious`). This is an **evaluation-only** projection (`evaluation.scored_as`).

## 3. Canonical DecisionEvent (schema v3)

One event per episode (`morphsat/decision_event.py`), built after all decisions:

* `monitor_*` — the monitor's proposal: **provenance**, not the outcome.
* `route_*`, `threshold_result`, `qubo_result`, `echo_*` — downstream stages.
* `attempted_*`, `override_blocked_by_terminal` — disagreeing proposals.
* `final_action`, `final_direction` — the **canonical emitted outcome**; the only
  answer to "what did the system do". `final_direction` is `None` for ABSTAIN.
* `outcome_ref` — hash of the canonical outcome core; every store write carries it.
* `stores` — read-back of what each store actually recorded.
* `evaluation` — ground truth and scoring (benchmark only; never an input).
* `e10_observed` — preregistered dead observables (`drift_like`,
  `stale_memory_like`, `poisoned_memory_like`, `sensor_graph_conflict`,
  `routing_triggered`); inverting them must not change behavior (tested).
* Canonical hash: SHA256 over semantic content only (no timestamps/PIDs/paths).

## 4. Store projections (P2C, `morphsat/history_projection.py`)

| Emitted outcome | SplitMemory | ReceiptGraph node | CorrectionEcho |
|---|---|---|---|
| COMMIT benign | tolerance | `benign` | marker if correction detected |
| COMMIT suspicious/escalate | threat | same label | marker if correction detected |
| ABSTAIN | abstain | `abstain` (non-directional) | no marker |
| ABSTAIN via SWARM | none | `handoff` (non-directional) | no marker |
| CONTINUE | none | `unknown` (non-directional) | no marker |

* Before P2C, every ABSTAIN was stored as `suspicious` in the **threat** store
  (C10), and as `null` in the graph — which counted as a directional vote.
* CorrectionEcho (P2C): correction detected from the system's own evidence;
  `outcome_before` from its own prior canonical outcome; no marker from an
  echo-influenced episode; echo-produced outcomes never used as prior evidence.
* Legacy entry points (`record_episode`, `close_episode` without
  `canonical_outcome`, `observe_episode`) are retained for the LLM benches.

## 5. Claim corrections (P2D)

| Claim | Status | Provenance |
|---|---|---|
| "Strange loop closure" (code docstrings, README, docs) | **Unsupported**; replaced by "memory feedback loop". Receipt → memory → future posture is ordinary feedback; no level-crossing exists. | `631b62d` (v7), v6 `commit_gate.py` |
| Mode M 98.6% vs 95.1% | Different versions: 98.6% (71/72) at `3c59918` (8 families); 95.1% (78/82) at `c8f8c17` (+ `wrong_correction`). Reproduced 95.1% at `14689b7`. **76/82 at P2C.** | commit messages `3c59918`, `c8f8c17` |
| old_guy_helped 0/72 vs 0/82 | Same cause; 0/82 reproduced at `14689b7`. | as above |
| "The model never sees the governor's state" | **False** for `gate_assists` (`tools/bench_gate_authority.py`) and all v8.1 conditions (`tools/bench_gate_authority_v81.py`): `_summarize_evidence` puts posture state and threat/safety scores in the prompt (added `9a7c121`). `commit_prompt_a` reveals commit direction coarsely. True only that posture is not shown by default and the model cannot override the boundary. | `9a7c121` |
| "Irreversible decision authority" | Held for the model; **not** for downstream harness stages until P2B. Since P2B COMMIT/ABSTAIN are terminal for all stages. | P2B receipt |
| CorrectionEcho test "has no override mechanism" | Was false at `3c59918` (tiebreak set verdicts). Since P2B the echo cannot change a terminal outcome. | `3c59918`, P2B |
| Package version 0.4.0 (pyproject) vs 0.5.0 (`__init__`) | Fixed to 0.5.0: `d593ce9` explicitly records "Version bump: 0.4.0 → 0.5.0" but missed `pyproject.toml`. The PyPI note in `morphsat_technical_note.md` (v0.4.0) describes what was published and is left unchanged (not verifiable here). | `d593ce9` |

## 6. Hypothesis status (P2C)

* H1 (extra memory): no demonstrated net final-outcome benefit.
* H2 (control/gain): the only observed history effects on outcomes were
  post-terminal overrides, now blocked. History currently has no lawful path to
  a decision.
* H3 (current-state self-model): unsupported.
* H4a (history model): canonical self-history now exists, but cannot be tested
  until a legitimate **pre-terminal** path exists (planned: DEFER → ARBITRATION).
* No strange-loop claim is made.
