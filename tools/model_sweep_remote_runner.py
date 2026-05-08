#!/usr/bin/env python3
"""Remote runner for MorphSAT v7 model capability sweep.

Runs on the pod. For each model:
  1. Downloads GGUF from HuggingFace
  2. Starts llama-server
  3. Runs v7_shadow benchmark (20 scenarios)
  4. Saves receipt
  5. Kills llama-server

Usage:
    python3 model_sweep_remote_runner.py --model-json '<json>'
"""

import argparse
import json
import os
import platform
import resource
import signal
import subprocess
import sys
import time
from pathlib import Path

# Add morphsat to path
sys.path.insert(0, "/root/morphsat")
sys.path.insert(0, "/root/sentinel_eval")

PORT = 8085


def download_model(model_cfg: dict) -> str:
    """Download GGUF from HuggingFace. Returns local path to first shard."""
    from huggingface_hub import hf_hub_download
    hf_repo = model_cfg["hf_repo"]
    split_files = model_cfg.get("hf_split_files")
    if split_files:
        # Split GGUF — download all shards, return path to first
        for f in split_files:
            print(f"  Downloading {hf_repo}/{f}...")
            path = hf_hub_download(hf_repo, f, cache_dir="/root/models/hf_cache")
        # Return path to first shard (llama-server finds the rest)
        first = hf_hub_download(hf_repo, split_files[0], cache_dir="/root/models/hf_cache")
        print(f"  All {len(split_files)} shards downloaded. First: {first}")
        return first
    else:
        hf_file = model_cfg["hf_file"]
        print(f"  Downloading {hf_repo}/{hf_file}...")
        path = hf_hub_download(hf_repo, hf_file, cache_dir="/root/models/hf_cache")
        print(f"  Downloaded: {path}")
        return path


def start_server(model_path: str, gpu_layers: int, ctx_size: int) -> subprocess.Popen:
    """Start llama-server. Returns process handle."""
    cmd = [
        "llama-server",
        "-m", model_path,
        "-ngl", str(gpu_layers),
        "-c", str(ctx_size),
        "--port", str(PORT),
        "--threads", "4",
    ]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    import urllib.request
    print(f"  Waiting for llama-server...", end="", flush=True)
    for i in range(90):  # up to 90s for large models
        try:
            resp = urllib.request.urlopen(
                f"http://localhost:{PORT}/health", timeout=2)
            if resp.status == 200:
                print(f" ready ({i+1}s)")
                return proc
        except Exception:
            pass
        time.sleep(1)
        if i % 10 == 9:
            print(".", end="", flush=True)

    # Failed
    proc.kill()
    stderr = proc.stderr.read().decode(errors="replace")
    print(f" FAILED")
    print(f"  stderr: {stderr[-500:]}")
    return None


def kill_server(proc: subprocess.Popen):
    """Kill llama-server cleanly."""
    if proc is None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    # Also kill any orphans
    subprocess.run(["pkill", "-f", "llama-server"], capture_output=True)
    time.sleep(1)


def get_vram_mb() -> int:
    """Get GPU VRAM usage in MB."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used",
             "--format=csv,noheader,nounits"],
            timeout=5).decode().strip()
        return int(out.split("\n")[0])
    except Exception:
        return 0


def get_gpu_name() -> str:
    """Get GPU name."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name",
             "--format=csv,noheader"],
            timeout=5).decode().strip()
        return out.split("\n")[0]
    except Exception:
        return "unknown"


