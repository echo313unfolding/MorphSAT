"""Frozen generative world model and exact posterior (prereg v1.0 §4, v1.1 §3,
v1.3 Amendment 2). EVALUATION ONLY — never imported by policy modules."""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass
from typing import Dict, List

from lineage_a.records import BENIGN, THREAT, Pattern, opposite


@dataclass(frozen=True)
class Env:
    r: float
    pi_drift: float
    rho: float
    alpha: float

    @property
    def key(self) -> str:
        return f"r={self.r}|pi={self.pi_drift}|rho={self.rho}|alpha={self.alpha}"


ENVS: List[Env] = [Env(r, p, rho, a) for r in (0.7, 0.9) for p in (0.2, 0.5)
                   for rho in (0.0, 0.5, 1.0) for a in (0.0, 0.3)]
assert len(ENVS) == 24


def _groups(p: Pattern):
    corr = p.correction
    groups: Dict[tuple, list] = {}
    for rec in p.records:
        epoch = "post" if (rec.is_correction or rec.order > corr.order) else "pre"
        groups.setdefault((rec.upstream_id, epoch), []).append(rec)
    return groups, corr


def _group_lik(recs, state, env: Env, adversarial: bool, corr_up: str, c: str, up: str) -> float:
    if adversarial and up == corr_up:
        return 1.0 if all(x.direction == c for x in recs) else 0.0
    r, rho = env.r, env.rho
    total = 0.0
    for latent, p_lat in ((state, r), (opposite(state), 1.0 - r)):
        prod = 1.0
        for x in recs:
            p_ind = r if x.direction == state else 1.0 - r
            prod *= rho * (1.0 if x.direction == latent else 0.0) + (1.0 - rho) * p_ind
        total += p_lat * prod
    return total


def posterior(p: Pattern, env: Env) -> Dict[str, float]:
    """q = P(correction valid), t_post = P(x_post = threat), mc = P(A=1 and invalid), Z."""
    groups, corr = _groups(p)
    c = corr.direction
    z = qv = tp = mc = 0.0
    for x_pre, d, a in itertools.product((BENIGN, THREAT), (0, 1), (0, 1)):
        x_post = opposite(x_pre) if d else x_pre
        w = 0.5 * (env.pi_drift if d else 1 - env.pi_drift) * (env.alpha if a else 1 - env.alpha)
        if w == 0.0:
            continue
        for (up, epoch), recs in groups.items():
            w *= _group_lik(recs, x_pre if epoch == "pre" else x_post, env, bool(a),
                            corr.upstream_id, c, up)
            if w == 0.0:
                break
        z += w
        if x_post == c:
            qv += w
        else:
            mc += w if a else 0.0
        if x_post == THREAT:
            tp += w
    if z == 0.0:
        # Pattern impossible under this environment (e.g. rho = 1 copies that
        # disagree). Its weight is 0 under the frozen cell normalization.
        return {"Z": 0.0, "q": None, "t_post": None, "mc": None}
    return {"Z": z, "q": qv / z, "t_post": tp / z, "mc": mc / z}


# --- Monte-Carlo sampler for posterior validation (v1.3 Amendment 2) -------

def sample_directions(p: Pattern, env: Env, rng: random.Random):
    """Sample hidden state and directions for p's structure; returns
    (directions tuple, x_post, correction_claim_ok)."""
    groups, corr = _groups(p)
    x_pre = rng.choice((BENIGN, THREAT))
    d = rng.random() < env.pi_drift
    a = rng.random() < env.alpha
    x_post = opposite(x_pre) if d else x_pre
    dirs = {}
    for (up, epoch), recs in groups.items():
        state = x_pre if epoch == "pre" else x_post
        if a and up == corr.upstream_id:
            for x in recs:
                dirs[x.order] = "ADV"
            continue
        latent = state if rng.random() < env.r else opposite(state)
        for x in recs:
            if rng.random() < env.rho:
                dirs[x.order] = latent
            else:
                dirs[x.order] = state if rng.random() < env.r else opposite(state)
    return dirs, x_post, a
