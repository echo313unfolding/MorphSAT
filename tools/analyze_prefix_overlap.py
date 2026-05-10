"""
analyze_prefix_overlap.py — Offline token-overlap analysis for WO-KVCAS-01 G1 pre-check.

Tokenizes all prompts from the sentinel bench scenarios, computes pairwise
longest common prefix, outputs:
  1. Empirical shared-token percentage (does G1 pass at all?)
  2. Theoretical prefill savings ceiling via (k/n)^2

No cache code touched. No integration risk. Pure measurement.

Usage:
    python tools/analyze_prefix_overlap.py [--tokenizer MODEL_PATH]
"""

import sys
from pathlib import Path

# Import scenarios from bench_morphsat
sys.path.insert(0, str(Path.home() / "tools" / "sentinel"))
from eval.bench_morphsat import BENCHMARK_SCENARIOS, TRIAGE_SYSTEM_PROMPT

# Try to use the actual tokenizer; fall back to whitespace split for estimation
try:
    from transformers import AutoTokenizer
    HAS_TOKENIZER = True
except ImportError:
    HAS_TOKENIZER = False


def longest_common_prefix_len(a: list[int], b: list[int]) -> int:
    """Return length of longest common prefix between two token sequences."""
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n


def theoretical_savings(shared_frac: float) -> float:
    """Prefill cost savings from caching k/n fraction: (k/n)^2."""
    return shared_frac ** 2


def build_prompts_from_bench():
    """Reconstruct the prompts that bench_morphsat.py sends to llama-server."""
    system_prompt = TRIAGE_SYSTEM_PROMPT

    prompts = []
    for scenario in BENCHMARK_SCENARIOS:
        alert = scenario["alert"]
        full_prompt = f"{system_prompt}\n\nAlert: {alert}"
        prompts.append({
            "id": scenario["id"],
            "text": full_prompt,
            "category": scenario["category"],
        })

    return prompts, system_prompt


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--tokenizer", default=None, help="HF model path for tokenizer")
    args = parser.parse_args()

    prompts, system_prompt = build_prompts_from_bench()

    if not prompts:
        print("ERROR: No prompts found in spec")
        sys.exit(1)

    # Tokenize
    if args.tokenizer and HAS_TOKENIZER:
        print(f"Using tokenizer: {args.tokenizer}")
        tok = AutoTokenizer.from_pretrained(args.tokenizer)
        tokenized = [tok.encode(p["text"]) for p in prompts]
        sys_tokens = tok.encode(system_prompt)
    else:
        # Approximate: split on whitespace, hash each word to int
        print("No tokenizer available — using whitespace approximation")
        tokenized = [[hash(w) for w in p["text"].split()] for p in prompts]
        sys_tokens = [hash(w) for w in system_prompt.split()]

    n_prompts = len(tokenized)
    lengths = [len(t) for t in tokenized]

    print(f"\n{'='*64}")
    print(f"PROMPT STATISTICS")
    print(f"{'='*64}")
    print(f"  Scenarios: {n_prompts}")
    print(f"  System prompt tokens: {len(sys_tokens)}")
    print(f"  Prompt lengths: min={min(lengths)} max={max(lengths)} avg={sum(lengths)/len(lengths):.0f}")

    # Pairwise longest common prefix
    print(f"\n{'='*64}")
    print(f"PAIRWISE PREFIX OVERLAP")
    print(f"{'='*64}")

    total_pairs = 0
    total_lcp = 0
    total_shared_frac = 0.0
    min_lcp = float('inf')
    max_lcp = 0

    for i in range(n_prompts):
        for j in range(i + 1, n_prompts):
            lcp = longest_common_prefix_len(tokenized[i], tokenized[j])
            shorter = min(len(tokenized[i]), len(tokenized[j]))
            frac = lcp / shorter if shorter > 0 else 0
            total_pairs += 1
            total_lcp += lcp
            total_shared_frac += frac
            min_lcp = min(min_lcp, lcp)
            max_lcp = max(max_lcp, lcp)

    avg_lcp = total_lcp / total_pairs
    avg_frac = total_shared_frac / total_pairs
    avg_len = sum(lengths) / len(lengths)

    print(f"  Pairs analyzed: {total_pairs}")
    print(f"  LCP: min={min_lcp} max={max_lcp} avg={avg_lcp:.1f}")
    print(f"  Avg shared fraction: {avg_frac:.3f} ({avg_frac*100:.1f}%)")

    # G1 check
    print(f"\n{'='*64}")
    print(f"GATE CHECKS")
    print(f"{'='*64}")

    # G1: if we cache one sequence and look up another, what's the hit rate?
    # Best case: system prompt is the shared prefix
    sys_frac = len(sys_tokens) / avg_len
    print(f"  System prompt fraction of avg prompt: {sys_frac:.3f} ({sys_frac*100:.1f}%)")
    print(f"  Measured pairwise shared fraction: {avg_frac:.3f} ({avg_frac*100:.1f}%)")
    print(f"  G1 (>50% shared): {'PASS' if avg_frac > 0.5 else 'FAIL'} (measured={avg_frac*100:.1f}%)")

    # G2 theoretical ceiling
    savings = theoretical_savings(avg_frac)
    savings_sys = theoretical_savings(sys_frac)
    print(f"\n  Theoretical prefill savings (k/n)^2:")
    print(f"    From measured LCP:      {savings*100:.1f}%")
    print(f"    From system prompt:     {savings_sys*100:.1f}%")
    print(f"  G2 ceiling (>15%): {'PASS' if savings > 0.15 else 'FAIL'} (ceiling={savings*100:.1f}%)")

    # Summary
    print(f"\n{'='*64}")
    print(f"VERDICT")
    print(f"{'='*64}")
    if avg_frac > 0.5 and savings > 0.15:
        print(f"  PROCEED TO PHASE 2 — workload has sufficient prefix sharing")
        print(f"  Expected: {avg_frac*100:.0f}% cache hits, up to {savings*100:.0f}% prefill savings")
    elif avg_frac > 0.3:
        print(f"  MARGINAL — prefix sharing exists but ceiling is low")
        print(f"  Consider: only worth it if prefill is actually the bottleneck")
    else:
        print(f"  CLOSE WO — insufficient prefix sharing for this workload")
        print(f"  Shared fraction {avg_frac*100:.1f}% is too low to justify integration")


if __name__ == "__main__":
    main()
