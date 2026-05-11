"""Tests for MorphSAT v9 DualAgentGate (recomputation gate)."""

import pytest
from morphsat.recomp_gate import (
    DualAgentGate,
    DualAgentVerdict,
    AgentResult,
    RecompVerdict,
    TRIAGE_SYSTEM_PROMPT,
    VERIFIER_SYSTEM_PROMPT,
)


def make_result(agent_id: str, verdict: str, confidence: float = 0.8) -> AgentResult:
    """Helper to build a minimal AgentResult."""
    return AgentResult(
        agent_id=agent_id,
        verdict=verdict,
        confidence=confidence,
        reasoning=f"Test reasoning for {verdict}",
        tool_calls=[{"name": "check_hash", "arguments": {"path": "/tmp/test"}}],
        n_turns=3,
        wall_time_s=1.0,
    )


def make_runner(verdict_a: str, verdict_b: str,
                conf_a: float = 0.8, conf_b: float = 0.7):
    """Create a deterministic runner that returns fixed verdicts."""
    call_count = [0]

    def runner(system_prompt: str, alert_text: str, context=None) -> AgentResult:
        call_count[0] += 1
        if call_count[0] == 1:
            return make_result("primary", verdict_a, conf_a)
        else:
            return make_result("verifier", verdict_b, conf_b)

    return runner


# ─── Agreement tests ──────────────────────────────────────────────────────

class TestAgreement:
    def test_both_agree_benign(self):
        gate = DualAgentGate(
            primary_prompt=TRIAGE_SYSTEM_PROMPT,
            verifier_prompt=VERIFIER_SYSTEM_PROMPT,
            runner=make_runner("benign", "benign", 0.9, 0.8),
        )
        result = gate.run("test alert")
        assert result.outcome == RecompVerdict.AGREED
        assert result.final_verdict == "benign"
        assert result.final_confidence == 0.8  # min(0.9, 0.8)
        assert result.agreed is True
        assert result.escalated is False

    def test_both_agree_escalate(self):
        gate = DualAgentGate(
            primary_prompt=TRIAGE_SYSTEM_PROMPT,
            verifier_prompt=VERIFIER_SYSTEM_PROMPT,
            runner=make_runner("escalate", "escalate", 0.95, 0.9),
        )
        result = gate.run("test alert")
        assert result.outcome == RecompVerdict.AGREED
        assert result.final_verdict == "escalate"
        assert result.final_confidence == 0.9

    def test_both_agree_suspicious(self):
        gate = DualAgentGate(
            primary_prompt=TRIAGE_SYSTEM_PROMPT,
            verifier_prompt=VERIFIER_SYSTEM_PROMPT,
            runner=make_runner("suspicious", "suspicious"),
        )
        result = gate.run("test alert")
        assert result.outcome == RecompVerdict.AGREED
        assert result.final_verdict == "suspicious"


# ─── Disagreement tests ───────────────────────────────────────────────────

class TestDisagreement:
    def test_disagree_benign_vs_escalate(self):
        gate = DualAgentGate(
            primary_prompt=TRIAGE_SYSTEM_PROMPT,
            verifier_prompt=VERIFIER_SYSTEM_PROMPT,
            runner=make_runner("benign", "escalate", 0.9, 0.85),
        )
        result = gate.run("test alert")
        assert result.outcome == RecompVerdict.ESCALATED
        assert result.final_verdict is None
        assert result.escalated is True
        assert result.agreed is False
        assert "Disagreement" in result.disagreement_detail

    def test_disagree_suspicious_vs_escalate(self):
        gate = DualAgentGate(
            primary_prompt=TRIAGE_SYSTEM_PROMPT,
            verifier_prompt=VERIFIER_SYSTEM_PROMPT,
            runner=make_runner("suspicious", "escalate"),
        )
        result = gate.run("test alert")
        assert result.outcome == RecompVerdict.ESCALATED
        assert result.final_verdict is None

    def test_disagree_benign_vs_suspicious(self):
        gate = DualAgentGate(
            primary_prompt=TRIAGE_SYSTEM_PROMPT,
            verifier_prompt=VERIFIER_SYSTEM_PROMPT,
            runner=make_runner("benign", "suspicious"),
        )
        result = gate.run("test alert")
        assert result.outcome == RecompVerdict.ESCALATED


# ─── Incomplete tests ─────────────────────────────────────────────────────

