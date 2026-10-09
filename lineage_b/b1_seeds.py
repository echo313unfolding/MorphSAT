"""B1 seed families (B1 prereg v1.5 @ 2473c2a §7a, §7b, §15). EVALUATOR side.

Three permanently disjoint roots. Spawn keys are (condition index,
deployment). A family can only be opened with its purpose token, which only
the corresponding runner passes:

* validation    2026100518000  -> tools/run_lineage_b1_validation.py  (v1.6; was 2026100517000)
* sizing        2026100519000  -> tools/run_lineage_b1_sizing.py     (v1.6; was 2026100516000)
* confirmatory  2026100514000  -> tools/run_lineage_b1_confirmatory.py
"""

from __future__ import annotations

import hashlib
import json
from typing import List, Tuple

import numpy as np

from lineage_b.params import E_E, E_L
from lineage_b.world import CONDITIONS, make_streams

ROOTS = {"validation": 2026100518000, "sizing": 2026100519000, "confirmatory": 2026100514000}
TOKENS = {"validation": "B1-VALIDATION-7b", "sizing": "B1-SIZING-7a-ONE-SHOT",
          "confirmatory": "B1-CONFIRMATORY-15h"}
# Earlier roots (B0 v1.1/v1.2/v1.3 gates, pilot) that must stay disjoint.
_EARLIER = ({20261005, 20261006, 20261007, 20261008}
            | {2026100512000 + k for k in range(1000)}
            | {2026100515000 + k for k in range(1000)} | {2026100513000}
            | {2026100516000, 2026100517000})   # retired v1.5.x roots
assert len(set(ROOTS.values())) == 3 and not set(ROOTS.values()) & _EARLIER

BOOTSTRAP_SPAWN_KEY = (len(CONDITIONS), 0)       # outside every (condition, deployment) key


class SeedFamilyError(RuntimeError):
    pass


def _check(purpose: str, token: str):
    if purpose not in ROOTS or TOKENS[purpose] != token:
        raise SeedFamilyError(f"seed family {purpose!r} requires its runner token")


def deployment_seeds(purpose: str, token: str, condition: str, dep: int):
    """(episode SeedSequences for E_L + E_E episodes, mu Generator) for one
    deployment. Same structure as lineage_b.harness.episode_seeds."""
    _check(purpose, token)
    ss = np.random.SeedSequence(entropy=ROOTS[purpose], spawn_key=(CONDITIONS.index(condition), dep))
    world_ss, mu_ss = ss.spawn(2)
    return world_ss.spawn(E_L + E_E), np.random.default_rng(mu_ss)


def bootstrap_rng(purpose: str, token: str) -> np.random.Generator:
    """The frozen bootstrap seed: a dedicated spawn of the family's root."""
    _check(purpose, token)
    return np.random.default_rng(np.random.SeedSequence(entropy=ROOTS[purpose], spawn_key=BOOTSTRAP_SPAWN_KEY))


def fresh_seedsequence(ss: np.random.SeedSequence) -> np.random.SeedSequence:
    """Reconstruct a SeedSequence from its specification, deliberately resetting
    n_children_spawned to zero (v1.5.3 rule: episode seeds are immutable specs)."""
    return np.random.SeedSequence(entropy=ss.entropy, spawn_key=ss.spawn_key, pool_size=ss.pool_size)


def b1_make_streams(ss: np.random.SeedSequence):
    """Centralized B1 world/stream materialization.  Every B1 call site that
    needs streams from an episode seed MUST go through this helper (v1.5.3)."""
    return make_streams(fresh_seedsequence(ss))


def seed_list(purpose: str, n: int, conditions=CONDITIONS) -> List[Tuple[str, int, int, Tuple[int, int]]]:
    """Canonical list (condition, deployment, root, spawn_key) for deployments 0..n-1."""
    return [(c, d, ROOTS[purpose], (CONDITIONS.index(c), d)) for c in conditions for d in range(n)]


def seed_list_sha256(purpose: str, n: int) -> str:
    """Frozen at the confirmatory freeze (§15 g) for purpose='confirmatory'."""
    return hashlib.sha256(json.dumps(seed_list(purpose, n), separators=(",", ":")).encode()).hexdigest()
