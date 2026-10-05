# Lineage B0 — Tank/Valve Simulator Validity: Preregistration v1.0 (CANDIDATE)

Status: **candidate; not frozen.** No Lineage B code exists. Scope: public
GitHub lineage of `14689b7`. Supersedes nothing. It builds on
`docs/LINEAGE_B_GROUNDED_FEEDBACK_SCOPING.md` (`965ec90`) and `_V1_1.md`,
decisions B-U1–B-U7. Branch `claude/lineage-b-prereg`.

**B0 makes no adaptive-learning or feedback-policy claim.** Its only output
is a frozen simulator plus a validity receipt. B1 outcomes may not exist
before the B0 implementation and validity receipts are committed.

Standing inputs from Lineage A / A4V (`1fe9b0a`): `upstream_id` is
provenance metadata only. The within-pattern shuffle sham did not reliably
destroy dependence. Every B sham must pass a structural validity gate
before outcomes (gate 13).

## 1. Separation (invariant, from scoping v1.1 §2)

```
Z_t      hidden evaluator state          evaluator only
X_t      agent-visible observation set   sensors + channel → agent
Ô_{t+1}  frozen probabilistic prediction hashed and committed BEFORE T runs
O_{t+1}  subsequent sensor observations  delivered through the channel
```

Packages (isolated from the MorphSAT runtime, like `lineage_a/`):

| Module | Side | May import |
|---|---|---|
| `lineage_b/world.py` (Z, T) | evaluator | stdlib, numpy |
| `lineage_b/sensors.py`, `channel.py` | evaluator | world |
| `lineage_b/obs.py` (Observation, Provenance types) | shared | stdlib only |
| `lineage_b/receipts.py` (commit store) | shared | stdlib, hashlib |
| `lineage_b/agent/*` | agent | `obs`, `receipts`, `morphsat.terminal_authority` |
| `lineage_b/evaluate.py` | evaluator | all |

## 2. Hidden state Z_t

| Component | Domain | Notes |
|---|---|---|
| level `h` | [0, H_max] m | spill above H_max is recorded as spill flow |
| inflow `q_in` | ≥ 0 | AR(1): `q_in' = q̄ + φ(q_in − q̄) + η`, clipped at 0 |
| valve position `u` | {0, .25, .5, .75, 1} | actual position; equals the commanded position (no valve fault in v1) |
| leak `ℓ` | {none, slow, fast} | onset hazard per step; repair after inspection (§4) |
| sensor / ADC fault states | per component | frozen per condition (§5) |

## 3. Transition T (explicit Euler, exact discrete form)

```
q_out  = Cv · u · sqrt(max(h, 0))
q_leak = k(ℓ) · sqrt(max(h, 0))            k(none)=0, k(slow), k(fast)
h_raw  = h + (dt / A) · (q_in − q_out − q_leak) + w,   w ~ N(0, σ_w²)
h'     = clip(h_raw, 0, H_max)
spill  = A · max(h_raw − H_max, 0) / dt;   shortfall = A · max(−h_raw, 0) / dt   (both recorded)
```

Actions: `open` → u + 0.25, `close` → u − 0.25 (clipped to [0, 1]); `hold`
and `inspect` leave `u`. `inspect` produces an inspection report (§4).

## 4. Inspection

`inspect` at step t yields an agent-visible report at t+1:
`LEAK_FOUND` / `NO_LEAK`. It has frozen error rates (miss `e_m`, false
alarm `e_f`). A true positive starts repair: the leak stops after `R_rep`
steps. Inspection reports are observations, never hidden-state access.

## 5. Sensors and channel

| Sensor | Upstream (ADC / feed) | Model |
|---|---|---|
| L1 | ADC_A | `h + ε_A + ε_1` |
| L2 | ADC_A | `h + ε_A + ε_2` (ε_A shared with L1, same draw) |
| L3 | ADC_B | `h + ε_3` (independent) |
| F (outlet flow) | FEED_F | `q_out + ε_F` |
| P (bottom pressure, kPa) | ADC_C | `ρ g h / 1000 + ε_P` |
| L4 (alias, condition C3 only) | relay of L1 | exact copy of L1's delivered value under a distinct `sensor_id` |

