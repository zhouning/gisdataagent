# ADR-047: Gate a conservative subcritical dynamic-wave confluence

- Status: Accepted
- Date: 2026-07-28
- Scope: Stage 6 junction coupling after ADR-046

## Context

ADR-046 implemented one variable-geometry reach. A dendritic geographic river
network additionally needs junctions where two or more upstream reaches enter
one downstream reach.

The kinematic-wave network can sum upstream outflows because it evolves only
storage and discharge. A dynamic-wave junction must close both `A` and `Q` at
every connected branch without over-specifying any subcritical reach end.
Applying independent ghost-state HLL fluxes would not guarantee that the mass
leaving upstream reaches equals the mass entering the downstream reach.

## Junction Contract

Stage 6 supports two or more upstream reaches and exactly one downstream reach.
All reaches are oriented downstream and all adjacent terminal states must be
wet and subcritical.

The junction unknown is a common free-surface elevation. For every upstream
right boundary, the solver retains the outgoing `u+c` characteristic invariant.
For the downstream left boundary, it retains the outgoing `u-c` invariant.
The common stage supplies one boundary area per branch and the invariants supply
one boundary discharge per branch.

The scalar root equation is:

`sum(Q_upstream) - Q_downstream = 0`

Only subcritical roots are retained. The search includes adjacent internal
surface elevations, scans wet stage on a logarithmic depth axis, then bisects a
sign-changing bracket to `1e-12 m3/s` mass-rate tolerance. A supercritical
terminal or absence of a common-stage subcritical root fails closed.

The junction has zero modeled storage. It does not currently impose momentum,
specific-energy, head-loss, mixing-angle, or structure equations.

## Discrete Coupling

All reaches advance synchronously:

1. apply the first lateral and section-specific friction half-steps;
2. solve one junction from the updated terminal states;
3. use each resolved physical junction flux once at its connected reach end;
4. advance all variable-geometry hydrostatic flux steps;
5. apply the second friction and lateral half-steps.

The same upstream junction mass flux is removed from an upstream terminal cell;
the solved downstream mass flux is added to the downstream first cell. The
junction equation makes their sum identical within the root tolerance.

The CFL estimator iterates the candidate timestep through the first source
half-step and junction solve. It returns only after the actual post-source
junction states satisfy the requested Courant limit. This fixes the stale-node
CFL failure found during the Stage 6 dynamic diagnostic.

The network ledger separately reports lateral volume, external-boundary volume,
junction residual volume, reach-local volume residuals, and the final global
residual. Reach momentum ledgers remain numerical closure checks; no global
junction momentum-conservation claim is made.

## Evidence

All 14 outcome-free Stage 6 gates pass. No public data, action values,
observations, or saved predictions are read.

A symmetric manufactured junction recovers stage 2.0 m and `5+5=10 m3/s`
exactly. A second case with three different sections and beds recovers stage
3.0 m and `3+4=7 m3/s`; its mass residual is `3.26e-13 m3/s`.

A three-reach lake uses varying widths, side slopes, and beds. After 100
synchronous steps and 800.42 seconds, maximum area drift is `2.13e-14 m2` and
maximum spurious discharge is `1.18e-13 m3/s`. The cumulative network volume
residual is `4.93e-11 m3`.

The dynamic diagnostic places a 0.05 m surface perturbation on only one
upstream reach. Each reach is 800 m long; the network evolves for 120 seconds
on 16, 32, and 64 cells per reach. The perturbation crosses the junction and
changes downstream discharge by `0.71-0.99 m3/s`.

| Comparison | Depth L1 | Depth Linf | Flow L1 | Flow Linf |
|---:|---:|---:|---:|---:|
| 16 vs 32 | 0.000831 m | 0.003216 m | 0.053575 m3/s | 0.223998 m3/s |
| 32 vs 64 | 0.000609 m | 0.002653 m | 0.041836 m3/s | 0.185412 m3/s |

The four self-convergence ratios range from 0.733 to 0.828, below the fixed
0.85 gate. Maximum dynamic node mass residual is below `1e-12 m3/s`, maximum
reported Courant number remains below 0.4, and cumulative network volume
residuals are below `6e-12 m3`.

## Decision

Retain the common-stage, characteristic-compatible, mass-conservative
multi-in/one-out junction and synchronous three-reach step as the Stage 6
diagnostic.

Do not call this a general network operator. It does not yet support multiple
junctions in one DAG, bifurcation, junction storage, dry or supercritical
branches, momentum/energy closure, branch angles, or local structure losses.
Those require explicit contracts and independent gates.

The next stage is to schedule this local solver over a general dendritic DAG,
ensuring that every reach participates in at most one synchronized flux per end
and that all junction and external-boundary volumes close in one global ledger.

## Artifact

- Dynamic-wave junction gate report SHA256:
  `67d790dd3ea5e2842edb5a5a436df557db1294dfb21064e6898c54c9a9ffb57b`

## Claim boundary

- `subcritical_multi_in_one_out_junction_implemented=true`
- `junction_common_stage_closure_implemented=true`
- `junction_mass_ledger_implemented=true`
- `synchronous_multi_reach_step_implemented=true`
- `junction_dynamic_self_convergence_gate_passed=true`
- `junction_momentum_or_energy_closure_implemented=false`
- `bifurcation_junction_implemented=false`
- `general_dag_network_operator_implemented=false`
- `candidate_operator_admitted=false`
- `predictive_validation_complete=false`
- `geospatial_kernel_validated=false`
