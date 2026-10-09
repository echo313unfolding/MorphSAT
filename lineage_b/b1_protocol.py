"""B1 protocol for one deployment (B1 prereg v1.5 @ 2473c2a §1–§6). EVALUATOR side.

Learning phase (common log), in two passes over one deterministic world:
  pass 1  G0 controller (theta0) + logging policy mu drive the world; this is
          the shared log (actions, propensities, delivered stream, events).
  pass 2  the same world is re-executed from the same seeds with the logged
          actions; every learning arm observes the identical delivered stream
          and commits its prediction receipt for t+1 BEFORE the shared
          transition (a lockstep barrier enforces it). Pass 2 must reproduce
          pass 1's trajectory and stream exactly (asserted).
  Two passes are needed only because G2-S's sham (prereg v1.5.1 §1) assigns
  each DEFER step the logged action of another step, possibly a later one.
  The stochastic behavior log is generated once; pass 2 is a deterministic
  replay of it, not a second stochastic sample.

Evaluation phase: each arm's learned model is frozen (deep copy, no updater)
and controls its own world from the same episode seeds (common random
numbers). No learning. Predictions are still committed and scored.

Nothing in this module computes a between-arm comparison; it returns
per-arm, per-deployment records only.
"""

from __future__ import annotations

import copy
import hashlib
import math
from typing import Dict, List, Tuple

import numpy as np

from lineage_b import params as P
from lineage_b.agent import predictor as pr
from lineage_b.agent.arms import B1Agent, DependencyModel
from lineage_b.agent.authority import monitor, resolve
from lineage_b.agent.core import Agent
from lineage_b.agent.sensor_model import SensorModel
from lineage_b.channel import Channel
from lineage_b.evaluate import episode_metrics, unsafe
from lineage_b.events import AppendOnlyStore, ControlDecisionEvent
from lineage_b.harness import feedback_record, run_episode
from lineage_b.b1_events import BEHAVIOR_ARM, RecordingPolicy, behavior_records
from lineage_b.receipts import ReceiptStore
from lineage_b.ref import RefSensorModel
from lineage_b.sensors import measure
from lineage_b.b1_seeds import b1_make_streams
from lineage_b.world import FaultState, World, Z

B1_LOGGING_EPSILON = 0.5    # v1.6: B1-specific exploration rate (B0 params.EPSILON=0.2 untouched)
LEARNERS = ("G1", "G2", "G3", "G2-S")
ALL_ARMS = ("G0", "G1", "G2", "G3", "G2-S", "REF-S", "REF-Z")
SIZING_ARMS = ("G0", "G1", "G2", "G2-S", "REF-S")
DEP_GROUP = {"L1": "ADC_A", "L2": "ADC_A", "L3": "L3", "P": "P", "F": "F", "L4": "alias_L4"}


def make_learner(arm: str) -> B1Agent:
    if arm == "G1":
        return B1Agent(SensorModel(), "consensus", arm="G1")
    if arm == "G2":
        return B1Agent(SensorModel(), "receipt", arm="G2")
    if arm == "G3":
        return B1Agent(DependencyModel(), "receipt", arm="G3")
    if arm == "G2-S":
        return B1Agent(SensorModel(), "sham", arm="G2-S")
    raise ValueError(arm)


# ---------------------------------------------------------------- lockstep barrier
class LockstepBarrier:
    """World-side commitment check for several arms: the transition for
    (episode, t+1) may run only after every registered arm committed its
    receipt for that key. Combined commitment = sha256 of the arms' receipt
    hashes in fixed arm order."""

    def __init__(self, arms):
        self.arms = tuple(arms)
        self._h: Dict[Tuple, Dict[str, str]] = {}
        self._c: Dict[Tuple, int] = {}
        self._clock = 0

    def register(self, key, arm, h):
        if arm in self._h.setdefault(key, {}):
            raise RuntimeError(f"{arm} committed {key} twice")
        self._h[key][arm] = h
        self._clock += 1
        self._c[key] = self._clock

    def hash_of(self, key):
        d = self._h.get(key, {})
        if set(d) != set(self.arms):
            return None
        return hashlib.sha256("".join(d[a] for a in self.arms).encode()).hexdigest()

    def clock_of(self, key):
        return self._c[key]

    def tick(self):
        self._clock += 1
        return self._clock


