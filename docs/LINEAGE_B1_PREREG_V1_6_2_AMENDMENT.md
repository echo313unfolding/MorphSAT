# Lineage B1 — v1.6.2 PRE-VALIDATION RUN-CONTROL HARDENING AMENDMENT

**Status: binding amendment.** Preserved unchanged:
* all prior amendments through v1.6.1 `4ca95b6`;
* all prior implementation commits through `5e04425`;
* all prior receipts.

No validation, sizing or confirmatory root has been touched.

## Problem

The v1.6.1 root-scoped `require_one_shot` parses receipt JSON and checks
`payload.get("root") == root`. A syntactically valid receipt that lacks a
`"root"` field, or whose `"root"` is not an integer, is silently ignored.
Missing provenance must not be interpreted as evidence that the receipt
belongs to another root.

## Binding rule (v1.6.2)

> **Every historical receipt in a one-shot family must carry a valid integer
> `root` field.** A receipt with missing, null, or non-integer `root` causes
> fail-closed rejection. `type(root) is int` is required (not
> `isinstance(..., int)`) so that JSON booleans cannot masquerade as integer
> roots.

## What is NOT changed

Everything listed as unchanged in the v1.6 and v1.6.1 amendments.
