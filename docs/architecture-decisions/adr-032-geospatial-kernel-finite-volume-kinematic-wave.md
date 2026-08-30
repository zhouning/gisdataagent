# ADR-032: Project-Owned Finite-Volume Kinematic-Wave Core

**Date**: 2026-07-27  
**Status**: Numerical operator baseline established; operator-form admission pending

## Context

ADR-031 showed that explicitly initializing the fixed t-route Muskingum-Cunge source removes its measured call-order
sensitivity but does not remove the registered negative-response and timestep-stability failures. The Geospatial Kernel
mission still requires a project-owned spatial-dynamics core. It cannot be reduced to calling traditional GIS tools, and it
must not depend on repairing one external routing implementation.

The user supplies no private data. This work therefore uses the already acquired public NOAA-OWP/t-route Hurricane Laura
RouteLink fixture, its nine consecutive full reaches, and synthetic boundary flows. It loads no observed discharge, action,
forcing, or target outcome.

## Decision

Implement a separate finite-volume kinematic-wave operator with explicit geographic state and flux contracts:

1. The conserved state is water volume in each linear-referenced cell, not an opaque per-reach routing memory.
2. Each reach is subdivided by a registered target cell length while retaining the RouteLink feature identity and
   within-reach cell index.
3. The solved equation is `dA/dt + dQ(A)/dx = q_lateral`.
4. `Q(A)` is computed from trapezoidal channel geometry, bed slope, and Manning roughness. The downstream Godunov/upwind
   flux follows the nonnegative kinematic-wave characteristic direction.
5. Explicit Euler updates use adaptive internal substeps derived from the analytic Manning `dQ/dA` and a CFL limit of
   `0.8`.
6. Every external step exposes physical input, outlet volume, initial and final storage, mass residual, maximum Courant
   number, and admission flags.
7. The implementation is independent of the existing nonlinear reach-storage operator and of the t-route shared library.

The boundary `Q -> A` inverse is solved against the same Manning relation and cached by boundary flow. The analytic wave
celerity is evaluated in a form with a finite dry limit; no artificial epsilon depth or post-hoc response clipping is used.

## Outcome-Free Matrix

The registered matrix repeats the ADR-029 background flows (`2/20/100 m3/s`), pulse rates (`0.1/1/10 m3/s`), external
timesteps (`300/900/3600 s`), 240-hour zero-state warmup, and 240-hour rollout. Every one of the 27 cases is run at target
cell lengths `2000/1000/500 m`, yielding 81 resolution runs. The 1000 m grid is primary and the 500 m grid is the fine
reference.

The following gates pass:

- every warmup and response step satisfies its explicit mass tolerance;
- every state remains finite and nonnegative;
- every CFL value is at or below the configured limit, up to floating-point comparison tolerance;
- all 81 response mass identities pass;
- all 81 negative-lobe checks pass; the largest accumulated negative differencing volume is approximately
  `2.05e-10 m3`, below the registered tolerance;
- all 54 primary-grid timestep comparisons pass;
- all 81 primary-to-fine spatial comparisons pass the registered `max(3600 s, 10%)` tolerance.

The strict auxiliary refinement-trend gate fails in 2 of 81 comparisons. Both are `t50` at background `2 m3/s`, pulse
`10 m3/s`, for external timesteps `300 s` and `900 s`. The 1000-to-500 m differences are approximately `263 s` and
`217 s`; in these two cases the 2000 m result happens to lie closer to the 500 m result. These differences are well inside
the registered spatial-stability tolerance, but strict error nonincrease was pre-registered and remains failed. The overall
diagnostic gate is therefore false; its threshold is not revised after observing the results.

## Analytic Shock Benchmark

Because comparison among numerical grids does not provide an exact reference, a second protocol uses the entropy solution
of a Riemann problem on a uniform 10 km reach. The initial/right state is `2 m3/s`, the upstream/left state is `10 m3/s`,
and the horizon is 3600 s. The independently evaluated Manning flux gives areas `3.4704 m2` and `9.8066 m2`; the
Rankine-Hugoniot shock speed is approximately `1.26259 m/s`, placing the exact front at `4545.34 m`. Numerically evaluated
characteristic speeds satisfy the Lax condition around that shock.

At target cell lengths `2000/1000/500/250 m`, normalized L1 errors against exact cell averages decrease as
`0.1403/0.0891/0.0742/0.0372`. All states remain bounded by the two Riemann states, all step mass and CFL gates pass, and
the 250 m excess-mass front position differs from the analytic position by approximately `1.4e-11 m`. Observed pairwise
orders are approximately `0.65/0.26/1.00`; the intermediate grids are not a clean asymptotic sequence. The admitted claim
is therefore finite-volume consistency and strict error decrease under this protocol, not a general proof of first-order
convergence.

## Consequences

The project now owns a transparent geographic transport equation whose state, geometry, spatial support, conservation, and
numerical stability can be inspected and tested. This is materially different from a traditional GIS routing tool: the
operator is designed as a typed, differentiable-by-contract world-state transition with explicit evidence and admission
boundaries. Its basic hydraulic formulas are nevertheless standard GIS/hydraulic mathematics and should continue to be
cross-checked against independent implementations.

Do not promote the operator yet. The present matrix establishes a numerical baseline on one public parameter path; it does
not establish that the kinematic approximation is appropriate where backwater, controls, floodplain exchange, branching,
or compound channels dominate. The next kernel work should add an independently sourced analytic or laboratory benchmark,
then a public observed holdout chosen without fitting the response operator. Real-world performance, parameter support, and
regime-specific admission must remain separate gates.

The two nonmonotone refinement cases do not indicate conservation failure, but they prevent a claim of clean monotonic
spatial convergence under the registered grid sequence. A future convergence study may add finer grids and an analytic
reference, but it must be registered as a new protocol rather than rewriting this result.

## Artifact Identity

- finite-volume response matrix: `5331a93555d43ec40cc5ea017615b26fb42ad0f6ae87403b65242be87322fdf6`.
- analytic shock report: `ff792f0dad1f4119696fcd35482e250c2478a58621422683f0f77f0a0e174d7a`.

## Claim Boundary

- `finite_volume_equation_implemented=true`
- `physical_volume_conservation_tested=true`
- `negative_lobe_cases_above_tolerance=0/81`
- `primary_timestep_stability_passed=54/54`
- `primary_to_fine_spatial_stability_passed=81/81`
- `strict_refinement_trend_passed=79/81`
- `analytic_shock_l1_error_decreased=3/3`
- `finite_volume_consistency_supported=true`
- `operator_form_admitted=false`
- `professional_transfer_operator_certified=false`
- `hydrodynamically_validated=false`
- `geospatial_kernel_validated=false`
