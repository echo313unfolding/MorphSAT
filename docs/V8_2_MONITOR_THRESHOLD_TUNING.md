# v8.2 Monitor Threshold Tuning

## Root cause found: evidence classifier bug

### The bug

`classify_tool_result` (commit_gate.py:293) matches keyword `"yara"` in the
tool result text. But `simulate_tool` prefixes YARA scan results with
"YARA scan {path}:" — every scan_file response contains the word "YARA"
regardless of whether a YARA rule actually matched.

```python
# Line 293 - matches "yara" or "suspicious_packer"
if any(kw in text_lower for kw in ["yara", "suspicious_packer"]):
    return "yara_match", THREAT_SIGNALS["yara_match"], 0.0  # +0.35 threat
```

Result: **all three scan_file responses** (escalate, suspicious, benign) classify
as `yara_match` (+0.35 threat), because "YARA" appears in all of them as the
tool name prefix.

### Impact trace

For suspicious scenarios, the model calls 4 tools. The threat/safety scores
accumulate:

```
Tool 1 (check_hash):    t=0.20 s=0.00  (not_in_known_good)
Tool 2 (check_process): t=0.25 s=0.05  (ambiguous)
Tool 3 (check_ports):   t=0.35 s=0.10  (moderate_signal)
Tool 4 (scan_file):     t=0.70 s=0.10  (yara_match ← BUG, should be ~0.50)
```

After tool 4, `threat_score=0.70 >= escalate_threat=0.55` fires ESCALATE_READY.
Without the bug, `threat_score=0.50 < 0.55` → direction would be `suspicious`.

This explains:
- **pioc_04, time_04, time_06**: monitor fires escalate for suspicious
- **pioc_05**: if the model calls a different tool sequence that avoids scan_file
  (or calls fewer tools before the monitor commits), the bug doesn't trigger

### Why pioc_05 survives

pioc_05 gets the correct direction (suspicious, commit_ready) despite having
identical tool responses. The difference must be in the model's tool call
sequence — it likely doesn't call scan_file, or the monitor commits before
scan_file is called based on earlier evidence pattern.

### The benign scan_file bug

The benign scan_file response also triggers yara_match:
```
"YARA scan /tmp/file: No matches. File is signed and in package database."
```
"YARA" matches → +0.35 threat. But for benign scenarios, enough safety signals
accumulate from other tools (baseline_match, known_good, signed_binary) to
overcome the false threat, and the monitor normalizes before scan_file matters.

## Fix

### Option A: Fix the keyword match (targeted)

Change the yara keyword check to match on the RESULT content, not the tool
name prefix:

```python
# Before (buggy):
if any(kw in text_lower for kw in ["yara", "suspicious_packer"]):

# After (fixed):
if any(kw in text_lower for kw in ["suspicious_packer", "yara match", "yara: match"]):
```

This only fires when a YARA rule actually matched, not when the tool name
appears in the output.

### Option B: Fix the tool response format (upstream)

Change `simulate_tool` to not include "YARA" in the response prefix:

```python
# Before:
return f"YARA scan {path}: No rule match. ..."
# After:
return f"File scan {path}: No YARA rule match. ..."
```

### Option C: Add "no match" short-circuit (defense in depth)

Before the yara check, add an explicit "no match" check:

```python
if any(kw in text_lower for kw in ["no rule match", "no matches", "no yara"]):
    # YARA tool ran but found nothing — this is a clean/ambiguous signal
    if "not signed" in text_lower or "unsigned" in text_lower:
        return "unsigned", THREAT_SIGNALS["unsigned"], 0.0
    elif "signed" in text_lower and "package" in text_lower:
        return "signed_binary", 0.0, SAFETY_SIGNALS["signed_binary"]
    else:
        return "clean", 0.0, SAFETY_SIGNALS["clean"]
```

### Recommended: Option A + C (belt and suspenders)

Option A fixes the keyword. Option C adds defense-in-depth for "no match"
results. Option B is a simulation change that masks the classifier bug.

## Experiment design

**This is NOT a threshold tuning experiment anymore.** It's a bug fix followed
by a verification run.

### Phase 1: Fix and verify locally

1. Apply Option A + C to `commit_gate.py`
2. Run unit test: verify suspicious scan_file no longer classifies as yara_match
3. Run unit test: verify escalate scan_file STILL classifies as yara_match
4. Run unit test: verify benign scan_file classifies as signed_binary

### Phase 2: Re-run v8 gate_assists with fix

Re-run v8's gate_assists condition (C) with the fixed classifier:

```
bench_gate_authority.py --port 8085  # same 20 scenarios
```

Compare to v8 results. Expected changes:
- pioc_04: suspicious→suspicious (RECOVERED if model doesn't independently escalate)
- time_04: suspicious→suspicious (RECOVERED if model doesn't independently escalate)
- time_06: suspicious→suspicious (RECOVERED — model was right when unprompted)
- supply_01: still wrong (monitor never reaches commit — separate issue)
- All escalate scenarios: unchanged (yara_match still fires for real matches)
- All benign scenarios: unchanged (safety signals dominate)

### Phase 3: Run v8.2 on pod

Full re-run of v8 three conditions (model_decides, gate_overrides, gate_assists)
with the fixed classifier. Same model, same 20 scenarios, temp=0.

**Expected outcome:**
- model_decides: ~87.5-90% (suspicious should improve)
- gate_assists: ~95-97.5% (suspicious recovered + escalation preserved)
- gate_overrides: ~95% (same improvement from correct direction signal)

### Decision gate

```
IF gate_assists with fix >= 95%:
    The v8 architecture was right all along. Ship it.
    The "prompt ceiling" from v8.1 was actually a classifier bug.

IF gate_assists with fix ≈ v8 result (90%):
    Bug fix didn't help (model independently escalates suspicious).
    Need per-scenario investigation.

IF fix breaks escalate scenarios:
    Yara keyword change was too aggressive. Refine.
```

## What this does NOT change

- ShadowMonitor thresholds (escalate_threat=0.55, commit_clarity=0.35, etc.)
- ShadowMonitor state machine logic
- Prompt language (v8 gate_assists prompt stays)
- Model or scenario set

## The lesson

v8.1 concluded "prompt ceiling reached — next step monitor threshold tuning."
The actual next step was **evidence classifier audit**. The monitor's thresholds
were fine. The monitor's INPUT was wrong.

This is a clean instance of: "don't tune the controller until you've verified
its inputs." The entire v8.1 experiment was testing the wrong layer.
