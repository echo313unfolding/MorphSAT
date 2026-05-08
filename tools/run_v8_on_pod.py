#!/usr/bin/env python3
"""Run the v8 gate authority experiment on a RunPod GPU pod.

Creates pod, uploads code, downloads 7B model, runs bench_gate_authority.py,
downloads receipt, terminates.

Usage:
    python3 tools/run_v8_on_pod.py
    python3 tools/run_v8_on_pod.py --pod-id <existing>
    python3 tools/run_v8_on_pod.py --no-terminate
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

# Reuse pod infra from sweep script
sys.path.insert(0, str(Path(__file__).parent))
from model_capability_sweep import (
    get_api_key, check_balance, create_pod, get_pod_ssh,
    terminate_pod, ssh_cmd, ssh_run, rsync_to_pod, rsync_from_pod,
    SSH_KEY_PATH,
)

GGUF_REPO = "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF"
GGUF_FILE = "qwen2.5-coder-7b-instruct-q4_k_m.gguf"
PORT = 8085


def setup_pod(ip, port):
    """Install deps, upload code, download model, build llama-server."""
    # Phase 1: rsync + pip
    phase1 = """
set -e
export DEBIAN_FRONTEND=noninteractive
which rsync >/dev/null 2>&1 || {
    apt-get update -qq && apt-get install -y -qq rsync 2>&1 | tail -1
}
pip install -q huggingface_hub numpy 2>&1 | tail -1
mkdir -p /root/morphsat /root/sentinel_eval /root/receipts /root/models
echo "Phase 1 done"
"""
    result = ssh_run(ip, port, phase1, timeout=120)
    print(f"    {result.stdout.strip().split(chr(10))[-1]}")

    # Upload code
    print("  Uploading morphsat...")
    rsync_to_pod(ip, port,
                 str(Path.home() / "morphsat" / "morphsat") + "/",
                 "/root/morphsat/morphsat/")
    print("  Uploading sentinel eval...")
    rsync_to_pod(ip, port,
                 str(Path.home() / "tools" / "sentinel" / "eval") + "/",
                 "/root/sentinel_eval/eval/")
    print("  Uploading bench script...")
    rsync_to_pod(ip, port,
                 str(Path.home() / "morphsat" / "tools" / "bench_gate_authority.py"),
                 "/root/")

    # Phase 2: llama-server
    phase2 = """
set -e
export DEBIAN_FRONTEND=noninteractive
which llama-server >/dev/null 2>&1 && { echo "llama-server already installed"; exit 0; }
export PATH="/usr/local/cuda/bin:/usr/local/cuda-11.8/bin:$PATH"
export CUDA_HOME="/usr/local/cuda"
echo "Building llama.cpp..."
apt-get install -y -qq cmake build-essential libcurl4-openssl-dev git 2>&1 | tail -1
cd /tmp
[ -d llama.cpp ] || git clone --depth 1 https://github.com/ggerganov/llama.cpp.git 2>&1 | tail -1
cd llama.cpp
cmake -B build -DGGML_CUDA=ON -DLLAMA_CURL=ON -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc 2>&1 | tail -3
cmake --build build --config Release -j$(nproc) --target llama-server 2>&1 | tail -3
cp build/bin/llama-server /usr/local/bin/
echo "llama-server installed"
"""
    print("  Installing llama-server...")
    result = ssh_run(ip, port, phase2, timeout=1800)
    last_lines = result.stdout.strip().split("\n")[-3:]
    for line in last_lines:
        print(f"    {line}")
    if result.returncode != 0:
        print(f"  FATAL: llama-server build failed: {result.stderr[:300]}")
        sys.exit(1)

    # Phase 3: download model + start server
    phase3 = f"""
set -e
python3 -c "
from huggingface_hub import hf_hub_download
path = hf_hub_download('{GGUF_REPO}', '{GGUF_FILE}', cache_dir='/root/models/hf_cache')
print(f'MODEL_PATH={{path}}')
" > /tmp/model_path.txt
cat /tmp/model_path.txt
MODEL_PATH=$(grep MODEL_PATH /tmp/model_path.txt | cut -d= -f2)

# Kill any existing server
pkill -f llama-server 2>/dev/null || true
sleep 1

# Start server
nohup llama-server -m "$MODEL_PATH" -ngl 99 -c 4096 --port {PORT} \
    > /root/llama_server.log 2>&1 &

