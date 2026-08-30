# ADR-046: Gate the variable-geometry dynamic-wave core

- Status: Accepted
- Date: 2026-07-28
- Scope: Stage 5 geometry coupling after ADR-045

## Context

Stages 2 through 4 used one trapezoidal section for every cell. A geographic
river cannot retain that assumption: bottom width, side slope, wetted area,
celerity, pressure, and friction all vary along the reach.

Simply evaluating each side of an HLL interface with its own section is not a
valid conservative flux. The two states would use incompatible area-pressure
relations, and width changes would generate spurious motion in a lake at rest.

Stage 5 therefore needs an explicit interface geometry and a cell-side pressure
contract. It does not yet need to assert a calibrated energy-loss law for an
abrupt contraction or expansion.

## Interface Contract

Each cell owns one trapezoidal section. At an interface, bottom width and side
slope are arithmetic means of the two cell parameters. Both cell states are
mapped to this common section while preserving reconstructed water depth and
mean velocity.

Bed reconstruction first uses the maximum interface bed elevation. The shared
HLL solver then receives the two mapped interface states. Its mass flux is used
on both sides, preserving finite-volume volume conservation.

The momentum flux returned to each cell is:

`shared_HLL_momentum + cell_pressure - reconstructed_interface_pressure`

At lake at rest, the shared HLL momentum equals reconstructed interface
pressure. Each side therefore receives its own original cell pressure. The
incoming and outgoing momentum fluxes of every cell cancel even when bed and
section geometry both vary.

If the two cell sections are identical, the interface section is identical and
the formula reduces to the Stage 2 hydrostatic reconstruction.

## Source Coupling

The Stage 3 symmetric source order is retained. Manning friction is evaluated
with each cell's own section, hydraulic radius, and roughness. Bed and geometry
acceleration remain in hydrostatic reconstruction only. Lateral volume retains
the explicit zero-momentum or matched-velocity convention.

Fixed and Stage 4 characteristic boundaries are supported with explicit
boundary sections. Characteristic closure distinguishes the adjacent internal
section from the boundary section. Boundary sections should normally continue
the terminal reach geometry; a geometry jump at a characteristic ghost is not
silently interpreted as a calibrated local loss.

The momentum ledger groups boundary, geometry, and bed contributions because
the hydrostatic interface correction represents all three in one flux step.

## Evidence

All 14 outcome-free Stage 5 gates pass. No public data, action values,
observations, or saved predictions are read.

With identical left and right sections, all area-flux terms and the left
momentum flux exactly match Stage 2. The right momentum difference is
`1.42e-14 m4/s2`, at floating-point rounding scale.

A four-cell lake combines bottom widths from 6 to 12 m, side slopes from 0.5
to 2.0, four bed elevations, and different boundary sections. After 100
coupled steps and 826.26 seconds, area drift and surface change are zero.
Maximum spurious discharge is `9.39e-15 m3/s`, and maximum step mass residual
is `6.19e-14 m3`.

The moving diagnostic uses a 2400 m smooth geometry field with bottom width
varying from 8 to 12 m and side slope from 1.2 to 1.8. A 0.1 m Gaussian
free-surface perturbation evolves for 120 seconds on 24, 48, and 96 cells.
There is no analytic solution, so each finer result is interpolated to the
coarser cell centers:

| Comparison | Depth L1 | Depth Linf | Flow L1 | Flow Linf |
|---:|---:|---:|---:|---:|
| 24 vs 48 | 0.002358 m | 0.005190 m | 0.126464 m3/s | 0.336978 m3/s |
| 48 vs 96 | 0.001505 m | 0.003842 m | 0.085618 m3/s | 0.244325 m3/s |

The four fine-to-coarse difference ratios range from 0.638 to 0.740, below the
fixed 0.8 self-convergence gate. All states remain wet and CFL-compliant. The
96-cell cumulative mass residual is `7.07e-12 m3`; its momentum ledger closes
exactly at reported precision.

## Decision

Retain the per-cell trapezoidal geometry, arithmetic interface section,
velocity-preserving state projection, cell-side pressure correction, and
section-specific friction as the Stage 5 variable-geometry diagnostic.

Do not interpret the arithmetic interface as a universal physical model for
abrupt structures. No contraction coefficient, expansion loss, bridge, gate,
weir, surveyed-section ingestion, or compound/floodplain section is present.
Those require explicit typed structures rather than hidden tuning inside the
Riemann flux.

The next numerical stage is conservative network-junction coupling with a
junction-local mass ledger. Public DEM and hydrograph adapters can then bind
geometry and boundary time series without changing the frozen equations or
reading development outcomes.

## Artifact

- Variable-geometry gate report SHA256:
  `d5b569ccb1f754b5906b5c8cec50c82be0254d4f48527ad3746934e95777342d`

## Claim boundary

- `variable_geometry_hydrostatic_flux_implemented=true`
- `variable_geometry_source_coupling_implemented=true`
- `variable_geometry_dynamic_self_convergence_gate_passed=true`
- `contraction_expansion_loss_model_implemented=false`
- `surveyed_cross_section_adapter_implemented=false`
- `network_operator_implemented=false`
- `candidate_operator_admitted=false`
- `predictive_validation_complete=false`
- `geospatial_kernel_validated=false`
