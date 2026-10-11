# MorphSAT Architecture: Evidence Flow and C0 Direction

**DESIGN DIRECTION / RESEARCH MEMORY — NOT A PREREGISTRATION, NOT AN EXPERIMENTAL AMENDMENT, NOT BINDING ON B1.**

This document preserves architectural reasoning from the v1.6.3 corrective
cycle. It does not authorize any experiment, alter any root, or freeze any
parameter.

## 1. Core architectural principle

The substrate is not a stack of independent layers. It is a directed evidence
flow with asymmetric modification authority.

| Plane | Produces | Consumes | May NOT modify |
|---|---|---|---|
| Authority | contracts, capability tokens | proposals, prior evidence | past contracts, past evidence |
| Invariant / Witness | execution evidence, invariant measurements, violation witnesses | contracts, live state | authority decisions, past receipts |
| Evidence Graph | structured causal records, lineage | all witness streams | raw observations, timestamps |
| Causal Learning | beliefs, predictions, future proposals | evidence graph | authority, witnesses, receipts, historical evidence |

The key asymmetry is:

`Causal Learning` may alter future proposals and beliefs only.

It may never rewrite evidence produced by the other planes.

## 2. Invariants are evidence-producing instruments

Do not model an invariant as only:

`predicate -> PASS/FAIL`

Prefer:

```text
InvariantWitness
├── invariant_id
├── contract_id
├── state_before
├── triggering_event
├── state_after
├── measured values / hashes
├── provenance
├── timestamp / sequence
└── verdict
```

Conceptually:

$$I(x_t, x_{t+1}) \rightarrow \{\mathrm{PASS}, \mathrm{FAIL}\}$$

while also producing:

$$W_t = (x_t, e_t, x_{t+1}, p_t)$$

The L4 frozen-theta failure is the motivating example:

- the invariant stopped execution;
- `theta_hash` was itself an intra-execution measurement;
- the exact failure boundary localized the structural mutation;
- the witness made the failure causally interpretable.

Therefore the invariant plane is an **evidence-producing enforcement layer**,
not merely a guard.

## 3. Failure legibility

Treat diagnosability as an explicit system objective.

Preferred failure sequence:

```text
violation
→ hard stop
→ immutable witness / receipt
→ experimental identity consumed
→ no silent retry
→ forensic explanation
→ prospective amendment
→ new implementation
→ fresh validation
→ new experimental identity
```

Not:

```text
failure → hotfix → retry under same identity
```

Consumed roots are not waste. They establish that information learned after a
failure cannot be smuggled backward into the identity of the original
experiment.

This gives the system a useful invariant:

$$\text{failure evidence} \not\rightarrow \text{retroactive experiment modification}$$

## 4. Durable substrate rule

The long-term architecture follows:

$$\boxed{\text{immutable past} \rightarrow \text{versioned interpretation} \rightarrow \text{bounded future behavior}}$$

and:

$$\boxed{\text{authorization at } t_0 \neq \text{permission to violate the contract at } t_1}$$

Models and learning algorithms are replaceable.

The evidence/authority substrate persists.

## 5. C0 physical-plant distinction

B1 relies heavily on deterministic reconstruction and common random numbers.

A physical Echo machine does not.

For C0:

$$S_{t+1} = f(S_t, A_t, \epsilon_t)$$

and $S_t$ includes physical history.

Prior interventions may causally alter later starting states through:

- GPU die temperature;
- heatsink/chassis temperature;
- ambient/exhaust temperature;
- fan state;
- power state;
- CPU/GPU clocks;
- scheduler/background load;
- memory pressure;
- other unmeasured environmental state.

Therefore prior intervention history must be treated as causal state, not
merely random noise.

## 6. C0a before C0b

Before designing the main physical intervention experiment, run a separate
thermal characterization experiment.

Dependency chain:

```text
C0a thermal characterization
        ↓
estimate τ_eff
or τ1, τ2 if multi-timescale
        ↓
freeze reset predicate R_t
        ↓
freeze thermal carryover kernel
        ↓
design / preregister C0b
```

C0a must be completed and receipted before C0b parameters are frozen.

## 7. Thermal response model

Begin with the falsifiable simple model:

$$T(t) = T_\infty + (T_0 - T_\infty) e^{-t/\tau}$$

but explicitly compare it against a multi-timescale model such as:

$$T(t) = T_\infty + A e^{-t/\tau_1} + B e^{-t/\tau_2}$$

Do not assume the two-component model is necessary until measured evidence
supports it.

Potential physical interpretation:

- fast component: GPU die / immediate heatsink;
- slow component: chassis / surrounding thermal mass.

This interpretation remains a hypothesis until measured.

