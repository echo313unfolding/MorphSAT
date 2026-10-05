"""Frozen nominal predictor: grid Bayes filter over (h, q_in, leak) with known
nominal physics (B0 §7). Identical for every arm; only (b, sigma) differ."""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

from lineage_b.agent.numerics import ncdf
from lineage_b.params import (A, BIN_EDGES, CV, DT, H_MAX, INSPECT_FA, INSPECT_MISS, K_LEAK,
                              KIND, LEAK_HAZARD, LEAKS, NH, NQ, P_GAIN, P_SLOW, PHI, Q_BAR,
                              SIGMA_ETA, SIGMA_W, U_LEVELS)

W = H_MAX / NH
H = (np.arange(NH) + 0.5) * W
H_EDGES = np.arange(NH + 1) * W
_SD_Q = SIGMA_ETA / math.sqrt(1 - PHI ** 2)
QG = np.maximum(Q_BAR + _SD_Q * np.linspace(-3, 3, NQ), 0.0)
SUB = 8


@lru_cache(maxsize=1)
def q_matrix() -> np.ndarray:
    mids = np.concatenate(([-np.inf], (QG[1:] + QG[:-1]) / 2, [np.inf]))
    m = Q_BAR + PHI * (QG - Q_BAR)
    Q = ncdf((mids[None, 1:] - m[:, None]) / SIGMA_ETA) - ncdf((mids[None, :-1] - m[:, None]) / SIGMA_ETA)
    return Q / Q.sum(axis=1, keepdims=True)


def q_stationary() -> np.ndarray:
    p = np.exp(-0.5 * ((QG - Q_BAR) / _SD_Q) ** 2)
    return p / p.sum()


BAND_SIGMAS = 10.0      # mass beyond ±10 sigma_w of every sub-point mean (< 1e-22) is not stored


def build_band(nh: int):
    """Banded form of the v1.1 h-transition kernel K[u, q, leak, from_h, to_h]
    (within-bin uniform sub-sampling, clip tails into end bins), for an
    nh-bin grid on [0, H_MAX]. Row i keeps to-bins start[..., i] + j,
    j < width; P[..., i, j] is their probability (0 past the grid end)."""
    w = H_MAX / nh
    x = np.arange(nh)[:, None] * w + (np.arange(SUB)[None, :] + 0.5) * w / SUB      # (nh, SUB)
    sq = np.sqrt(np.maximum(x, 0.0))
    shape = (len(U_LEVELS), NQ, len(LEAKS), nh)
    means = np.empty(shape + (SUB,))
    for ui, u in enumerate(U_LEVELS):
        for qi, q in enumerate(QG):
            for li, lk in enumerate(LEAKS):
                means[ui, qi, li] = x + (DT / A) * (q - CV * u * sq - K_LEAK[lk] * sq)
    lo = np.floor((means.min(axis=-1) - BAND_SIGMAS * SIGMA_W) / w).astype(int)
    hi = np.floor((means.max(axis=-1) + BAND_SIGMAS * SIGMA_W) / w).astype(int)
    start = np.clip(lo, 0, nh - 1)
    width = int((np.clip(hi, 0, nh - 1) - start).max()) + 1
    k = start[..., None] + np.arange(width + 1)                                  # edge indices
    e = np.where(k <= 0, -np.inf, np.where(k >= nh, np.inf, k * w))              # clip: tails into end bins
    c = ncdf((e[..., None, :] - means[..., :, None]) / SIGMA_W)                  # P(h' < edge)
    P = np.diff(c, axis=-1).mean(axis=-2)
    return start, P


@lru_cache(maxsize=1)
def h_kernels():
    """Banded kernel for the frozen grid plus flat scatter indices per u."""
    start, P = build_band(NH)
    width = P.shape[-1]
    rows = (np.arange(NQ)[:, None, None] * len(LEAKS) + np.arange(len(LEAKS))[None, :, None]) * NH
    idx = rows[None, ..., None] + np.minimum(start[..., None] + np.arange(width), NH - 1)
    return idx, P


def apply_band(B: np.ndarray, idx: np.ndarray, P: np.ndarray, nh: int) -> np.ndarray:
    """sum_h B[h, q, l] K[q, l, h, k] -> [k, q, l] for one u, banded."""
    contrib = B.transpose(1, 2, 0)[..., None] * P
    out = np.bincount(idx.ravel(), weights=contrib.ravel(), minlength=NQ * len(LEAKS) * nh)
    return out.reshape(NQ, len(LEAKS), nh).transpose(2, 0, 1)


def g_and_var(sensor: str, u: float):
    """Measured quantity on the h grid and within-bin variance contribution."""
    k = KIND[sensor]
    if k == "level":
        return H, np.full(NH, W * W / 12)
    if k == "pressure":
        return P_GAIN * H, np.full(NH, (P_GAIN * W) ** 2 / 12)
    sq = np.sqrt(H)
    return CV * u * sq, (CV * u / (2 * sq)) ** 2 * W * W / 12


def initial_belief() -> np.ndarray:
    ph = np.exp(-0.5 * ((H - 1.0) / 0.05) ** 2)
    B = ph[:, None, None] * q_stationary()[None, :, None] * np.array([1.0, 0.0, 0.0])[None, None, :]
    return B / B.sum()


def predict(B: np.ndarray, u_new: float, repair_now: bool) -> np.ndarray:
    ui = U_LEVELS.index(u_new)
    idx, P = h_kernels()
    Bp = apply_band(B, idx[ui], P[ui], NH)
    Bp = np.einsum("hql,qr->hrl", Bp, q_matrix())
    none, slow, fast = Bp[..., 0], Bp[..., 1], Bp[..., 2]
    if repair_now:
        out = np.stack([none + slow + fast, np.zeros_like(none), np.zeros_like(none)], axis=-1)
    else:
        out = np.stack([none * (1 - LEAK_HAZARD), slow + none * LEAK_HAZARD * P_SLOW,
                        fast + none * LEAK_HAZARD * (1 - P_SLOW)], axis=-1)
    return out / out.sum()


def assimilate(B: np.ndarray, loglik_h: np.ndarray) -> np.ndarray:
    ll = loglik_h - loglik_h.max()
    post = B * np.exp(ll)[:, None, None]
    s = post.sum()
    return post / s if s > 0 else B


def assimilate_inspection(B: np.ndarray, report: str) -> np.ndarray:
    lik = np.array([INSPECT_FA, 1 - INSPECT_MISS, 1 - INSPECT_MISS]) if report == "LEAK_FOUND" \
        else np.array([1 - INSPECT_FA, INSPECT_MISS, INSPECT_MISS])
    post = B * lik[None, None, :]
    return post / post.sum()


def categorical(sensor: str, ph: np.ndarray, u: float, b: float, sigma: float):
    """Predictive categorical over frozen bins (+ under/overflow), and latent
    predictive mean/variance of the measured quantity."""
    g, wv = g_and_var(sensor, u)
    sd = np.sqrt(sigma ** 2 + wv)
    e = np.asarray(BIN_EDGES[KIND[sensor]])
    c = ncdf((e[None, :] - (g + b)[:, None]) / sd[:, None])
    c = np.concatenate([np.zeros((NH, 1)), c, np.ones((NH, 1))], axis=1)
    probs = ph @ np.diff(c, axis=1)
    m = float(ph @ g)
    s2 = float(ph @ ((g - m) ** 2 + wv))
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