Every delivered record carries `sensor_id`, `seq`, `measured_at`,
`delivered_at`, `value | MISSING`, and agent-visible provenance
`{sensor_id, declared_upstream}`. `declared_upstream` is visible metadata.
Only arm G3 is allowed to *use* it (B1 §3).

**Channel.**
* Per-sensor delay `d ~` frozen distribution.
* Dropout with probability `p_drop`, MCAR in v1: independent of value and
  state. MNAR is out of scope and flagged.
* Transport redelivery: the same `(sensor_id, seq)` is delivered twice.
* Alias copies (L4).

**Agent-visible status per sensor and measurement time:**
* `VALUE(v)`;
* `PENDING` (not yet received, age ≤ `D_max`);
* `MISSING` (timeout after `D_max`; reached either by drop or by delay
  beyond `D_max`). The agent cannot distinguish the two; the evaluator can.

**Frozen nonadaptive corruption** (onset step and parameters fixed per
condition): stuck-at, bias `+b`, drift `+δ·(t − t_f)`, noise inflation
`σ×k`, dropout. An ADC fault applies to every sensor on that ADC
simultaneously.

**RNG.** Independent seeded substreams are spawned from one root seed via
`numpy.random.SeedSequence`, one each for: inflow noise, process noise, leak
process, each ε (including ε_A), inspection errors, channel delay and drop,
and the logging-policy randomization. Exogenous draws therefore do not
depend on actions (common random numbers across arms).

## 6. Conditions (sensor-fault configurations, shared with B1)

| ID | Condition | Faults |
|---|---|---|
| C0 | nominal | none |
| C1 | independent fault | L3 stuck-at from `t_f` |
| C2 | shared-upstream fault | ADC_A bias `+b_A` from `t_f` (L1 and L2 together) |
| C3 | duplicated reports | L1 drift `δ` from `t_f`, plus relay alias L4 = copy of L1 |
| C4 | corrupt non-level sensors | P noise ×`k_P`, F bias `+b_F`, from `t_f` |
| C5 | delayed / missing | L3 delay `~ Geom(mean d̄)`, dropout L1/L2 `p₁`, P `p₂`; no value faults |

The leak process runs in every condition.

## 7. Validity gates (all must pass; a failure stops B0, no B1 run)

User-specified gates 1–12; proposed additional gates 13–17 are marked (P).