# ---------------------------------------------------------------- sham (G2-S, v1.5.1 §1)
def max_mismatch_sham(dep_id: str, defer: List[Tuple[Tuple[int, int], str]]) -> Dict[Tuple[int, int], str]:
    """v1.5.1 §1: deterministic maximum-mismatch multiset permutation over the
    learning-phase DEFER steps. Groups in ACTIONS order; within a group,
    positions ordered by sha256(deployment|g), g = episode*EP_LEN + t; labels
    rotated left by the largest count. Preserves exact counts and attains
    min(n, 2(n - n_max)) mismatches."""
    n = len(defer)
    if n <= 1:
        return {}
    def h(key):
        ep, t = key
        return hashlib.sha256(f"{dep_id}|{ep * P.EP_LEN + t}".encode()).hexdigest()
    positions, labels = [], []
    for a in P.ACTIONS:
        grp = sorted((k for k, x in defer if x == a), key=h)
        positions += grp
        labels += [a] * len(grp)
    m = max(labels.count(a) for a in P.ACTIONS)
    rotated = labels[m:] + labels[:m]
    return dict(zip(positions, rotated))


def max_mismatches(defer) -> int:
    n = len(defer)
    n_max = max((sum(1 for _, a in defer if a == x) for x in P.ACTIONS), default=0)
    return min(n, 2 * (n - n_max)) if n > 1 else 0


def sham_validity_counts(defer, sham) -> dict:
    """SV1–SV3 inputs for one deployment (no control outcome)."""
    logged = [a for _, a in defer]
    shamed = [sham[k] for k, _ in defer] if sham else []
    from collections import Counter
    return {"n": len(defer), "sv1_marginals_equal": Counter(logged) == Counter(shamed),
            "sv2_pairing_changed": logged != shamed,
            "n_differ": sum(x != y for x, y in zip(logged, shamed))}


def kl(p, q) -> float:
    p, q = np.maximum(np.asarray(p), 1e-300), np.maximum(np.asarray(q), 1e-300)
    return float((p * np.log(p / q)).sum())


# ---------------------------------------------------------------- one-step cost / REF-Z
_GHX, _GHW = np.polynomial.hermite.hermgauss(20)
_GHW = _GHW / math.sqrt(math.pi)


def one_step_cost(h_next, action, u, u_new, q_leak, spill) -> float:
    """Cost attributable to A_t over t -> t+1 (OPE reward = -this; REF-Z objective)."""
    return (P.COSTS["U"] * unsafe(h_next) + P.COSTS["D"] * (h_next - P.H_SET) ** 2
            + P.COSTS["I"] * (action == "inspect") + P.COSTS["M"] * (u_new != u)
            + P.COSTS["L"] * q_leak * P.DT + P.COSTS["S"] * spill * P.DT)


REFZ_ORDER = ("hold", "open", "close", "inspect")


def refz_action(h, q_in, u, leak) -> str:
    """REF-Z: myopic optimal action on the full hidden state Z_t, expected one-step
    cost over the process noise (20-point Gauss–Hermite). Evaluator only."""
    best, best_c = None, None
    sq = math.sqrt(max(h, 0.0))
    for a in REFZ_ORDER:
        u_new = min(1.0, max(0.0, u + (P.DU if a == "open" else -P.DU if a == "close" else 0.0)))
        q_out, q_leak = P.CV * u_new * sq, P.K_LEAK[leak] * sq
        c = 0.0
        for x, w in zip(_GHX, _GHW):
            h_raw = h + (P.DT / P.A) * (q_in - q_out - q_leak) + P.SIGMA_W * math.sqrt(2) * x
            hn = min(max(h_raw, 0.0), P.H_MAX)
            c += w * one_step_cost(hn, a, u, u_new, q_leak, P.A * max(h_raw - P.H_MAX, 0.0) / P.DT)
        if best_c is None or c < best_c - 1e-15:
            best, best_c = a, c
    return best


