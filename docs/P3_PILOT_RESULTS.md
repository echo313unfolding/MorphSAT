# P3 Pilot Results — DEFER → ARBITRATION

Preregistration: v2 (`e4bc7d9`) + v2.1 (`d89837a`); held-out procedure
(`ca394ff`). Implementation frozen before the run (`eb3f6d3`; observational
event-builder fix `e0348b0`, made after a crash that printed no result).
Receipt: `receipts/p3_pilot/p3_pilot_20261004T190312Z.json` (sha256 prefix `c2aacd633b3d30a0`). Scope: public GitHub lineage of
`14689b7`. No rule, threshold or baseline was changed after the run.

## Verdict (primary mode A; all 9 modes give identical nets)

* **Run valid:** B0 finals and metrics identical to P2D; terminal-invariant
  violations 0; final DEFER 0; leakage, prefix-invariance and E10 tests pass.
* **H0 (history irrelevant): supported** — net(B3) = 0.
* **H1 (generic memory): not supported** — net(B1) = 0.
* **H2 (causal-history effect): fails.** **Critical falsifier triggered:** in
  this harness, canonical causal history does not improve DEFER arbitration
  beyond a matched generic-memory baseline. Preserved as the P3 result.
* Ladder: B1>B0 no · B2>B1 no · B3>B2 no. B2M diagnostic: net 1 (> B3).

## Metrics (19 DEFER: 18 HARNESS_END, 1 STAGNATION; 6 history-eligible)

| | commits | correct | wrong | net | selective risk | coverage | abstention | false_safe | unsafe | against lean |
|---|---|---|---|---|---|---|---|---|---|---|
| B0 | 0 | 0 | 0 | 0 | — | 0.00 | 1.00 | 0 | 0 | 0 |
| B1 | 4 | 2 | 2 | 0 | 0.50 | 0.67 | 0.79 | 0 | 0 | 2 |
| B2 | 4 | 2 | 2 | 0 | 0.50 | 0.67 | 0.79 | 0 | 0 | 2 |
| B2M | 1 | 1 | 0 | 1 | 0.00 | 0.17 | 0.95 | 0 | 0 | 1 |
| B3 | 0 | 0 | 0 | 0 | — | 0.00 | 1.00 | 0 | 0 | 0 |

Stratified: B1/B2 HARNESS_END net −1 (drift_05, drift_06 wrong; wc_05
correct), STAGNATION net +1 (wc_04 correct). B3 0/0 in both strata.

## Mechanism (descriptive; not used to revise anything)

* **B1 ≡ B2 on every request.** In this benchmark every history slot's
  canonical outcome equals its evidence lean, so the agent's prior decisions
  carry no information beyond generic evidence memory. B2 > B1 is
  structurally untestable here.
* **B3 supersession identified stale history but could not act on it.** In
  drift_05, drift_06 and stale_03 it removed the stale escalate records that
  made B1/B2 commit wrongly, leaving one benign vote (< 2) → ABSTAIN. In
  wc_04/wc_05 (false correction) the same rule removed the correct escalate
  records → ABSTAIN, losing B1/B2's two correct resolutions. Net effect:
  two wrong and two correct commits converted into abstentions (net 0,
  selective risk undefined). Supersession cannot distinguish a genuine from a
  false correction — the limitation already recorded at `c8f8c17`.
* **B2M** (noncausal mask) kept two escalate votes in wc_05 by chance → one
  correct commit. B3 > B2M is false; the pilot gives no evidence that
  causally identifying which history to suppress helps.

## Interpretation limits

* 18/19 DEFERs are externally induced (3-tool harness closure); only wc_04 is
  endogenous. This pilot says nothing about naturally occurring deferral.
* At most 6 eligible requests: the null is a valid falsification in this
  harness, not evidence about other harnesses.
* The frozen held-out procedure has not been run.
