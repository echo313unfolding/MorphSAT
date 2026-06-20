#!/usr/bin/env python3
"""CDR Memory Trace Distillation — replay SplitMemory behavior.

Runs stress benchmark episodes through modes A, B, K, J simultaneously
and records what SplitMemory did at each step. Produces a trace table
showing where the "old guy" helped, where he hurt, and what graph signal
should have triggered instead.

Usage:
    python3 tools/trace_splitmemory_cdr.py
    python3 tools/trace_splitmemory_cdr.py --family concept_drift --verbose
    python3 tools/trace_splitmemory_cdr.py --json
"""

import argparse
import json
import os
import random
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from morphsat.commit_gate import SplitMemoryStore, classify_tool_result
from morphsat.receipt_chain import ReceiptChain
from morphsat.receipt_graph import ReceiptGraph
from morphsat.memory_qubo import MemoryQUBO
from morphsat.gate_qubo import GateQUBO, GateSnapshot
from morphsat.two_stage_gate import TwoStageGate
from morphsat.graph_routing_signal import extract_graph_routing_signal

# Import bench infrastructure
from bench_memory_stress import (
    STRESS_FAMILIES,
    build_stress_sequence,
    run_stress_episode,
    get_stress_phase,
    classify_tool_result_semantic,
)


@dataclass
class CDRTraceEntry:
    """One episode traced across all modes."""
    episode_id: str
    family: str
    alert: str
    expected_verdict: str
    stress_phase: str

    # Mode results
    baseline_verdict: str       # Mode A
    splitmemory_verdict: str    # Mode B
    graph_only_verdict: str     # Mode K
    hybrid_verdict: str         # Mode J

    # SplitMemory internals (from Mode B run)
    splitmemory_lookup_store: Optional[str] = None
    splitmemory_confidence: float = 0.0
    splitmemory_exposures: int = 0

    # Graph state (from Mode K run)
    graph_candidate_count: int = 0
    graph_edge_count: int = 0
    graph_reinforcement_count: int = 0
    graph_contradiction_count: int = 0

    # Gate routing (from Mode J run)
    gate_backend_used: str = "unknown"
    correction_seen: bool = False

    # CDR analysis
    old_guy_helped: bool = False
    old_guy_hurt: bool = False
    graph_should_have_triggered: bool = False
    graph_signal_type: str = "none"


_tmp_ctr = 0

def _tmp(suffix: str) -> str:
    global _tmp_ctr
    _tmp_ctr += 1
    return f"/tmp/cdr_trace_{suffix}_{os.getpid()}_{_tmp_ctr}"


