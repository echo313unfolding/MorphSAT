#!/usr/bin/env python3
"""MORPHSAT_V7_MODEL_CAPABILITY_SWEEP — Pod-based model zoo sweep.

Key question: Is v7 solving an agent-control problem, or is it mostly
compensating for a weak 3B model?

Decision logic:
  - If 7B with same v7 controller jumps to 80%+: MODEL was the bottleneck
  - If 7B stays at ~70%: CONTROLLER work matters more
  - 14B is the ceiling test

This script:
  1. Creates/reuses a RunPod GPU pod
  2. Uploads morphsat + sentinel benchmark code
  3. For each model: download GGUF, start llama-server, run v7_shadow, save receipt
  4. Downloads receipts locally
  5. Prints summary table + decision

Models (start with 3):
  - Qwen2.5-Coder-3B Q4_K_M   (baseline, matches local T2000 result)
  - Qwen2.5-Coder-7B Q4_K_M   (scale test)
  - Qwen2.5-14B Q4_K_M         (ceiling)

Usage:
    python3 tools/model_capability_sweep.py
    python3 tools/model_capability_sweep.py --pod-id <existing>
    python3 tools/model_capability_sweep.py --no-terminate  # keep pod alive
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Vault access — keys read from disk, never printed or logged
# ---------------------------------------------------------------------------

def _read_secret(path: str) -> str:
    """Read a secret from disk. Never print, log, or embed in commands."""
    p = Path(path).expanduser()
    if not p.exists():
        print(f"FATAL: Secret not found at {p}")
        sys.exit(1)
    return p.read_text().strip()

RUNPOD_API_KEY = None  # loaded lazily
SSH_KEY_PATH = Path.home() / ".ssh" / "id_ed25519_runpod"
SSH_PUBKEY_PATH = Path.home() / ".ssh" / "id_ed25519_runpod.pub"

def get_api_key():
    global RUNPOD_API_KEY
    if RUNPOD_API_KEY is None:
        RUNPOD_API_KEY = _read_secret("~/.runpod_api_key")
    return RUNPOD_API_KEY


# ---------------------------------------------------------------------------
# Model definitions
# ---------------------------------------------------------------------------

MODELS = [
    {
        "name": "qwen2.5-coder-3b",
        "label": "Qwen2.5-Coder-3B Q4_K_M (baseline)",
        "hf_repo": "Qwen/Qwen2.5-Coder-3B-Instruct-GGUF",
        "hf_file": "qwen2.5-coder-3b-instruct-q4_k_m.gguf",
        "gpu_layers": 99,
        "ctx_size": 4096,
    },
    {
        "name": "qwen2.5-coder-7b",
        "label": "Qwen2.5-Coder-7B Q4_K_M (scale test)",
        "hf_repo": "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
        "hf_file": "qwen2.5-coder-7b-instruct-q4_k_m.gguf",
        "gpu_layers": 99,
        "ctx_size": 4096,
    },
    {
        "name": "qwen2.5-14b",
        "label": "Qwen2.5-14B Q4_K_M (ceiling)",
        "hf_repo": "Qwen/Qwen2.5-14B-Instruct-GGUF",
        "hf_file": "qwen2.5-14b-instruct-q4_k_m-00001-of-00003.gguf",
        "hf_split_files": [
            "qwen2.5-14b-instruct-q4_k_m-00001-of-00003.gguf",
            "qwen2.5-14b-instruct-q4_k_m-00002-of-00003.gguf",
            "qwen2.5-14b-instruct-q4_k_m-00003-of-00003.gguf",
        ],
        "gpu_layers": 99,
        "ctx_size": 4096,
    },
]


# ---------------------------------------------------------------------------
# RunPod API helpers
# ---------------------------------------------------------------------------

def runpod_graphql(query: str) -> dict:
    """Execute a RunPod GraphQL query via curl. API key never appears in output."""
    api_key = get_api_key()
    payload = json.dumps({"query": query})
    result = subprocess.run(
        ["curl", "-s", "-X", "POST",
         "https://api.runpod.io/graphql",
         "-H", "Content-Type: application/json",
         "-H", f"Authorization: Bearer {api_key}",
         "-d", payload],
        capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        print(f"FATAL: RunPod API call failed: {result.stderr[:200]}")
        sys.exit(1)
    data = json.loads(result.stdout)
    if "errors" in data:
        print(f"RunPod API error: {data['errors']}")
    return data


def create_pod(gpu_type: str = "NVIDIA GeForce RTX 3090",
               volume_gb: int = 50) -> str:
    """Create a RunPod on-demand pod. Returns pod_id."""
    pubkey = SSH_PUBKEY_PATH.read_text().strip()
    # Escape pubkey for GraphQL string
    pubkey_escaped = pubkey.replace('"', '\\"')
    query = """
    mutation {
      podFindAndDeployOnDemand(input: {
        name: "morphsat-sweep"
        templateId: "runpod-torch-v21"
        gpuTypeId: "%s"
        gpuCount: 1
        volumeInGb: %d
        containerDiskInGb: 20
        ports: "22/tcp"
        cloudType: COMMUNITY
        env: [{ key: "PUBLIC_KEY", value: "%s" }]
      }) { id desiredStatus machine { podHostId } }
    }
    """ % (gpu_type, volume_gb, pubkey_escaped)
    resp = runpod_graphql(query)
    if "errors" in resp:
        print(f"FATAL: Pod creation failed: {resp['errors']}")
        sys.exit(1)
    pod_id = resp["data"]["podFindAndDeployOnDemand"]["id"]
    print(f"  Pod created: {pod_id}")
    return pod_id


def get_pod_ssh(pod_id: str) -> tuple:
    """Wait for pod to boot and return (ip, port). Polls until ready."""
    print(f"  Waiting for pod {pod_id} to boot...", end="", flush=True)
    for attempt in range(120):  # up to 10 min
        query = '{ pod(input: {podId: "%s"}) { runtime { ports { ip privatePort publicPort type } } } }' % pod_id
        resp = runpod_graphql(query)
        runtime = resp.get("data", {}).get("pod", {}).get("runtime")
        if runtime and runtime.get("ports"):
            for port_info in runtime["ports"]:
                if port_info.get("privatePort") == 22 and port_info.get("type") == "tcp":
                    ip = port_info["ip"]
                    pub_port = port_info["publicPort"]
                    print(f" ready! ({ip}:{pub_port})")
                    return ip, pub_port
        print(".", end="", flush=True)
        time.sleep(5)
    print(" TIMEOUT")
    print("FATAL: Pod did not become ready in 10 minutes")
    sys.exit(1)


def terminate_pod(pod_id: str):
    """Terminate a RunPod pod."""
    query = 'mutation { podTerminate(input: {podId: "%s"}) }' % pod_id
    runpod_graphql(query)
    print(f"  Pod {pod_id} terminated.")


def check_balance():
    """Print current RunPod balance."""
    resp = runpod_graphql('{ myself { clientBalance currentSpendPerHr } }')
    myself = resp.get("data", {}).get("myself", {})
    balance = myself.get("clientBalance", "?")
    spend = myself.get("currentSpendPerHr", "?")
    print(f"  RunPod balance: ${balance}, current spend: ${spend}/hr")


# ---------------------------------------------------------------------------
# SSH helpers
# ---------------------------------------------------------------------------

def ssh_cmd(ip: str, port: int) -> list:
    """Base SSH command with proper key and options."""
    return [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "IdentitiesOnly=yes",
        "-o", "ConnectTimeout=10",
        "-i", str(SSH_KEY_PATH),
        "-p", str(port),
        f"root@{ip}",
    ]


def ssh_run(ip: str, port: int, command: str, timeout: int = 600,
            check: bool = True) -> subprocess.CompletedProcess:
    """Run a command on the pod via SSH."""
    cmd = ssh_cmd(ip, port) + [command]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode != 0:
        print(f"  SSH command failed (rc={result.returncode}):")
        print(f"    cmd: {command[:200]}")
        if result.stderr:
            print(f"    stderr: {result.stderr[:500]}")
    return result


def rsync_to_pod(ip: str, port: int, local_path: str, remote_path: str):
    """rsync local files to pod."""
    cmd = [
        "rsync", "-az", "--delete",
        "-e", f"ssh -o StrictHostKeyChecking=no -o IdentitiesOnly=yes -i {SSH_KEY_PATH} -p {port}",
        local_path,
        f"root@{ip}:{remote_path}",
    ]
    subprocess.run(cmd, check=True, timeout=300)


def rsync_from_pod(ip: str, port: int, remote_path: str, local_path: str):
    """rsync pod files to local."""
    cmd = [
        "rsync", "-az",
        "-e", f"ssh -o StrictHostKeyChecking=no -o IdentitiesOnly=yes -i {SSH_KEY_PATH} -p {port}",
        f"root@{ip}:{remote_path}",
        local_path,
    ]
    subprocess.run(cmd, check=True, timeout=300)


# ---------------------------------------------------------------------------
# Pod setup
# ---------------------------------------------------------------------------

def setup_pod(ip: str, port: int):
    """Install dependencies and upload code to the pod."""
    print("  Installing dependencies on pod...")

    # Install rsync + llama-server + pip deps
    setup_script = """