def run_refz_episode(streams, faults, episode, g0, store, events, deployment):
    world = World(streams, faults, episode, g0, store)
    ch = Channel(streams, faults.condition)
    records, traj = {}, []
    for t in range(P.EP_LEN):
        z = world.z
        ch.push(t, z.g, measure(z, streams, faults))
        for r in ch.deliver(t):
            records.setdefault(r.key, r)
        mon = monitor(records, t)
        proposal = refz_action(z.h, z.q_in, z.u, z.leak) if mon[0] == "DEFER" else None
        final, by = resolve(mon, proposal)
        rh = store.commit((episode, t + 1), {"arm": "REF-Z", "action": final, "t_target": t + 1,
                                             "decision_key": [episode, t]})
        events.append(ControlDecisionEvent(deployment, episode, t, "REF-Z", {}, mon[0], mon[1], mon[2],
                                           mon[3], {"refz": proposal}, proposal, final, by,
                                           "REF-Z", rh, 1.0, False, ""))
        step = {"t": t, "h": z.h, "q_in": z.q_in, "u": z.u, "leak": z.leak, "action": final,
                "path": mon[3]}
        world.step(final, rh)
        step.update(world.last_flows)
        step["h_next"] = world.z.h
        traj.append(step)
        if world.inspection_report is not None:
            ch.push_inspection(*world.inspection_report)
    return traj


# ---------------------------------------------------------------- learning phase
def _fresh_flags(delivered, t):
    got = {r.sensor_id for r in delivered if r.measured_at == t and r.sensor_id in P.SENSORS}
    return [1.0 if s in got else 0.0 for s in P.SENSORS]


def pass1(dep_id, condition, eps, mu_rng):
    """The shared log: G0 controller (theta0) + mu drive the world (E_L episodes)."""
    faults = FaultState(condition)
    g0_agent = Agent(SensorModel(), arm=BEHAVIOR_ARM)
    mu = RecordingPolicy(mu_rng, epsilon=B1_LOGGING_EPSILON)
    st, ev, fb = ReceiptStore(), AppendOnlyStore(), AppendOnlyStore()
    log = {"dep_id": dep_id, "condition": condition, "episodes": []}
    for ep in range(P.E_L):
        traj, stream = run_episode(streams=b1_make_streams(eps[ep]), faults=faults, episode=ep,
                                   g0=ep * P.EP_LEN, agent=g0_agent, store=st, events=ev, feedback=fb,
                                   deployment=dep_id, mu=mu, arm=BEHAVIOR_ARM)
        log["episodes"].append({"traj": traj, "stream": stream})
    log["events"] = {(e.episode, e.t): e for e in ev.items()}
    log["behavior"] = behavior_records(dep_id, ev.items(), mu.calls, epsilon=B1_LOGGING_EPSILON)
    log["stuck_value"] = faults.stuck_value
    log["defer"] = [((ep, s["t"]), s["action"]) for ep, e in enumerate(log["episodes"])
                    for s in e["traj"] if s["path"] == "arbitration"]
    log["sham"] = max_mismatch_sham(dep_id, log["defer"])
    return log


