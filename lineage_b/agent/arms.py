"""B1 learning arms (B1 prereg v1.5 @ 2473c2a §3). Agent side: sees only
delivered Records, its own receipts and its own learned (b, sigma).

* G2  : ``B1Agent(SensorModel(), "receipt")``. Reference = latent mean/var of
        the frozen pre-action receipt for the record's measured_at step.
* G1  : ``B1Agent(SensorModel(), "consensus")``. Reference = same-time
        leave-one-out precision-weighted static fusion of the *other*
        sensors' readings for the same measured_at step (no dynamics, no
        action).
* G2-S: ``B1Agent(SensorModel(), "sham")``. As G2, but the reference is a
        prediction for a sham action committed in the same receipt. The sham
        action enters ONLY ``receipt["sham"]``; belief propagation, the
        executed action and every authority input use the true action.
* G3  : ``B1Agent(DependencyModel(), "receipt")``. As G2, plus a
        dependency-aware likelihood over ``declared_upstream`` groups
        (shared variance tau^2 and a group bias) and relay copies collapsed
        onto their declared source. Dependency metadata changes the
        likelihood only; it is never an authority or credibility signal.

The frozen predictor (lineage_b.agent.predictor) is used unchanged. No
function here builds a predictive distribution except through
``predictor.predict`` / ``predictor.categorical``.
"""

from __future__ import annotations

import hashlib
import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from lineage_b.agent import predictor as pr
from lineage_b.agent.core import Agent, _u_after
from lineage_b.agent.sensor_model import SensorModel
from lineage_b.obs import Record
from lineage_b.params import (CV, D_MAX, ETA_B, ETA_S, KIND, NOMINAL_SIGMA, P_GAIN,
                              SIGMA_MIN_FRAC)
from lineage_b.receipts import canonical

UPDATERS = (None, "receipt", "consensus", "sham")
BASE = ("L1", "L2", "L3", "F", "P")


# ---------------------------------------------------------------- G1 reference
def level_equivalent(sensor: str, y: float, b: float, sigma: float, u: float) -> Optional[Tuple[float, float]]:
    """Static measurement equation inverted to a level estimate (h_hat, var).
    Flow uses the first-order (delta-method) inverse of q = Cv*u*sqrt(h); it
    carries no level information when u = 0 or the corrected reading <= 0."""
    k = KIND[sensor]
    if k == "level":
        return y - b, sigma ** 2
    if k == "pressure":
        return (y - b) / P_GAIN, (sigma / P_GAIN) ** 2
    q = y - b
    if u <= 0.0 or q <= 0.0:
        return None
    h = (q / (CV * u)) ** 2
    dh_dq = 2.0 * q / (CV * u) ** 2
    return h, (dh_dq * sigma) ** 2


def to_sensor_units(sensor: str, h: float, var_h: float, u: float) -> Optional[Tuple[float, float]]:
    """Map a fused level (h, var_h) to sensor i's measured quantity (mean, var)."""
    k = KIND[sensor]
    if k == "level":
        return h, var_h
    if k == "pressure":
        return P_GAIN * h, P_GAIN ** 2 * var_h
    if u <= 0.0 or h <= 0.0:
        return None
    g = CV * u / (2.0 * math.sqrt(h))
    return CV * u * math.sqrt(h), g * g * var_h


def consensus_reference(target: str, others: Dict[str, float], params, u: float):
    """Leave-one-out precision-weighted fusion of the other sensors' same-time
    readings, returned in the target sensor's units as (m_ref, s2_ref)."""
    num = den = 0.0
    for s, y in others.items():
        if s == target:
            continue
        b, sig = params(s)
        le = level_equivalent(s, y, b, sig, u)
        if le is None or not (le[1] > 0.0) or not math.isfinite(le[0]):
            continue
        num += le[0] / le[1]
        den += 1.0 / le[1]
    if den <= 0.0:
        return None
    return to_sensor_units(target, num / den, 1.0 / den, u)


