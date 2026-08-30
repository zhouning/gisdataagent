# ADR-037: Attribute kinematic-wave phase error before the next operator

- Status: Accepted
- Date: 2026-07-28
- Scope: Geospatial Kernel transport-closure development after ADR-036

## Context

ADR-036 rejected predictive admission of the branching finite-volume
kinematic-wave operator. The numerical core conserved mass, preserved
nonnegative finite state, respected its CFL contract, and executed complete
tributary DAGs, but failed the two-system predictive gate. Post-score evidence
showed delayed and attenuated responses. That evidence could not determine
whether the delay came from timestamp labels, branch topology, RouteLink
geometry, Manning wave celerity, or missing dynamics.

The completed 2022-03-31 through 2022-04-28 public blind window is now outcome
visible. It is therefore reused only as a posthoc development window. The
current kinematic operator was rerun without changing its equation, geometry,
cell length, CFL number, forcing, initial state, or action boundary. A reusable
temporal-support-aware auditor first maps every label to the center of its
declared support, then scans integer time shifts. Statistical shifts are
explicitly diagnostic and are never admitted as flood-wave travel time.

## Evidence

All action, prediction, and observation values are hourly interval means with
end-of-period labels. Their temporal-support center offset is zero in both
systems. Timestamp-position semantics therefore do not explain the measured
phase error on this window.

| Diagnostic | Center Hill | J. Percy Priest |
| --- | ---: | ---: |
| Action shift giving minimum observation RMSE | +6 h | 0 h |
| Kinematic prediction shift giving minimum observation RMSE | -10 h | -2 h |
| Branch-silent prediction shift | -10 h | -2 h |
| Initial-state Manning `dQ/dA` path time | 15.56 h | 2.64 h |
| RouteLink effective path length | 25.17 km | 4.77 km |
| Full-DAG zero-shift RMSE improvement over branch-silent | 10.00 m3/s | 0.69 m3/s |

A positive action shift moves the release to a later observation timestamp; a
negative prediction shift moves a delayed prediction earlier. Center Hill's
approximately 15.6-hour physical path time exceeds its 6-hour action phase by
about 9.6 hours, consistent with the independently measured -10-hour
prediction correction. J. Percy Priest's approximately 2.6-hour physical path
time is likewise consistent with the -2-hour prediction correction relative
to its zero-hour action phase. This agreement is attribution evidence, not a
calibration rule.

The initial Manning `Q -> A` closure is not grossly inconsistent with the
independent NWM `streamflow / velocity` area proxy. Manning-to-NWM area-ratio
q05/q50/q95 values are `1.002/1.017/1.095` at Center Hill and
`1.003/1.046/1.138` at J. Percy Priest. NWM area remains a modeled proxy, not
ground truth, but the comparison does not support initial area scaling as the
primary defect.

An outcome-free sensitivity using positive public boundary releases as a
uniform path state gives Manning travel-time q05/q50/q95 values of
`12.87/17.01/17.23 h` and `2.08/2.08/2.15 h`. The excess delay persists over
the observed positive-action range. Branch inclusion improves amplitude,
especially at Center Hill, but does not change the best phase in either system.

Every rerun execution gate passed. The maximum Courant number equaled the
predeclared two-ULP reporting limit `0.8000000000000003`; conservation,
positivity, zero-input identity, and diagnostic-only flags all passed.

## Decision

Retain the conservative finite-volume state transition, explicit mass ledger,
typed spatial support, and complete tributary DAG. Do not admit the present
Manning kinematic closure as a predictive operator.

Do not deploy the observed `+6/0 h` action shifts or `-10/-2 h` prediction
shifts. Do not fit a celerity multiplier, Manning coefficient, affine
correction, or storage constant on this outcome-visible window.

The next operator work proceeds in this order:

1. expose a public, typed state-dependent path-response diagnostic rather than
   relying on a private hydraulics method;
2. acquire public NWM streamflow and velocity over development windows and
   compile outcome-free celerity envelopes along the exact linear-referenced
   action-to-outlet paths;
3. audit boundary and gauge spatial measures against the RouteLink path,
   retaining effective partial-reach lengths;
4. compare kinematic, diffusive-wave, and local-inertial response families on
   analytic and public development cases with the same mass ledger;
5. add controlled storage only where independent infrastructure or operating
   evidence identifies a storage state; an unconstrained storage term is not
   the first response to an already delayed and attenuated prediction;
6. freeze a new multi-system holdout only after the operator family and all
   missing/negative observation rules are fixed.

Local-inertial or diffusive dynamics are candidates, not predetermined winners.
The evidence says the current closure propagates the relevant observed signal
too slowly; it does not by itself identify which omitted physical term is
responsible.

## Artifacts

- Development attribution report SHA256:
  `5e573ebbc6776b23fa44128737401543d0d95530ab4f2a03081a173fe92f0bc0`
- Center Hill prediction SHA256:
  `733fdf2fdb5815cc4980638f2bc76b2a034c6ac7b8c041ca4011ef60c60df6b6`
- J. Percy Priest prediction SHA256:
  `c26711e87583d8a3c5c99879f888299e66a81719aca5e03aaa652139be79c1fd`

## Claim boundary

- `outcome_visible_development_only=true`
- `temporal_support_offset_primary_failure=false`
- `initial_area_scaling_primary_failure=false`
- `tributary_DAG_primary_phase_failure=false`
- `current_propagation_closure_too_slow_supported=true`
- `statistical_shift_admitted_as_flood_wave_lag=false`
- `physical_travel_time_prior_admitted=false`
- `operator_form_admitted=false`
- `geospatial_kernel_validated=false`