def pass2(log, eps, learners: Dict[str, B1Agent], ope: bool = False, world_eps=None,
          stream_override=None, poison: bool = False):
    """Lockstep learning over the log. By default the world is re-executed from
    the same seeds and must reproduce the log exactly. Validation variants:
    `world_eps` (a different hidden world), `stream_override` (agents receive
    this stream instead of the world's), `poison` (NaN hidden state)."""
    condition, dep_id, events = log["condition"], log["dep_id"], log["events"]
    if "G2-S" in learners:
        learners["G2-S"].set_sham_schedule(log["sham"])
    exact = world_eps is None and stream_override is None and not poison
    order = tuple(sorted(learners))
    stores = {a: ReceiptStore() for a in order}
    fbs = {a: AppendOnlyStore() for a in order}
    executed = []
    faults2 = FaultState(condition, log["stuck_value"])
    snapshots = {}
    for ep in range(P.E_L):
        streams = b1_make_streams((world_eps or eps)[ep])
        barrier = LockstepBarrier(order)
        world = World(streams, faults2, ep, ep * P.EP_LEN, barrier)
        ch = Channel(streams, condition)
        for a in order:
            learners[a].begin_episode(ep, ep * P.EP_LEN, stores[a])
        logged = log["episodes"][ep]
        for t in range(P.EP_LEN):
            z = world.z
            if not poison:
                ch.push(t, z.g, measure(z, streams, faults2))
                delivered = ch.deliver(t)
            else:
                delivered = []
            if stream_override is not None:
                delivered = stream_override[ep][t]
            if exact and (delivered != logged["stream"][t] or z.h != logged["traj"][t]["h"]):
                raise RuntimeError(f"pass 2 diverged from the log at {(ep, t)}")
            for a in order:
                for info in learners[a].observe(t, delivered):
                    e = events.get(info["decision_key"])
                    fbs[a].append(feedback_record(dep_id, ep, info, stores[a],
                                                  e.canonical_hash if e else ""))
            act = logged["traj"][t]["action"]
            for a in order:
                barrier.register((ep, t + 1), a, learners[a].commit_prediction(t, act))
            if ope and logged["traj"][t]["path"] == "arbitration":
                snap = copy.copy(world)
                snap.rng = copy.deepcopy(world.rng)
                snap.z = copy.copy(world.z)
                snap.receipts = None
                snapshots[(ep, t)] = snap
            world.step(act, barrier.hash_of((ep, t + 1)))
            executed.append(act)
            if world.inspection_report is not None and not poison:
                ch.push_inspection(*world.inspection_report)
            if poison:
                world.z = Z(h=math.nan, q_in=math.nan, u=world.z.u, leak=world.z.leak,
                            repair_at=None, t=world.z.t, g=world.z.g)
    final_flushes = {a: learners[a].finalize_learning() for a in order}     # v1.5.2 §2
    return {"stores": stores, "feedback": fbs, "snapshots": snapshots, "executed": executed,
            "final_flushes": final_flushes}


def learning_phase(dep_id, condition, eps, mu_rng, learners: Dict[str, B1Agent], ope: bool = False):
    """Pass 1 (log) then pass 2 (lockstep learning); learners are trained in place."""
    log = pass1(dep_id, condition, eps, mu_rng)
    log.update(pass2(log, eps, learners, ope=ope))
    return log


def sham_validity(log, learner_store: ReceiptStore) -> dict:
    """SV1–SV4 inputs from logs and predictions only (no control outcome).
    SV4 uses the sensors gate 13 tested (L3, F), on DEFER steps whose sham
    action differs from the logged action."""
    c = sham_validity_counts(log["defer"], log["sham"])
    c["max_possible_differ"] = max_mismatches(log["defer"])
    kls = []
    for (ep, t), a in log["defer"]:
        if log["sham"].get((ep, t), a) == a:
            continue
        pay = learner_store.payload((ep, t + 1))
        for s in ("L3", "F"):
            if s in pay["sensors"] and s in pay.get("sham", {}):
                kls.append(kl(pay["sensors"][s]["probs"], pay["sham"][s]["probs"]))
    c["kl_sum"], c["kl_n"] = float(sum(kls)), len(kls)
    return c


# ---------------------------------------------------------------- evaluation phase
def _prediction_rows(store, feedback):
    rows = []
    for f in feedback.items():
        sp = store.payload(tuple(f.receipt_key))["sensors"][f.sensor_id]
        rows.append((f.sensor_id, f.log_score, f.brier, pr.pit(f.sensor_id, sp["probs"], f.observed)))
    return rows


def _summarize_predictions(rows):
    out = {}
    for key, sel in [(s, lambda r, s=s: r[0] == s) for s in ("L1", "L2", "L3", "L4", "F", "P")] + \
                    [("group:" + g, lambda r, g=g: DEP_GROUP[r[0]] == g) for g in sorted(set(DEP_GROUP.values()))]:
        v = [r for r in rows if sel(r)]
        if not v:
            continue
        pit = np.array([r[3] for r in v])
        out[key] = {"n": len(v), "log_score": float(np.mean([r[1] for r in v])),
                    "brier": float(np.mean([r[2] for r in v])),
                    "cov90": float(np.mean((pit >= 0.05) & (pit <= 0.95))),
                    "cov50": float(np.mean((pit >= 0.25) & (pit <= 0.75)))}
    return out