# ---------------------------------------------------------------- G3 model
class DependencyModel:
    """G2's (b, sigma) plus a dependency-aware likelihood over declared_upstream
    groups.

    * A group (>= 2 sensors sharing a non-relay declared_upstream, here ADC_A:
      L1, L2) has a shared variance component tau^2 and a group bias b_g;
      each member keeps an individual deviation d_i and individual sigma_i.
      Effective bias b_i = b_g + d_i; marginal sd = sqrt(tau^2 + sigma_i^2).
    * Joint group likelihood via the frozen ``predictor.assimilate(joint_l12=R)``,
      R = [[tau^2 + s1^2, tau^2], [tau^2, tau^2 + s2^2]].
    * Relay copies (declared_upstream "relay:X") are collapsed onto X: dropped
      when X is present for the same step, else used as X.
    * Initial state: b_g = d_i = 0, tau^2 = 0, sigma_i = nominal marginal, i.e.
      G3 starts identical to G2 and must learn any shared component.
    """

    GROUP = ("L1", "L2")

    def __init__(self):
        self.base = SensorModel()
        self.b_g = 0.0
        self.d = {s: 0.0 for s in self.GROUP}
        self.tau2 = 0.0
        self.c: Optional[float] = None
        self.v = {s: None for s in self.GROUP}
        self.sig = {s: NOMINAL_SIGMA[s] for s in self.GROUP}
        self.relays: Dict[str, str] = {}

    def note_relay(self, sensor: str, declared_upstream: str):
        if declared_upstream.startswith("relay:"):
            self.relays[sensor] = declared_upstream.split(":", 1)[1]

    def source_of(self, s: str) -> str:
        return self.relays.get(s, s)

    def params(self, s: str, g: int):
        s = self.source_of(s)
        if s in self.GROUP:
            return self.b_g + self.d[s], math.sqrt(self.tau2 + self.sig[s] ** 2)
        return self.base.params(s, g)

    def joint_R(self):
        t = self.tau2
        s1, s2 = self.sig["L1"] ** 2, self.sig["L2"] ** 2
        return np.array([[t + s1, t], [t, t + s2]])

    def collapse(self, fresh: Dict[str, float]) -> Dict[str, float]:
        out = {}
        for s, y in fresh.items():
            src = self.source_of(s)
            if src != s:
                if src not in fresh:
                    out[src] = y
                continue
            out[s] = y
        return out

    def assimilate(self, B, fresh: Dict[str, float], u: float, g: int):
        return pr.assimilate(B, self.collapse(fresh), u, lambda s: self.params(s, g),
                             joint_l12=self.joint_R())

    # -- learning (matched rule form, B1 §3) --------------------------------
    def update(self, s: str, residual: float, ref_var: float) -> None:
        """Non-group sensors: identical to G2."""
        self.base.update(s, residual, ref_var)

    def update_group(self, residuals: Dict[str, float], ref_var: float) -> None:
        """One update per (group, measured_at) slot with the members present."""
        rbar = sum(residuals.values()) / len(residuals)
        self.b_g += ETA_B * (rbar - self.b_g)
        for s, r in residuals.items():
            self.d[s] += ETA_B * ((r - rbar) - self.d[s])
        e = {s: r - (self.b_g + self.d[s]) for s, r in residuals.items()}
        if len(e) == 2:
            prod = e["L1"] * e["L2"]
            if self.c is None:
                self.c = ref_var
            self.c = (1 - ETA_S) * self.c + ETA_S * prod
            self.tau2 = max(0.0, self.c - ref_var)
        for s, es in e.items():
            if self.v[s] is None:
                self.v[s] = NOMINAL_SIGMA[s] ** 2 + ref_var
            self.v[s] = (1 - ETA_S) * self.v[s] + ETA_S * es * es
            smin = SIGMA_MIN_FRAC * NOMINAL_SIGMA[s]
            self.sig[s] = math.sqrt(max(smin ** 2, self.v[s] - ref_var - self.tau2))

    def theta_hash(self) -> str:
        d = {"base": self.base.theta_hash(), "b_g": self.b_g, "d": self.d, "tau2": self.tau2,
             "c": self.c, "v": self.v, "sig": self.sig, "relays": self.relays}
        return hashlib.sha256(canonical(d).encode()).hexdigest()


