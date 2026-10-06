"""Public nominal constants (B0 prereg v1.1 §11). No fault assignments or
seeds live here; those are evaluator-only."""

import math

# Tank and nominal physics (agent's nominal model uses these; equal to the
# simulator's values in v1).
A = 1.0
H_MAX = 2.0
H_SET = 1.0
DT = 1.0
Q_BAR = 0.05
PHI = 0.9
SIGMA_ETA = 0.003
CV = 0.1
DU = 0.25
U_LEVELS = (0.0, 0.25, 0.5, 0.75, 1.0)
LEAKS = ("none", "slow", "fast")
K_LEAK = {"none": 0.0, "slow": 0.01, "fast": 0.03}
LEAK_HAZARD = 0.002
P_SLOW = 0.7
SIGMA_W = 0.002
INSPECT_MISS = 0.10
INSPECT_FA = 0.05
R_REP = 5

# Safety bands and interlock
UNSAFE_HI, UNSAFE_LO = 1.8, 0.2
WARN_HI, WARN_LO = 1.6, 0.4
IL_HI, IL_LO = 1.7, 0.3

# Sensor specification (public datasheet values)
SIGMA_A = 0.01
SIGMA_L12 = 0.01
SIGMA_L3 = 0.014
SIGMA_F = 0.003
SIGMA_P = 0.196
P_GAIN = 9.81                     # kPa per metre
SENSORS = ("L1", "L2", "L3", "F", "P")
LEVEL_IL = ("L1", "L2", "L3")    # interlock / terminal-abstain sensors
DECLARED_UPSTREAM = {"L1": "ADC_A", "L2": "ADC_A", "L3": "ADC_B", "F": "FEED_F",
                     "P": "ADC_C", "L4": "relay:L1", "INSPECT": "INSPECTION"}
_L12 = math.sqrt(SIGMA_A ** 2 + SIGMA_L12 ** 2)
NOMINAL_SIGMA = {"L1": _L12, "L2": _L12, "L3": SIGMA_L3, "F": SIGMA_F,
                 "P": SIGMA_P, "L4": _L12}
KIND = {"L1": "level", "L2": "level", "L3": "level", "L4": "level",
        "F": "flow", "P": "pressure"}


def _edges(lo, hi, step):
    n = int(round((hi - lo) / step))
    return tuple(lo + i * step for i in range(n + 1))


BIN_EDGES = {"level": _edges(0.0, 2.0, 0.02), "pressure": _edges(0.0, 19.62, 0.1962),
             "flow": _edges(0.0, 0.15, 0.003)}

# Channel
D_MAX = 3
REDELIVERY_P = 0.02

# Schedule
T_F = 50
EP_LEN = 200
E_L, E_E = 5, 5

# Controller / logging policy
EPSILON = 0.2
TAU_I = 0.3
R_COOL = 10
ACTIONS = ("open", "hold", "close", "inspect")
COSTS = {"U": 100.0, "D": 10.0, "I": 2.0, "M": 0.1, "L": 200.0, "S": 200.0}

# Learning (infrastructure; arms are B1)
ETA_B = 0.02
ETA_S = 0.02
SIGMA_MIN_FRAC = 0.25

# Agent inflow grid (v1.3: the level is a Gaussian per (inflow, leak) hypothesis; no level grid)
NQ = 11
