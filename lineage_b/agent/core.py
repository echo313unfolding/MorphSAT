"""Agent: frozen predictor + sensor model + controller (B0 §7–§9).
Consumes only delivered Records; commits receipts before each transition."""

from __future__ import annotations

import hashlib
from typing import Dict, List, Optional

from lineage_b.agent import predictor as pr
from lineage_b.agent.authority import monitor
from lineage_b.obs import Record
from lineage_b.params import COSTS, DU, H_SET, R_COOL, R_REP, TAU_I
from lineage_b.receipts import ReceiptStore, canonical

CANDIDATES = ("hold", "open", "close")          # tie-break order


def _u_after(u: float, a: str) -> float:
    return min(1.0, max(0.0, u + (DU if a == "open" else -DU if a == "close" else 0.0)))


class Agent:
    def __init__(self, sensor_model, updater: Optional[str] = None, arm: str = "G0"):
        self.model = sensor_model
        self.updater = updater          # None (G0) or "receipt" (G2-style reference; infrastructure)
        self.arm = arm
        self.log: List[dict] = []       # skipped / no-op updates (gate 6)
        self.assim_log: List[dict] = []  # belief left unchanged: all component likelihoods underflowed (v1.3 §1.4)

    # -- episode ----------------------------------------------------------
    def begin_episode(self, episode: int, g0: int, store: ReceiptStore, u0: float = 0.5):
        self.episode, self.g0, self.store, self.u = episode, g0, store, u0
        self.B = pr.initial_belief()
        self.records: Dict[tuple, Record] = {}
        self.repairs = set()
        self.last_inspect: Optional[int] = None
        self.sensors_seen = set()
        self._vis = hashlib.sha256()

    # -- observation --------------------------------------------------------
    def observe(self, t: int, delivered: List[Record]) -> List[dict]:
        infos = []
        fresh: Dict[str, float] = {}
        for r in delivered:
            if r.key in self.records:                       # transport redelivery: once (gate 14)
                self.log.append({"t": t, "skip": "redelivery", "key": r.key})
                continue
            self.records[r.key] = r
            self._vis.update(canonical([r.sensor_id, r.seq, r.measured_at, r.delivered_at, r.value]).encode())
            if r.sensor_id == "INSPECT":
                self.B = pr.assimilate_inspection(self.B, r.value)
                if r.value == "LEAK_FOUND":
                    self.repairs.add(r.measured_at + R_REP)
                continue
            self.sensors_seen.add(r.sensor_id)
            info = self._feedback(r)
            if info is not None:
                infos.append(info)
            if r.measured_at == t:
                fresh[r.sensor_id] = r.value
        if fresh:
            self.B, underflow = self.model.assimilate(self.B, fresh, self.u, self.g0 + t)
            if underflow:
                self.assim_log.append({"t": t, "underflow": underflow})
        return infos

    def _feedback(self, r: Record) -> Optional[dict]:
        key = (self.episode, r.measured_at)
        if not self.store.has(key):
            self.log.append({"skip": "no_receipt", "key": r.key})
            return None
        pay = self.store.payload(key)
        if r.sensor_id not in pay["sensors"]:
            self.log.append({"skip": "sensor_not_in_receipt", "key": r.key})
            return None
        before = self.model.theta_hash()
        applied = False
        if self.updater == "receipt":
            sp = pay["sensors"][r.sensor_id]
            self.model.update(r.sensor_id, r.value - sp["latent_mean"], sp["latent_var"])
            applied = True
        return {"record": r, "receipt_key": key, "receipt_hash": self.store.hash_of(key),
                "decision_key": tuple(pay["decision_key"]), "theta_before": before,
                "theta_after": self.model.theta_hash(), "applied": applied}

    # -- decision -------------------------------------------------------------
    def belief_summary(self) -> Dict[str, float]:
        m, sd, p_leak = pr.summary(self.B)
        return {"mean_h": m, "sd_h": sd, "p_leak": p_leak, "digest": self.B.digest()}

    def decide(self, t: int) -> dict:
        mon = monitor(self.records, t)
        p_leak = float(self.B.pi[:, 1:].sum())
        costs = {}
        for a in CANDIDATES:
            Bp = pr.predict(self.B, _u_after(self.u, a), False)
            costs[a] = COSTS["D"] * pr.expected_sq_dev(Bp, H_SET) + COSTS["U"] * pr.p_unsafe(Bp) \
                + (COSTS["M"] if a != "hold" else 0.0)
        cool = self.last_inspect is None or t - self.last_inspect >= R_COOL
        if p_leak >= TAU_I and cool:
            proposal, why = "inspect", "p_leak"
        else:
            proposal = min(CANDIDATES, key=lambda a: (costs[a], CANDIDATES.index(a)))
            why = "min_expected_cost"
        return {"monitor": mon, "proposal": proposal,
                "reason": {"costs": costs, "p_leak": p_leak, "trigger": why},
                "belief": self.belief_summary(), "theta_hash": self.model.theta_hash(),
                "visible_digest": self._vis.hexdigest()}

    def theta_view(self):
        return {s: self.model.params(s, 0) for s in sorted(self.sensors_seen | {"L1", "L2", "L3", "F", "P"})}

    # -- prediction receipt (before the transition) ---------------------------
    def commit_prediction(self, t: int, final_action: str) -> str:
        u_new = _u_after(self.u, final_action)
        Bp = pr.predict(self.B, u_new, (t + 1) in self.repairs)
        sensors = {}
        for s in sorted(self.sensors_seen | {"L1", "L2", "L3", "F", "P"}):
            p = self.model.params(s, self.g0 + t + 1)
            if p is None:
                continue
            probs, m, s2 = pr.categorical(s, Bp, u_new, *p)
            sensors[s] = {"probs": probs.tolist(), "b": p[0], "sigma": p[1],
                          "latent_mean": m, "latent_var": s2}
        payload = {"arm": self.arm, "action": final_action, "u_next": u_new, "t_target": t + 1,
                   "theta_hash": self.model.theta_hash(), "decision_key": [self.episode, t],
                   "belief_digest": Bp.digest(), "sensors": sensors}
        h = self.store.commit((self.episode, t + 1), payload)
        self.B, self.u = Bp, u_new
        if final_action == "inspect":
            self.last_inspect = t
        return h