# Wait for ready
echo "Waiting for llama-server..."
for i in $(seq 1 90); do
    if curl -s http://localhost:{PORT}/health | grep -q ok; then
        echo "llama-server ready (${{i}}s)"
        exit 0
    fi
    sleep 1
done
echo "FATAL: llama-server did not start"
cat /root/llama_server.log | tail -20
exit 1
"""
    print("  Downloading model + starting server...")
    result = ssh_run(ip, port, phase3, timeout=300)
    for line in result.stdout.strip().split("\n")[-3:]:
        print(f"    {line}")
    if result.returncode != 0:
        print(f"  FATAL: Server start failed: {result.stderr[:300]}")
        sys.exit(1)

    print("  Pod setup complete.")


def run_experiment(ip, port):
    """Run the v8 experiment on the pod."""
    cmd = (
        f"cd /root && "
        f"PYTHONPATH=/root/morphsat:/root/sentinel_eval:$PYTHONPATH "
        f"python3 bench_gate_authority.py --port {PORT} 2>&1"
    )
    print(f"\n  Running v8 gate authority experiment...")
    result = ssh_run(ip, port, cmd, timeout=3600, check=False)
    if result.stdout:
        for line in result.stdout.strip().split("\n"):
            print(f"  [pod] {line}")
    if result.returncode != 0 and result.stderr:
        print(f"  [stderr] {result.stderr[:500]}")
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(
        description="Run v8 gate authority experiment on RunPod")
    parser.add_argument("--pod-id", type=str, default=None)
    parser.add_argument("--no-terminate", action="store_true")
    parser.add_argument("--terminate-only", action="store_true")
    parser.add_argument("--gpu", type=str, default="NVIDIA GeForce RTX 3090")
    args = parser.parse_args()

    if args.terminate_only:
        if not args.pod_id:
            print("--terminate-only requires --pod-id")
            sys.exit(1)
        terminate_pod(args.pod_id)
        return

    print("MORPHSAT v8 GATE AUTHORITY — Pod Runner")
    print(f"  Model: Qwen2.5-Coder-7B Q4_K_M")
    print(f"  Conditions: model_decides, gate_overrides, gate_assists")
    print(f"  Scenarios: 20")
    print()
    check_balance()

    # Create or reuse pod
    if args.pod_id:
        print(f"  Reusing pod: {args.pod_id}")
        pod_id = args.pod_id
    else:
        print(f"  Creating pod (GPU: {args.gpu})...")
        pod_id = create_pod(gpu_type=args.gpu)

    # Save pod ID
    receipt_dir = Path.home() / "receipts" / "morphsat_v8_gate_authority"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    (receipt_dir / "active_pod_id.txt").write_text(pod_id + "\n")
    print(f"  Pod ID saved: {receipt_dir / 'active_pod_id.txt'}")

    # Get SSH
    ip, ssh_port = get_pod_ssh(pod_id)

    # Wait for SSH
    print("  Verifying SSH...", end="", flush=True)
    for attempt in range(30):
        result = ssh_run(ip, ssh_port, "echo OK", timeout=10, check=False)
        if result.returncode == 0 and "OK" in result.stdout:
            print(" connected!")
            break
        time.sleep(2)
        print(".", end="", flush=True)
    else:
        print(" FAILED")
        if not args.no_terminate:
            terminate_pod(pod_id)
        sys.exit(1)

    # Setup
    print("  Setting up pod...")
    setup_pod(ip, ssh_port)

    # Run experiment
    success = run_experiment(ip, ssh_port)

    # Download receipts
    print("\n  Downloading receipts...")
    rsync_from_pod(ip, ssh_port, "/root/receipts/", str(receipt_dir) + "/")
    print(f"  Saved to: {receipt_dir}")

    # List what we got
    for f in sorted(receipt_dir.glob("morphsat_v8_*.json")):
        print(f"    {f.name}")

    # Terminate
    if args.no_terminate:
        print(f"\n  Pod {pod_id} left running.")
        print(f"  SSH: ssh -o StrictHostKeyChecking=no -o IdentitiesOnly=yes "
              f"-i {SSH_KEY_PATH} -p {ssh_port} root@{ip}")
    else:
        print(f"\n  Terminating pod...")
        terminate_pod(pod_id)

    # Check balance
    check_balance()


if __name__ == "__main__":
    main()
