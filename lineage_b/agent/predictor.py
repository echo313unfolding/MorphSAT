"""Frozen nominal predictor (B0 prereg v1.3 @ 701c4c2 §1; T6 per v1.3.1 @ ebdb0f1):
a Gaussian level belief per (inflow, leak) hypothesis, with 20-point
Gauss-Hermite moments for sqrt(h). A moment-closure approximation (v1.3
§1.7), not an exact filter. Identical for every arm; only (b, sigma) differ."""

from __future__ import annotations

import hashlib
import math
from functools import lru_cache
from typing import NamedTuple, Tuple

import numpy as np

from lineage_b.agent.numerics import ncdf
from lineage_b.params import (A, BIN_EDGES, CV, DT, H_MAX, INSPECT_FA, INSPECT_MISS, K_LEAK,
                              KIND, LEAK_HAZARD, LEAKS, NQ, P_GAIN, P_SLOW, PHI, Q_BAR,
                              SIGMA_ETA, SIGMA_W, UNSAFE_HI, UNSAFE_LO)

ALPHA = DT / A
_SD_Q = SIGMA_ETA / math.sqrt(1 - PHI ** 2)
QG = np.maximum(Q_BAR + _SD_Q * np.linspace(-3, 3, NQ), 0.0)
KL = np.array([K_LEAK[lk] for lk in LEAKS])
GH_N = 20
GH_X, _GH_W = np.polynomial.hermite.hermgauss(GH_N)       # physicists' rule, weight exp(-x^2)
GH_W = _GH_W / math.sqrt(math.pi)                         # h_k = m + sqrt(2v) x_k  (§1.2)
_LOG_GH_W = np.log(GH_W)
_SQRT_2PI = math.sqrt(2 * math.pi)


class Belief(NamedTuple):
    """pi, m, v of shape (NQ, 3): weight, level mean, level variance per (j, leak)."""
    pi: np.ndarray
    m: np.ndarray
    v: np.ndarray

    def digest(self) -> str:
        return hashlib.sha256(self.pi.tobytes() + self.m.tobytes() + self.v.tobytes()).hexdigest()


@lru_cache(maxsize=1)
def q_matrix() -> np.ndarray:
    mids = np.concatenate(([-np.inf], (QG[1:] + QG[:-1]) / 2, [np.inf]))
    m = Q_BAR + PHI * (QG - Q_BAR)
    Q = ncdf((mids[None, 1:] - m[:, None]) / SIGMA_ETA) - ncdf((mids[None, :-1] - m[:, None]) / SIGMA_ETA)
    return Q / Q.sum(axis=1, keepdims=True)


def q_stationary() -> np.ndarray:
    p = np.exp(-0.5 * ((QG - Q_BAR) / _SD_Q) ** 2)
    return p / p.sum()


def _placeholders(pi, m, v) -> Belief:
    """Components with pi = 0 carry placeholder moments (m = 0, v = 0) (§1.1)."""
    z = pi == 0
    return Belief(pi, np.where(z, 0.0, m), np.where(z, 0.0, v))


def initial_belief() -> Belief:
    pi = q_stationary()[:, None] * np.array([1.0, 0.0, 0.0])[None, :]
    return _placeholders(pi, np.full((NQ, 3), 1.0), np.full((NQ, 3), 0.05 ** 2))


# ---------------------------------------------------------------- §1.2 / §1.3(a)
def gh_nodes(m, v) -> np.ndarray:
    m, v = np.asarray(m, float), np.asarray(v, float)
    return m[..., None] + np.sqrt(2 * v)[..., None] * GH_X


def det_map(h, q, u, k) -> np.ndarray:
    """mu(h) = h + (dt/A)(q - Cv*u*sqrt(max(h,0)) - k*sqrt(max(h,0))), unclipped (§0.1, §1.3a)."""
    sq = np.sqrt(np.maximum(h, 0.0))
    return h + ALPHA * (q - CV * u * sq - k * sq)


