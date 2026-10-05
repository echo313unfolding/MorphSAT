"""Evaluator-side harness: drives world, channel and agent; writes
ControlDecisionEvents and FeedbackRecords (B0 §9). The agent never receives Z."""

from __future__ import annotations

import math
from typing import List, Optional

import numpy as np

from lineage_b.agent import predictor as pr
from lineage_b.agent.authority import resolve
from lineage_b.channel import Channel
from lineage_b.events import AppendOnlyStore, ControlDecisionEvent, FeedbackRecord
from lineage_b.params import EP_LEN, T_F
from lineage_b.sensors import measure
from lineage_b.world import FaultState, World, Z, make_streams


def episode_seeds(root: int, deployment: int, n_episodes: int):
    ss = np.random.SeedSequence(entropy=root, spawn_key=(deployment,))
    world_ss, mu_ss = ss.spawn(2)
    return world_ss.spawn(n_episodes), np.random.default_rng(mu_ss)


def feedback_record(deployment, episode, info, store, ev_hash) -> FeedbackRecord:
    r = info["record"]
    sp = store.payload(info["receipt_key"])["sensors"][r.sensor_id]
    ls, br = pr.score(r.sensor_id, sp["probs"], r.value)
    return FeedbackRecord(deployment, episode, r.sensor_id, r.seq, r.measured_at, r.delivered_at,
                          info["receipt_key"], info["receipt_hash"], ev_hash, float(r.value),
                          {"sensor_id": r.sensor_id, "declared_upstream": r.declared_upstream},
                          float(r.value - sp["latent_mean"]), ls, br,
                          info["theta_before"], info["theta_after"], info["applied"])


def run_episode(*, streams, faults: FaultState, episode: int, g0: int, agent, store,
                events: AppendOnlyStore, feedback: AppendOnlyStore, deployment: str,
                mu=None, arm: str = "G0", replay: Optional[List] = None,
                poison: bool = False, noise: bool = True, n_steps: int = EP_LEN):
    world = World(streams, faults, episode, g0, store, noise=noise)
    ch = Channel(streams, faults.condition)
    agent.begin_episode(episode, g0, store)
    traj, stream, ev_hash = [], [], {}
    for t in range(n_steps):
        z = world.z
        if replay is None:
            ch.push(t, z.g, measure(z, streams, faults, noise))
            delivered = ch.deliver(t)
        else:
            delivered = replay[t]
        stream.append(delivered)
        for info in agent.observe(t, delivered):
            feedback.append(feedback_record(deployment, episode, info, store,
                                            ev_hash.get(info["decision_key"], "")))
        d = agent.decide(t)
        mon = d["monitor"]
        randomizable = mon[0] == "DEFER"
        if mu is not None:
            act, prop, rnd = mu.choose(d["proposal"], randomizable)
        else:
            act, prop, rnd = d["proposal"], 1.0, False
        final, by = resolve(mon, act if randomizable else None)
        rh = agent.commit_prediction(t, final)
        ev = ControlDecisionEvent(deployment, episode, t, arm, d["belief"], mon[0], mon[1], mon[2],
                                  mon[3], d["reason"], act if randomizable else None, final, by,
                                  d["theta_hash"], rh, prop, rnd, d["visible_digest"])
        events.append(ev)
        ev_hash[(episode, t)] = ev.canonical_hash
        step = {"t": t, "h": z.h, "q_in": z.q_in, "u": z.u, "leak": z.leak, "action": final,
                "path": mon[3], "propensity": prop, "randomized": rnd}
        world.step(final, rh)
        step.update(world.last_flows)
        step["h_next"] = world.z.h
        step["commit_clock"], step["transition_clock"] = world.transition_clock[-1][1:]
        traj.append(step)
        if world.inspection_report is not None and replay is None:
            ch.push_inspection(*world.inspection_report)
        if poison:
            world.z = Z(h=math.nan, q_in=math.nan, u=world.z.u, leak=world.z.leak,
                        repair_at=None, t=world.z.t, g=world.z.g)
    return traj, stream


def run_world(streams, faults: FaultState, actions: List[str], episode: int = 0, g0: int = 0,
              noise: bool = True, h0: Optional[float] = None, u0: float = 0.5):
    """World + channel only, for a fixed action sequence (gates 1–5, 15)."""
    world = World(streams, faults, episode, g0, None, noise=noise, h0=h0, u0=u0)
    ch = Channel(streams, faults.condition)
    zs, readings, delivered = [], [], []
    for t, a in enumerate(actions):
        z = world.z
        r = measure(z, streams, faults, noise)
        ch.push(t, z.g, r)
        delivered.append(ch.deliver(t))
        zs.append(z)
        readings.append(r)
        world.step(a, None)
        if world.inspection_report is not None:
            ch.push_inspection(*world.inspection_report)
    return zs, readings, delivered, world