class TestIncomplete:
    def test_agent_a_no_verdict(self):
        def runner(prompt, alert, ctx=None):
            if "triage" in prompt.lower():
                return AgentResult("primary", None, None, None, [], 3, 1.0)
            return make_result("verifier", "escalate")

        gate = DualAgentGate(
            primary_prompt=TRIAGE_SYSTEM_PROMPT,
            verifier_prompt=VERIFIER_SYSTEM_PROMPT,
            runner=runner,
        )
        result = gate.run("test alert")
        assert result.outcome == RecompVerdict.INCOMPLETE

    def test_agent_b_no_verdict(self):
        def runner(prompt, alert, ctx=None):
            if "independent" in prompt.lower():
                return AgentResult("verifier", None, None, None, [], 3, 1.0)
            return make_result("primary", "benign")

        gate = DualAgentGate(
            primary_prompt=TRIAGE_SYSTEM_PROMPT,
            verifier_prompt=VERIFIER_SYSTEM_PROMPT,
            runner=runner,
        )
        result = gate.run("test alert")
        assert result.outcome == RecompVerdict.INCOMPLETE


# ─── Normalization tests ──────────────────────────────────────────────────

class TestNormalization:
    def test_case_insensitive_match(self):
        gate = DualAgentGate(
            primary_prompt=TRIAGE_SYSTEM_PROMPT,
            verifier_prompt=VERIFIER_SYSTEM_PROMPT,
            runner=make_runner("Escalate", "ESCALATE"),
        )
        result = gate.run("test alert")
        assert result.outcome == RecompVerdict.AGREED
        assert result.final_verdict == "escalate"

    def test_whitespace_stripped(self):
        gate = DualAgentGate(
            primary_prompt=TRIAGE_SYSTEM_PROMPT,
            verifier_prompt=VERIFIER_SYSTEM_PROMPT,
            runner=make_runner("  benign  ", "benign\n"),
        )
        result = gate.run("test alert")
        assert result.outcome == RecompVerdict.AGREED

    def test_custom_normalizer(self):
        # Map "safe" to "benign" via custom normalizer
        def norm(v):
            v = v.lower().strip()
            return "benign" if v == "safe" else v

        gate = DualAgentGate(
            primary_prompt=TRIAGE_SYSTEM_PROMPT,
            verifier_prompt=VERIFIER_SYSTEM_PROMPT,
            runner=make_runner("safe", "benign"),
            normalize_verdict=norm,
        )
        result = gate.run("test alert")
        assert result.outcome == RecompVerdict.AGREED


# ─── Receipt tests ────────────────────────────────────────────────────────

class TestReceipt:
    def test_receipt_structure(self):
        gate = DualAgentGate(
            primary_prompt=TRIAGE_SYSTEM_PROMPT,
            verifier_prompt=VERIFIER_SYSTEM_PROMPT,
            runner=make_runner("escalate", "escalate", 0.9, 0.85),
        )
        result = gate.run("test alert")
        receipt = result.to_receipt()

        assert receipt["outcome"] == "agreed"
        assert receipt["final_verdict"] == "escalate"
        assert receipt["final_confidence"] == 0.85
        assert receipt["agreed"] is True
        assert "wall_time_s" in receipt

    def test_escalated_receipt(self):
        gate = DualAgentGate(
            primary_prompt=TRIAGE_SYSTEM_PROMPT,
            verifier_prompt=VERIFIER_SYSTEM_PROMPT,
            runner=make_runner("benign", "escalate"),
        )
        result = gate.run("test alert")
        receipt = result.to_receipt()

        assert receipt["outcome"] == "escalated"
        assert receipt["final_verdict"] is None
        assert receipt["agreed"] is False


# ─── Independence tests ───────────────────────────────────────────────────

class TestIndependence:
    """Verify that both agents are called and receive different prompts."""

    def test_both_agents_called(self):
        calls = []

        def tracking_runner(prompt, alert, ctx=None):
            calls.append(prompt[:30])
            return make_result("agent", "suspicious")

        gate = DualAgentGate(
            primary_prompt="PRIMARY: " + TRIAGE_SYSTEM_PROMPT,
            verifier_prompt="VERIFIER: " + VERIFIER_SYSTEM_PROMPT,
            runner=tracking_runner,
        )
        gate.run("test alert")
        assert len(calls) == 2
        assert calls[0] != calls[1]  # Different prompts
        assert "PRIMARY" in calls[0]
        assert "VERIFIER" in calls[1]
