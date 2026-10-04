"""Lineage A — correction authority (policy-level), per
docs/LINEAGE_A_CORRECTION_AUTHORITY_PREREG_V1_3.md (and v1.0–v1.2).

Isolated from the MorphSAT runtime: no import of morphsat decision code.
Modules:
    records     ObservationRecord / DeclaredRecord / Pattern
    generator   FAM-G, FAM-T, FAM-I pattern families
    world       frozen generative model, 24 environments, exact posterior
    policies    A1..A5n, S1..S4 (agent-visible records only)
    corollary   C1 / C2 external-artifact comparators (declared view only)
    evaluate    weighting, metrics, Pareto, claim rule, diagnostics
"""