## 8. Carryover covariate

Do not use an unweighted thermal-history integral if C0a shows time-dependent
decay.

Candidate one-timescale thermal debt:

$$C(t_0) = \int_{t_0 - \Delta}^{t_0} \max(T(t) - T_{\mathrm{baseline}}, 0) \, e^{-(t_0 - t)/\tau_{\mathrm{eff}}} \, dt$$

If C0a supports two thermal timescales, consider:

$$C(t_0) = \int \max(T(t) - T_{\mathrm{baseline}}, 0) \left[ w_1 e^{-(t_0 - t)/\tau_1} + w_2 e^{-(t_0 - t)/\tau_2} \right] dt$$

The kernel parameters must come from C0a and be frozen before C0b.

Do not fit them using C0b outcomes.

## 9. Reset criterion

C0a should determine whether a measurable reset condition can make subsequent
interventions sufficiently independent.

Candidate structure:

$$R_t = |T_{\mathrm{GPU}} - T_{\mathrm{baseline}}| < \epsilon_T \land |P - P_{\mathrm{idle}}| < \epsilon_P \land |f - f_{\mathrm{idle}}| < \epsilon_f$$

continuously for a preregistered interval.

The actual thresholds are NOT frozen here.

C0a exists partly to determine scientifically defensible values.

If no reliable washout/reset state exists, C0b must explicitly model carryover
rather than pretending it has been eliminated.

## 10. Randomized-order intervention design

For physical experiments use randomized crossover/block ordering such as:

```text
AB
BA
BA
AB
...
```

because execution of A may alter the starting state of B.

A single AB block cannot separate treatment effect from order/carryover.

Opposite ordering provides identifiability in expectation, but the eventual
power model must include period/order/carryover effects rather than assuming
they are zero.

Candidate structure only:

$$Y_{b,p} = \mu + \tau A_{b,p} + \pi_p + \lambda C_{b,p} + \beta^\top X_{b,p} + u_b + \epsilon_{b,p}$$

This equation is architectural guidance, not a frozen C0 model.

## 11. Independent evidence paths

Potential C0 telemetry:

Internal:
- `nvidia-smi`;
- GPU temperature;
- GPU clocks;
- utilization;
- power;
- throttling state;
- CPU/system thermal zones;
- workload throughput;
- scheduler/load/memory state.

Independent external path:
- ESP32 temperature sensor(s);
- ambient temperature;
- exhaust temperature;
- potentially later independent power sensing.

Do not count correlated measurements from the same upstream source as
independent corroboration.

## 12. Long-term execution object

The eventual persistent causal unit should look more like:

```text
authorized contract
+
pre-action prediction
+
action receipt
+
execution witness stream
+
state-history evidence
+
terminal outcome receipt
+
future-only interpretation
```

rather than simply:

```text
action → outcome
```

This enables later causal motifs such as:

```text
high residual thermal state
→ workload X
→ clock reduction
→ throughput degradation
```

with the intermediate evidence preserved.

## 13. Future motif / symbol direction

Once sufficient real causal history exists:

```text
raw receipts
→ causal graph
→ recurrent causal motifs
→ canonical motif identity
→ compressed symbol
→ reversible expansion to evidence
```

Test whether compressed motifs preserve useful decision behavior relative to:

- full causal graph;
- equal-token summary;
- shuffled/control motif;
- no-memory lower bound.

Do not begin this stage until B1/B2 and initial physical-plant validity work
justify it.

## 14. Current boundary

This document does NOT:

- alter B1;
- authorize any B1 run;
- alter B1 roots;
- alter B1 scientific thresholds;
- modify B0;
- freeze C0a;
- freeze C0b;
- select thermal thresholds;
- select a statistical model;
- authorize physical hardware experiments.

It preserves architectural reasoning only.

## 15. Architectural refinement — learned world model and immutable evidence substrate (2026-10-11)

**DESIGN DIRECTION / RESEARCH MEMORY — NOT A PREREGISTRATION, NOT AN
EXPERIMENTAL AMENDMENT, NOT BINDING ON B1.**

### 15.1 Core refinement

The architecture now distinguishes three objects that must not be conflated:

$$\boxed{\text{Evidence is not the reasoning state.}}$$

$$\boxed{\text{The learned world model is the fast reasoning/predictive state.}}$$

$$\boxed{\text{Immutable evidence is the substrate that trains, audits, and falsifies the learned model.}}$$

Revised flow:

```text
                         immutable evidence
                        /                  \
                       /                    \
              causal evidence graph       replay/training data
              audit / falsification              │
                                                 ▼
                                          learned world model
                                                 │
                                          compact predictive state
                                                 │
                                           causal motifs
                                                 │
                                           reasoning model
```

