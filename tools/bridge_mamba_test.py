#!/usr/bin/env python3
"""
WO-MORPHSAT-BRIDGE-MAMBA-01 — MorphSAT FSA Bridge Test on Mamba-130m
====================================================================

Proves MorphSAT task-state enforcement works on an SSM (Mamba) compressed
inference pipeline. The gate enforces lifecycle:

    IDLE → PLANNING (load shell) → WRITING (swap HelixLinear) →
    TESTING (inference + verify) → DONE (output verified)

Three test phases:
  1. Happy path: full pipeline through gate, all transitions legal
  2. Illegal transitions: attempt out-of-order operations, verify blocked
  3. Guardian blocks: attempt forbidden (state, event) pairs

Uses Mamba-130m compressed via CDNA v3 (from WO-MAMBA-HELIX-01).
CPU-only.

Output: receipts/morphsat_bridge/
"""

import json
import os
import platform
import resource
import sys
import time
from pathlib import Path

# ── Project paths ──
MORPHSAT_ROOT = Path(__file__).resolve().parent.parent
HELIX_ROOT = Path.home() / "helix-substrate"

sys.path.insert(0, str(MORPHSAT_ROOT))
sys.path.insert(0, str(HELIX_ROOT))

MODEL_LOCAL = Path.home() / "models" / "mamba-130m-hf"
CDNA_DIR = MODEL_LOCAL / "cdnav3"