def _control_rows(trajs):
    """Per-deployment control metrics: means over evaluation episodes."""
    ms = [episode_metrics(tr) for tr in trajs]
    defer = [s for tr in trajs for s in tr if s["path"] == "arbitration"]
    err = [s["action"] != refz_action(s["h"], s["q_in"], s["u"], s["leak"]) for s in defer]
    covered = [(s["action"] != "inspect", e) for s, e in zip(defer, err)]
    n_cov = sum(c for c, _ in covered)
    return {"J": float(np.mean([m["J"] for m in ms])),
            "unsafe_transition_rate": float(np.mean([m["unsafe_transition_rate"] for m in ms])),
            "false_safe_rate": float(np.mean([m["false_safe_rate"] for m in ms])),
            "inspect_rate": float(np.mean([m["inspect_rate"] for m in ms])),
            "action_error": float(np.mean(err)) if err else None,
            "coverage": n_cov / len(defer) if defer else None,
            "selective_risk": (sum(e for c, e in covered if c) / n_cov) if n_cov else None,
            "interlock_steps": sum(s["path"] == "interlock" for tr in trajs for s in tr),
            "terminal_abstain_steps": sum(s["path"] == "terminal_abstain" for tr in trajs for s in tr)}


def evaluate_arm(arm, dep_id, condition, eps, stuck_value, model=None):
    """Frozen-theta, on-policy evaluation over episodes E_L .. E_L+E_E-1."""
    faults = FaultState(condition, stuck_value)
    st, ev, fb = ReceiptStore(), AppendOnlyStore(), AppendOnlyStore()
    trajs = []
    if arm == "REF-Z":
        for ep in range(P.E_L, P.E_L + P.E_E):
            trajs.append(run_refz_episode(b1_make_streams(eps[ep]), faults, ep, ep * P.EP_LEN, st, ev, dep_id))
        return {"control": _control_rows(trajs), "trajs": trajs}
    if arm == "G0":
        agent = Agent(SensorModel(), arm="G0")
    elif arm == "REF-S":
        agent = Agent(RefSensorModel(condition), arm="REF-S")
    else:
        agent = B1Agent(copy.deepcopy(model), None, arm=arm)
    theta0 = agent.model.theta_hash()
    for ep in range(P.E_L, P.E_L + P.E_E):
        tr, _ = run_episode(streams=b1_make_streams(eps[ep]), faults=faults, episode=ep, g0=ep * P.EP_LEN,
                            agent=agent, store=st, events=ev, feedback=fb, deployment=dep_id, arm=arm)
        trajs.append(tr)
    if agent.model.theta_hash() != theta0:
        raise RuntimeError(f"{arm}: theta changed during evaluation")
    skips = {}
    for e in agent.log:
        k = e.get("skip")
        if k:
            skips[k] = skips.get(k, 0) + 1
    return {"control": _control_rows(trajs), "prediction": _summarize_predictions(_prediction_rows(st, fb)),
            "skips": skips, "receipts_verify": st.verify(), "trajs": trajs}


# ---------------------------------------------------------------- theta snapshots
def theta_view(model) -> dict:
    if isinstance(model, DependencyModel):
        b = model.base
        out = {s: [b.b[s], b.sigma[s]] for s in ("L3", "F", "P")}
        for s in DependencyModel.GROUP:
            out[s] = [model.b_g + model.d[s], math.sqrt(model.tau2 + model.sig[s] ** 2)]
        out["tau2"], out["b_g"] = model.tau2, model.b_g
        return out
    return {s: [model.b[s], model.sigma[s]] for s in sorted(model.sigma)}