# ---------------------------------------------------------------- B1 agent
class B1Agent(Agent):
    """core.Agent with the B1 reference rules. Decision, authority and belief
    propagation are inherited unchanged; only learning and receipt contents
    differ."""

    def __init__(self, sensor_model, updater: Optional[str] = None, arm: str = "G0"):
        if updater not in UPDATERS:
            raise ValueError(updater)
        super().__init__(sensor_model, updater=updater if updater == "receipt" else None, arm=arm)
        self.b1_updater = updater
        self.sham: Dict[Tuple[int, int], str] = {}      # (episode, t) -> sham action (G2-S only)
        self.theta_trace: List[Tuple[int, int, str]] = []

    def set_sham_schedule(self, schedule: Dict[Tuple[int, int], str]):
        if self.b1_updater != "sham":
            raise RuntimeError("sham schedule only for G2-S")
        self.sham = dict(schedule)

    def begin_episode(self, episode, g0, store, u0=0.5):
        # G3: slots still open at the previous episode's end close now, before
        # any decision of the new episode (future-only influence preserved)
        for m in sorted(getattr(self, "pending_group", {})):
            self.model.update_group(self.pending_group[m], self.pending_ref_var[m])
            self.log.append({"group_update": m, "members": sorted(self.pending_group[m]), "at": "episode_end"})
        super().begin_episode(episode, g0, store, u0)
        self.u_hist = {0: u0}
        self._batch: Dict[tuple, Record] = {}
        self._snap: Dict[str, tuple] = {}
        self.g1_refs: List[tuple] = []
        self.pending_group: Dict[int, Dict[str, float]] = {}
        self.pending_ref_var: Dict[int, float] = {}

    def observe(self, t: int, delivered: List[Record]) -> List[dict]:
        if isinstance(self.model, DependencyModel):
            for r in delivered:
                self.model.note_relay(r.sensor_id, r.declared_upstream)
        # v1.5.1 §2: canonical processing order (measured_at, sensor_id, seq) for
        # every learning arm (two EWMA updates of one sensor do not commute);
        # G1 sees the whole delivered batch and reads (b, sigma) from a
        # pre-batch snapshot, so references do not depend on batch order.
        batch = sorted(delivered, key=lambda r: (r.measured_at, r.sensor_id, r.seq))
        self._batch = {r.key: r for r in batch}
        if self.b1_updater == "consensus":
            ids = self.sensors_seen | set(BASE) | {r.sensor_id for r in batch if r.sensor_id != "INSPECT"}
            self._snap = {s: tuple(self.model.params(s, self.g0 + t)) for s in sorted(ids)}
        infos = super().observe(t, batch)
        self._batch, self._snap = {}, {}
        if isinstance(self.model, DependencyModel) and self.b1_updater == "receipt":
            self._flush_groups(t)
        self.theta_trace.append((self.episode, t, self.model.theta_hash()))
        return infos

    # -- reference selection (only learning differs between arms) -----------
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
        applied = self._apply_update(r, pay)
        return {"record": r, "receipt_key": key, "receipt_hash": self.store.hash_of(key),
                "decision_key": tuple(pay["decision_key"]), "theta_before": before,
                "theta_after": self.model.theta_hash(), "applied": applied}

    def _apply_update(self, r: Record, pay: dict) -> bool:
        mode = self.b1_updater
        if mode is None:
            return False
        if mode == "consensus":
            visible = {**self.records, **self._batch}
            others = {x.sensor_id: x.value for x in visible.values()
                      if x.measured_at == r.measured_at and x.sensor_id != "INSPECT"
                      and x.sensor_id != r.sensor_id}
            u = self.u_hist.get(r.measured_at)
            ref = None if u is None else consensus_reference(r.sensor_id, others, lambda s: self._snap[s], u)
            self.g1_refs.append((r.key, ref))
            if ref is None:
                self.log.append({"skip": "no_consensus_reference", "key": r.key})
                return False
            self.model.update(r.sensor_id, r.value - ref[0], ref[1])
            return True
        if mode == "sham":
            sp = pay.get("sham", {}).get(r.sensor_id)
            if sp is None:
                self.log.append({"skip": "no_sham_reference", "key": r.key})
                return False
            self.model.update(r.sensor_id, r.value - sp["latent_mean"], sp["latent_var"])
            return True
        # "receipt": G2, and G3 (group members buffered per slot)
        sp = pay["sensors"][r.sensor_id]
        if isinstance(self.model, DependencyModel):
            src = self.model.source_of(r.sensor_id)
            if src != r.sensor_id:
                self.log.append({"skip": "relay_collapsed", "key": r.key})
                return False
            if src in DependencyModel.GROUP:
                self.pending_group.setdefault(r.measured_at, {})[src] = r.value - sp["latent_mean"]
                self.pending_ref_var[r.measured_at] = sp["latent_var"]
                return False                               # applied when the slot closes
        self.model.update(r.sensor_id, r.value - sp["latent_mean"], sp["latent_var"])
        return True

    def _flush_groups(self, t: int):
        """A (group, measured_at) slot closes when every member is present, or
        when the slot is older than D_MAX (absent members are MISSING)."""
        for m in sorted(list(self.pending_group)):
            res = self.pending_group[m]
            if len(res) == len(DependencyModel.GROUP) or t - m > D_MAX:
                self.model.update_group(res, self.pending_ref_var[m])
                self.log.append({"group_update": m, "members": sorted(res), "t": t})
                del self.pending_group[m], self.pending_ref_var[m]

    # -- receipts: genuine prediction always; G2-S adds a separate sham block --
    def commit_prediction(self, t: int, final_action: str) -> str:
        u_new = _u_after(self.u, final_action)
        repair = (t + 1) in self.repairs
        Bp = pr.predict(self.B, u_new, repair)
        sensors = self._sensor_block(Bp, u_new, t)
        payload = {"arm": self.arm, "action": final_action, "u_next": u_new, "t_target": t + 1,
                   "theta_hash": self.model.theta_hash(), "decision_key": [self.episode, t],
                   "belief_digest": Bp.digest(), "sensors": sensors}
        if self.b1_updater == "sham":
            a_sham = self.sham.get((self.episode, t), final_action)
            u_sham = _u_after(self.u, a_sham)
            Bs = pr.predict(self.B, u_sham, repair)                # reference path only
            payload["sham"] = self._sensor_block(Bs, u_sham, t)
            payload["sham_action"] = a_sham
        h = self.store.commit((self.episode, t + 1), payload)
        self.B, self.u = Bp, u_new                                 # true action only
        self.u_hist[t + 1] = u_new
        if final_action == "inspect":
            self.last_inspect = t
        return h

    def _sensor_block(self, Bp, u, t):
        out = {}
        for s in sorted(self.sensors_seen | set(BASE)):
            p = self.model.params(s, self.g0 + t + 1)
            if p is None:
                continue
            probs, m, s2 = pr.categorical(s, Bp, u, *p)
            out[s] = {"probs": probs.tolist(), "b": p[0], "sigma": p[1],
                      "latent_mean": m, "latent_var": s2}
        return out
