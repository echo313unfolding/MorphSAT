import sys, json, collections
sys.path.insert(0, "/home/user/morphsat"); sys.path.insert(0, "/home/user/morphsat/tools")
import bench_memory_stress as B
from morphsat.shadow_monitor import ShadowMonitor
log = []
orig = ShadowMonitor.close_episode
def wrapped(self, final_resolution, confidence):
    log.append({"monitor_action": self.last_action.action, "monitor_dir": self.last_action.direction,
                "emitted": final_resolution, "graph": self._receipt_graph is not None})
    return orig(self, final_resolution, confidence)
ShadowMonitor.close_episode = wrapped
fams = B.build_stress_families() if hasattr(B, "build_stress_families") else B.STRESS_FAMILIES
out = {}
for mode in "ADHJKLM":
    log.clear()
    r = B.run_stress_mode(mode, fams)
    eps = r.episodes if hasattr(r, "episodes") else [e for f in r.families.values() for e in f.episodes]
    c = collections.Counter()
    for L, e in zip(log, eps):
        mdir = L["monitor_dir"] or "suspicious"   # bench default when direction None
        c["n"] += 1
        if L["emitted"] != mdir:
            c["emitted_ne_monitor"] += 1
            c[f"{L['monitor_action']}:{mdir}->{L['emitted']}|correct={e.verdict_correct}"] += 1
            if L["graph"]: c["graph_vs_memory_divergent_record"] += 1
    out[mode] = dict(c)
print(json.dumps(out, indent=1))