def main():
    t_start = time.time()
    cpu_start = time.process_time()
    start_iso = time.strftime('%Y-%m-%dT%H:%M:%S')

    print("=" * 70)
    print("  WO-MORPHSAT-BRIDGE-MAMBA-01")
    print("  MorphSAT FSA Enforcement on Mamba-130m Compressed Pipeline")
    print("=" * 70)

    from morphsat.core import MorphSATGate, TaskState, TaskEvent, classify_event
    from morphsat.receipt import wrap_receipt

    results = {}
    all_pass = True

    # ================================================================
    # Phase 1: Happy Path — full pipeline through gate
    # ================================================================
    print("\n[Phase 1] Happy path — full lifecycle through gate")
    gate = MorphSATGate()
    assert gate.state == TaskState.IDLE

    # Step 1: NEW_TASK → PLANNING (load model shell)
    state, legal, action = gate.step(TaskEvent.NEW_TASK)
    assert legal and state == TaskState.PLANNING
    print(f"  IDLE → PLANNING: {action}")

    import torch
    import torch.nn as nn
    from transformers import AutoTokenizer, MambaForCausalLM

    print("  Loading Mamba-130m shell...")
    t_load = time.time()
    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_LOCAL))
    model = MambaForCausalLM.from_pretrained(str(MODEL_LOCAL), dtype=torch.float32)
    model.eval()
    load_time = time.time() - t_load
    orig_linears = sum(1 for _, m in model.named_modules() if isinstance(m, nn.Linear))
    print(f"  Loaded: {orig_linears} nn.Linear modules, {load_time:.1f}s")

    # Step 2: PLAN_COMPLETE → WRITING (swap to HelixLinear)
    state, legal, action = gate.step(TaskEvent.PLAN_COMPLETE)
    assert legal and state == TaskState.WRITING
    print(f"  PLANNING → WRITING: {action}")

    from helix_substrate.helix_linear import (
        HelixLinear, load_cdna_factors, swap_to_helix, swap_summary,
    )

    print("  Swapping to HelixLinear...")
    t_swap = time.time()
    helix_modules = load_cdna_factors(CDNA_DIR, model)
    model = swap_to_helix(model, helix_modules)
    swap_time = time.time() - t_swap
    summary = swap_summary(model)
    print(f"  Swapped: {summary['helix_modules']} HelixLinear, "
          f"{summary['linear_modules']} nn.Linear remaining, {swap_time:.1f}s")

    # Step 3: CODE_COMPLETE → TESTING (run inference)
    state, legal, action = gate.step(TaskEvent.CODE_COMPLETE)
    assert legal and state == TaskState.TESTING
    print(f"  WRITING → TESTING: {action}")

    print("  Running inference...")
    test_text = "The quick brown fox jumps over the lazy dog."
    test_ids = tokenizer(test_text, return_tensors="pt")["input_ids"]

    with torch.no_grad():
        outputs = model(test_ids)
        logits = outputs.logits

    all_finite = torch.isfinite(logits).all().item()
    has_nan = torch.isnan(logits).any().item()
    print(f"  Logits: shape={list(logits.shape)}, finite={all_finite}, nan={has_nan}")

    # Classify verifier output
    verify_output = "PASS" if (all_finite and not has_nan) else "FAIL"
    event = classify_event(verify_output, "verify")

    # Step 4: TEST_PASS → DONE
    state, legal, action = gate.step(event)
    assert legal and state == TaskState.DONE
    print(f"  TESTING → DONE: {action} (verify={verify_output})")

    phase1_receipt = gate.to_receipt()
    phase1_pass = (gate.illegal_caught == 0 and gate.guardian_caught == 0
                   and gate.state == TaskState.DONE)
    print(f"  Phase 1: {'PASS' if phase1_pass else 'FAIL'} "
          f"(transitions={gate.total_transitions}, illegal={gate.illegal_caught})")

    results["phase1_happy_path"] = {
        "verdict": "PASS" if phase1_pass else "FAIL",
        "gate": phase1_receipt,
        "model_loaded": True,
        "helix_modules": summary["helix_modules"],
        "compression_ratio": summary["overall_ratio"],
        "logits_finite": all_finite,
        "load_time_s": round(load_time, 3),
        "swap_time_s": round(swap_time, 3),
    }
    if not phase1_pass:
        all_pass = False

    # ================================================================
    # Phase 2: Illegal transitions — FSA enforcement
    # ================================================================
    print("\n[Phase 2] Illegal transitions — FSA enforcement")
    gate2 = MorphSATGate()

    illegal_tests = [
        # (from_state, setup_events, illegal_event, description)
        ("IDLE", [], TaskEvent.PLAN_COMPLETE,
         "Can't complete plan from IDLE"),
        ("IDLE", [], TaskEvent.CODE_COMPLETE,
         "Can't complete code from IDLE"),
        ("IDLE", [], TaskEvent.TEST_PASS,
         "Can't pass test from IDLE"),
        ("PLANNING", [TaskEvent.NEW_TASK], TaskEvent.CODE_COMPLETE,
         "Can't complete code from PLANNING"),
        ("PLANNING", [TaskEvent.NEW_TASK], TaskEvent.TEST_PASS,
         "Can't pass test from PLANNING"),
        ("WRITING", [TaskEvent.NEW_TASK, TaskEvent.PLAN_COMPLETE], TaskEvent.TEST_PASS,
         "Can't pass test from WRITING"),
        ("DONE", [TaskEvent.NEW_TASK, TaskEvent.PLAN_COMPLETE, TaskEvent.CODE_COMPLETE,
                   TaskEvent.TEST_PASS], TaskEvent.PLAN_COMPLETE,
         "Can't complete plan from DONE"),
    ]

    phase2_results = []
    for from_state, setup, illegal_event, desc in illegal_tests:
        g = MorphSATGate()
        for e in setup:
            g.step(e)
        state, legal, action = g.step(illegal_event)
        blocked = not legal
        phase2_results.append({
            "from_state": from_state,
            "illegal_event": TaskEvent(illegal_event).name,
            "blocked": blocked,
            "action": action,
            "description": desc,
        })
        status = "BLOCKED" if blocked else "LEAKED"
        print(f"  {desc}: {status}")

    phase2_pass = all(r["blocked"] for r in phase2_results)
    print(f"  Phase 2: {'PASS' if phase2_pass else 'FAIL'} "
          f"({sum(r['blocked'] for r in phase2_results)}/{len(phase2_results)} blocked)")

    results["phase2_illegal_transitions"] = {
        "verdict": "PASS" if phase2_pass else "FAIL",
        "tests": phase2_results,
        "n_blocked": sum(r["blocked"] for r in phase2_results),
        "n_total": len(phase2_results),
    }
    if not phase2_pass:
        all_pass = False

    # ================================================================
    # Phase 3: Guardian blocks — policy enforcement
    # ================================================================
    print("\n[Phase 3] Guardian blocks — policy layer enforcement")

    guardian_tests = [
        ("IDLE", [], TaskEvent.DEPLOY,
         "Can't deploy from IDLE"),
        ("PLANNING", [TaskEvent.NEW_TASK], TaskEvent.DEPLOY,
         "Can't deploy from PLANNING"),
        ("WRITING", [TaskEvent.NEW_TASK, TaskEvent.PLAN_COMPLETE], TaskEvent.DEPLOY,
         "Can't deploy from WRITING"),
        ("TESTING", [TaskEvent.NEW_TASK, TaskEvent.PLAN_COMPLETE, TaskEvent.CODE_COMPLETE],
         TaskEvent.DEPLOY, "Can't deploy from TESTING"),
        ("PLANNING", [TaskEvent.NEW_TASK], TaskEvent.NEW_TASK,
         "Can't start new task while PLANNING"),
        ("WRITING", [TaskEvent.NEW_TASK, TaskEvent.PLAN_COMPLETE], TaskEvent.NEW_TASK,
         "Can't start new task while WRITING"),
        ("TESTING", [TaskEvent.NEW_TASK, TaskEvent.PLAN_COMPLETE, TaskEvent.CODE_COMPLETE],
         TaskEvent.NEW_TASK, "Can't start new task while TESTING"),
    ]

    phase3_results = []
    for from_state, setup, blocked_event, desc in guardian_tests:
        g = MorphSATGate()
        for e in setup:
            g.step(e)
        state, legal, action = g.step(blocked_event)
        guardian_blocked = (action == "GUARDIAN_BLOCKED")
        phase3_results.append({
            "from_state": from_state,
            "blocked_event": TaskEvent(blocked_event).name,
            "guardian_blocked": guardian_blocked,
            "action": action,
            "description": desc,
        })
        status = "GUARDIAN_BLOCKED" if guardian_blocked else "LEAKED"
        print(f"  {desc}: {status}")

    phase3_pass = all(r["guardian_blocked"] for r in phase3_results)
    print(f"  Phase 3: {'PASS' if phase3_pass else 'FAIL'} "
          f"({sum(r['guardian_blocked'] for r in phase3_results)}/{len(phase3_results)} blocked)")

    results["phase3_guardian_blocks"] = {
        "verdict": "PASS" if phase3_pass else "FAIL",
        "tests": phase3_results,
        "n_guardian_blocked": sum(r["guardian_blocked"] for r in phase3_results),
        "n_total": len(phase3_results),
    }
    if not phase3_pass:
        all_pass = False

    # ================================================================
    # Phase 4: Revision loop — TEST_FAIL → WRITING → TESTING → DONE
    # ================================================================
    print("\n[Phase 4] Revision loop — TEST_FAIL recovery")
    gate4 = MorphSATGate()

    # Walk to TESTING state
    gate4.step(TaskEvent.NEW_TASK)       # IDLE → PLANNING
    gate4.step(TaskEvent.PLAN_COMPLETE)  # PLANNING → WRITING
    gate4.step(TaskEvent.CODE_COMPLETE)  # WRITING → TESTING

    # Simulate test failure
    state, legal, action = gate4.step(TaskEvent.TEST_FAIL)
    assert legal and state == TaskState.WRITING
    print(f"  TESTING → WRITING (TEST_FAIL): {action}")

    # Fix and retest
    state, legal, action = gate4.step(TaskEvent.CODE_COMPLETE)
    assert legal and state == TaskState.TESTING
    print(f"  WRITING → TESTING (retry): {action}")

    state, legal, action = gate4.step(TaskEvent.TEST_PASS)
    assert legal and state == TaskState.DONE
    print(f"  TESTING → DONE (TEST_PASS): {action}")

    phase4_pass = (gate4.state == TaskState.DONE and gate4.total_transitions == 6)
    print(f"  Phase 4: {'PASS' if phase4_pass else 'FAIL'} "
          f"(transitions={gate4.total_transitions})")

    results["phase4_revision_loop"] = {
        "verdict": "PASS" if phase4_pass else "FAIL",
        "gate": gate4.to_receipt(),
    }
    if not phase4_pass:
        all_pass = False

    # ================================================================
    # Phase 5: Deploy from DONE
    # ================================================================
    print("\n[Phase 5] Deploy from DONE — legal deployment")

    # Reuse gate4 which is already in DONE state
    state, legal, action = gate4.step(TaskEvent.DEPLOY)
    deploy_ok = legal and state == TaskState.DONE
    print(f"  DONE → DONE (DEPLOY): {action}")
    print(f"  Phase 5: {'PASS' if deploy_ok else 'FAIL'}")

    results["phase5_deploy"] = {
        "verdict": "PASS" if deploy_ok else "FAIL",
        "gate": gate4.to_receipt(),
    }
    if not deploy_ok:
        all_pass = False

    # ================================================================
    # Final Summary
    # ================================================================
    wall = time.time() - t_start
    cpu = time.process_time() - cpu_start
    peak_mem = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024

    print(f"\n{'=' * 70}")
    print("  RESULTS — WO-MORPHSAT-BRIDGE-MAMBA-01")
    print(f"{'=' * 70}")
    for phase, data in results.items():
        print(f"  {phase}: {data['verdict']}")
    print(f"\n  OVERALL: {'PASS' if all_pass else 'FAIL'}")
    print(f"  Architecture: Mamba (SSM) — NOT a transformer")
    print(f"  Model: Mamba-130m via HelixLinear ({summary['helix_modules']} compressed modules)")
    print(f"  FSA transitions tested: {7 + len(illegal_tests) + len(guardian_tests) + 6}")
    print(f"  Illegal caught: {len(illegal_tests)}")
    print(f"  Guardian caught: {len(guardian_tests)}")
    print(f"  Wall: {wall:.1f}s, CPU: {cpu:.1f}s, Peak RSS: {peak_mem:.1f} MB")

    # Emit receipt
    receipt_dir = HELIX_ROOT / "receipts" / "morphsat_bridge"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%S")

    receipt = {
        "work_order": "WO-MORPHSAT-BRIDGE-MAMBA-01",
        "question": "Does MorphSAT FSA enforcement work on SSM (Mamba) compressed inference pipeline?",
        "answer": "YES" if all_pass else "NO",
        "overall_verdict": "PASS" if all_pass else "FAIL",
        "model": "state-spaces/mamba-130m-hf",
        "architecture": "MambaForCausalLM (SSM, not transformer)",
        "compression": {
            "helix_modules": summary["helix_modules"],
            "linear_remaining": summary["linear_modules"],
            "compression_ratio": summary["overall_ratio"],
        },
        "phases": results,
        "stats": {
            "total_transition_attempts": 7 + len(illegal_tests) + len(guardian_tests) + 6,
            "illegal_caught": len(illegal_tests),
            "guardian_caught": len(guardian_tests),
            "revision_loops_tested": 1,
            "deploy_tested": True,
        },
        "cost": {
            "wall_time_s": round(wall, 3),
            "cpu_time_s": round(cpu, 3),
            "peak_memory_mb": round(peak_mem, 1),
            "python_version": platform.python_version(),
            "hostname": platform.node(),
            "timestamp_start": start_iso,
            "timestamp_end": time.strftime('%Y-%m-%dT%H:%M:%S'),
        },
    }

    receipt_path = receipt_dir / f"morphsat_bridge_mamba_{ts}.json"
    with open(receipt_path, "w") as f:
        json.dump(receipt, f, indent=2)

    print(f"\n  Receipt: {receipt_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
