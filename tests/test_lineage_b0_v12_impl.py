"""B0 v1.2 implementation-only checks (B0 prereg v1.2, Amendment 3 step 2). Not a validity
gate and not a tuning instrument: (a) the banded kernel is the v1.1 dense
kernel; (b) synthetically, the 0.005 m grid diffuses less than the 0.02 m
grid by the frozen factor. Receipt: tools/run_lineage_b0_v12_impl.py."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lineage_b import params as P  # noqa: E402
from lineage_b.agent import predictor as pr  # noqa: E402
from lineage_b.agent.numerics import ncdf  # noqa: E402

EQUIV_TOL = 1e-12
DIFFUSION_MIN_RATIO = 8.0          # frozen: W^2 scaling predicts 16
SCENARIOS = {"equilibrium": 0.5, "rising": 0.25, "draining": 0.75}   # u; q = Q_BAR, no leak, h0 ~ N(1, 0.05^2)
N_STEPS, N_MC, MC_SEED = 20, 2_000_000, 120512


def dense_kernel(nh, ui, qi, li):
    """v1.1 h_kernels() body (642d3fd), verbatim except parametrized by nh."""
    w = P.H_MAX / nh
    h_edges = np.arange(nh + 1) * w
    u, q, lk = P.U_LEVELS[ui], pr.QG[qi], P.LEAKS[li]
    x = (np.arange(nh)[:, None] * w + (np.arange(pr.SUB)[None, :] + 0.5) * w / pr.SUB).ravel()
    sq = np.sqrt(np.maximum(x, 0.0))
    inner = h_edges[1:-1]
    m = x + (P.DT / P.A) * (q - P.CV * u * sq - P.K_LEAK[lk] * sq)
    c = ncdf((inner[None, :] - m[:, None]) / P.SIGMA_W)
    c = np.concatenate([np.zeros((len(x), 1)), c, np.ones((len(x), 1))], axis=1)
    p = np.diff(c, axis=1)
    return p.reshape(nh, pr.SUB, nh).mean(axis=1)


def band_to_dense(start, Pb, nh):
    K = np.zeros((nh, nh))
    for i in range(nh):
        for j in range(Pb.shape[-1]):
            k = start[i] + j
            if k < nh:
                K[i, k] += Pb[i, j]
    return K


def equivalence(nh):
    start, Pb = pr.build_band(nh)
    worst = 0.0
    for ui in range(len(P.U_LEVELS)):
        for qi in range(P.NQ):
            for li in range(len(P.LEAKS)):
                Kd = dense_kernel(nh, ui, qi, li)
                Kb = band_to_dense(start[ui, qi, li], Pb[ui, qi, li], nh)
                worst = max(worst, float(np.abs(Kd - Kb).max()))
    return {"nh": nh, "band_width": int(Pb.shape[-1]), "max_abs_diff": worst, "pass": worst <= EQUIV_TOL}


def _grid_var(nh, u, qi):
    w = P.H_MAX / nh
    H = (np.arange(nh) + 0.5) * w
    start, Pb = pr.build_band(nh)
    ui, li = P.U_LEVELS.index(u), 0
    K = band_to_dense(start[ui, qi, li], Pb[ui, qi, li], nh)
    p = np.exp(-0.5 * ((H - 1.0) / 0.05) ** 2)
    p /= p.sum()
    v0 = float(p @ (H - p @ H) ** 2) + w * w / 12
    for _ in range(N_STEPS):
        p = p @ K
    return float(p @ (H - p @ H) ** 2) + w * w / 12 - v0      # within-bin uniform variance included


def diffusion():
    qi = int(np.argmin(np.abs(pr.QG - P.Q_BAR)))
    q = float(pr.QG[qi])
    rng = np.random.default_rng(MC_SEED)
    out, ok = {}, True
    for name, u in SCENARIOS.items():
        h = 1.0 + 0.05 * rng.standard_normal(N_MC)
        v0 = float(h.var())
        for _ in range(N_STEPS):
            sq = np.sqrt(np.maximum(h, 0.0))
            h = np.clip(h + (P.DT / P.A) * (q - P.CV * u * sq) + P.SIGMA_W * rng.standard_normal(N_MC), 0, P.H_MAX)
        dv_mc = float(h.var()) - v0
        ex = {nh: (_grid_var(nh, u, qi) - dv_mc) / N_STEPS for nh in (100, 400)}
        ratio = ex[100] / ex[400] if ex[400] > 0 else float("inf")
        passed = ex[100] > 0 and ratio >= DIFFUSION_MIN_RATIO
        out[name] = {"u": u, "q": q, "mc_dvar": dv_mc, "excess_per_step_0.02": ex[100],
                     "excess_per_step_0.005": ex[400], "ratio": ratio,
                     "w2_over_12": {"0.02": 0.02 ** 2 / 12, "0.005": 0.005 ** 2 / 12}, "pass": passed}
        ok &= passed
    return {"pass": ok, "min_ratio": DIFFUSION_MIN_RATIO, "n_steps": N_STEPS, "n_mc": N_MC,
            "mc_seed": MC_SEED, "scenarios": out}


def test_band_equals_dense_v11_grid():
    assert equivalence(100)["pass"]


def test_band_equals_dense_v12_grid():
    assert equivalence(400)["pass"]


def test_finer_grid_diffuses_less():
    assert diffusion()["pass"]