def trace_family(
    family_name: str,
    scenarios: List[Dict],
    verbose: bool = False,
) -> List[CDRTraceEntry]:
    """Run one family through A, B, K, J and trace SplitMemory behavior."""

    # --- Set up per-mode state ---
    # Mode A: baseline
    # Mode B: SplitMemory only
    mem_b = SplitMemoryStore(_tmp("b_mem") + ".json")
    # Mode K: graph-only (no SplitMemory)
    chain_k = ReceiptChain(_tmp("k_chain") + ".json")
    graph_k = ReceiptGraph(_tmp("k_graph") + ".json")
    mqubo_k = MemoryQUBO(max_k=5)
    ts_gate_k = TwoStageGate()
    # Mode J: full hybrid
    mem_j = SplitMemoryStore(_tmp("j_mem") + ".json")
    chain_j = ReceiptChain(_tmp("j_chain") + ".json")
    graph_j = ReceiptGraph(_tmp("j_graph") + ".json")
    mqubo_j = MemoryQUBO(max_k=5)
    ts_gate_j = TwoStageGate()

    entries: List[CDRTraceEntry] = []

    for ep_idx, scenario in enumerate(scenarios):
        seq = build_stress_sequence(scenario, n_tools=3, rng=random.Random(42))
        alert = scenario["alert"]
        expected = scenario["category"]
        phase = get_stress_phase(family_name, scenario["id"])

        # --- Run Mode A (baseline) ---
        res_a = run_stress_episode(
            scenario=scenario, tool_sequence=seq,
            mode="A", family=family_name, episode_index=ep_idx,
            classifier_fn=classify_tool_result_semantic,
            classifier_name="semantic",
        )

        # --- Run Mode B (SplitMemory only) ---
        res_b = run_stress_episode(
            scenario=scenario, tool_sequence=seq,
            mode="B", family=family_name, episode_index=ep_idx,
            memory=mem_b,
            classifier_fn=classify_tool_result_semantic,
            classifier_name="semantic",
        )
        # Capture SplitMemory lookup state
        sm_store = None
        sm_conf = 0.0
        sm_exp = 0
        ev_vec = [(t, classify_tool_result_semantic(r)[0]) for t, r in seq]
        sm_result = mem_b.lookup(alert, ev_vec)
        if sm_result:
            sm_store, sm_entry = sm_result
            sm_conf = sm_entry.confidence
            sm_exp = sm_entry.exposures

        # --- Run Mode K (graph-only, no SplitMemory) ---
        res_k = run_stress_episode(
            scenario=scenario, tool_sequence=seq,
            mode="K", family=family_name, episode_index=ep_idx,
            receipt_chain=chain_k, receipt_graph=graph_k,
            memory_qubo=mqubo_k, two_stage_gate=ts_gate_k,
            classifier_fn=classify_tool_result_semantic,
            classifier_name="semantic",
        )

        # Get graph routing signal for this episode
        alert_tags = [w.lower() for w in alert.split()
                      if len(w) > 3 and w.isalpha()]
        graph_signal = extract_graph_routing_signal(
            graph_k, alert_tags, domain="security",
            current_threat=res_k.final_threat_score,
            current_safety=res_k.final_safety_score,
        )

        # --- Run Mode J (full hybrid) ---
        res_j = run_stress_episode(
            scenario=scenario, tool_sequence=seq,
            mode="J", family=family_name, episode_index=ep_idx,
            memory=mem_j, receipt_chain=chain_j, receipt_graph=graph_j,
            memory_qubo=mqubo_j, two_stage_gate=ts_gate_j,
            classifier_fn=classify_tool_result_semantic,
            classifier_name="semantic",
        )

        # --- CDR analysis ---
        b_correct = res_b.verdict_correct
        a_correct = res_a.verdict_correct
        k_correct = res_k.verdict_correct

        old_guy_helped = b_correct and not a_correct  # B right, A wrong
        old_guy_hurt = not b_correct and a_correct     # B wrong, A right

        # Graph should have triggered = old guy helped but graph didn't
        graph_should_triggered = old_guy_helped and not k_correct

        entry = CDRTraceEntry(
            episode_id=scenario["id"],
            family=family_name,
            alert=alert[:120],
            expected_verdict=expected,
            stress_phase=phase,
            baseline_verdict=res_a.final_verdict,
            splitmemory_verdict=res_b.final_verdict,
            graph_only_verdict=res_k.final_verdict,
            hybrid_verdict=res_j.final_verdict,
            splitmemory_lookup_store=sm_store,
            splitmemory_confidence=round(sm_conf, 3),
            splitmemory_exposures=sm_exp,
            graph_candidate_count=graph_signal.matching_nodes,
            graph_edge_count=graph_signal.matching_active_edges,
            graph_reinforcement_count=res_k.graph_active_edges,
            graph_contradiction_count=graph_k.cold_edge_count,
            gate_backend_used=res_j.final_action or "unknown",
            correction_seen=graph_signal.correction_related,
            old_guy_helped=old_guy_helped,
            old_guy_hurt=old_guy_hurt,
            graph_should_have_triggered=graph_should_triggered,
            graph_signal_type=graph_signal.strongest_signal,
        )
        entries.append(entry)

        if verbose:
            mark_b = "OK" if b_correct else "WRONG"
            mark_k = "OK" if k_correct else "WRONG"
            helped = " HELPED" if old_guy_helped else ""
            hurt = " HURT" if old_guy_hurt else ""
            gap = " GRAPH_GAP" if graph_should_triggered else ""
            sig = f" sig={graph_signal.strongest_signal}" if graph_signal.routing_triggered else ""
            print(f"  {scenario['id']:12s} exp={expected:10s} "
                  f"A={res_a.final_verdict:10s} "
                  f"B={res_b.final_verdict:10s}[{mark_b}] "
                  f"K={res_k.final_verdict:10s}[{mark_k}] "
                  f"J={res_j.final_verdict:10s}"
                  f"{helped}{hurt}{gap}{sig}")

    # Cleanup
    for obj in [mem_b, mem_j, chain_k, chain_j, graph_k, graph_j]:
        if hasattr(obj, "store_path"):
            p = Path(obj.store_path)
        elif hasattr(obj, "path"):
            p = Path(obj.path)
        else:
            continue
        if p.exists():
            p.unlink()

    return entries


