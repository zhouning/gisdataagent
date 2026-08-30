# ADR-049: Close subcritical junctions with explicit energy losses

- Status: Accepted
- Date: 2026-07-28
- Scope: Stage 8 hydraulic junction closure after ADR-048

## Context

ADR-047 and ADR-048 used a common free-surface elevation, branch outgoing
characteristics, and mass conservation. That closure is conservative in mass
but does not represent velocity-head differences or local junction losses.

An energy equation cannot simply be added to the common-stage system. The
existing characteristic, common-stage, and mass equations already determine
all boundary areas and discharges. Adding another independent condition would
over-specify the node. Stage 8 therefore introduces an alternative closure
that replaces common stage with a node reference total head.

## Energy Contract

For branch state `(A,Q)`, velocity `u=Q/A`, bed elevation `z`, and section depth
`h(A)`, boundary total head is:

`H_branch = z + h(A) + u^2/(2g)`

The node has one unknown reference total head `H_node`. For upstream branches:

`H_branch - H_node = K_branch * u^2/(2g)`

For the downstream branch:

`H_node - H_branch = K_branch * u^2/(2g)`

Every `K` is a finite nonnegative dimensionless multiplier on that branch's
velocity head. `K=0` gives equal total head, not equal free-surface elevation.
Positive `K` requires total head to decrease in the downstream direction.

The remaining equations are one outgoing characteristic invariant per branch
and zero-storage mass closure:

`sum(Q_upstream) - Q_downstream = 0`

The model does not impose vector momentum balance. A momentum closure would
also require branch directions, control-volume pressure forces, reactions, and
possibly mixing or structure geometry. Reach-local momentum ledgers remain
numerical arithmetic checks only.

## Numerical Solution

The outgoing invariant expresses each branch discharge as a function of area.
Within a downstream-oriented subcritical branch, equivalent node head is
monotone with area while upstream discharge decreases and downstream discharge
increases. The node mass residual is therefore monotone in `H_node`.

For each branch, the solver:

1. verifies a wet, subcritical, downstream-oriented terminal;
2. samples the connected subcritical area interval around the interior state;
3. separately bisects the exact `Q=0` characteristic boundary, which is needed
   for lake and very-low-Froude states;
4. maps the retained area interval to its feasible node-head interval;
5. intersects all branch intervals and bisects the mass residual.

The area scan brackets the feasible interval but does not set root accuracy.
Boundary area and node mass roots use nested bisection. The mass-rate tolerance
is `1e-12 m3/s`. Flow below `-1e-12 m3/s` fails as reverse flow; smaller signed
roundoff is treated as numerical zero. Dry, transcritical, supercritical, and
incompatible-head cases fail closed.

An initial coarse implementation used only 201 logarithmic area samples. It
incorrectly truncated the narrow positive-flow interval of low-Froude right
boundaries. The accepted implementation adds the analytically identified
zero-discharge boundary. A dedicated regression verifies that the flat
`2+3=5 m3/s` low-Froude case retains a positive-flow root.

## DAG Integration

The Stage 7 scheduler accepts an optional energy-loss contract for every
internal node. When supplied, both the initial and post-source CFL node solves
and the synchronous flux step use the energy closure. Contracts must name
exactly the topology's incoming reaches in deterministic order. A partial or
misattached map fails before stepping.

Omitting the map preserves the Stage 7 common-stage behavior. Both closures
produce the same boundary interface type and use one physical flux per
internal reach end, so the whole-network mass ledger is unchanged.

## Evidence

All 16 outcome-free Stage 8 gates pass. No public data, user data, action
values, observations, or saved predictions are read. The coefficients are
manufactured diagnostic inputs, not fitted values.

Zero-loss and positive-loss manufactured junctions both recover node head
3.0 m and `2+3=5 m3/s`. Maximum positive-loss analytic energy residual is below
`4e-16 m`. Negative coefficients, material reverse flow, and a downstream head
range shifted 100 m above the upstream feasible ranges all fail closed.

A five-reach, two-node lake with positive coefficients remains at rest for 100
steps and 895.77 seconds. Maximum area drift is `1.42e-14 m2`, maximum spurious
flow is `7.13e-14 m3/s`, maximum energy residual is `4.44e-16 m`, and the
cumulative network volume residual is `-2.94e-11 m3`.

The dynamic diagnostic uses the Stage 7 five-reach topology, manufactured
energy-consistent terminal beds, and positive loss coefficients at both nodes.
A 0.03 m smooth perturbation is placed on A. Each perturbed run is differenced
against an unperturbed control on the same grid. After 180 seconds, the
response crosses both nodes and changes E discharge by `0.327-0.440 m3/s` on
16, 32, and 64 cells per reach.

The four response self-convergence ratios are `0.711-0.777`, below the fixed
0.85 gate. Across all control and perturbed runs, maximum energy-equation
residual is below `6.0e-15 m`, maximum node mass residual is below
`1e-12 m3/s`, cumulative network volume residual magnitude is below
`8.3e-12 m3`, and the reported Courant number does not exceed 0.4.

## Decision

Retain the loss-aware total-head junction as an explicit alternative Stage 8
closure and retain common stage as the Stage 7 default. This advances the
kernel from topology-only composition to a hydraulic law that distinguishes
free surface, velocity head, and irreversible local loss.

Do not admit the operator for prediction. The diagnostic does not estimate
`K`, validate it against observations, model reverse flow, close vector
momentum, or distinguish natural confluences from culverts, gates, weirs, and
other structures.

The next stage should bind loss semantics to geographic junction geometry and
structure type. Public centerlines, branch angles, widths, elevations, and
documented structure metadata can supply those inputs; an empirical loss law
must retain its source and applicability envelope rather than treating `K` as
a free universal constant.

## Artifact

- Dynamic-wave energy-junction gate report SHA256:
  `b7e4e0ac29017644ebc1b768641eff6083633601f7be56d19178b75d4e9163f0`

## Claim Boundary

- `subcritical_total_head_junction_closure_implemented=true`
- `dimensionless_branch_energy_losses_implemented=true`
- `loss_aware_dendritic_dag_scheduling_implemented=true`
- `loss_aware_dynamic_self_convergence_gate_passed=true`
- `junction_vector_momentum_closure_implemented=false`
- `reverse_flow_energy_junction_implemented=false`
- `dry_or_supercritical_energy_junction_implemented=false`
- `structure_specific_loss_model_implemented=false`
- `loss_coefficients_calibrated_from_observations=false`
- `candidate_operator_admitted=false`
- `predictive_validation_complete=false`
- `geospatial_kernel_validated=false`
