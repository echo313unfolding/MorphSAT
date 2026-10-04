import sys, json
sys.path.insert(0, "/home/user/morphsat"); sys.path.insert(0, "/home/user/morphsat/tools")
import bench_memory_stress as B
from morphsat.shadow_monitor import ShadowMonitor
from morphsat.two_stage_gate import TwoStageGate
from morphsat.correction_echo import CorrectionEcho
cur = {}
o_close, o_dec, o_chk = ShadowMonitor.close_episode, TwoStageGate.decide, CorrectionEcho.check
def close(self, res, conf):
    cur.update(mon=(self.last_action.action, self.last_action.direction), emitted=res,
               t=round(self.threat_score,3), s=round(self.safety_score,3), state=self.state.value)
    rows.append(dict(cur)); cur.clear(); return o_close(self, res, conf)
def dec(self, snap):
    r = o_dec(self, snap); cur.update(backend=r.gate_backend_used, reason=r.routing_reason, ts=(r.action, r.direction),
        mem_in=snap.memory_outcome); return r
def chk(self, alert):
    trig, m = o_chk(self, alert); cur.update(echo=trig, echo_out=(m.outcome_after if m else None),
        echo_cc=(m.contradiction_count if m else None)); return trig, m
ShadowMonitor.close_episode, TwoStageGate.decide, CorrectionEcho.check = close, dec, chk
for mode in "JM":
    rows = []
    r = B.run_stress_mode(mode, B.STRESS_FAMILIES)
    eps = [e for f in r.families.values() for e in f.episodes]
    for row, e in zip(rows, eps):
        if row["emitted"] != (row["mon"][1] or "suspicious"):
            print(mode, e.scenario_id, e.family, "expected=", e.category, json.dumps(row))
