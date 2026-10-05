"""Lineage B0 validity gates as tests (B0 prereg v1.1 §10). Gate 17 (pilot)
runs only from tools/run_lineage_b0.py."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lineage_b import gates  # noqa: E402


@pytest.mark.parametrize("name,fn", gates.FAST, ids=[n for n, _ in gates.FAST])
def test_gate(name, fn):
    r = fn()
    assert r["pass"], r