set -e
export DEBIAN_FRONTEND=noninteractive

# rsync is needed for file upload
which rsync >/dev/null 2>&1 || {
    echo "Installing rsync..."
    apt-get update -qq && apt-get install -y -qq rsync 2>&1 | tail -1
}

pip install -q huggingface_hub numpy 2>&1 | tail -1

which llama-server >/dev/null 2>&1 || {
    echo "Installing llama.cpp (this takes a few minutes)..."
    apt-get install -y -qq cmake build-essential libcurl4-openssl-dev git 2>&1 | tail -1
    cd /tmp
    [ -d llama.cpp ] || git clone --depth 1 https://github.com/ggerganov/llama.cpp.git 2>&1 | tail -1
    cd llama.cpp
    cmake -B build -DGGML_CUDA=ON -DLLAMA_CURL=ON 2>&1 | tail -3
    cmake --build build --config Release -j$(nproc) --target llama-server 2>&1 | tail -3
    cp build/bin/llama-server /usr/local/bin/
    echo "llama-server installed"
}
mkdir -p /root/morphsat /root/sentinel_eval /root/receipts /root/models
echo "Setup done"
"""
    # Phase 1: install rsync + pip deps (fast)
    phase1 = """
set -e
export DEBIAN_FRONTEND=noninteractive
which rsync >/dev/null 2>&1 || {
    echo "Installing rsync..."
    apt-get update -qq && apt-get install -y -qq rsync 2>&1 | tail -1
}
pip install -q huggingface_hub numpy 2>&1 | tail -1
mkdir -p /root/morphsat /root/sentinel_eval /root/receipts /root/models
echo "Phase 1 done"
"""
    result = ssh_run(ip, port, phase1, timeout=120)
    print(f"    {result.stdout.strip().split(chr(10))[-1]}")
    if result.returncode != 0:
        print(f"  WARNING: Phase 1 had errors: {result.stderr[:200]}")

    # Upload files (now rsync is available)
    print("  Uploading morphsat...")
    rsync_to_pod(ip, port,
                 str(Path.home() / "morphsat" / "morphsat") + "/",
                 "/root/morphsat/morphsat/")

    print("  Uploading sentinel eval...")
    rsync_to_pod(ip, port,
                 str(Path.home() / "tools" / "sentinel" / "eval") + "/",
                 "/root/sentinel_eval/eval/")

    print("  Uploading remote runner...")
    runner_path = Path(__file__).parent / "model_sweep_remote_runner.py"
    rsync_to_pod(ip, port, str(runner_path), "/root/")

    # Phase 2: install llama-server if needed
    # Try building from source with proper CUDA path; fall back to pip llama-cpp-python
    phase2 = """
