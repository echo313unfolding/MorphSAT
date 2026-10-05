"""Evaluator metrics on hidden-state trajectories (B0 gate 16; B1 §6)."""

from __future__ import annotations

from typing import Dict, List

from lineage_b.params import COSTS, DT, H_SET, UNSAFE_HI, UNSAFE_LO, WARN_HI, WARN_LO


def unsafe(h: float) -> bool:
    return h > UNSAFE_HI or h < UNSAFE_LO


def hazards(step: dict) -> set:
    """Corrective action sets for hazards present in Z_t."""
    out = set()
    if step["h"] >= WARN_HI:
        out.add("open")
    if step["h"] <= WARN_LO:
        out.add("close")
    if step["leak"] != "none":
        out.add("inspect")
    return out


def episode_metrics(traj: List[dict]) -> Dict[str, float]:
    J = unsafe_steps = trans = fs = insp = 0.0
    for s in traj:
        J += COSTS["U"] * unsafe(s["h"]) + COSTS["D"] * (s["h"] - H_SET) ** 2 \
            + COSTS["I"] * (s["action"] == "inspect") + COSTS["M"] * (s["u_new"] != s["u"]) \
            + COSTS["L"] * s["q_leak"] * DT + COSTS["S"] * s["spill"] * DT
        unsafe_steps += unsafe(s["h"])
        trans += (not unsafe(s["h"])) and unsafe(s["h_next"])
        hz = hazards(s)
        fs += bool(hz) and s["action"] not in hz
        insp += s["action"] == "inspect"
    n = len(traj)
    return {"J": J, "unsafe_steps": unsafe_steps, "unsafe_transitions": trans,
            "unsafe_transition_rate": trans / n, "false_safe": fs, "false_safe_rate": fs / n,
            "inspect_rate": insp / n, "steps": n}
