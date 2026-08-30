# ADR-039: Retain the path after auditing action and gauge measures

- Status: Accepted
- Date: 2026-07-28
- Scope: Geospatial Kernel transport-closure development after ADR-038

## Context

ADR-038 rejected ordinary state variation and NWM advective velocity as
remedies for the kinematic-wave phase failure. Before adding a physical term
to the transport equation, the action and observation endpoints had to be
audited against the exact NLDI path. A misplaced endpoint could otherwise
look like a propagation error.

The new typed spatial-measure audit separates two facts that a conventional
nearest-point operation often conflates:

1. a finite candidate projection can be computed for a point and flowline;
2. that projection is close enough to be admitted as a linear measure.

The audit orients every reach into directed path order, reproduces the public
NLDI path length, checks inter-reach continuity, and projects the authoritative
USACE action point and USGS/NLDI gauge point. A 100 m snap limit is fixed for
measure resolution. Candidate measures outside the limit remain visible but
their admitted measure is `null`.

## Evidence

| Spatial diagnostic | Center Hill | J. Percy Priest |
| --- | ---: | ---: |
| Action-point snap distance | 10.78 m | 676.32 m |
| Action measure resolved | yes | no |
| Candidate action position on control reach | 100.0% | 74.3%, not admitted |
| Gauge-point snap distance | 54.39 m | 86.28 m |
| Gauge measure resolved | yes | yes |
| Terminal effective length to gauge | 938.43 m | 612.03 m |
| Current initial Manning path time | 15.56 h | 2.64 h |
| Time after removing entire first and terminal active reaches | 14.63 h | 2.22 h |
| Action-to-observation statistical phase | 6 h | 0 h |

Both directed paths are continuous and reproduce the reported NLDI full path
length to substantially less than the fixed 5 m tolerance. Both terminal
measures exactly reproduce the effective terminal reach already used by the
kernel.

Center Hill's action point resolves at the downstream end of the excluded
control reach. The current rule that the release enters the first downstream
reach is therefore spatially supported.

The J. Percy Priest action point is too far from the generalized NHDPlus
centerline to support a precise along-reach measure. Its 2.68 km candidate
measure and 0.93 km candidate residual are retained as diagnostics but are
not admitted. NLDI still assigns the point to the excluded upstream control
feature, so this uncertainty cannot justify shortening the current active
path. It could only add an upstream residual under that topology.

As a deliberately over-permissive negative control, the posthoc audit removes
the complete first and terminal active-reach travel-time contributions. This
is a larger shortening than either endpoint evidence supports. The remaining
times are still 8.63 hours beyond Center Hill's action phase and 2.22 hours
beyond J. Percy Priest's action phase. Endpoint measure error therefore cannot
explain the shared slow-propagation failure.

The phase comparison remains outcome-visible development evidence. Its shifts
are not physical travel times and are not deployed as corrections.

## Decision

Retain the current directed paths, control-reach exclusion, terminal partial
reaches, and effective-length ledger for transport-operator development.
Reject action or gauge measure error as the primary phase failure.

Retain Center Hill's action and gauge measures as derived, resolved spatial
support. Retain J. Percy Priest's gauge measure, but keep its candidate action
linear measure unadmitted. A future confirmatory protocol must either obtain
independent public dam/outlet geometry or freeze an explicit unresolved
boundary bracket; it must not silently promote the candidate projection.

Do not use endpoint adjustment, reach deletion, or the posthoc bound as a
prediction correction. The next kernel work proceeds to outcome-independent
analytic gates that distinguish kinematic, diffusive-wave, and local-inertial
response families while preserving the existing mass ledger.

## Artifact

- Spatial-measure audit report SHA256:
  `3978af46ed6280162d5c0296831401b2f471d5e4c3db17b360c2abbeb52ea81a`

## Claim boundary

- `public_data_without_user_supplied_data=true`
- `center_hill_action_measure_resolved=true`
- `j_percy_priest_action_measure_resolved=false`
- `both_gauge_measures_resolved=true`
- `j_percy_priest_candidate_action_measure_admitted=false`
- `endpoint_measure_primary_phase_failure=false`
- `statistical_shift_admitted_as_flood_wave_lag=false`
- `operator_form_admitted=false`
- `geospatial_kernel_validated=false`