def censored(mu, s: float) -> Tuple[np.ndarray, np.ndarray]:
    """Moments of clip(N(mu, s^2), 0, H_MAX) (§1.3d), frozen ncdf for Phi."""
    mu = np.asarray(mu, float)
    if s == 0:
        return np.clip(mu, 0.0, H_MAX), np.zeros_like(mu)
    a, b = 0.0, H_MAX
    za, zb = (a - mu) / s, (b - mu) / s
    Pa, Pb = ncdf(za), ncdf(zb)
    pa, pb = np.exp(-0.5 * za * za) / _SQRT_2PI, np.exp(-0.5 * zb * zb) / _SQRT_2PI
    E = mu + (a - mu) * Pa + (b - mu) * (1 - Pb) + s * (pa - pb)
    M2 = (a - mu) ** 2 * Pa + (b - mu) ** 2 * (1 - Pb) + s * s * (Pb - Pa) + s * ((a - mu) * pa - (b - mu) * pb)
    V = np.maximum(M2 - (E - mu) ** 2, 0.0)
    interior = (Pa == 0.0) & (Pb == 1.0)
    return np.where(interior, mu, E), np.where(interior, s * s, V)


def combine(E, V) -> Tuple[np.ndarray, np.ndarray]:
    """m' = sum w E_k, v' = sum w [V_k + (E_k - m')^2] over the last (node) axis.
    Evaluated centred at E_0: m' = E_0 + sum w d_k, (E_k - m') = d_k - sum w d with
    d_k = E_k - E_0 -- the same expressions given sum w = 1, so v' = 0 exactly when
    all node values coincide."""
    E0 = E[..., :1]
    d = E - E0
    dbar = (GH_W * d).sum(-1)
    return E0[..., 0] + dbar, (GH_W * (V + (d - dbar[..., None]) ** 2)).sum(-1)


def level_step(m, v, q, u, k, sigma_w: float = SIGMA_W):
    """§1.3(a): per component, noise first then clip, node-wise censored moments."""
    mu = det_map(gh_nodes(m, v), np.asarray(q, float)[..., None], u, np.asarray(k, float)[..., None])
    return combine(*censored(mu, sigma_w))


def collapse(alpha, m, v):
    """§1.3(b): moment-match a mixture along the last axis (stable nonnegative form)."""
    P = alpha.sum(-1)
    ok = P > 0
    Ps = np.where(ok, P, 1.0)
    mm = (alpha * m).sum(-1) / Ps
    vv = (alpha * (v + (m - mm[..., None]) ** 2)).sum(-1) / Ps
    return P, np.where(ok, mm, 0.0), np.where(ok, vv, 0.0)


def predict(B: Belief, u_new: float, repair_now: bool, sigma_w: float = SIGMA_W,
            Q: np.ndarray = None, hazard: float = LEAK_HAZARD) -> Belief:
    """§1.3 (a) level step, (b) inflow transition, (c) leak transition, renormalize.
    sigma_w / Q / hazard overrides exist for the implementation-only tests (T3)."""
    m1, v1 = level_step(B.m, B.v, QG[:, None], u_new, KL[None, :], sigma_w)
    Qm = q_matrix() if Q is None else Q
    alpha = (B.pi[:, None, :] * Qm[:, :, None]).transpose(1, 2, 0)          # (r, l, j)
    pi2, m2, v2 = collapse(alpha, m1.T[None, :, :], v1.T[None, :, :])       # (r, l)
    if repair_now:
        pn, mn, vn = collapse(pi2, m2, v2)
        z = np.zeros_like(pn)
        pi3, m3, v3 = np.stack([pn, z, z], -1), np.stack([mn, z, z], -1), np.stack([vn, z, z], -1)
    else:
        moved = [pi2[:, 0] * hazard * P_SLOW, pi2[:, 0] * hazard * (1 - P_SLOW)]
        cols = [(pi2[:, 0] * (1 - hazard), m2[:, 0], v2[:, 0])]
        for li, w in ((1, moved[0]), (2, moved[1])):
            cols.append(collapse(np.stack([pi2[:, li], w], -1), np.stack([m2[:, li], m2[:, 0]], -1),
                                 np.stack([v2[:, li], v2[:, 0]], -1)))
        pi3, m3, v3 = (np.stack([c[i] for c in cols], -1) for i in range(3))
    return _placeholders(pi3 / pi3.sum(), m3, v3)


