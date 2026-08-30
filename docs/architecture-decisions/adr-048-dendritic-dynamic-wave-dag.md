# ADR-048: Schedule dynamic waves over a dendritic reach DAG

- Status: Accepted
- Date: 2026-07-28
- Scope: Stage 7 network scheduling after ADR-047

## Context

ADR-047 closed one subcritical multi-in/one-out junction and advanced its three
reaches synchronously. A geographic river network needs the same local
conservation contract at more than one connected junction. Applying the
three-reach function successively would mix time levels: an upstream junction
could update a shared reach before the downstream junction reads its terminal
state. It would also make it easy to apply more than one numerical flux at the
same reach end.

Stage 7 therefore adds topology and scheduling without replacing the accepted
Stage 4-6 characteristic, source, flux, or variable-section primitives.

## Topology Contract

The graph vertices are oriented reaches. Each reach declares either one
downstream reach or `None`. The constructor requires:

- unique, nonempty reach identifiers;
- exactly one `None` outlet;
- every downstream identifier to name a reach in the graph;
- no self-loop or longer directed cycle.

Those conditions define one connected dendritic graph directed toward its
outlet. Indegree may be one for a serial connection or two or more for a
confluence. Outdegree cannot exceed one, so bifurcation is intentionally not
representable.

The common-stage characteristic solver now accepts one or more upstream
terminals. The existing Stage 6 three-reach network API retains its stricter
requirement of two or more upstream reaches, preserving that API's claim
boundary.

## Synchronous Schedule

One network step uses a single time level:

1. apply the first lateral and section-specific friction half-step to every
   reach;
2. solve every internal node independently from those post-source terminal
   states;
3. bind exactly one physical node flux to each internal reach end;
4. advance every variable-geometry hydrostatic reach step;
5. apply the second friction and lateral half-step to every reach.

A reach may participate in two different nodes, once at each end. Its upstream
end reads the downstream boundary state of its own node; its downstream end
reads its branch state at the target node. Neither end observes an already
advanced neighboring reach.

The CFL estimator follows the same schedule. It first estimates a candidate,
applies the candidate source half-step to all reaches, resolves every node, and
recomputes the allowed hydrostatic timestep. It returns only after the actual
post-source states satisfy the requested Courant bound.

## Conservation Contract

Each reach retains its local finite-volume mass and numerical momentum ledger.
The signed whole-network mass residual is:

`V_after - V_before - V_lateral - V_source + V_outlet + V_junction_residual`

where `V_junction_residual` is the timestep multiplied by the sum over nodes of
`sum(Q_upstream) - Q_downstream`. Internal flux contributions therefore cancel
to root-solver tolerance. Source-boundary inflow and outlet-boundary outflow
remain separate report fields instead of being hidden in one net value.

Node momentum, energy, direction-dependent losses, mixing, and storage are not
closed. Reach momentum ledgers only verify arithmetic decomposition of each
reach update and do not imply global momentum conservation across a junction.

## Evidence

All 16 outcome-free Stage 7 gates pass. They read no public data, user data,
action values, observations, or saved prediction values.

The gate topology is:

```text
A --\
     > C --\
B --/       > E -> outlet
D ---------/
```

Base discharges are `A=2`, `B=3`, `C=5`, `D=4`, and `E=9 m3/s`. Both nodes
recover the manufactured common stage. Invalid multiple-outlet and cyclic
graphs fail closed, as does a supercritical terminal.

A five-reach variable-section lake remains at rest for 100 steps and 800.42
seconds. Maximum area drift is `1.71e-13 m2`, maximum spurious discharge is
`7.83e-13 m3/s`, and both recovered node surfaces remain 3.0 m. The cumulative
network volume residual is `2.83e-11 m3`.

The dynamic diagnostic places a smooth 0.05 m surface perturbation on A only.
Each reach is 400 m long and the network evolves for 180 seconds on 16, 32, and
64 cells per reach. The signal crosses both nodes and changes E discharge by
`0.54-0.72 m3/s`. The four depth and discharge self-convergence ratios are
`0.705-0.775`, below the fixed 0.85 gate.

Across the dynamic grids, maximum node mass-rate residual is below
`1e-12 m3/s`, maximum reported Courant number is 0.4, and cumulative whole-
network volume residual magnitude is below `4.8e-12 m3`.

## Decision

Retain the topology-validated, synchronous, single-outlet dendritic scheduler
as the Stage 7 diagnostic implementation. It establishes that the local
geospatial hydraulic law can compose over multiple connected places while
preserving time-level and mass-conservation semantics.

Do not admit it as a predictive operator. Do not describe it as an arbitrary
DAG solver: bifurcation, multiple outlets, loops, node storage, dry or
supercritical transitions, structures, and momentum/energy junction closure
remain outside the implementation.

The next stage should add an explicit hydraulic junction momentum/energy-loss
contract before expanding topology. That contract must distinguish ordinary
confluences from structures and cannot be inferred from the mass ledger.

## Artifact

- Dynamic-wave DAG gate report SHA256:
  `66bcbaa533c5bcc413b4f036f6789ce0e8ce08e87781ab44989846528574fd6e`

## Claim Boundary

- `single_outlet_dendritic_dag_implemented=true`
- `serial_and_multi_in_one_out_nodes_implemented=true`
- `synchronous_multi_node_step_implemented=true`
- `source_aware_whole_network_cfl_implemented=true`
- `whole_network_mass_ledger_implemented=true`
- `dynamic_dag_self_convergence_gate_passed=true`
- `junction_momentum_or_energy_closure_implemented=false`
- `bifurcation_junction_implemented=false`
- `general_arbitrary_dag_implemented=false`
- `candidate_operator_admitted=false`
- `predictive_validation_complete=false`
- `geospatial_kernel_validated=false`
