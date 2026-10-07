# Lineage B1 — §7b validation run 1: FAILED at V0-runtime (2026-10-07)

* **Implementation tested:** `3877889` (clean tree).
* **Prereg references:** `2473c2a`, `f4f5990`, `1e8bd91`.
* **Root:** 2026100517000, the only root opened.
* **Receipt:** `receipts/lineage_b1/b1_validation_FAILED_20261007T163340Z.json`
  (sha256 `082404d931b99b9725cfabd74785c8985667739bca99065fabd4642577d401d0`).
* This was the first seeded execution of the B1 implementation lineage. It
  ran once, with no code changed before it, and it is preserved as evidence.

| Check | Result | Time |
|---|---|---|
| V0-static | PASS (`predictor.py` = `94f4f11`, no foreign predictive definitions) | 0.3 s |
| V0-runtime | **FAIL**: `RuntimeError: pass 2 diverged from the log at (0, 0)` | 9.4 s |
| gate 7, gate 11, gate 12 | not run (the runner stops at the first failure) | — |

The sizing root (2026100516000) and the confirmatory root (2026100514000)
were not touched. No cost, safety, variance or SV quantity was computed.

## Cause (identified by reading code; nothing re-run)

`lineage_b.world.make_streams(seed_seq)` calls `seed_seq.spawn(16)`. NumPy's
`SeedSequence.spawn` is **stateful**: each call advances
`n_children_spawned`. A second `make_streams` on the *same* SeedSequence
object therefore yields different streams. Shown on an arbitrary,
non-reserved seed, with no simulation: `SeedSequence(123)` gives spawn keys
(0,)(1,)(2,) on the first spawn and (3,)(4,)(5,) on the second.

B1 reuses each episode's SeedSequence object:
* pass 1 (`b1_protocol.py:220`);
* pass 2 (`make_streams((world_eps or eps)[ep])`);
* each arm's evaluation (`b1_protocol.py:368`, `:378`);
* the validation decision-path replays (`b1_validation.py:139`, `:206`,
  `:214`, `:272`).

Consequences:
1. **Pass 2 re-ran a different world.** The divergence assertion caught
   this at the first step, as intended.
2. **Evaluation would not have used common random numbers.** Each arm's
   evaluation episode would have drawn a later spawn, silently breaking the
   pairing that every paired criterion relies on. No assertion would have
   caught this one.
3. **The B0 gate-17 pilot (`gates.py:574`, `:582`) has the same pattern.**
   G0's evaluation episodes used the first spawn of `eps[5..9]` and REF-S
   the second. G0 and REF-S were therefore **not** on common random numbers
   in the pilot. Their per-condition means remain unbiased estimates, but
   the G0 − REF-S gap behind Δ* = 1.737 J and δ_null = 0.8876 J came from
   unpaired noise. B0's other gates create a fresh SeedSequence per call
   and are unaffected. B0 and its receipts are not modified here; this is
   recorded for the user's decision.

## Status

* §7b FAILED and the run is stopped.
* No patch was applied.
* Any correction needs a new disclosed amendment and implementation commit,
  then a re-run of §7b on root 2026100517000.