# ---------------------------------------------------------------- §1.4 assimilation
def _reweight(B: Belief, ll, m_new, v_new):
    """pi <- pi * exp(ll), log-sum-exp normalized. If every component likelihood
    underflows (no finite log weight), the belief is returned unchanged with flag True."""
    with np.errstate(divide="ignore", invalid="ignore"):
        lw = np.log(B.pi) + ll
    lw = np.where(np.isfinite(lw), lw, -np.inf)
    if not np.isfinite(lw).any():
        return B, True
    w = np.exp(lw - lw.max())
    pi = w / w.sum()
    return _placeholders(pi, m_new, v_new), False


def update_linear(B: Belief, y: float, b: float, sigma: float, G: float):
    """Level (G = 1) / pressure (G = P_GAIN) closed-form Kalman update per component.
    v <- (1 - K G) v is evaluated as v * sigma^2 / S (identical; nonnegative)."""
    S = G * G * B.v + sigma ** 2
    K = G * B.v / S
    r = y - G * B.m - b
    ll = -0.5 * r * r / S - 0.5 * np.log(2 * math.pi * S)
    return _reweight(B, ll, B.m + K * r, B.v * (sigma ** 2 / S))


def update_flow(B: Belief, y: float, u: float, b: float, sigma: float):
    """Flow: Gauss-Hermite node reweighting per component (§1.4)."""
    h = gh_nodes(B.m, B.v)
    g = CV * u * np.sqrt(np.maximum(h, 0.0))
    lk = _LOG_GH_W + (-0.5 * ((y - g - b) / sigma) ** 2 - math.log(_SQRT_2PI * sigma))
    mx = lk.max(-1, keepdims=True)
    wk = np.exp(lk - mx)
    sw = wk.sum(-1)
    p = wk / sw[..., None]
    m_new = (p * h).sum(-1)
    v_new = (p * (h - m_new[..., None]) ** 2).sum(-1)
    return _reweight(B, mx[..., 0] + np.log(sw), m_new, v_new)


def update_joint_levels(B: Belief, y1: float, y2: float, b1: float, b2: float, R: np.ndarray):
    """REF-S joint (L1, L2) update: y = h [1, 1] + b + N(0, R), exact 2-D Kalman per component."""
    v = B.v
    S11, S12, S22 = v + R[0, 0], v + R[0, 1], v + R[1, 1]
    det = S11 * S22 - S12 * S12
    i11, i12, i22 = S22 / det, -S12 / det, S11 / det
    r1, r2 = y1 - B.m - b1, y2 - B.m - b2
    ll = -0.5 * (i11 * r1 * r1 + 2 * i12 * r1 * r2 + i22 * r2 * r2) - 0.5 * np.log((2 * math.pi) ** 2 * det)
    Rd = R[0, 0] * R[1, 1] - R[0, 1] * R[1, 0]
    c = (R[1, 1] - 2 * R[0, 1] + R[0, 0]) / Rd                              # 1' R^-1 1
    v_new = v / (1 + v * c)                                                  # Sherman-Morrison, nonnegative
    k1, k2 = v * (i11 + i12), v * (i12 + i22)
    return _reweight(B, ll, B.m + k1 * r1 + k2 * r2, v_new)


ORDER = ("L1", "L2", "L3", "L4", "F", "P")


def assimilate(B: Belief, fresh, u: float, params, joint_l12=None):
    """Sequential fresh-record assimilation in the frozen order (§1.4). `params(s)` -> (b, sigma)
    or None (skip). `joint_l12` (REF-S only) -> 2x2 covariance for a joint L1/L2 update.
    Returns (belief, list of sensors whose update underflowed)."""
    underflow, done = [], set()
    if joint_l12 is not None and "L1" in fresh and "L2" in fresh:
        p1, p2 = params("L1"), params("L2")
        if p1 is not None and p2 is not None:
            B, uf = update_joint_levels(B, fresh["L1"], fresh["L2"], p1[0], p2[0], joint_l12)
            done |= {"L1", "L2"}
            if uf:
                underflow.append("L1+L2")
    for s in ORDER:
        if s not in fresh or s in done:
            continue
        p = params(s)
        if p is None:
            continue
        kind = KIND[s]
        if kind == "level":
            B, uf = update_linear(B, fresh[s], p[0], p[1], 1.0)
        elif kind == "pressure":
            B, uf = update_linear(B, fresh[s], p[0], p[1], P_GAIN)
        else:
            B, uf = update_flow(B, fresh[s], u, p[0], p[1])
        if uf:
            underflow.append(s)
    return B, underflow