The learned world model may be lossy, revisable, compressed, and wrong.

The evidence substrate may not be retroactively rewritten by the learned model.

### 15.2 Two-speed online architecture

Do not put the full evidence graph in the normal reasoning path.

Routine path:

```text
current state
→ learned world model
→ predicted consequences
→ reasoning/proposal
→ cheap authority gate
→ execution
→ append witness/outcome evidence
```

Escalated path (triggered only when needed):

```text
uncertainty
or model disagreement
or high risk
or invariant anomaly
        ↓
deeper evidence retrieval
        ↓
audit / falsification / revised proposal
```

Candidate conceptual escalation predicate:

$$Q_t = [\text{uncertainty} > \tau_u] \lor [\text{model disagreement} > \tau_d] \lor [\text{risk} > \tau_r] \lor [\text{invariant anomaly}]$$

This is architectural guidance only. No thresholds are frozen here.

Durable operational rule:

**Evidence writes are routine; evidence reads are exceptional.**

### 15.3 Adjacent-work lessons

World-model reinforcement learning supports borrowing the following mechanisms:

- action-conditioned prediction as learning signal;
- learned latent/predictive state as compact decision substrate;
- replay of stored experience for training (not raw-trajectory reasoning);
- imagined rollouts for planning where justified;
- selective experience retention over naïve accumulation.

These works do not prove MorphSAT's architecture.

Their relevance is that successful systems generally compress historical
experience into a learned predictive state rather than making the policy
repeatedly consume raw trajectories.

MorphSAT's prospective distinction is the parallel immutable evidentiary path
that the learned model cannot overwrite.

The useful comparison with DreamerV3 specifically is not "forgets vs.
remembers" — DreamerV3 trains from replayed experience. It is whether a
parallel immutable evidence path exists that the learned model cannot
overwrite. In DreamerV3, the replay buffer is mutable infrastructure. In
MorphSAT, the evidence graph is not.

Memory research provides empirical support for the immutable/mutable
separation as a performance principle, not only an integrity principle: naïve
memory accumulation can degrade agent performance through error propagation and
misaligned replay, while selective retention improves it.

### 15.4 B1 inferential boundary

B1 tests whether consequence-conditioned learning adds information beyond
same-time observational consistency under the frozen B1 design.

If B1 fails, do NOT infer that authority, sham controls, frozen theta, or
other controls suppressed the effect.

A negative B1 result must be interpreted only through the preregistered outcome
mapping (F1–F6, P0, safety noninferiority). To claim that the controls cost
performance would require a separate experiment that explicitly varies those
controls.

### 15.5 Research sequence

Refined sequence:

```text
B1
→ B2 / replication or structural extension
→ model-class transfer
→ performance lineage
→ causal-memory / motif compression
```

Do not jump directly from a positive B1 result to replacing the learner.

The model-class transfer question is:

> Does the action-conditioned causal-learning advantage survive a change in
> representation/model class?

Candidate future comparison (not authorized or preregistered here):

```text
same environment
same action log
same authority
same outcome receipts

G2-tabular
vs
G2-neural world model
vs
G2-LLM/RWML-style predictor
```

If the advantage is representation-invariant, that is substantially stronger
than "our particular SensorModel happened to work."

### 15.6 Borrow versus research

**Borrow / adapt from established work:**

- action-conditioned prediction;
- learned latent/world models;
- replay;
- selective retention;
- planning/imagined rollouts where justified.

**Research (no existing system demonstrates the complete combination):**

- immutable evidence graph parallel to the learned model;
- authority/witness/evidence separation;
- model-independent cross-model causal-memory transfer;
- reversible motif compression tied to evidence;
- evidence escalation policy;
- whether evidentiary backing improves or harms reasoning efficiency;
- representation invariance of the causal-learning advantage.

### 15.7 Compatibility with §13 motif direction

The motif pathway from §13:

```text
raw receipts
→ causal graph
→ recurrent causal motifs
→ canonical motif identity
→ compressed symbol
→ reversible expansion to evidence
```

remains the evidentiary/compression pathway.

Motifs are no longer assumed to be the sole predictive memory.

A learned world model is the candidate fast predictive state. Motifs provide
interpretable and potentially transferable causal abstractions tied back to
evidence. The two serve different roles: the world model optimizes prediction
speed; motifs preserve interpretability and evidence linkage.

### 15.8 Scope of this update

This update does NOT:

- alter B1;
- alter B1 roots;
- alter frozen thresholds;
- authorize confirmatory execution;
- preregister model-class transfer;
- freeze an evidence-escalation policy;
- authorize C0 work;
- modify any executable source.

It refines architectural reasoning only.
