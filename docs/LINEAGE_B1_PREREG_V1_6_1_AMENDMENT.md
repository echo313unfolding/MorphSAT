# Lineage B1 — v1.6.1 PRE-VALIDATION RUN-CONTROL AMENDMENT

**Status: binding amendment.** Preserved unchanged:
* sizing-design freeze `2473c2a`;
* all prior amendments through v1.6 `58653eb`;
* all prior implementation commits through `662a8ed`;
* all prior receipts (including v1.5.x sizing-attempt-1 evidence).

No v1.6 validation or sizing root has been touched. The v1.5.x sizing
attempt 1 remains permanently consumed at root `2026100516000`. No
scientific design, hypothesis, arm, epsilon, sham rule, SV threshold,
endpoint, margin, sizing formula, or analysis is changed.

## Problem

`b1_runctl.require_one_shot(prefix)` blocks on **any** historical receipt
whose filename starts with the given prefix:

```python
def require_one_shot(prefix):
    found = existing_receipts(prefix)
    if found:
        raise SystemExit(...)
```

The sizing runner calls `rc.require_one_shot("b1_sizing")`. But the
repository permanently contains the v1.5.x sizing-attempt-1 receipts from
consumed root `2026100516000`:

* `b1_sizing_STARTED_20261009T163712Z.json`
* `b1_sizing_STOPPED_20261009T181653Z.json`

Therefore a future v1.6 sizing execution on the new root `2026100519000`
would be rejected before opening that root. The same issue applies to the
confirmatory runner.

This is a run-control namespace bug, not a scientific-design failure.

## Binding rule (v1.6.1)

> **One-shot identity is `(receipt family, seed root)`, not receipt-family
> name globally.** Historical receipts from a permanently disjoint root must
> remain visible evidence but must not consume a newly preregistered root.

## Corrective implementation

`require_one_shot(prefix, root)` now:

1. Reads every historical receipt matching the prefix.
2. Fails closed (raises `SystemExit`) on any receipt that cannot be parsed
   as valid JSON — an unreadable receipt is never silently ignored.
3. Blocks only if a receipt's `"root"` field matches the current root.
4. Receipts from other roots remain preserved and are not consumed.

The sizing runner passes `ROOTS["sizing"]` (2026100519000). The
confirmatory runner passes `ROOTS["confirmatory"]` (2026100514000).
Validation has no one-shot guard (re-validation after disclosed correction
is explicitly permitted).

## What is NOT changed

Everything listed as unchanged in the v1.6 amendment, plus:

* `B1_LOGGING_EPSILON = 0.5`
* Validation root `2026100518000`
* Sizing root `2026100519000`
* Confirmatory root `2026100514000`
* All existing receipts (byte-identical)
* Validation procedure (no one-shot guard added)