| # | Gate | Test (exact) |
|---|---|---|
| 1 | Mass balance / transition correct | With `w = 0`, per step: `A·(h' − h) = dt·(q_in − q_out − q_leak − spill + shortfall)` holds within 1e-12, where `shortfall = A·max(−h_raw, 0)/dt` is the recorded volume the clip at 0 adds back. Both clip branches are covered. Hand-computed fixtures cover valve closed with constant inflow (linear rise), drain only (discrete Torricelli recursion), leak only, and overflow. |
| 2 | Deterministic replay | Same `(seed, config, action sequence)` → byte-identical hashes of the Z trajectory and of the delivered observation stream (3 seeds × 6 conditions). |
| 2b (P) | Common random numbers | Two different action sequences from one seed → identical exogenous draws (inflow noise, every ε, channel) step for step. |
| 3 | Actions change later state | From identical states and seeds, `open`×k vs `close`×k changes `h` at t+k by ≥ `Δ_min3`. The one-step effect of `open` vs `close` on E[L3] is reported in units of L3 noise σ. |
| 4 | Shared-upstream dependence as specified | Over N draws: corr(ε-errors of L1, L2) = `σ_A²/(σ_A²+σ_i²)` within ±3 SE. Under an ADC_A fault, L1 and L2 are affected at the same steps with the same offset. |
| 5 | No accidental shared noise | Every pair other than (L1, L2) and (L1, L4): |corr| ≤ 3/√N. Structurally, every sensor uses a distinct SeedSequence spawn key, except the specified sharing. |
| 6 | Missing/delayed explicit, never success | Status is always one of VALUE/PENDING/MISSING. No code path maps PENDING/MISSING to a value or to a reward or credibility increase. A unit test feeds all-MISSING streams; every agent-side update is a no-op and is logged. |
| 7 | Hidden state never agent-visible | (a) AST: `agent/*` imports only `obs`, `receipts`, `morphsat.terminal_authority`. (b) `Observation` has no hidden fields. (c) Metamorphic: two different Z trajectories engineered to yield identical delivered observation streams → identical agent decisions, predictions, memory and θ (hash equality). (d) Sentinel: evaluator fields poisoned with NaN do not change agent outputs. |
| 8 | Prediction hash committed before transition | `world.step(action, commitment)` raises unless a receipt for `(episode, t+1)` is committed. The receipt store is append-only and hash-chained. The commit's logical clock is strictly before the transition's. Scoring verifies the hash. |
| 9 | DecisionEvents immutable | `ControlDecisionEvent` is a frozen dataclass with a canonical hash. The store is append-only. Read-back hashes are equal after a full B1-style run including updates. Attempted mutation raises. |
| 10 | Logging propensities correct | For μ (B1 §5): propensities sum to 1 over the lawful set. The empirical action frequency over ≥ 10⁵ seeded draws matches the recorded propensities (χ² p ≥ 0.001 per context class). Interlock and terminal-ABSTAIN steps record propensity 1 and are flagged as non-randomized. |
| 11 | Updates only affect future lawful routing/arbitration | Decision at t records `theta_hash` = version built only from receipts scored before t. Changing any observation after t leaves decisions ≤ t identical. Metamorphic: θ randomized → interlock and terminal-ABSTAIN outputs identical. |
| 12 | Terminal authority untouched | `morphsat/terminal_authority.py` byte-identical to `14689b7`. Every step's final action passes through `resolve_terminal_authority`. Arbitration resolves only DEFER, and only to COMMIT/ABSTAIN. Interlock COMMITs are never altered. |
| 13 (P) | Sham validity, structural, before outcomes | B1's action-scrambled sham G2-S: mean KL(Ô_true ‖ Ô_scrambled) over μ-logged steps ≥ `κ` in every condition. Otherwise the sham cannot detect action-conditioning, and B1 must not run with it. |
| 14 (P) | Transport duplicates never double-count | Redelivered `(sensor_id, seq)` enters fusion and updates exactly once, in every arm. |
| 15 (P) | Fault semantics | Each fault mode reproduces its specification at its onset step (fixtures). |
| 16 (P) | Evaluator metrics | Cost, unsafe-transition, false-safe and REF reference actions are unit-tested on hand-built trajectories. |
| 17 (P) | G0-only variance pilot (for B-U7) | Fixed policy G0 and REF only, on seeds disjoint from B1's, estimating var(J) per condition for sample size. No G1/G2/G3 run, no contrast computed. |

## 8. Freeze procedure

1. Freeze this document after your edits (v1.x).
2. Implement; commit before running any gate.
3. Run gates and write `receipts/lineage_b0/validity_<ts>.json` (with the
   config hash, the seed-list hash and the source sha256 of every B module).
4. Commit the receipts and record failures, if any, as with the Lineage A
   and A4V aborts.
5. Only then may the B1 prereg be frozen and B1 code run. Any later
   simulator change invalidates B0 and requires a new B0 receipt.

## 9. Threats (stated before implementation)

* **T-B1 Designer-determined results.** Which faults are identifiable from
  dynamics or from cross-physics references (flow, pressure) is set here.
  B1 outcomes are conditional on these choices. B1 §8 states expectations in
  advance so that a design property is not read as a discovery.
* **T-B2 MCAR missingness** is easier than reality. MNAR is a later stress
  test.
* **T-B3 Agent nominal model.** The agent's physics model uses nominal
  parameters (B1 §2). Model mismatch other than leaks and sensor faults is
  absent in v1.