def run_v7_sweep(model_cfg: dict) -> dict:
    """Run the v7_shadow benchmark for one model. Returns receipt."""
    from morphsat.shadow_monitor import ShadowMonitor, ShadowState
    from morphsat.commit_gate import SplitMemoryStore
    from eval.grammar import query_llama_multi
    from eval.bench_morphsat import (
        BENCHMARK_SCENARIOS, TRIAGE_SYSTEM_PROMPT,
        simulate_tool, classify_output, score_verdict,
    )

    name = model_cfg["name"]
    print(f"\n{'='*60}")
    print(f"  MODEL: {model_cfg['label']}")
    print(f"{'='*60}")

    # Download
    model_path = download_model(model_cfg)

    # Start server
    proc = start_server(model_path, model_cfg["gpu_layers"], model_cfg["ctx_size"])
    if proc is None:
        return {"model": name, "error": "server_start_failed"}

    vram_mb = get_vram_mb()
    gpu_name = get_gpu_name()
    print(f"  VRAM: {vram_mb} MB on {gpu_name}")

    # Fresh memory for each model run
    memory_path = f"/tmp/sweep_memory_{name}_{int(time.time())}.json"
    memory = SplitMemoryStore(memory_path)

    start_iso = time.strftime("%Y-%m-%dT%H:%M:%S")
    t_start = time.time()
    cpu_start = time.process_time()

    MAX_TURNS = 8
    results = []
    total_tokens = 0

    for i, scenario in enumerate(BENCHMARK_SCENARIOS):
        print(f"  [{i+1:2d}/{len(BENCHMARK_SCENARIOS)}] "
              f"{scenario['id']:12s} ({scenario['category']:10s}) ...",
              end="", flush=True)

        monitor = ShadowMonitor(memory=memory)
        monitor.initialize(scenario["alert"])

        messages = [
            {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
            {"role": "user", "content": f"Triage this alert:\n{scenario['alert']}"},
        ]
        turns = []
        verdict = None
        tool_call_count = 0
        sc_start = time.time()

        for turn_num in range(MAX_TURNS):
            if monitor.committed:
                action = monitor.last_action
                if action.action == "ABSTAIN":
                    messages.append({"role": "user", "content":
                        "[SYSTEM] Evidence is contradictory or exceeds local capacity. "
                        "Issue verdict as 'suspicious' with low confidence."})
                elif action.direction == "escalate":
                    messages.append({"role": "user", "content":
                        "[SYSTEM] Threat evidence sufficient. Issue your verdict now."})
                elif action.direction == "benign":
                    messages.append({"role": "user", "content":
                        "[SYSTEM] Safety evidence sufficient. Issue your verdict now."})
                else:
                    messages.append({"role": "user", "content":
                        "[SYSTEM] Evidence threshold reached. Issue your verdict now."})

            resp = query_llama_multi(PORT, messages, max_tokens=400)
            content = resp["content"]
            total_tokens += resp.get("tokens", 0)
            event_type, payload = classify_output(content)

            if event_type is None:
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content":
                    "Continue. Use a tool or issue your verdict."})
                turns.append({"turn": turn_num, "type": "reasoning"})
                continue

            if event_type == "TOOL_CALL":
                if monitor.committed:
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content":
                        "[SYSTEM] Investigation complete. You must decide now."})
                    turns.append({"turn": turn_num, "type": "gate_block"})
                    continue

                tool_call_count += 1
                tool_name = payload.get("name", "unknown")
                tool_args = payload.get("arguments", {})
                tool_result = simulate_tool(tool_name, tool_args, scenario)
                action = monitor.process_evidence(
                    tool_name, tool_result, model_output=content)

                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": f"Tool result:\n{tool_result}"})
                turns.append({
                    "turn": turn_num, "type": "tool_call", "tool": tool_name,
                    "shadow_state": monitor.state.value,
                    "action": action.action,
                    "direction": action.direction,
                })

            elif event_type == "VERDICT_ISSUED":
                verdict = payload.get("verdict", "").lower().strip()
                turns.append({"turn": turn_num, "type": "verdict", "verdict": verdict})
                break

        # Force verdict if none issued
        if verdict is None:
            if not monitor.committed:
                monitor._force_commit("max_turns_no_verdict")
            messages.append({"role": "user", "content":
                "You must issue your final verdict NOW. Output a verdict block."})
            resp = query_llama_multi(PORT, messages, max_tokens=200)
            _, payload = classify_output(resp["content"])
            if payload and "verdict" in payload:
                verdict = payload["verdict"].lower().strip()
                turns.append({"turn": len(turns), "type": "forced_verdict",
                              "verdict": verdict})

        # Close episode
        gate_direction = monitor.last_action.direction if monitor.committed else None
        resolution = verdict or gate_direction or "suspicious"
        confidence = 0.8 if verdict and score_verdict(verdict, scenario["category"]) == 2 else 0.5
        monitor.close_episode(resolution, confidence)

        tool_loop = verdict is None or any(t["type"] == "forced_verdict" for t in turns)
        score = score_verdict(verdict, scenario["category"])
        sc_wall = round(time.time() - sc_start, 2)

        result = {
            "scenario_id": scenario["id"],
            "category": scenario["category"],
            "verdict": verdict,
            "score": score,
            "n_turns": len(turns),
            "n_tool_calls": tool_call_count,
            "tool_loop": tool_loop,
            "wall_time_s": sc_wall,
            "final_state": monitor.state.value,
            "abstained": monitor.last_action.action == "ABSTAIN" if monitor.committed else False,
        }
        results.append(result)

        v = verdict or "NONE"
        loop_str = " LOOP" if tool_loop else ""
        print(f" => {v:10s} {score}/2 [{tool_call_count}tc]{loop_str} ({sc_wall:.1f}s)")

    # Kill server
    kill_server(proc)

    # Compute summary
    n = len(results)
    total_score = sum(r["score"] for r in results)
    max_score = n * 2

    cat_scores = {}
    for r in results:
        cat = r["category"]
        if cat not in cat_scores:
            cat_scores[cat] = {"score": 0, "max": 0, "turns": [], "loops": 0}
        cat_scores[cat]["score"] += r["score"]
        cat_scores[cat]["max"] += 2
        cat_scores[cat]["turns"].append(r["n_turns"])
        if r["tool_loop"]:
            cat_scores[cat]["loops"] += 1

    per_category = {}
    for cat, cs in cat_scores.items():
        n_cat = cs["max"] // 2
        per_category[cat] = {
            "accuracy_pct": round(100 * cs["score"] / cs["max"], 1) if cs["max"] else 0,
            "avg_turns": round(sum(cs["turns"]) / len(cs["turns"]), 2),
            "n_scenarios": n_cat,
            "tool_loop_rate_pct": round(100 * cs["loops"] / n_cat, 1),
        }

    wall_total = round(time.time() - t_start, 3)

    # Wrong scenarios detail
    wrong = [r for r in results if r["score"] < 2]

    receipt = {
        "experiment": "MORPHSAT_V7_MODEL_CAPABILITY_SWEEP",
        "model": name,
        "model_label": model_cfg["label"],
        "hf_repo": model_cfg["hf_repo"],
        "hf_file": model_cfg["hf_file"],
        "mode": "v7_shadow",
        "n_scenarios": n,
        "accuracy_pct": round(100 * total_score / max_score, 1),
        "total_score": total_score,
        "max_score": max_score,
        "tool_loop_rate_pct": round(100 * sum(1 for r in results if r["tool_loop"]) / n, 1),
        "avg_turns": round(sum(r["n_turns"] for r in results) / n, 2),
        "n_tool_calls_total": sum(r["n_tool_calls"] for r in results),
        "n_abstains": sum(1 for r in results if r.get("abstained")),
        "per_category": per_category,
        "wrong_scenarios": [
            {"id": r["scenario_id"], "category": r["category"],
             "verdict": r["verdict"], "score": r["score"]}
            for r in wrong
        ],
        "n_wrong": len(wrong),
        "total_tokens": total_tokens,
        "memory_final": memory.to_receipt(),
        "hardware": {
            "gpu": gpu_name,
            "vram_mb": vram_mb,
        },
        "cost": {
            "wall_time_s": wall_total,
            "cpu_time_s": round(time.process_time() - cpu_start, 3),
            "peak_memory_mb": round(
                resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
            "python_version": platform.python_version(),
            "hostname": platform.node(),
            "timestamp_start": start_iso,
            "timestamp_end": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
        "results": results,
    }

    # Print summary
    print(f"\n  SUMMARY: {model_cfg['label']}")
    print(f"  Accuracy:       {receipt['accuracy_pct']}%")
    print(f"  Tool-loop rate: {receipt['tool_loop_rate_pct']}%")
    print(f"  Avg turns:      {receipt['avg_turns']}")
    print(f"  Wrong:          {len(wrong)}/{n}")
    for cat, cs in per_category.items():
        print(f"    {cat:12s}: {cs['accuracy_pct']}%")
    print(f"  Wall time:      {wall_total:.1f}s")

    # Write receipt
    receipt_path = f"/root/receipts/morphsat_sweep_{name}.json"
    with open(receipt_path, "w") as f:
        json.dump(receipt, f, indent=2, default=str)
    print(f"  Receipt: {receipt_path}")

    # Cleanup temp memory
    mem_file = Path(memory_path)
    if mem_file.exists():
        mem_file.unlink()

    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-json", required=True,
                        help="JSON string with model config")
    args = parser.parse_args()
    model_cfg = json.loads(args.model_json)
    run_v7_sweep(model_cfg)


if __name__ == "__main__":
    main()
