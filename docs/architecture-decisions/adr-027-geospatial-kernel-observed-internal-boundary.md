# ADR-027: Observed Internal Boundary Replacement

**Date**: 2026-07-27  
**Status**: Accepted as a conservative operator contract; current held-boundary candidate rejected

## Context

ADR-026 found that the contemporaneous rank-one graph correction changed sign at 24 hours. That did not justify a
horizon-specific multiplier. It instead motivated a history-aware alternative: treat the Smith Fork gauge as an observed
internal boundary and reconstruct only the network downstream of that cut. The project acquired the required NLDI
flowlines itself; no user-supplied data was required.

An internal observation cannot be added as ordinary lateral forcing. The modeled upstream network already transfers water
into the gauge reach, so adding the observed discharge would count the same upstream contribution twice. A replacement
operator must remove the modeled transfer whenever the observed boundary is active, including when the observed value is
zero.

## Decision

Introduce `ObservedInternalBoundaryReplacement` as a typed Kernel input. For every affected substep, the observed
boundary flow enters the cut reach exactly once and the direct modeled upstream transfer leaves the analyzed domain as
`displaced_upstream_outflow_volume_m3`. The forecast-cycle identity is:

```text
initial storage + action + supported forcing + observed boundary
= final storage + outlet + displaced modeled upstream outflow
```

The GIS compiler, not a learned closure, owns the gauge attachment, directed reach, downstream segment, partial length,
forcing support, and spatial evidence. The reference candidate attaches USGS `03424730` to COMID `18421273`, whose
downstream COMID is `18421279`. NLDI and RouteLink agree on direction and length, but the gauge point is `52.071m` from
the NLDI line. This exceeds the frozen `30m` gate. Therefore the central downstream fraction `0.5844053909`, partial
RouteLink length `334.864m`, and bracket `[0.56817, 0.5844053909]` are diagnostic candidates only. Neither the linear
reference nor its length-scaled `q_lateral` support is admitted.

The preregistered development diagnostic compares:

- observed internal boundary: latest issue-time-available Smith Fork discharge held through one branch rollout;
- modeled-cut control: identical cut geometry and state but retained modeled upstream transfer;
- zero internal boundary: identical cut geometry with modeled upstream transfer removed and boundary flow set to zero;
- hash-verified parent local multi-gauge and persistence baselines.

No post-issue Smith Fork observation may enter a rollout. Future realized release and retrospective `q_lateral` remain
oracle archive inputs, so this is not an operational forecast.

## Evidence

The reference report SHA-256 is
`c0be689aaab2a2b6b13aab3fc3fe8481a61c7ebb844e198ef2b596b35d60f69b`; the frozen protocol SHA-256 is
`9366c726a1af9a8a9c609b34ddd7ff849c8143f3273e62b217984e721e710ab0`.

Common-mask RMSE is:

| Horizon | Observed boundary | Modeled cut | Zero boundary | Parent local | Causal persistence |
|---:|---:|---:|---:|---:|---:|
| 1h | 48.453 | 48.104 | 53.932 | 48.076 | 34.609 |
| 3h | 81.807 | 81.484 | 96.453 | 81.385 | 62.730 |
| 6h | 84.149 | 84.013 | 99.894 | 83.901 | 90.702 |
| 12h | 84.715 | 83.381 | 99.874 | 83.334 | 114.442 |
| 24h | 88.717 | 82.317 | 100.165 | 82.307 | 86.588 |

The candidate beats the zero-boundary ablation at every horizon, proving that nonzero upstream boundary information is
material. It fails to beat modeled-cut and parent-local RMSE at every horizon. It beats causal persistence only at 6h and
12h, so all four non-compensatory core horizons fail. The development gate is closed.

The failure is dynamic rather than conservative. All three scenarios pass the mass gate; the largest residual-to-tolerance
ratio is below `4.78e-4`. Across unique cycling ledgers, the observed-boundary scenario injects
`56,624,308.981m3`, displaces `59,810,251.036m3`, and records the resulting `-3,185,942.055m3` net analysis volume.
No future observation update occurs.

Held-last boundary flow is especially unsuitable during hydrograph transitions. For the issue at
`2021-12-30T10:00Z`, `256.268m3/s` is held for 24 hours; the candidate predicts `525.580m3/s` at the outlet while the
observed target is `266.178m3/s` and modeled-cut predicts `348.429m3/s`. This is diagnostic error attribution, not a
license to fit a decay parameter on the exposed window.

Prediction SHA-256 is `d737452afba873f02bbbaf070cdf72ed7a2af2d908138bf5f63cea6316b766ad`; report SHA-256 is
`78549912fe362142a109fd8957dd3cc18a5654987cecbbe75b29edd3056b2528`.

## Relationship to Traditional GIS Operators

Traditional GIS linear referencing and network tracing compile where a gauge lies, which downstream segment is retained,
and which features are upstream or downstream. Those spatial results are necessary and are reused unchanged. They do not
define a causal time-varying boundary condition, decide which modeled flux must be displaced, carry an observation vintage,
or prove a recursive mass identity.

The Kernel operator therefore differs in execution and scientific contract, not in basic geometry mathematics. It consumes
the GIS-compiled cut at every transition, changes the dynamic state domain, replaces rather than overlays flux, writes an
auditable volume ledger, rejects unavailable observation vintages, and propagates the boundary effect through future state.
Learning may forecast the boundary hydrograph or estimate hidden state, but it cannot move the gauge, reverse the reach,
change the cut support, or bypass conservation.

## Consequences

Retain the generic internal-boundary replacement contract and its conservation tests. Reject the current combination of
unadmitted 52m linear reference, length-proportional partial forcing, and issue-time observation persistence as a predictive
candidate. This is not a failure of the Geospatial Kernel mission: the operator has made the geographic domain, information
boundary, and failed temporal assumption independently testable.

The next candidate must separate four responsibilities:

1. an evidence-gated GIS compiler for attachment, direction, cut geometry, and catchment support;
2. a causal observer using only issue-time and earlier gauge history;
3. a low-dimensional boundary-hydrograph transition with topology and hydraulic travel-time priors;
4. the unchanged conservative downstream routing and displacement ledger.

The project must acquire another public development interval itself and freeze its use before estimating transition
parameters. The exposed interval cannot select recession constants, lag, or horizon weights. A higher-precision gauge-to-
flowline/catchment source is also required before the partial boundary can be admitted. A new untouched multi-system window
must not be consumed until this development candidate beats the registered baselines.

## Claim Boundary

- `public_internal_boundary_reference_acquired=true`
- `internal_boundary_contract_implemented=true`
- `internal_boundary_mass_gate_passed=true`
- `internal_boundary_reference_admitted=false`
- `partial_forcing_support_admitted=false`
- `held_boundary_development_gate_passed=false`
- `operational_observation_vintage_verified=false`
- `operational_forecast_evaluated=false`
- `forecast_closure_validated=false`
- `geospatial_kernel_validated=false`
