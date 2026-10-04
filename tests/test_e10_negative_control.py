"""
E10 negative control (Phase 2.5, preregistered).

The GraphRoutingSignal observables

    drift_like, stale_memory_like, poisoned_memory_like,
    sensor_graph_conflict, routing_triggered

are computed but have no behavioral consumer at public GitHub state
14689b7. They are retained as a negative-control channel: ablating or
inverting them MUST NOT change behavior. If any test here fails, either
the system changed (E10 got wired) or an intervention harness is broken.
"""

import ast
import itertools
import sys
from dataclasses import asdict, fields
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

from morphsat.decision_event import E10_OBSERVABLES  # noqa: E402
from morphsat.gate_qubo import GateSnapshot  # noqa: E402
from morphsat.graph_routing_signal import (  # noqa: E402
    GraphRoutingSignal,
    apply_graph_signal_to_snapshot,
)

DECISION_MODULES = [
    "two_stage_gate.py", "gate_qubo.py", "shadow_monitor.py",
    "correction_echo.py", "memory_qubo.py", "commit_gate.py",
    "receipt_graph.py",
]


def _referenced_names(tree):
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.add(n.value)
    return out


class TestStructural:
    def test_gate_snapshot_has_no_e10_fields(self):
        assert not {f.name for f in fields(GateSnapshot)} & set(E10_OBSERVABLES)

    @pytest.mark.parametrize("module", DECISION_MODULES)
    def test_decision_modules_never_reference_e10(self, module):
        tree = ast.parse((ROOT / "morphsat" / module).read_text())
        assert not _referenced_names(tree) & set(E10_OBSERVABLES), module

    def test_apply_graph_signal_ignores_e10(self):
        src = (ROOT / "morphsat" / "graph_routing_signal.py").read_text()
        fn = next(n for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "apply_graph_signal_to_snapshot")
        assert not _referenced_names(fn) & set(E10_OBSERVABLES)


class TestUnitInvariance:
    @pytest.mark.parametrize("flags", list(itertools.product([False, True],
                                                             repeat=5)))
    def test_snapshot_mapping_invariant_to_e10(self, flags):
        base = GraphRoutingSignal(graph_memory_outcome="escalate",
                                  graph_memory_confidence=0.7,
                                  graph_memory_exposures=3,
                                  correction_related=False)
        flipped = GraphRoutingSignal(**{**asdict(base),
                                        **dict(zip(E10_OBSERVABLES, flags))})
        args = ("unknown", 0.0, 0, False)
        assert apply_graph_signal_to_snapshot(base, *args) == \
               apply_graph_signal_to_snapshot(flipped, *args)


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    import bench_memory_stress as B
    from test_decision_event import _isolate_bench

    mp = pytest.MonkeyPatch()
    _isolate_bench(B, mp, tmp_path_factory.mktemp("e10_iso"))
    modes = "LM"   # the only modes that compute GraphRoutingSignal
    try:
        control = {m: B.run_stress_mode(m, B.STRESS_FAMILIES) for m in modes}
        real = B.extract_graph_routing_signal

        def inverted(*a, **kw):
            sig = real(*a, **kw)
            for k in E10_OBSERVABLES:
                setattr(sig, k, not getattr(sig, k))
            return sig

        mp.setattr(B, "extract_graph_routing_signal", inverted)
        ablated = {m: B.run_stress_mode(m, B.STRESS_FAMILIES) for m in modes}
    finally:
        mp.undo()
    return control, ablated


class TestEndToEndAblation:
    """Invert every E10 flag inside the live benchmark; behavior must not move."""

    def test_ablation_actually_applied(self, results):
        control, ablated = results
        for m in control:
            c = [e.e10_observed for e in control[m].decision_events]
            a = [e.e10_observed for e in ablated[m].decision_events]
            assert any(x is not None for x in c), m
            assert c != a, f"ablation did not change E10 observables in {m}"

    def test_behavior_identical_under_ablation(self, results):
        control, ablated = results
        for m in control:
            assert [asdict(e) for e in control[m].episodes] == \
                   [asdict(e) for e in ablated[m].episodes], m
            assert control[m].to_dict() == ablated[m].to_dict(), m

    def test_decision_chain_identical_except_e10(self, results):
        control, ablated = results
        for m in control:
            for c, a in zip(control[m].decision_events,
                            ablated[m].decision_events):
                cd, ad = c.payload(), a.payload()
                cd.pop("e10_observed"); ad.pop("e10_observed")
                assert cd == ad, (m, c.scenario_id)