set -e
export DEBIAN_FRONTEND=noninteractive
which llama-server >/dev/null 2>&1 && { echo "llama-server already installed"; exit 0; }

# Set CUDA path — RunPod images have nvcc at /usr/local/cuda*/bin/
export PATH="/usr/local/cuda/bin:/usr/local/cuda-11.8/bin:$PATH"
export CUDA_HOME="/usr/local/cuda"
export LD_LIBRARY_PATH="/usr/local/cuda/lib64:${LD_LIBRARY_PATH:-}"

echo "Building llama.cpp from source with CUDA..."
apt-get install -y -qq cmake build-essential libcurl4-openssl-dev git 2>&1 | tail -1
cd /tmp
[ -d llama.cpp ] || git clone --depth 1 https://github.com/ggerganov/llama.cpp.git 2>&1 | tail -1
cd llama.cpp
cmake -B build -DGGML_CUDA=ON -DLLAMA_CURL=ON -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc 2>&1 | tail -5
cmake --build build --config Release -j$(nproc) --target llama-server 2>&1 | tail -5
cp build/bin/llama-server /usr/local/bin/
echo "llama-server installed"
"""
    print("  Installing llama-server on pod...")
    result = ssh_run(ip, port, phase2, timeout=1800)  # CUDA build can take 30+ min
    for line in result.stdout.strip().split("\n")[-5:]:
        print(f"    {line}")
    if result.returncode != 0:
        print(f"  WARNING: Build from source failed, trying pip fallback...")
        print(f"  stderr: {result.stderr[:300]}")
        # Fallback: try pip install with CUDA
        fallback = """
