# ADR-029: Volume-Consistent Transfer Response Certification

**Date**: 2026-07-27  
**Status**: Response-metric contract admitted; current t-route MC integration rejected for promotion

## Context

ADR-028 exposed the state-conditioned Manning response from Smith Fork to the Center Hill outlet, but reported timing by a
fixed first-arrival threshold, peak hour, and endpoint-weighted center of mass. That representation could hide finite-window
tail loss and numerical negative response by clipping. It also did not place the fixed-commit t-route Muskingum-Cunge (MC)
adapter and the conservative Manning storage baseline under one state, amplitude, and timestep protocol.

The project receives no user-supplied data. This decision therefore uses only the previously verified RouteLink fixture,
fixed official t-route source at commit `12a8eae0cdfed437143c590659fa7077605a5e70`, and synthetic boundary perturbations.
No observed action, forcing, upstream discharge, or downstream outcome is loaded.

## Decision

Admit `DynamicTransferResponseMetrics` as the common outcome-free response contract. It accepts interval-mean incremental
outlet flow, the injected volume, and final incremental storage. It does not clip negative response. It reports positive,
negative, and net outlet volume; the mass identity; peak and center time; and `t01/t05/t50/t95` under two explicit bases:

1. the positive response volume recovered inside the simulated window; and
2. net cumulative outlet response as a fraction of the known input volume, where an unreached quantile is null.

Quantile time is linearly interpolated inside a constant-rate interval. The center uses interval midpoints rather than
interval endpoints. Threshold first arrival is retained only as a secondary diagnostic.

For professional-baseline screening, fork base and pulse branches from the identical operator-specific warmed state. Use
background flows `2/20/100m3/s`, pulse rates `0.1/1/10m3/s` integrated over one hour, timesteps `300/900/3600s`, a 240-hour
warmup, and a 240-hour response window. Timestep stability compares `t05/t50/t95` against the 300-second result with a
pre-registered tolerance of the greater of one hour or 10 percent.

## Smith Fork Response Evidence

The v2 Smith Fork audit preserves the 12-reach, `21.720km` path and the one-hour `3,600m3` unit pulse. It passes solver,
differenced-mass, negative-lobe, `t95` recovery, and outcome-isolation gates. Input-volume recovery timing is:

| Metric | Hours |
|---|---:|
| t01 | 6.120 |
| t05 | 8.265 |
| t50 | 17.359 |
| t95 | 47.998 |
| positive-response center | 21.507 |
| peak interval end | 14.000 |

The 240-hour net recovered fraction is `99.9242%`; `2.729m3` remains in storage and the differenced mass residual is
`-4.21e-8m3`. These are model-conditioned Manning response facts, not observed transfer truth.

## Fixed t-route MC Matrix Evidence

All nine warmup combinations finish nonnegative and finite. Their outlet relative steady errors are below `3.9e-6` for the
MC adapter and below `3.7e-12` for Manning, so the matrix is not a cold-start comparison.

The conservative Manning baseline passes all 27 differenced mass identities, all negative-response gates, all solver step
mass gates, and all 54 timestep comparisons. Its net recovered fraction is numerically `1.0000000000` to
`1.0000000035`. At 300 seconds its `t50` decreases consistently with higher background flow for every pulse amplitude.

The current fixed t-route MC integration does not pass promotion gates:

- 24 of 27 cases have a negative response volume above the registered tolerance;
- 28 of 54 timestep comparisons fail;
- net recovered fraction ranges from `0.7235` to `3.4750` under the derived physical-stock diagnostic;
- some low-flow cases show large amplitude sensitivity, and the `20m3/s` background with `10m3/s` pulse does not recover
  input `t95` inside the window;
- higher-background `t50` ordering fails for the `10m3/s` pulse at the 300-second reference step.

The official single-segment kernel does not expose an authoritative internal MC storage state. Therefore the derived
depth-times-area mass residual is diagnostic and cannot establish that the MC method or the complete t-route application is
nonconservative. The negative-lobe and timestep gates, however, are observable directly on the adapter's incremental outlet
response and are sufficient to reject promotion of this integration.

## Consequences

Keep the fixed-commit t-route adapter as a professional diagnostic baseline; do not make it the default Geospatial Kernel
transfer operator. Keep conservative Manning storage as the current diagnostic baseline, not as validated geographic truth.

Before another MC promotion attempt, audit the current adapter against the complete t-route reach-execution contract,
including upstream recursion, timestep/subdivision policy, lateral-flow semantics, channel-side-slope convention, compound
geometry, and float32 perturbation resolution. Add an independently implemented kinematic-wave comparator and explicit
reach subdivision. Repeat the outcome-free matrix before opening any new downstream gauge-pair outcomes.

This rejects one operator integration, not the Geospatial Kernel mission, the Muskingum-Cunge method in general, or the
official t-route application as a whole.

## Artifact Identity

- Smith Fork volume-response v2 report: `f3daaca5059f9c8628d4380d788fa7006bd120df3a0d3123ba0a5a59aa231898`;
- t-route professional baseline v2 report: `85ced7459e891230de8e80c9864aaf2be00a47086d3732fbd5f869946138859d`;
- t-route MC response matrix report: `d84b1b34c4dc3874fedc4f0cd012815fb342b948fb726abe610dbe3a02d4b075`.

## Claim Boundary

- `volume_response_metric_contract_admitted=true`
- `smith_fork_outcome_free_response_gates_passed=true`
- `t_route_mc_state_amplitude_timestep_matrix_executed=true`
- `t_route_mc_promotion_gate_passed=false`
- `official_mc_conservation_verified=false`
- `kinematic_wave_comparator_available=false`
- `real_world_transfer_validated=false`
- `professional_transfer_operator_certified=false`
- `geospatial_kernel_validated=false`
