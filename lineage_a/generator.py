"""Pattern families (prereg v1.1 §4, v1.2 Amendment 2, v1.3 Amendment 2)."""

from __future__ import annotations

from typing import List

from lineage_a.records import BENIGN, THREAT, ObservationRecord as R, Pattern, opposite

POST_STRUCTURES = ("A-corr", "B-corr", "A-oth", "B-oth", "C")
FAMT_STRUCTURES = ("repeated", "shared-upstream", "independent")
CORR_SRC, CORR_UP = "S_c", "U_c"


def _post_ids(structure: str, n: int):
    if structure == "A-corr":
        return [(CORR_SRC, CORR_UP)] * n
    if structure == "B-corr":
        return [(f"S_q{i}", CORR_UP) for i in range(n)]
    if structure == "A-oth":
        return [("S_x", "U_x")] * n
    if structure == "B-oth":
        return [(f"S_q{i}", "U_x") for i in range(n)]
    if structure == "C":
        return [(f"S_q{i}", f"U_q{i}") for i in range(n)]
    raise ValueError(structure)


def fam_g() -> List[Pattern]:
    out = []
    for n_pre in range(4):
        for c in (BENIGN, THREAT):
            d_pre = opposite(c)
            variants = [(0, None, None)] + [(n, pd, st) for n in (1, 2, 3)
                                             for pd in ("support", "contradict")
                                             for st in POST_STRUCTURES]
            for n_post, post_dir, st in variants:
                recs, o = [], 0
                for i in range(n_pre):
                    recs.append(R(o, d_pre, f"S_p{i}", f"U_p{i}")); o += 1
                recs.append(R(o, c, CORR_SRC, CORR_UP, True)); o += 1
                if n_post:
                    d = c if post_dir == "support" else d_pre
                    for sid, uid in _post_ids(st, n_post):
                        recs.append(R(o, d, sid, uid)); o += 1
                cell = f"G|npre={n_pre}|c={c}|npost={n_post}|st={st}"
                pid = f"{cell}|dir={post_dir}"
                out.append(Pattern(pid, "FAM-G", cell, tuple(recs),
                                   {"n_pre": n_pre, "c": c, "n_post": n_post,
                                    "post_dir": post_dir, "structure": st}))
    return out


def _famt_ids(s: str, group: str, n: int):
    base_s, base_u = ("S_x", "U_x") if group == "pre" else ("S_y", "U_y")
    tag = "a" if group == "pre" else "b"
    if s == "repeated":
        return [(base_s, base_u)] * n
    if s == "shared-upstream":
        return [(f"S_{tag}{i}", base_u) for i in range(n)]
    if s == "independent":
        return [(f"S_{tag}{i}", f"U_{tag}{i}") for i in range(n)]
    raise ValueError(s)


def fam_t() -> List[Pattern]:
    out = []
    for s in FAMT_STRUCTURES:
        for c in (BENIGN, THREAT):
            d_pre = opposite(c)
            for b in (1, 2, 3):
                agree_ids = _famt_ids(s, "agree", b)
                for j in range(b + 1):
                    recs, o = [], 0
                    for sid, uid in _famt_ids(s, "pre", 2):
                        recs.append(R(o, d_pre, sid, uid)); o += 1
                    for sid, uid in agree_ids[:j]:
                        recs.append(R(o, c, sid, uid)); o += 1
                    recs.append(R(o, c, CORR_SRC, CORR_UP, True)); o += 1
                    for sid, uid in agree_ids[j:]:
                        recs.append(R(o, c, sid, uid)); o += 1
                    pid = f"T|s={s}|c={c}|b={b}|j={j}"
                    out.append(Pattern(pid, "FAM-T", pid, tuple(recs),
                                       {"structure": s, "c": c, "b": b, "j": j}))
    return out


def fam_i(g: List[Pattern] = None) -> List[Pattern]:
    """Named subset of FAM-G (n_pre=2, n_post in {2,3}, support)."""
    g = g if g is not None else fam_g()
    return [p for p in g if p.meta["n_pre"] == 2 and p.meta["n_post"] in (2, 3)
            and p.meta["post_dir"] == "support"]