set -e
export PATH="/usr/local/cuda/bin:$PATH"
export CUDA_HOME="/usr/local/cuda"
CMAKE_ARGS="-DGGML_CUDA=ON" pip install llama-cpp-python[server] 2>&1 | tail -5
# Create a wrapper
cat > /usr/local/bin/llama-server << 'WRAPPER'
#!/bin/bash
python3 -m llama_cpp.server "$@"
WRAPPER
chmod +x /usr/local/bin/llama-server
echo "llama-server installed via pip"
"""
        result2 = ssh_run(ip, port, fallback, timeout=600)
        for line in result2.stdout.strip().split("\n")[-3:]:
            print(f"    {line}")
        if result2.returncode != 0:
            print(f"  FATAL: llama-server install failed both ways")
            sys.exit(1)

    print("  Pod setup complete.")


# ---------------------------------------------------------------------------
# Remote runner (generated as a separate file)
# ---------------------------------------------------------------------------

REMOTE_RUNNER_CODE = r'''#!/usr/bin/env python3
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
'''


# ---------------------------------------------------------------------------
# Main orchestrator (runs locally)
# ---------------------------------------------------------------------------

def run_sweep(pod_id: str = None, no_terminate: bool = False,
              gpu_type: str = "NVIDIA GeForce RTX 3090",
              models: list = None):
    """Orchestrate the full model capability sweep."""
    if models is None:
        models = MODELS

    print(f"MORPHSAT_V7_MODEL_CAPABILITY_SWEEP")
    print(f"  Models: {len(models)}")
    print(f"  Scenarios: 20 (v7_shadow only)")
    print(f"  Key question: model bottleneck or controller bottleneck?")
    print()

    # Check balance
    check_balance()

    # Create or reuse pod
    if pod_id:
        print(f"  Reusing pod: {pod_id}")
    else:
        print(f"  Creating pod (GPU: {gpu_type})...")
        pod_id = create_pod(gpu_type=gpu_type)

    # Save pod ID immediately in case of later crash
    local_receipt_dir = Path.home() / "receipts" / "morphsat_model_sweep"
    local_receipt_dir.mkdir(parents=True, exist_ok=True)
    pod_id_file = local_receipt_dir / "active_pod_id.txt"
    pod_id_file.write_text(pod_id + "\n")
    print(f"  Pod ID saved to: {pod_id_file}")

    # Get SSH info
    ip, port = get_pod_ssh(pod_id)

    # Wait for SSH to actually be ready (image pull can finish before sshd starts)
    print("  Verifying SSH connectivity...", end="", flush=True)
    for attempt in range(30):
        result = ssh_run(ip, port, "echo OK", timeout=10, check=False)
        if result.returncode == 0 and "OK" in result.stdout:
            print(" connected!")
            break
        time.sleep(2)
        print(".", end="", flush=True)
    else:
        print(" FAILED")
        print("FATAL: Cannot SSH to pod")
        if not no_terminate:
            terminate_pod(pod_id)
        sys.exit(1)

    # Write the remote runner to disk so we can upload it
    runner_path = Path(__file__).parent / "model_sweep_remote_runner.py"
    runner_path.write_text(REMOTE_RUNNER_CODE)

    # Setup pod
    setup_pod(ip, port)

    # Run each model
    sweep_start = time.time()
    all_receipts = []

    for i, model_cfg in enumerate(models):
        print(f"\n{'#'*60}")
        print(f"  MODEL {i+1}/{len(models)}: {model_cfg['label']}")
        print(f"{'#'*60}")

        # Run on pod via SSH
        model_json = json.dumps(model_cfg).replace("'", "'\\''")
        cmd = (
            f"cd /root && "
            f"PYTHONPATH=/root/morphsat:/root/sentinel_eval:$PYTHONPATH "
            f"python3 model_sweep_remote_runner.py "
            f"--model-json '{model_json}'"
        )
        result = ssh_run(ip, port, cmd, timeout=3600, check=False)

        # Print output
        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                print(f"  [pod] {line}")
        if result.returncode != 0 and result.stderr:
            print(f"  [pod stderr] {result.stderr[:500]}")

        # Check if receipt was created
        receipt_name = f"morphsat_sweep_{model_cfg['name']}.json"
        check = ssh_run(ip, port, f"cat /root/receipts/{receipt_name}",
                        timeout=10, check=False)
        if check.returncode == 0 and check.stdout.strip():
            try:
                receipt = json.loads(check.stdout)
                all_receipts.append(receipt)
                print(f"  Receipt OK: {receipt.get('accuracy_pct', '?')}% accuracy")
            except json.JSONDecodeError:
                print(f"  WARNING: Receipt exists but is not valid JSON")
        else:
            print(f"  WARNING: No receipt found for {model_cfg['name']}")

    # Download all receipts
    print(f"\n  Downloading receipts...")
    rsync_from_pod(ip, port, "/root/receipts/",
                   str(local_receipt_dir) + "/")
    print(f"  Saved to: {local_receipt_dir}")

    # Print final summary table
    sweep_wall = round(time.time() - sweep_start, 1)
    print(f"\n{'='*70}")
    print(f"  FINAL COMPARISON — v7 Shadow Monitor across models")
    print(f"{'='*70}")
    print(f"  {'Model':<35s} {'Acc':>6s} {'Benign':>8s} {'Susp':>8s} "
          f"{'Esc':>8s} {'Loops':>7s} {'Turns':>6s} {'Wrong':>6s}")
    print(f"  {'-'*35} {'-'*6} {'-'*8} {'-'*8} {'-'*8} {'-'*7} {'-'*6} {'-'*6}")

    for receipt in all_receipts:
        if "error" in receipt:
            print(f"  {receipt.get('model_label', '?'):<35s} FAILED")
            continue
        pc = receipt.get("per_category", {})
        print(f"  {receipt['model_label']:<35s} "
              f"{receipt['accuracy_pct']:>5.1f}% "
              f"{pc.get('benign', {}).get('accuracy_pct', '?'):>7}% "
              f"{pc.get('suspicious', {}).get('accuracy_pct', '?'):>7}% "
              f"{pc.get('escalate', {}).get('accuracy_pct', '?'):>7}% "
              f"{receipt['tool_loop_rate_pct']:>6.1f}% "
              f"{receipt['avg_turns']:>5.1f} "
              f"{receipt['n_wrong']:>5d}")

    # Decision logic
    print(f"\n{'='*70}")
    print(f"  DECISION")
    print(f"{'='*70}")

    baseline = next((r for r in all_receipts
                     if r.get("model") == "qwen2.5-coder-3b"), None)
    scale_test = next((r for r in all_receipts
                       if r.get("model") == "qwen2.5-coder-7b"), None)
    ceiling = next((r for r in all_receipts
                    if r.get("model") == "qwen2.5-14b"), None)

    if baseline and scale_test:
        base_acc = baseline["accuracy_pct"]
        scale_acc = scale_test["accuracy_pct"]
        delta = scale_acc - base_acc

        if scale_acc >= 80:
            print(f"  7B accuracy {scale_acc}% >= 80% (3B was {base_acc}%)")
            print(f"  >>> MODEL BOTTLENECK — v7 controller is fine, upgrade the model")
        elif abs(delta) <= 5:
            print(f"  7B accuracy {scale_acc}% ~ 3B {base_acc}% (delta {delta:+.1f}pp)")
            print(f"  >>> CONTROLLER BOTTLENECK — bigger model doesn't help, improve v7")
        else:
            print(f"  7B accuracy {scale_acc}% vs 3B {base_acc}% (delta {delta:+.1f}pp)")
            print(f"  >>> MIXED — model helps but doesn't clear 80%. Both matter.")

        if ceiling:
            ceil_acc = ceiling["accuracy_pct"]
            print(f"  14B ceiling: {ceil_acc}%")
            if ceil_acc >= 90:
                print(f"  >>> Ceiling is high — v7 at {ceil_acc}% with 14B, "
                      f"controller has room")
            elif ceil_acc <= scale_acc + 3:
                print(f"  >>> Diminishing returns at 14B — 7B may be sufficient")

    # Wrong-scenario overlap
    if len(all_receipts) >= 2:
        print(f"\n  Wrong scenario overlap:")
        wrong_sets = {}
        for receipt in all_receipts:
            if "error" not in receipt:
                wrong_ids = {w["id"] for w in receipt.get("wrong_scenarios", [])}
                wrong_sets[receipt["model"]] = wrong_ids
                print(f"    {receipt['model']}: {sorted(wrong_ids)}")

        if len(wrong_sets) >= 2:
            all_wrong = set.intersection(*wrong_sets.values()) if wrong_sets else set()
            if all_wrong:
                print(f"    ALL MODELS WRONG: {sorted(all_wrong)}")
                print(f"    >>> These {len(all_wrong)} scenarios may be "
                      f"scenario/eval issues, not model issues")

    print(f"\n  Total sweep wall time: {sweep_wall:.0f}s "
          f"({sweep_wall/60:.1f}m)")
    print(f"  Receipts: {local_receipt_dir}")

    # Write combined receipt
    combined = {
        "experiment": "MORPHSAT_V7_MODEL_CAPABILITY_SWEEP",
        "date": time.strftime("%Y-%m-%d"),
        "n_models": len(all_receipts),
        "n_scenarios": 20,
        "mode": "v7_shadow",
        "sweep_wall_time_s": sweep_wall,
        "pod_id": pod_id,
        "models": {r["model"]: {
            "accuracy_pct": r["accuracy_pct"],
            "per_category": r.get("per_category", {}),
            "tool_loop_rate_pct": r["tool_loop_rate_pct"],
            "avg_turns": r["avg_turns"],
            "n_wrong": r["n_wrong"],
            "wrong_scenarios": r.get("wrong_scenarios", []),
        } for r in all_receipts if "error" not in r},
        "receipts": [str(local_receipt_dir / f"morphsat_sweep_{r['model']}.json")
                     for r in all_receipts if "error" not in r],
    }
    combined_path = local_receipt_dir / "sweep_combined.json"
    combined_path.write_text(json.dumps(combined, indent=2))
    print(f"  Combined: {combined_path}")

    # Terminate pod (unless --no-terminate)
    if no_terminate:
        print(f"\n  Pod {pod_id} left running (--no-terminate).")
        print(f"  SSH: ssh -o StrictHostKeyChecking=no -o IdentitiesOnly=yes "
              f"-i {SSH_KEY_PATH} -p {port} root@{ip}")
    else:
        print(f"\n  Terminating pod...")
        terminate_pod(pod_id)


def main():
    parser = argparse.ArgumentParser(
        description="MorphSAT v7 Model Capability Sweep (pod-based)")
    parser.add_argument("--pod-id", type=str, default=None,
                        help="Reuse existing pod instead of creating new one")
    parser.add_argument("--no-terminate", action="store_true",
                        help="Keep pod alive after sweep completes")
    parser.add_argument("--terminate-only", action="store_true",
                        help="Just terminate an existing pod (requires --pod-id)")
    parser.add_argument("--gpu", type=str,
                        default="NVIDIA GeForce RTX 3090",
                        help="GPU type for pod creation")
    parser.add_argument("--models", nargs="+", default=None,
                        help="Model names to run (default: all 3)")
    args = parser.parse_args()

    if args.terminate_only:
        if not args.pod_id:
            print("--terminate-only requires --pod-id")
            sys.exit(1)
        terminate_pod(args.pod_id)
        return

    selected_models = MODELS
    if args.models:
        selected_models = [m for m in MODELS if m["name"] in args.models]
        if not selected_models:
            print(f"No models matched: {args.models}")
            print(f"Available: {[m['name'] for m in MODELS]}")
            sys.exit(1)

    run_sweep(
        pod_id=args.pod_id,
        no_terminate=args.no_terminate,
        gpu_type=args.gpu,
        models=selected_models,
    )


if __name__ == "__main__":
    main()