# ---------------------------------------------------------------- OPE data
def ope_data(log, learners, arms_models: Dict[str, object], condition):
    """Per-DEFER-step learning-phase OPE inputs (B1 §5): behaviour context,
    action, propensity, reward, and for each arm its frozen policy's action and
    the exact counterfactual one-step reward (CRN replay)."""
    feats, acts, props, rew = [], [], [], []
    keys = []
    for ep, e in enumerate(log["episodes"]):
        for s in e["traj"]:
            if s["path"] != "arbitration":
                continue
            ev = log["events"][(ep, s["t"])]
            b = ev.belief
            feats.append([b["mean_h"], b["sd_h"] ** 2, b["p_leak"], s["u"]] + _fresh_flags(e["stream"][s["t"]], s["t"]))
            acts.append(P.ACTIONS.index(s["action"]))
            props.append(s["propensity"])
            rew.append(-one_step_cost(s["h_next"], s["action"], s["u"], s["u_new"], s["q_leak"], s["spill"]))
            keys.append((ep, s["t"]))
    out = {"X": np.array(feats, dtype=np.float64), "a": np.array(acts), "mu": np.array(props),
           "r": np.array(rew), "pi": {}, "r_pi": {}}
    for arm, model in arms_models.items():
        if arm == "G0":
            agent = Agent(SensorModel(), arm="G0")
        elif arm == "REF-S":
            agent = Agent(RefSensorModel(condition), arm="REF-S")
        else:
            agent = B1Agent(copy.deepcopy(model), None, arm=arm)
        st = ReceiptStore()
        pi = {}
        for ep, e in enumerate(log["episodes"]):
            agent.begin_episode(ep, ep * P.EP_LEN, st)
            for s in e["traj"]:
                t = s["t"]
                agent.observe(t, e["stream"][t])
                if s["path"] == "arbitration":
                    pi[(ep, t)] = agent.decide(t)["proposal"]
                agent.commit_prediction(t, s["action"])
        a_pi, r_pi = [], []
        for k in keys:
            a = pi[k]
            a_pi.append(P.ACTIONS.index(a))
            snap = copy.copy(log["snapshots"][k])
            snap.rng = copy.deepcopy(snap.rng)
            snap.z = copy.copy(snap.z)
            z = snap.z
            snap.step(a, None)
            fl = snap.last_flows
            r_pi.append(-one_step_cost(snap.z.h, a, z.u, fl["u_new"], fl["q_leak"], fl["spill"]))
        out["pi"][arm], out["r_pi"][arm] = np.array(a_pi), np.array(r_pi)
    return out


# ---------------------------------------------------------------- stages (v1.5.1 §6)
def stage_a(dep_id, condition, eps, mu_rng, arms, ope: bool = False):
    """Learning/logging only: no evaluation, no control outcome. Returns the
    learned models, SV inputs and provenance digests (and, with ope=True, the
    log needed for OPE)."""
    learners = {a: make_learner(a) for a in arms if a in LEARNERS}
    log = learning_phase(dep_id, condition, eps, mu_rng, learners, ope=ope)
    if any(getattr(ag, "pending_group", {}) for ag in learners.values()):
        raise RuntimeError("pending G3 group state survived the end of learning")    # v1.5.2 §2
    out = {"deployment": dep_id, "condition": condition, "stuck_value": log["stuck_value"],
           "models": {a: ag.model for a, ag in learners.items()},
           "theta_hash": {a: ag.model.theta_hash() for a, ag in learners.items()},
           "theta": {a: theta_view(ag.model) for a, ag in learners.items()},
           "theta_trace_end_of_episode": {a: [h for (ep, t, h) in ag.theta_trace if t == P.EP_LEN - 1]
                                          for a, ag in learners.items()},
           "learning_skips": {a: len(ag.log) for a, ag in learners.items()},
           "final_flushes": log["final_flushes"],
           "behavior_digest": hashlib.sha256("".join(b.canonical_hash for b in log["behavior"]).encode()).hexdigest()}
    if "G2-S" in learners:
        out["sham_validity"] = sham_validity(log, log["stores"]["G2-S"])
    return out, (log if ope else None)


def stage_b(a_out, eps, arms, ope_log=None, keep_trajs=False):
    """Frozen-theta evaluation (only after pooled SV has been decided)."""
    rec = {"deployment": a_out["deployment"], "condition": a_out["condition"], "arms": {},
           "theta": a_out["theta"], "theta_trace_end_of_episode": a_out["theta_trace_end_of_episode"],
           "learning_skips": a_out["learning_skips"]}
    if "sham_validity" in a_out:
        rec["sham_validity"] = a_out["sham_validity"]
    models = a_out["models"]
    for a in arms:
        r = evaluate_arm(a, a_out["deployment"], a_out["condition"], eps, a_out["stuck_value"],
                         model=models.get(a))
        if not keep_trajs:
            r.pop("trajs", None)
        rec["arms"][a] = r
    if ope_log is not None:
        rec["ope"] = ope_data(ope_log, None, {a: models.get(a) for a in arms if a != "REF-Z"},
                              a_out["condition"])
    return rec