def assimilate_inspection(B: Belief, report: str) -> Belief:
    lik = np.array([INSPECT_FA, 1 - INSPECT_MISS, 1 - INSPECT_MISS]) if report == "LEAK_FOUND" \
        else np.array([1 - INSPECT_FA, INSPECT_MISS, INSPECT_MISS])
    post = B.pi * lik[None, :]
    return _placeholders(post / post.sum(), B.m, B.v)


# ---------------------------------------------------------------- §1.5 outputs
def summary(B: Belief):
    mean = float((B.pi * B.m).sum())
    var = float((B.pi * (B.v + (B.m - mean) ** 2)).sum())
    return mean, math.sqrt(max(var, 0.0)), float(B.pi[:, 1:].sum())


def expected_sq_dev(B: Belief, h_set: float) -> float:
    return float((B.pi * ((B.m - h_set) ** 2 + B.v)).sum())


def p_unsafe(B: Belief) -> float:
    sd = np.sqrt(B.v)
    pos = sd > 0
    s = np.where(pos, sd, 1.0)
    tails = ncdf((UNSAFE_LO - B.m) / s) + 1 - ncdf((UNSAFE_HI - B.m) / s)
    ind = ((B.m > UNSAFE_HI) | (B.m < UNSAFE_LO)).astype(float)
    return float((B.pi * np.where(pos, tails, ind)).sum())


def categorical(sensor: str, B: Belief, u: float, b: float, sigma: float):
    """Predictive categorical over the frozen bins (+ under/overflow), and latent
    predictive mean/variance of the measured quantity (§1.5)."""
    kind = KIND[sensor]
    e = np.asarray(BIN_EDGES[kind])
    pi = B.pi.ravel()
    if kind in ("level", "pressure"):
        G = 1.0 if kind == "level" else P_GAIN
        lat, lv_c = G * B.m.ravel(), G * G * B.v.ravel()
        c = ncdf((e[None, :] - (lat + b)[:, None]) / np.sqrt(lv_c + sigma ** 2)[:, None])
        c = np.concatenate([np.zeros((len(pi), 1)), c, np.ones((len(pi), 1))], axis=1)
        probs = pi @ np.diff(c, axis=1)
        m = float(pi @ lat)
        s2 = float(pi @ (lv_c + (lat - m) ** 2))
    else:
        h = gh_nodes(B.m, B.v).reshape(len(pi), GH_N)
        g = CV * u * np.sqrt(np.maximum(h, 0.0))
        c = ncdf((e[None, None, :] - (g + b)[..., None]) / sigma)
        n = c.shape[:2] + (1,)
        c = np.concatenate([np.zeros(n), c, np.ones(n)], axis=2)
        probs = np.einsum("c,k,cke->e", pi, GH_W, np.diff(c, axis=2))
        m = float(np.einsum("c,k,ck->", pi, GH_W, g))
        s2 = float(np.einsum("c,k,ck->", pi, GH_W, (g - m) ** 2))
    return probs / probs.sum(), m, s2


def bin_index(sensor: str, y: float) -> int:
    e = BIN_EDGES[KIND[sensor]]
    return int(np.searchsorted(np.asarray(e), y, side="right"))   # 0 = underflow, len(e) = overflow


def score(sensor: str, probs, y: float):
    k = bin_index(sensor, y)
    p = np.asarray(probs)
    return math.log(max(float(p[k]), 1e-300)), float((p ** 2).sum() - 2 * p[k] + 1.0)


def pit(sensor: str, probs, y: float) -> float:
    e = BIN_EDGES[KIND[sensor]]
    k = bin_index(sensor, y)
    p = np.asarray(probs)
    below = float(p[:k].sum())
    if k == 0 or k == len(e):
        return below + 0.5 * float(p[k])
    return below + float(p[k]) * (y - e[k - 1]) / (e[k] - e[k - 1])