def main():
    parser = argparse.ArgumentParser(
        description="CDR Memory Trace Distillation")
    parser.add_argument("--family", type=str, default=None)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    families = STRESS_FAMILIES
    if args.family:
        if args.family not in families:
            print(f"Unknown family: {args.family}")
            sys.exit(1)
        families = {args.family: families[args.family]}

    print("CDR Memory Trace Distillation")
    print(f"  Families: {len(families)}")
    print()

    all_entries: List[CDRTraceEntry] = []

    for fam_name, scenarios in families.items():
        if args.verbose:
            print(f"--- {fam_name} ---")
        entries = trace_family(fam_name, scenarios, verbose=args.verbose)
        all_entries.extend(entries)
        if args.verbose:
            print()

    # Summary
    total = len(all_entries)
    helped = sum(1 for e in all_entries if e.old_guy_helped)
    hurt = sum(1 for e in all_entries if e.old_guy_hurt)
    gaps = sum(1 for e in all_entries if e.graph_should_have_triggered)
    signals = sum(1 for e in all_entries if e.graph_signal_type != "none")

    print(f"CDR Summary ({total} episodes):")
    print(f"  Old guy helped:  {helped}/{total}")
    print(f"  Old guy hurt:    {hurt}/{total}")
    print(f"  Graph gaps:      {gaps}/{total} (old guy helped, graph didn't)")
    print(f"  Graph signals:   {signals}/{total}")
    print()

    # Per-family breakdown
    print(f"{'Family':<30s} {'Helped':>7} {'Hurt':>5} {'Gap':>4} {'Signals':>8}")
    print("-" * 60)
    for fam in sorted(STRESS_FAMILIES.keys()):
        fam_entries = [e for e in all_entries if e.family == fam]
        if not fam_entries:
            continue
        f_helped = sum(1 for e in fam_entries if e.old_guy_helped)
        f_hurt = sum(1 for e in fam_entries if e.old_guy_hurt)
        f_gaps = sum(1 for e in fam_entries if e.graph_should_have_triggered)
        f_sigs = sum(1 for e in fam_entries if e.graph_signal_type != "none")
        print(f"  {fam:<28s} {f_helped:>7} {f_hurt:>5} {f_gaps:>4} {f_sigs:>8}")
    print()

    # Signal type breakdown
    signal_types: Dict[str, int] = {}
    for e in all_entries:
        if e.graph_signal_type != "none":
            signal_types[e.graph_signal_type] = signal_types.get(
                e.graph_signal_type, 0) + 1
    if signal_types:
        print("Signal types fired:")
        for sig, count in sorted(signal_types.items(), key=lambda x: -x[1]):
            print(f"  {sig}: {count}")
        print()

    # Gap analysis: where old guy helped but graph didn't
    if gaps > 0:
        print("Graph gaps (old guy helped, graph missed):")
        for e in all_entries:
            if e.graph_should_have_triggered:
                print(f"  {e.episode_id:12s} [{e.family}] "
                      f"exp={e.expected_verdict} "
                      f"B={e.splitmemory_verdict} K={e.graph_only_verdict} "
                      f"sm_store={e.splitmemory_lookup_store} "
                      f"sm_conf={e.splitmemory_confidence:.2f} "
                      f"graph_nodes={e.graph_candidate_count}")
        print()

    # Write receipt
    receipt_dir = Path.home() / "receipts" / "morphsat_cdr_trace"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    receipt = {
        "type": "cdr_memory_trace",
        "timestamp": ts,
        "total_episodes": total,
        "old_guy_helped": helped,
        "old_guy_hurt": hurt,
        "graph_gaps": gaps,
        "graph_signals": signals,
        "signal_types": signal_types,
        "entries": [asdict(e) for e in all_entries],
    }
    receipt_path = receipt_dir / f"cdr_trace_{ts}.json"
    receipt_path.write_text(json.dumps(receipt, indent=2))
    print(f"Receipt: {receipt_path}")

    if args.json:
        print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
