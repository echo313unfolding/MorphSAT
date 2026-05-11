"""
MorphSAT v9 Recomputation Gate — dual-agent independent verification.

Unconditional dual-agent: every security verdict is independently recomputed
by a second agent with a different prompt framing. Disagreement = escalate.

Pre-flight receipt (WO-RECOMP-04) proved:
  - Cost-gating is UNSAFE (overconfident wrong answers at 0.95 conf)
  - Disagreement precision is 100% (every disagreement involved a real error)
  - Prompt independence is sufficient (same model, different framing)

Architecture:
    Agent A (primary)   ──┐
                          ├── Agreement Gate → EMIT or ESCALATE
    Agent B (verifier)  ──┘

    Both agents:
      - Get same alert + same tool simulation
      - Run under MorphSAT FSA (MIN_TOOLS_BEFORE_VERDICT enforced)
      - Never see each other's output
      - Produce independent verdicts

    Agreement Gate:
      - MATCH   → emit verdict (confidence = min of both)
      - MISMATCH → ESCALATE with both reasoning chains attached

Receipt: ~/receipts/wo_recomp_04/recomp_gate_bench_20260511T035503Z.json
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple


class RecompVerdict(Enum):
    """Outcome of the dual-agent recomputation gate."""
    AGREED = "agreed"           # Both agents reached same verdict
    ESCALATED = "escalated"     # Agents disagreed — route to human
    INCOMPLETE = "incomplete"   # One or both agents failed to produce verdict


@dataclass
class AgentResult:
    """Result from a single agent run."""
    agent_id: str
    verdict: Optional[str]
    confidence: Optional[float]
    reasoning: Optional[str]
    tool_calls: List[Dict]
    n_turns: int
    wall_time_s: float
    raw: Optional[Dict] = None


@dataclass
class DualAgentVerdict:
    """Output of the recomputation gate."""
    outcome: RecompVerdict
    final_verdict: Optional[str]       # None if escalated
    final_confidence: Optional[float]  # min(a, b) if agreed
    agent_a: AgentResult
    agent_b: AgentResult
    disagreement_detail: Optional[str]  # Why they disagreed (for human reviewer)
    wall_time_s: float

    @property
    def agreed(self) -> bool:
        return self.outcome == RecompVerdict.AGREED

    @property
    def escalated(self) -> bool:
        return self.outcome == RecompVerdict.ESCALATED

    def to_receipt(self) -> Dict:
        return {
            "outcome": self.outcome.value,
            "final_verdict": self.final_verdict,
            "final_confidence": self.final_confidence,
            "agent_a_verdict": self.agent_a.verdict,
            "agent_a_confidence": self.agent_a.confidence,
            "agent_b_verdict": self.agent_b.verdict,
            "agent_b_confidence": self.agent_b.confidence,
            "agreed": self.agreed,
            "wall_time_s": self.wall_time_s,
        }


# Type for the agent runner function
AgentRunner = Callable[[str, str, Any], AgentResult]
# Signature: (system_prompt, alert_text, context) -> AgentResult


class DualAgentGate:
    """Unconditional dual-agent recomputation gate.

    Runs two independent agents on the same input, compares verdicts.
    No confidence gating. No shortcuts. Every verdict is recomputed.

    Usage:
        gate = DualAgentGate(
            primary_prompt=TRIAGE_PROMPT,
            verifier_prompt=ANALYST_PROMPT,
            runner=my_agent_runner,
        )
        result = gate.run(alert_text="...", context={})
        if result.escalated:
            route_to_human(result)
        else:
            emit_verdict(result.final_verdict)
    """

    def __init__(
        self,
        primary_prompt: str,
        verifier_prompt: str,
        runner: AgentRunner,
        normalize_verdict: Optional[Callable[[str], str]] = None,
    ):
        self.primary_prompt = primary_prompt
        self.verifier_prompt = verifier_prompt
        self.runner = runner
        self.normalize_verdict = normalize_verdict or (lambda v: v.lower().strip())

    def run(self, alert_text: str, context: Any = None) -> DualAgentVerdict:
        """Run both agents, compare, return gated verdict."""
        t_start = time.time()

        # Run independently — Agent B never sees Agent A's output
        result_a = self.runner(self.primary_prompt, alert_text, context)
        result_b = self.runner(self.verifier_prompt, alert_text, context)

        wall_total = round(time.time() - t_start, 3)

        # Normalize verdicts for comparison
        v_a = self.normalize_verdict(result_a.verdict) if result_a.verdict else None
        v_b = self.normalize_verdict(result_b.verdict) if result_b.verdict else None

        # Determine outcome
        if v_a is None or v_b is None:
            outcome = RecompVerdict.INCOMPLETE
            final_verdict = None
            final_confidence = None
            detail = (f"Agent {'A' if v_a is None else 'B'} failed to produce verdict. "
                      f"A={v_a}, B={v_b}")
        elif v_a == v_b:
            outcome = RecompVerdict.AGREED
            final_verdict = v_a
            # Conservative: take min confidence
            conf_a = result_a.confidence or 0.0
            conf_b = result_b.confidence or 0.0
            final_confidence = min(conf_a, conf_b)
            detail = None
        else:
            outcome = RecompVerdict.ESCALATED
            final_verdict = None
            final_confidence = None
            detail = (f"Agent A: {v_a} (conf={result_a.confidence}). "
                      f"Agent B: {v_b} (conf={result_b.confidence}). "
                      f"Disagreement on same inputs — routing to human review.")

        return DualAgentVerdict(
            outcome=outcome,
            final_verdict=final_verdict,
            final_confidence=final_confidence,
            agent_a=result_a,
            agent_b=result_b,
            disagreement_detail=detail,
            wall_time_s=wall_total,
        )


# ─── Default prompts ──────────────────────────────────────────────────────

TRIAGE_SYSTEM_PROMPT = """You are a security triage agent. Analyze alerts step by step.

Available tools:
- check_hash: Look up a file hash. Args: {"path": "/path/to/file"}
- check_process: Check running processes. Args: {"filter": "keyword"}
- check_ports: List listening ports. Args: {}
- scan_file: YARA scan a file. Args: {"path": "/path/to/file"}
- search_cve: Search CVE database. Args: {"query": "CVE-ID or keyword"}

To use a tool, output:
```tool_call
{"name": "tool_name", "arguments": {"key": "value"}}
```

After investigating, output your verdict:
```verdict
{"verdict": "benign|suspicious|escalate", "confidence": 0.0-1.0, "reasoning": "brief explanation"}
```

IMPORTANT: Investigate BEFORE issuing a verdict. Use at least one tool to gather evidence."""

VERIFIER_SYSTEM_PROMPT = """You are an independent security analyst performing a second-opinion review.

You are given a security alert. Analyze it independently using the available tools.
Do NOT assume any prior analysis has been done. Form your own conclusion from scratch.

Available tools:
- check_hash: Look up a file hash. Args: {"path": "/path/to/file"}
- check_process: Check running processes. Args: {"filter": "keyword"}
- check_ports: List listening ports. Args: {}
- scan_file: YARA scan a file. Args: {"path": "/path/to/file"}
- search_cve: Search CVE database. Args: {"query": "CVE-ID or keyword"}

To use a tool, output:
```tool_call
{"name": "tool_name", "arguments": {"key": "value"}}
```

After investigating, output your assessment:
```verdict
{"verdict": "benign|suspicious|escalate", "confidence": 0.0-1.0, "reasoning": "brief explanation"}
```

Be thorough. Use at least one tool before concluding. Err on the side of caution — if evidence is ambiguous, escalate rather than dismiss."""
