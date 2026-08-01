# GeoTransport v0.1

This directory freezes the public-data contract for the first Geospatial
Kernel 2.0 falsification loop. It contains no benchmark time-series bundle and
makes no benchmark-performance claim. One bounded local NWM value smoke is
recorded solely as extractor evidence.

The `minimal` cohort contains:

- 3 hourly USACE action to USGS outcome systems (`GeoTransport-H`);
- 4 daily USBR action to USGS outcome systems (`GeoTransport-D`);
- 2 USBR reservoir mass-balance systems (`GeoConservation-D`).

Every transport system requires NOAA NWM v3 retrospective `q_lateral` as an
explicit modeled forcing channel. The seven action-to-outcome NLDI paths and
all 158 path COMIDs have passed NWM v3 `feature_id` membership. The registry
therefore freezes each path's `feature_ids`, global `feature_indices`, and
required q_lateral feature chunks. It also pins the parent-registry and
crosswalk-report hashes used to admit those fields.

The Center Hill 24-hour smoke acquired one time chunk and one q_lateral chunk,
then reconstructed 648 values for 27 path reaches. The frozen smoke report
verifies raw and derived hashes, time continuity, feature order, fill masking,
scaling, and modeled-forcing semantics. That NWM-only report does not make an
action, state, outcome, training-panel, benchmark, or Kernel claim.

A second bounded step acquired three Center Hill CWMS series plus USGS
03424860, then compiled a 24-row, no-missing multisource smoke panel. The panel
remains `compiled_not_admitted`: CWMS hourly-average timestamp semantics and
action-to-gauge travel time have not been frozen, so timestamp-equality joins
cannot support training or evaluation claims.

NWM values must use the dedicated bounded extractor, which validates the
frozen crosswalk, aligns requests to hourly time coordinates, downloads only
intersecting `[672, 30000]` chunks,
masks the packed fill value before scaling, and retains `q_lateral` as modeled
forcing rather than an observation. A plan can be inspected without fetching
values:

```shell
uv run python -m scripts.extract_geotransport_nwm_q_lateral \
  --system center_hill \
  --start 2022-01-01T00:00:00Z \
  --end 2022-01-02T00:00:00Z \
  --plan-only
```

The registry does not authorize redistribution of CWMS values. Source
attribution, provisional/revision flags, retrieval timestamps, request URLs,
raw hashes and the final data-license audit must be retained in any acquired
bundle.

The directory also contains two outcome-free operator reports on an official
Hurricane Laura RouteLink fixture. The nonlinear Manning reach-storage report
uses `horizontal_per_vertical = 1 / RouteLink ChSlp`, preserves an explicit
physical-volume state, and passes its conservation and direction invariants.
The fixed-commit t-route report executes the official
`c_muskingcungenwm` Fortran entrypoint and compares Q/V/D and reversed-order
response with that research operator.

The t-route report is intentionally marked
`pass_with_conservation_limitation`: the public Q/V/D plus returned `ck/X` do
not expose or reconstruct a telescoping internal MC storage. It is admitted as
a professional Q/V/D and direction baseline, not as a conservation oracle.
Neither fixture covers any Center Hill active feature, and neither report is a
benchmark or real-world direction validation.

Kernel v2 also freezes an outcome-free causal-update and partial-forcing
report. It rejects future, not-yet-available, stale, and unadmitted-quality
discharge observations; records a Manning discharge-to-storage correction as
an external analysis increment rather than transition flux; and verifies that
partial-reach forcing closes separate raw, applied, and excluded-volume
ledgers. The probe uses official RouteLink geometry plus synthetic values. It
loads no observed outcome, action, or forcing series and does not access the
next Center Hill evaluation chunk, so it supports contract invariants only.

A separate NOAA OWP NWM v3.0 parameter acquisition now verifies the full
CONUS RouteLink distribution and compiles a 27-feature Center Hill subset. All
26 active path features and all required hydraulic fields are present, and
the active `to` topology is consecutive. This passes the geometry/parameter
gate. It does not establish byte identity with the retrospective production
domain.

The D1 acquisition reads only the pre-window NWM v3 retrospective
`streamflow/560.63` object and compiles a modeled initial state at
`2022-02-03T00:00:00Z`. It covers 27/27 source features and 26 active reaches;
the zero-effective-length waterbody/action feature is explicitly excluded.
The state is modeled, not ground truth, and has no verified operational-online
availability. Neither chunk `561` nor evaluation outcome is read.

The D2 audit uses the official EPA NHDPlus V2.1 `05a` FAC/FDR archive and the
USGS NLDI split-catchment process. The NLDI measure point itself falls on an
adjacent low-FAC cell, so the frozen method snaps to the nearest cell whose
accumulated drainage area matches the terminal COMID scale. Nine consecutive
D8 main-channel cells have monotonic split coverage, and the selected response
is byte-identical on repeat and from the nearest centerline point. Terminal
coverage is `0.842973815499`, with an adjacent 30 m cell bracket of
`[0.827204578700, 0.936645191100]`.

This compiles an admitted 26-feature `ReachForcingSupport`: 25 full reaches
have fraction `1`, while terminal COMID `18421703` uses the selected
split-catchment fraction. The bracket is retained, and the artifact explicitly
states that subcatchment q_lateral values were not observed. D0-D2 therefore
open retrospective transition-input execution only.

D3 was subsequently frozen before chunk `561` or the new-window outcome was
read. The protocol fixes a 672-hour window, the central support candidate, two
report-only support brackets, four causal ablations, persistence, official
t-route MC, direct release, conservation gates, and scoring thresholds. Its
SHA-256 is
`d3675aaadd1274949748da754bc843f11aa7e31bed8e7c4cf74c28fe1e689f8c`.

After freeze, `q_lateral/561.63`, CWMS action, and the initial state drove an
outcome-free Linux/aarch64 rollout. The prediction CSV SHA-256 is
`0a309b2c37b3ca4e503dfea0e2e96832bbe6d06b54f913728cdb2d5da784f074`;
all seven nonlinear scenarios conserve physical volume. Only then was the
USGS outcome opened and scored for all 672 hours.

D3 failed. The central nonlinear RMSE is `162.753 m3/s`, versus `15.058 m3/s`
for persistence and `167.864 m3/s` for t-route MC. Zero action, no forcing,
and state-only degrade as required, but reversed topology is slightly better
than the authoritative order (`162.616 m3/s`). The support upper bracket is
also slightly better than central and remains report-only, as preregistered.

The result preserves D0-D2 but closes the current linear-mainstem model claim.
The path includes only mainstem q_lateral and omits routed flux from off-path
tributaries joining between the dam and gauge. The next kernel task is to
compile a branching NHDPlus/NWM DAG with explicit confluence boundary support
and a network conservation ledger, then evaluate it on a fresh window and a
second system. Operational-online and general Geospatial Kernel validation
remain closed.

D4 has now compiled the first branching remediation without changing the D3
artifacts. A bounded NLDI upstream-tributary response identifies 19 direct
off-path tributary mouths along the 25.17 km linear-referenced effective
interval (28.38 km full-reach navigation envelope), attached to 19 exact
mainstem receiving features. All 19 tributary IDs occur on the NWM v3 feature
axis; their retrospective streamflow values require chunks `561.63` and
`561.87` and contain no fill values for the 672-hour window.

The total modeled tributary-mouth flow averages `63.906 m3/s`. It is typed as
`modeled_tributary_boundary_flux`, with `ground_truth=false` and
`possible_nudging=true`; it is neither an observation nor a conservation
oracle. The scientific endpoint remains full-subnetwork routing with branch
state and distributed q_lateral.

The new DAG-capable Manning operator reproduces the D3 mainstem-only central
series to `3.98e-13 m3/s` maximum absolute difference. Both the reproduced
mainstem and tributary-boundary rollouts pass network-volume conservation.
After prediction sealing, a post-hoc diagnostic on the already public D3
window reduces RMSE from `162.753` to `70.545 m3/s` and bias from `-84.869` to
`-21.013 m3/s`, but still fails to beat persistence at `15.058 m3/s`.

This D4 score has no activation gate and cannot be used for parameter tuning
or model selection. It supports the structural diagnosis that missing
tributaries explain much, but not all, of the D3 error. Predictive validation,
full-subnetwork readiness, and general Geospatial Kernel validation remain
false.

D5 subsequently reached the full-subnetwork endpoint without using D3 outcome
values for topology or configuration. Official NWM v3 RouteLink reverse
traversal compiles 435 Center Hill reaches: 26 mainstem and 409 branch reaches.
All 19 D4 mouths become internal reaches, with branch state and distributed
`q_lateral`; no modeled tributary streamflow boundary remains. On public D3,
the sealed post-hoc D5 RMSE is `73.251 m3/s`, slightly worse than D4 at
`70.545 m3/s` and far worse than persistence at `15.058 m3/s`. This result is
diagnostic only and did not select the later blind configuration.

The independent second system, J. Percy Priest, compiles 43 reaches: 5 active
mainstem and 38 branch reaches. Control COMID `18401827` is excluded, action
enters reach `18401881`, and terminal reach `18401497` is linearly cut at USGS
`03430200`. Its full network, RouteLink subset, and NWM crosswalk hashes are
recorded in `j_percy_priest_v1_full_subnetwork_report.json`.

The two-system protocol freezes the NWM chunk-563 window from
`2022-03-31T01:00Z` to `2022-04-28T01:00Z`. A metadata-only erratum corrects
the pre-existing Center Hill CWMS token from a hyphen to the catalogued
underscore; the original hash and evidence are retained. The amended protocol
SHA-256 is
`7b99c0a7765f2e491e12e9dd110cdfcdcdeed72e70f3f30c65b9b9aac3d167cb`.

Both outcome-free predictions passed actual, branch-silent, and zero-input
conservation before a joint seal was written:

- joint seal: `98fc3257ffe53c24245db80c36d1a376b9d332ceb0e82300c2ea5a1dbb94526c`;
- Center Hill prediction:
  `ade3586c0b62d65d459b8acce554ee13eed1d1ba0bbec1bf2e52b792431554ef`;
- J. Percy Priest prediction:
  `5d6ae07d156af4bcae20b999d0555753160365871b19be3fc9b77ef30dba1819`.

Only after the joint seal were both USGS outcomes acquired. Common complete
cases leave 670 Center Hill and 668 J. Percy Priest hours. The blind score is:

| System | Kernel RMSE | Persistence RMSE | Branch-silent RMSE | Kernel NSE | Bias |
|---|---:|---:|---:|---:|---:|
| Center Hill | 82.675 | 16.206 | 93.913 | 0.0419 | -25.116 |
| J. Percy Priest | 26.543 | 20.903 | 27.435 | 0.8142 | -4.267 |

Both complete networks improve on branch-silent and both fail the registered
persistence gate. The uncalibrated open-loop Manning instance is therefore
rejected as a predictive default; topology, evidence, forcing support, and
conservation contracts remain retained kernel components. Strict confirmation
is also false because native USGS cadence aggregation was clarified post-seal:
30-minute samples at Center Hill and 15-minute samples at J. Percy Priest were
reduced with the same complete-sample hourly mean rule. No predictions,
metrics, baselines, or gates changed.

The scored window is now public development evidence and cannot validate a
revision. The next candidate must add a separately typed, causally available
forecast closure for rolling state update and state-dependent wave/storage
dynamics, train it only on declared development windows, and freeze an
untouched multi-system window with native sampling aggregation fully specified.

The typed forecast-closure boundary is now implemented separately from the
sealed D5 runner. It accepts only issue-time-available observations, records
analysis increments outside transition flux, and applies a bounded
state-dependent log-roughness residual. The residual changes the constitutive
storage-discharge law but cannot create an external source or sink; the
unchanged branching solver still routes every transferred volume over the
authoritative DAG. Synthetic contract tests pass.

The first public-development training run is also complete. It uses only the
pre-D3 Center Hill window from `2021-12-09T01Z` to `2022-01-06T01Z`, NWM time
chunk `559`, all 435 reaches, and 672 hours of no-fill initial-state and
`q_lateral` inputs. Neither the D3 outcomes nor the later two-system blind
outcomes were used. The input report SHA-256 is
`8b6b42ba3cd07403d2c1a7b96d8a521717200758e1d369734aa0f6e21b9cb67c`.

To avoid reach-wise overfitting, the fitted closure has only two shared free
parameters: log-roughness intercept `0.0253762411` and normalized-storage slope
`-0.1099906632`, with multiplier bounds `[0.5, 2.0]`. The first 168 complete
target hours are used for fitting, and activation starts one hour after the
training cutoff. Observation gain is fixed at `1.0`; the assumed publication
lag is one hour, maximum age is two hours, and missing observations are not
imputed. Operational vintage availability is not verified.

The subsequent development diagnostic gives:

| Scenario | RMSE (m3/s) |
|---|---:|
| update + residual | 46.588 |
| state update only | 47.179 |
| residual, no update | 81.959 |
| identity, no update | 82.827 |
| latency-matched persistence | 33.803 |
| one-hour persistence | 17.415 |

The residual improves on state-update-only by `0.591 m3/s`, but the complete
candidate fails both persistence comparisons. All four Kernel scenarios pass
the full forecast-cycle mass ledger, with maximum residual-to-tolerance ratio
below `5.0e-4`. The development gate is therefore closed: the architecture and
conservation contract are retained, while predictive validation remains false.

Frozen public-development artifacts are:

- parameters SHA-256:
  `a0bebf3c2625d1ffab60528b9d4b8c78a4eacfaad1600fa2a2e6f35f88236d5d`;
- predictions SHA-256:
  `4b1a88c0a9437deff5788adb6f4d3266b8a8f8b7bff98c20b56ad6bb96bcfff3`;
- development report SHA-256:
  `44d3bf50b7d9e11169bf18d7b0f113395f76d2b0269f0144c1afa12142dd7228`.

The next development candidate should prioritize graph-constrained,
low-dimensional, multi-gauge state estimation and verified observation
latency/vintage evidence. It should not add one outcome-fitted parameter per
reach or consume a new untouched blind window before beating the declared
development baselines.

The public multi-gauge follow-up is now complete. NLDI returned 160 catalog
sites within a 1000 km upstream-tributary query; intersection with the frozen
435-reach domain retained 28 sites on 26 reaches. Only Smith Fork USGS
`03424730` and the existing outlet USGS `03424860` return eligible `00060`
series for the pre-D3 window, with 639 and 668 complete hours respectively.
Both have 30-minute native cadence and retained `A` qualifiers. Missing hours
are not imputed, and operational archive vintage is not verified.

An optional graph-state update contract now restricts every gauge basis to
strict upstream ancestors on the frozen DAG, bounds gains to `[0,1]`, forbids
overlapping gauge supports, and records every spatial correction as an
explicit analysis increment. The first rank-one basis uses only the first 168
hours of NWM modeled streamflow/velocity states. It has zero outcome-fitted
parameters and remains `candidate` with `possible_nudging=true`.

| Scenario | RMSE (m3/s) |
|---|---:|
| graph multi-gauge | 47.400 |
| local multi-gauge | 47.115 |
| outlet only | 47.162 |
| interior only | 82.631 |
| no update | 82.770 |
| latency-matched persistence | 33.803 |
| one-hour persistence | 17.415 |

The local second gauge gives a small positive effect, but contemporaneous NWM
covariance propagation is worse than both local multi-gauge and outlet-only.
All Kernel scenarios conserve mass. This development gate is closed and no
new blind window was consumed. The next protocol must evaluate preregistered
`1/3/6/12/24h` lead times and separate oracle-forcing diagnostics from an
operational forecast claim before a lagged graph kernel is attempted.

Multi-gauge input, graph-parameter, prediction, and diagnostic-report SHA-256
values are respectively:

- `f96d059434668bd564932d5ae5bf03cb9ecdf0d4826f34013b7fafad3621cc2b`;
- `7128a100867af237b00f3d83bca67288b4df12f4f15f1386f344e0ddfd40f633`;
- `99e29085f22c9b9ad1fad4747d4a61707a942425b74aa472c35d1b66aa5fe8a4`;
- `fdd1b0996eb2ead2b03be75606f320d054b6983e5337c434e53b2a5e5e850492`.

The lead-time follow-up was preregistered before execution with horizons
`1/3/6/12/24h`; 1h is diagnostic and `3/6/12/24h` are non-compensatory core
horizons. Every issue-time analysis is branched into one continuous 24-hour
rollout with no later observation assimilation. Realized future release and
retrospective `q_lateral` make this an oracle-forcing archive replay, not an
operational forecast. Operational metrics remain null because historical
forcing-forecast, release-plan, and observation-publication vintages are absent.

| Horizon | Graph RMSE | Local RMSE | Outlet RMSE | Causal persistence RMSE |
|---:|---:|---:|---:|---:|
| 1h | 48.490 | 48.076 | 48.106 | 34.609 |
| 3h | 81.866 | 81.385 | 81.488 | 62.730 |
| 6h | 84.232 | 83.901 | 84.017 | 90.702 |
| 12h | 85.081 | 83.334 | 83.385 | 114.442 |
| 24h | 82.041 | 82.307 | 82.320 | 86.588 |

Only 24h passes the registered graph-vs-local/outlet/causal-persistence gate;
the overall development gate therefore fails. All forecast cycles conserve
mass, no post-issue observations are assimilated, and all 1h Kernel predictions
match the parent run exactly.

Lead-time protocol, prediction, and report SHA-256 values are respectively:

- `201beae6cf04fbab6ad2966e73d677d39ff4bde81a1f5252f031a1d04c3752c3`;
- `7c208b1479aa035c58c701252f7f1fd3a122c6dc73cbf31e0b4e6599dc38dbb2`;
- `f6c6c7a8c0b27469e1f098cd16a07b45d188e470a9481ee10a7e3392177319c9`.

The next diagnostic compiles Smith Fork USGS `03424730` as an observed
internal boundary. Public NLDI flowlines confirm COMID `18421273`, downstream
COMID `18421279`, flow direction, and close NLDI/RouteLink length agreement.
The point-to-line distance is `52.071m`, however, so it fails the frozen `30m`
precision gate. The `334.864m` downstream partial length and length-scaled
`q_lateral` support are diagnostic candidates, not admitted spatial facts.

`ObservedInternalBoundaryReplacement` removes direct modeled upstream transfer
when boundary flow is injected. This prevents double-counting and gives the
forecast-cycle identity:

```text
initial + action + supported forcing + observed boundary
= final + outlet + displaced modeled upstream outflow
```

The frozen experiment persists the latest issue-time-available Smith Fork
observation through each branch. No later gauge value is assimilated.

| Horizon | Observed boundary | Modeled cut | Zero boundary | Parent local | Causal persistence |
|---:|---:|---:|---:|---:|---:|
| 1h | 48.453 | 48.104 | 53.932 | 48.076 | 34.609 |
| 3h | 81.807 | 81.484 | 96.453 | 81.385 | 62.730 |
| 6h | 84.149 | 84.013 | 99.894 | 83.901 | 90.702 |
| 12h | 84.715 | 83.381 | 99.874 | 83.334 | 114.442 |
| 24h | 88.717 | 82.317 | 100.165 | 82.307 | 86.588 |

The nonzero boundary beats the zero-boundary ablation at every horizon but is
worse than modeled cut and parent local at every horizon. The held-boundary
development gate therefore fails. All scenarios conserve mass, with maximum
residual-to-tolerance ratio below `4.78e-4`. This retains the replacement
contract while rejecting observation persistence as the boundary dynamics.

Internal-boundary reference, protocol, prediction, and report SHA-256 values
are respectively:

- `c0be689aaab2a2b6b13aab3fc3fe8481a61c7ebb844e198ef2b596b35d60f69b`;
- `9366c726a1af9a8a9c609b34ddd7ff849c8143f3273e62b217984e721e710ab0`;
- `d737452afba873f02bbbaf070cdf72ed7a2af2d908138bf5f63cea6316b766ad`;
- `78549912fe362142a109fd8957dd3cc18a5654987cecbbe75b29edd3056b2528`.

The project next acquired 11 months of pre-window Smith Fork history without
user-supplied data or Center Hill outlet targets. A frozen stationary log-AR(2)
uses 5,719 complete fit hours and passes a separate 2,338-hour boundary-only
holdout against one-hour-lag persistence at every registered horizon.

| Horizon | Boundary AR(2) RMSE | Boundary persistence RMSE |
|---:|---:|---:|
| 1h | 6.409 | 7.941 |
| 3h | 13.385 | 14.427 |
| 6h | 20.563 | 21.518 |
| 12h | 27.341 | 27.728 |
| 24h | 26.535 | 30.340 |

The frozen transition does not pass the downstream combination gate:

| Horizon | Dynamic boundary | Held boundary | Modeled cut | Parent local |
|---:|---:|---:|---:|---:|
| 1h | 48.655 | 48.453 | 48.104 | 48.076 |
| 3h | 82.215 | 81.807 | 81.484 | 81.385 |
| 6h | 84.582 | 84.149 | 84.013 | 83.901 |
| 12h | 85.720 | 84.715 | 83.381 | 83.334 |
| 24h | 87.861 | 88.717 | 82.317 | 82.307 |

It improves held boundary only at 24h and remains worse than modeled cut and
parent local everywhere. A current-window posthoc check still finds that the
boundary AR(2) beats boundary persistence at all five horizons, isolating the
failure to spatial support or downstream dynamic transfer.

An outcome-free unit impulse compiles the transfer shape. The authoritative
Smith Fork-to-outlet path has 12 reaches over `21.720km`; NWM initial velocity
implies `19.250h` travel time. The conservative Manning response peaks at 14h,
has a `22.007h` center of mass within 240h, and recovers `99.9242%` of the
`3,600m3` pulse with `4.21e-8m3` differenced mass residual. This delay shape
explains why boundary dynamics help held-boundary prediction only at 24h.

The next candidate must expose this outcome-free path response as geographic
transfer support for the graph observer. It must also resolve the unadmitted
52m attachment and replace length-scaled partial forcing with catchment-based
support before another downstream predictive gate.

Key artifact SHA-256 values are:

- boundary transition report:
  `599ff46086e1f49cc02cd0f85dcde52391a54c6a60a68d7fd83220a9b70db5db`;
- dynamic downstream protocol:
  `c2eade8b3d0e0d63d2909765a8bc44e46a4fcce88658066842fe32794175c6f4`;
- dynamic downstream report:
  `596c6895d4bc73ca6afe4ee11cef8d10cce9f8616fa42bc1faf883cd93ee9fea`;
- boundary skill-transfer diagnostic:
  `64b9a1da539b2a017d7920e2cd4b9d5ed78e8bc3526754e1d023e996a6e77a6f`;
- outcome-free transfer impulse:
  `e9c4d2016562d1f86b7d9e85323722650c144be911565bb20fd21075966265ff`.

Stage 30 tested, rather than assumed, whether the Stage 29 `5-6h` response
range could be explained by antecedent release state. A two-phase public-data
protocol froze `antecedent mean >= 200m3/s -> 5h`, otherwise `6h`, before
selecting one event from each flow-state and release-direction stratum. New
Stonewall and Smith Fork values were acquired only after the four events and
eight observation requests were hash frozen.

| Stratum | Predicted lag | Best lag | Predicted-lag r | Pass |
|---|---:|---:|---:|---|
| high/increase | 5h | 4h | 0.425413 | no |
| high/decrease | 5h | 6h | 0.932414 | yes |
| low/increase | 6h | 6h | 0.899034 | yes |
| low/decrease | 6h | 6h | 0.854651 | yes |

The all-strata admission gate rejects the single-threshold lag rule. This is a
falsified Kernel hypothesis, not a failure of the Geospatial Kernel mission.
The result directs the next stage toward a release-only event-identifiability
operator rather than posthoc threshold tuning.

Stage 30 also promotes Smith Fork from a site-level evidence statement to
support-aware observed graph values at COMID `18421273`. The four event
windows preserve `84/80/82/84` complete approved hours with no fill. Typed
contracts reject using these node states as tributary-mouth flux, total lateral
inflow, or a conservation oracle. All 27 Stage 30 evidence gates pass.

Stage 31 adds a release-only experimental support operator. It measures
excitation duration and normalized volume alongside release variance,
autocorrelation, and lag-design condition number. The operator rejects Stage
30's one-hour rebound before any downstream value is available and is hash
frozen into the new selection plan.

Four new public events pass the release-support gate across high/low flow and
increase/decrease strata. Their blind Stonewall results are:

| Stratum | Best lag | Best r | Second lag | Peak margin | Detectable |
|---|---:|---:|---:|---:|---|
| high/increase | 6h | 0.941048 | 5h | 0.016312 | yes |
| high/decrease | 6h | 0.936895 | 5h | 0.017948 | yes |
| low/increase | 6h | 0.919997 | 5h | 0.023221 | yes |
| low/decrease | 6h | 0.831027 | 5h | 0.010555 | yes |

The input support gate is validated on all four blind events. Only the third
event exceeds the frozen `0.02` best-versus-second margin, so universal exact
hour remains unadmitted. The positive result is therefore a Kernel experiment
admission rule, not yet a point-valued propagation law or physical travel time.
Smith Fork retains `84/81/84/84` complete graph-state hours without fill. All
29 Stage 31 gates pass.

Stage 32 replaces scalar argmax lag with a frozen `EmpiricalLagSupport` set.
For integer lags `0..12`, a candidate enters the set only when it has at least
60 real pairs, Pearson correlation at least `0.8`, and loss from the best
correlation no greater than `0.02`. Both this operator and the Stage 31 release
support operator were frozen before four new release-only events and eight
later USGS observation requests.

| Event rank | Complete outlet hours | Best lag | Best r | Support set |
|---:|---:|---:|---:|---|
| 1 | 84/84 | 6h | 0.853397 | `{5,6,7}` |
| 2 | 84/84 | 6h | 0.867272 | `{6,7}` |
| 3 | 77/84 | 7h | 0.856126 | `{7}` |
| 4 | 84/84 | 7h | 0.747652 | empty |

The third event uses 65 or 66 real pairs per lag after preserving seven
missing hours; no fill is applied. The fourth event fails the frozen `0.8`
response threshold. Consequently the all-event intersection is empty and
common empirical lag support is rejected. The first three event-local sets are
bound to the Center Hill operational boundary-to-Stonewall graph relation, but
none is admitted as physical travel time, hydraulic edge time, or runtime
delay. Smith Fork preserves `74/84/84/81` complete graph-state hours without
fill. All 32 Stage 32 protocol and refusal gates pass with the explicit status
`blind_common_empirical_lag_support_rejected`.

Stage 33 keeps that negative result and asks a different Kernel question:
whether the empirical union can be reconciled with independently located
physics support on the same source-target path. One outcome-free public NLDI
request resolves 24 directed flowlines from Center Hill tailwater COMID
`18421761` to Stonewall COMID `18421703`. The `25.145km` linear-referenced path
passes source and target snap tolerances, has zero connection gap, matches both
prior physics path suffixes, and differs in effective length by only `28.210m`.
The spatial path is admitted.

The empirical union `{5,6,7}` hours overlaps none of the same-path physics
supports:

| Quantity | Support interval | Minimum gap |
|---|---:|---:|
| gravity-wave time | 1.164-1.243 h | 3.757 h |
| Manning kinematic centroid time | 15.583-16.802 h | 8.583 h |
| NWM advective residence time | 18.330-24.171 h | 11.330 h |

The union is not common support, and numerical overlap would not by itself
validate a physical response time. All 33 Stage 33 gates pass with status
`spatial_path_admitted_temporal_reconciliation_rejected`: spatial access is
admitted while physical-consistency and runtime-transition methods fail closed.
The reconciliation ledger SHA-256 is
`7e69e9dc4eaa027ae23503cf6fb121035030f953260a989df29c9515fcf9b7df`.

Stage 34 moves from interval overlap to process meaning. A single outcome-free
request freezes the official CWMS time-series semantics document at commit
`beb8d507c9da8ec074d444117bda7d7daf69e5ee`. It confirms that `1Hour` duration
is a composite over a one-hour window and that USACE stores composite values at
end of period by default.

The source is therefore an authoritative end-labelled interval average. The
Stonewall target remains a derived mean of two approved instantaneous samples
at `t-30m` and `t`. Both fields admit a `3600s` label-shift grid for empirical
association, but they do not admit a physical actuation instant, a continuous
target-hour mean, or physical observation equivalence.

The Kernel now keeps four process meanings separate:

| Quantity | Carrier | Target functional |
|---|---|---|
| empirical response lag | discharge series | association peak |
| gravity-wave time | hydraulic disturbance | first signal arrival |
| Manning time | discharge perturbation | response centroid |
| advective residence | water mass | material-exit centroid |

All three physics substitutions retain five typed rejection reasons: carrier,
source marker, target functional, physical admission, and numerical overlap.
All 34 Stage 34 gates pass with status
`interval_label_shift_admitted_physical_response_semantics_rejected`. The
semantic ledger SHA-256 is
`45b5a51d4ec0500e9288dd97b1a41a9632c9c95d45c7a959a65ffc4cab8a101c`.

Stage 35 propagates the Stage 34 observation supports as set-valued event-time
uncertainty without acquiring new data or tuning a parameter. With one-hour
end-labelled source and target supports, each label shift `L` becomes the
conservative relative-delay interval `[max(0,L-1),L+1]`.

| Event rank | Empirical lag set | Dilated delay envelope |
|---:|---:|---:|
| 1 | `{5,6,7}` | `[4,8]h` |
| 2 | `{6,7}` | `[5,8]h` |
| 3 | `{7}` | `[6,8]h` |
| 4 | empty | empty |

The fourth event remains empty, so the all-event delay intersection is still
empty. The maximum empirical envelope `[4,8]h` remains separated from the
gravity-wave, Manning-centroid, and NWM-residence supports by `2.756515h`,
`7.582960h`, and `10.329537h`. Numerical overlap is absent, and Stage 34 process
semantic refusals would remain mandatory even if overlap occurred.

All 35 Stage 35 gates pass with status
`event_time_uncertainty_propagated_physical_response_rejected`. The uncertainty
ledger SHA-256 is
`2d66862d4b746885d24fb8e52eff4d80c88a93cd1357e9e774077942a6daf3e2`.

Stage 36 freezes the next experiment before acquiring a new candidate pool.
The source is the public 30-minute instantaneous Center Hill tailwater-elevation
series, typed as an observed hydraulic boundary state rather than a release
action or discharge flux. A user-approved 72-hour development probe returned
145 complete samples; its predeclared `0.329184m` rise passes the frozen
source-support gate without requesting a downstream outcome.

The blind selector requires a complete 24-hour pre-marker and 48-hour
post-marker window, at least `0.25m` primary change, six half-hour excursion
intervals, six normalized excursion intervals, and `0.10m` diagnostic standard
deviation. It excludes every Stage 29-32 event with previously loaded outcomes
and selects four new events at least 180 days apart from tailwater elevation
alone.

The downstream functional is frozen concurrently: the first three-sample
persistent discharge departure above
`max(4*1.4826*MAD,5% of baseline,1m3/s)`, with missing samples breaking the run.
This is a statistical departure, not an admitted causal response, physical
first arrival, or travel time.

The protocol and five-request, `5MB`-bounded CWMS selection plan are frozen at
SHA-256
`b0be7dedec2b7dfd933f2c81ea16a2b6bf853a3acafa499fd9beef84f7551ff7`
and
`bee38f828d4a40fb9322e3cbf9bb14181b7e976b2a6e93c31423493c1f8e66a2`.
The approved source-only acquisition is complete: five logical requests, seven
attempts, `2,535,193` bytes, 87,649 unique half-hour positions, 144 explicit
nulls, and 7,370 eligible candidates. The nonzero quality-code counts are 197,
163, and 103 for codes `-2147480957`, `-2147478653`, and `-2147474557`;
87,190 rows have code `0`. The interruption audit SHA-256 is
`6a0d372a39eb5bfefd77e5e4fe1961d1cb2c6986cf44df3d9394107ac18c18cb`.

The four blind rise events are `2023-10-04T17:30Z` (`+1.383792m`),
`2021-09-01T15:30Z` (`+1.350264m`), `2021-03-03T23:30Z`
(`+1.344168m`), and `2022-09-03T16:30Z` (`+1.301496m`). Their selection
manifest SHA-256 is
`532a94a860b65d46f2361703c6acd6c1dafa2a4ab5860b801aebe339960a7540`.
The four-request, `4MB`-bounded USGS observation plan is frozen at SHA-256
`6402bbe5ef8fabca8090590b97379cc422bfbc557df53829f23cbfd5869e4f6f`.
The approved downstream acquisition completed in four requests, four attempts,
and `292,009` bytes; its manifest SHA-256 is
`88c88416741287984ab5091e3d6e4a6d95384dad14a545832e76c50bf784a269`.

Three windows have complete 97-point half-hour support. The 2023 event contains
48 hourly samples and only 18 real baseline positions, so it fails closed under
the frozen 30-sample minimum. The assessable events have frozen thresholds
`269.528014`, `246.857434`, and `437.290311m3/s`; none detects a persistent
departure. The evidence ledger SHA-256 is
`81d981243976d147c2a6b2fba78bef2f478095c21fde118d24f57eab88250689`.

All 40 focused Stage 36 tests and all 32 outcome gates pass with status
`blind_hydraulic_boundary_departure_support_rejected`. The gate report SHA-256
is `a48cdfbe0d808dd1e409c4676f75caf92665cef3d7a037c89bde611d8f752e58`.
All-event statistical departure, causal response, physical timing, and runtime
admission are rejected.

Stage 37 attributes that negative result without acquiring data or defining a
replacement detector. It first reproduces the exact Stage 36 ledger and gate
report. The 2023 event remains a measurement-support failure with 18 real
baseline samples. The other three are frozen-threshold failures.

For every assessable event, the robust-MAD term dominates the frozen threshold.
The strongest persistent departure-to-threshold ratios are `0.142883`,
`0.722669`, and `0.188826`; even the maximum single-sample ratios remain below
one at `0.151288`, `0.739875`, and `0.191352`. Thus persistence alone causes
none of the failures. All source events are rises while all strongest target
runs are decreases, giving zero direction-concordant assessable events without
admitting an inverse causal relation.

The Stage 37 attribution ledger SHA-256 is
`2bad541ec95387ca57bdf63a916b72c95a50db346befa96de77f56f0d1a7a989`.
All 13 focused tests and all 31 gates pass with status
`stage36_falsification_attributed_no_alternative_admitted`; the gate report
SHA-256 is
`f1326a8b2ae2e766b71556697849fe5ea84daa4b706337be1b2f08c0aa81e71d`.
Only failure attribution is admitted. Any later blind test must identify a
directionally meaningful action or discharge-flux source independently of the
target outcome.

Stage 38 screens the public USACE CWMS LRN TIMESERIES catalog for that source
identity without requesting values. The user-approved boundary contained one
exact Center Hill catalog request, at most three attempts, and at most `1MB`.
It succeeded on the first attempt with `62,337` bytes, 37 entries, and no
pagination token. The raw response SHA-256 is
`845f357258d6c2729363df7eb0ba85735a35dbdfc82e8e455d34a1f1c66a2312`;
the acquisition manifest SHA-256 is
`2c908e632c9f389730f7c5184ed719bdc87bf49f5058ee29832ef19c8d3601ac`.

Four exact hourly manual-revision component-discharge identities are admitted:
orifice, sluice, spillway, and turbine. Their explicit aliases are `Orifice
Flow`, `Sluice Gate Flow`, `Spillway Flow`, and `Turbine Flow`; all report
`cms`, `1Hour`, zero interval offset, and `US/Central`. Catalog earliest times
are 2008-08-04 for orifice, 2004-09-30 for sluice, and 1987-05-20 for spillway
and turbine. All latest catalog times are `2026-07-28T05:00:00Z`. Similarly
named daily forecast series are excluded.

These are source identities only. Catalog extents do not establish continuous
values, quality, or revision support, and component discharge does not identify
a gate command or human decision. Historical values, continuous coverage,
gate commands, human actions, causal interventions, and runtime operators all
remain rejected. A separate bounded plan and fresh approval are required
before any value request.

The Stage 38 catalog ledger SHA-256 is
`1cbd80d6ffde6c142dbf2f364475c6b94713b93d8f6de348d8bfecb40e4af7b4`.
All 18 focused tests and all 34 gates pass with status
`stage38_cwms_component_discharge_catalog_checkpoint_admitted`; the gate report
SHA-256 is
`0eeab2e425200a0698041acdb64ae91bc4233c6c657b55817fc7b303862ea021`.

Stage 39 freezes the separate component-value protocol required by Stage 38.
It binds the authoritative Stage 34 hourly composite semantics: every value is
an interval average over the prior hour and is end-labelled by default. This
does not identify a release actuation instant, gate command, or human action.

The exact source-only plan covers 2021-01-01 through 2026-01-01 for Orifice,
Sluice, Spillway, and Turbine Flow. Five inclusive annual windows per component
produce 20 logical requests. The expected ideal grid has 43,825 unique hourly
positions per component. Shared annual boundary rows must be identical before
deduplication; explicit nulls and quality codes remain unfilled and uninterpreted.

The request boundary permits only the public CWMS host, at most three attempts
and `1MB` per request, `20MB` persisted successful responses, and `60MB` total
response bytes in the retry worst case. Unexpected pagination fails closed.
No workspace, tailwater, tributary, or downstream outcome data is requested.
The planner has no network code path and records that execution still requires
fresh approval.

The Stage 39 protocol and request-plan SHA-256 values are respectively
`b065308dd8b5e44aebd08d3da41dc6a0d822cf4aeb5c5ea5e88500ad95aa557b`
and
`0870a5c636d59b8074efaab199b881e4a384b58d19fd7410ca12e00a329e4f26`.
All 19 focused tests and all 34 gates pass with status
`stage39_component_discharge_value_plan_frozen_values_pending_approval`; the
gate report SHA-256 is
`6b205a953f4f69f27322366fdbdf86cb7241e03529d13e4fa61fcdab5a179802`.
Component values, synchronized total discharge, events, causal response,
physical time, and runtime use all remain unadmitted.

After explicit approval, Stage 40 executes the 20 frozen requests. Every
request succeeds on its first attempt, persists `4,225,697` bytes in total, and
retains exact URL, retrieval, TLS, source-term, and SHA-256 provenance. No
pagination, tailwater, tributary, or downstream request occurs. The acquisition
state and manifest SHA-256 values are respectively
`683837d491b41e02103aeca85851eeb07aee27f17f49947b37a49421f24d36cf`
and
`ed77dacf3743713817177ba6fd7e553c71823693d831af5d38523dbb5fb45a0b`.

Each component returns 43,829 raw rows. Four shared annual boundaries are
identical, leaving 43,825 unique hours per component with zero missing
timestamps, zero nulls, and zero negative values. All 43,825 hours therefore
have synchronized real, nonnegative Orifice, Sluice, Spillway, and Turbine
support. Per-component complete hourly coverage and synchronized structural
support are admitted.

Quality codes `0`, `-2147478653`, and `-2147480957` remain uninterpreted. The
Kernel does not compile a total-discharge series, select an event, request a
downstream outcome, or promote the values to commands, human actions, causal
interventions, physical response time, or runtime operators.

The Stage 40 support ledger SHA-256 is
`d4d8b1b145ddd9f45e6c5d0905d6d5cabbdf99da0414cacaa43f6c0798d70de1`.
All 28 focused acquisition/support tests and all 38 gates pass with status
`stage40_complete_component_discharge_source_support_admitted`; the gate report
SHA-256 is
`6d9c78138d635467814a372b2faafb9eb534fd6c8cc66ebe4063e933f5a72dec`.

Stage 41 performs no new acquisition. It exact-hour joins and sums the four
Stage 40 components for source-only event selection, without persisting the
full 43,825-value derived total. The unchanged Stage 31 excitation gate is
applied to 73-hour windows. Every complete candidate window must avoid 15 prior
outcome markers, four Stage 36 target-exposed markers, and the prior outcome
window after each is expanded by 30 days.

The selector finds 2,547 eligible total-discharge candidates: 51 high-flow
increases, 77 high-flow decreases, 1,262 low-flow increases, and 1,157 low-flow
decreases. It freezes one event from each stratum at least 180 days apart. All
four selected one-hour steps are Turbine-only.

Applying the same gate independently to each component finds 0 Orifice, 0
Sluice, 0 Spillway, and 2,542 Turbine candidates. Stage 41 therefore admits the
four source-only total-discharge excitation events but rejects non-Turbine
component contrast. It freezes an empirical lag-support target functional for
a possible later experiment, while acquiring no downstream or tributary values.

The Stage 41 protocol, candidate ledger, event manifest, and public evidence
ledger SHA-256 values are respectively
`e5da6a7c3a8b9dba355f41e92114cf3ae8bd726c2c6026fdb1d8fd4b5ed88f33`,
`625b1bee79ccf1eb83059a906250497c3460eb247cdfe06d6b3fb3ef8bcab60f`,
`3ffecd85ce74147eb11e1ccc084b4ac5b2774bae81511a416c54735b156d7e6a`,
and
`6c859b4cc52455beea308e2418832c9ce71a679f9ca882d3bcea9facbaf7a1d3`.
All 21 focused tests and all 37 gates pass with status
`stage41_complete_source_only_total_discharge_events_admitted`; the gate report
SHA-256 is
`46d92725139c4d9a93fadad708aea6ba9e4edcce93187cf2bcff945c1cbfe340`.

Stage 42 freezes the target-value protocol and exact request plan before any
new outcome acquisition. Each of the four Stage 41 events maps to Stonewall
`USGS-03424860` downstream discharge and Smith Fork `USGS-03424730` observed
graph-state discharge, producing eight event-local requests. Every window is
84 hours: the original 72-hour source window plus 12 hours needed for the
frozen `0..12h` empirical lag search.

The plan permits only `api.waterdata.usgs.gov`, at most three attempts and
`2MB` per request, `16MB` persisted successful responses, and `48MB` total
response bytes in the retry worst case. Unexpected pagination fails closed.
The planner has no network code path and records that execution authorization
is false and fresh user approval is required.

The Stage 42 protocol and request-plan SHA-256 values are respectively
`f5de9f9fb7b3f33964f2dd72490291362b5c20e9670fd65b539a36039de32fc1`
and
`28519b1c7834527da9b9b8c2bf30e15f15b293e040b264f60cdbf8df88449ef0`.
All 16 focused tests and all 37 plan gates pass with status
`stage42_component_event_target_plan_frozen_values_pending_approval`; the gate
report SHA-256 is
`4c23a499ed26e527808c83b77d863ccce2e8eb70ecca615f044941cf550dce19`.

After explicit approval, the Stage 42 acquirer executed the eight frozen USGS
requests. All succeeded on their first attempt with no retry or pagination and
persisted `1,112,317` bytes. The acquisition state and manifest SHA-256 values
are respectively
`b22afc9697c07d4578427a634eef907a51cca5f8e2ec6c2c59135d8003e39d8f`
and
`55201c79b843a4d961efc2388d4e6bae54a4f505e50a8c429f634be048f20df7`.

Stage 43 performs the allowed assessment offline. It reconstructs each
72-hour source series as the exact synchronized sum of Orifice, Sluice,
Spillway, and Turbine discharge, aggregates the target into 84 open-closed
hourly means, and applies the unchanged frozen empirical-lag operator.

The four events have best lags `5, 5, 6, 6h` and Pearson correlations
`0.8217600767931865`, `0.8790617592474798`, `0.9244168189654225`, and
`0.919474372916006`. Their admitted event-local support sets are respectively
`{5}`, `{5}`, `{6, 7}`, and `{6}`. All four observed responses pass the frozen
detectability gate.

Their cross-event intersection is empty, so common empirical support is
rejected. Smith Fork graph-state support remains unfilled at 68, 80, 78, and
84 complete hours. USGS approval and qualifier fields are retained as source
metadata without scientific approval semantics. Because every source event is
Turbine-only, non-Turbine component contrast remains rejected. Causal response,
physical travel time, hydraulic edge time, tributary-mouth flux, and runtime
operators also remain rejected.

The Stage 43 evidence ledger SHA-256 is
`91c85ba78d1f4bd8e500b800b3496f395b378244549c7e0b1a68fa107e85e94a`.
All 10 focused tests and all 43 gates pass with status
`stage43_component_event_local_lag_support_admitted_common_support_rejected`;
the gate report SHA-256 is
`c18c11f2d637e272304b1b60a9ab39e8e135a27cc6fb4e89a86a531a4471c46c`.

Stage 44 performs no acquisition. It first audits every known prior Stonewall
`USGS-03424860 / 00060` target-value exposure from 15 hash-frozen acquisition
manifests, outcome reports, and sealed protocols. The compiler extracts 34
real request intervals and merges them into 27 unique intervals. This closes a
Stage 41 inventory gap: broad development and holdout outcome windows had not
been included, so a provisional `2021-12-30T15:00:00Z` candidate was not blind.

After expanding all 27 intervals by 30 days, the unchanged source-only selector
finds 1,343 candidates: 3 high increases, 11 high decreases, 700 low increases,
and 629 low decreases. It freezes four Turbine-only events at
`2023-01-29T01Z`, `2025-01-22T20Z`, `2021-04-28T17Z`, and
`2023-07-29T04Z`, with at least 180 days between every pair.

The prospective replication rule is strict: both high-flow directions must
support `5h`, both low-flow directions must support `6h`, and every event must
pass the unchanged Stage 43 detectability operator. Partial flow-class or
direction success fails. Event reselection and target-operator retuning after
values are forbidden.

Stage 44 creates no target request plan and makes no network request. A later
bounded plan and fresh user approval are required before acquisition. Even a
future pass would admit only Center Hill component-total flow-class cohort
replication; Stage 30 historical falsification, universal lag, non-Turbine
contrast, causal or physical time, and runtime promotion remain rejected.

The exposure inventory, protocol, candidate ledger, event manifest, and gate
report SHA-256 values are respectively
`ccb102452ec522c8303d52d71fc01969504f668e5c17f17011eac3041517aa9d`,
`ee84167cf3b58b6ce1721795286f6539448f9fec5d781cd2212abfc67e47006d`,
`8ee23589977a0bf0520da90a4fb062b72f7448ba05fca4cda2ad84da2564f12b`,
`b98851b30c5c3556eb52daff493546d7832e072beee256d9a6dd82e5c99abe9f`,
and
`1481f7426bd0102a2f1661a6de9c903c99d20ef1607d122989ec2f76f7107a49`.
All 44 gates pass with status
`stage44_component_lag_replication_cohort_frozen_source_only`.

Stage 45 freezes the exact target protocol, four-request plan, and fail-closed
executor for the Stage 44 replication cohort. Each event maps only to Stonewall
`USGS-03424860 / 00060` downstream continuous discharge. Smith Fork graph
state, CWMS source values, tailwater elevation, private data, and workspace data
are excluded.

The four request windows are `2023-01-28T01Z / 2023-01-31T13Z`,
`2025-01-21T20Z / 2025-01-25T08Z`,
`2021-04-27T17Z / 2021-05-01T05Z`, and
`2023-07-28T04Z / 2023-07-31T16Z`. Each has 84 elapsed hours and at most 169
inclusive half-hour positions.

The plan permits exactly four HTTPS GET requests to the allowlisted USGS OGC
continuous-items endpoint, three attempts per request, 2 MB per response,
8 MB persisted success bytes, and 24 MB across the retry worst case.
Unexpected pagination or target identity, statistic, unit, grid, duplicate,
non-finite, redirect, and size behavior fails closed. The executor requires an
explicit `--execute-frozen-plan` flag in addition to separate user approval.

Stage 45 makes no network request. Execution authorization and target values
remain false, so the strict `high -> 5h / low -> 6h` replication test has not
run. All Stage 44 scientific boundaries remain unchanged.

The Stage 45 protocol and request-plan SHA-256 values are respectively
`6c24d7b507bd4046dcd9e5ff329a090c57ab4e2a760609364f1b5e7a4bca790b`
and
`4b100d5bd2286e5df149a5fb2724162fc0eb9d5da8632a1a26e8dc57f89cf08b`.
All 45 gates pass with status
`stage45_component_lag_replication_target_plan_frozen_values_pending_approval`;
the gate report SHA-256 is
`6324d80b982f7364f98af972ac451418fb66ec3a82ac2de5a89e9990735ae4a3`.

Stage 46 performs no acquisition. It freezes the confirmatory Kernel operator
and complete assessment protocol before any Stage 45 target value exists. The
operator requires exactly four events in the frozen high-increase,
high-decrease, low-increase, low-decrease order. Both high-flow directions must
have detectable responses with support sets containing `5h`; both low-flow
directions must have detectable responses with support sets containing `6h`.
Support membership is required, not exact best-lag equality, and any one event
failure rejects the whole cohort.

Every future source series is fixed to 72 exact-hour sums of Orifice, Sluice,
Spillway, and Turbine Flow. Missing source components fail without filling.
Every future Stonewall target series uses its frozen 84-hour Stage 45 window
and open-closed hourly means of observed half-hour values; missing target
samples or hours remain unfilled.

The assessment cannot run until a future acquisition manifest proves exactly
four artifacts from the frozen Stage 45 plan and matching raw hashes. Those raw
files, acquisition state, and manifest remain absent, so target acquisition and
replication execution are false. Stage 45 still requires separate approval and
the explicit `--execute-frozen-plan` flag.

Even a future pass admits only Center Hill component-total flow-class cohort
replication. Universal lag, Stage 30 override, non-Turbine component contrast,
causal or physical interpretation, and runtime promotion remain rejected.

The Stage 46 assessment operator and protocol SHA-256 values are respectively
`8370ad5889ec0e39aff8a13492d63fcf50709a1d89a74d18c7674bc38f4104c3`
and
`a5c976927bde7084047e29f6b20ac75806ca41457562f91f2c049bdeca793803`.
All 46 gates pass with status
`stage46_component_lag_replication_assessment_protocol_frozen_targets_pending`;
the gate report SHA-256 is
`d4297f065b1b15136db4befe65300fc3705ee292e7d4a964b53d45a83a43de22`.

Stage 47 performs no acquisition and does not execute the real assessment. It
freezes the evidence compiler and offline runner that will connect a future
Stage 45 acquisition checkpoint to the Stage 46 cohort operator. The compiler
accepts only the fixed Stage 45 directory and validates its protocol, plan,
state, manifest, four raw paths, hashes, sizes, request metadata, attempt and
byte totals, TLS flag, and raw payloads before compiling evidence.

Each source series remains the 72 exact-hour sum of Orifice, Sluice, Spillway,
and Turbine Flow. Each target hour remains the mean of the observed half-hour
and hour-end Stonewall samples. Missing samples are not filled. Lag pairing is
now explicitly gap-aware and timestamp-based: source hour end plus lag must
equal target hour end. A missing target hour removes only its exact pair and
never shifts later observations. Synthetic tests verify 71 correctly aligned
pairs after one missing hour and rejection at 59 pairs.

The runner requires `--execute-frozen-assessment`, writes only the fixed Stage
47 ledger, and contains no network request capability. The Stage 45 acquisition
module is imported only for payload validation; no acquisition function is
called. Stage 45 state, manifest, and raw files and the Stage 47 result ledger
remain absent.

The Stage 47 evidence compiler and execution protocol SHA-256 values are
respectively
`63ca89193e5159827ddf2e7be9774ed31f683ead4c98236ebc44938a964b57c9`
and
`8c0bc867315b43a6439ea616914bcde768d5134355f69853979aa1fdd0d61a9f`.
All 47 gates pass with status
`stage47_component_lag_replication_executor_frozen_targets_pending`; the gate
report SHA-256 is
`713ff753d04add9c236e18f2ef98459d543a4822d0d74b6e60d6e561b515997f`.

Target acquisition and replication execution remain false. Universal lag,
Stage 30 override, non-Turbine contrast, causal or physical interpretation,
and runtime promotion remain rejected.

## Non-stage Kernel MVP pivot

The numbered evidence-protocol sequence stops at Stage 47. The project next
implemented a bounded action-conditioned Kernel MVP rather than opening another
protocol stage. It binds the Center Hill action feature to the outlet over the
26-reach full-subnetwork path, uses the candidate `5/6/7h` response-support
union with fixed uniform weights, consumes the current causal outlet state and
hourly NWM lateral forcing, and returns recursively writeable `1/3/6/12h`
states.

Only four shared coefficients are fitted on the first 168 public development
hours. On the later common complete cases, the candidate, causal-persistence,
graph-Manning, and local-Manning RMSE values are:

| Horizon | Kernel MVP | Causal persistence | Graph Manning | Local Manning |
|---:|---:|---:|---:|---:|
| 1h | 32.898 | 34.609 | 48.490 | 48.076 |
| 3h | 55.201 | 62.601 | 81.717 | 81.238 |
| 6h | 72.238 | 90.660 | 84.355 | 83.829 |
| 12h | 80.593 | 114.672 | 85.478 | 83.569 |

The bounded development gate passes at every horizon. No future outlet value
is passed to the Kernel, no missing state is filled, and no Stage 45 request or
new blind target is consumed. The run does use realized future action and
retrospective NWM forcing, so it is not an operational forecast. The support
and fitted closure remain candidate, the conservative graph operator remains
the mass-routing layer, and general Geospatial Kernel validation remains false.

The detailed implementation and claim boundary are documented in
`docs/research/GEOSPATIAL_KERNEL_MVP.md`; the machine-readable report is
`geospatial_kernel_mvp_development_report.json`.

### Non-stage fixed-parameter temporal transfer

The exact MVP parameter artifact was subsequently loaded without refitting and
replayed on the already-public January temporal holdout and February D3
windows. These are posthoc transfer diagnostics, not fresh blind windows. The
Kernel sees only the one-hour-old outlet state at issue time, realized future
action, and retrospective NWM forcing; no future outlet observation is passed
to the rollout.

The January Kernel-versus-persistence RMSE values are respectively
`15.569/12.036`, `28.229/22.402`, `42.892/34.918`, and `64.257/56.200` at
`1/3/6/12h`. The February D3 values are `29.228/29.221`, `50.071/52.840`,
`67.615/75.977`, and `86.789/104.373`. Thus January loses at every horizon;
D3 wins at `3/6/12h` but misses `1h` by about `0.007 m3/s`.

The non-compensatory transfer gate fails and the four-coefficient closure is
not admitted. Required action and forcing ablations do degrade the longer
horizon predictions, so the result supports an action-conditioned mechanism
without supporting coefficient stability across flow regimes. General Kernel
validation and operational forecast validation remain false. The report is
`geospatial_kernel_mvp_temporal_transfer_report.json`.

### Non-stage state-anchored innovation candidate

The raw-level transfer failure was followed by one bounded architecture
revision. The revised closure preserves the last causal outlet state with a
fixed persistence coefficient of `1.0` and predicts only the next discharge
change from a drift term, the change in the fixed `5/6/7h` lagged release, and
current NWM lateral forcing. It fits three coefficients on the same first 168
development hours. The path, candidate response support, uniform weights, and
archive-oracle information boundary are unchanged.

Development candidate/persistence RMSE is `25.493/34.609`, `40.373/62.601`,
`51.904/90.660`, and `69.513/114.672` at `1/3/6/12h`. January posthoc RMSE is
`9.604/12.036`, `17.784/22.402`, `27.528/34.918`, and `43.609/56.200`.
February D3 posthoc RMSE is `20.370/29.242`, `33.831/52.878`, `48.098/76.033`,
and `70.343/104.252`. Required action and forcing ablations also pass, as do
the development Manning comparisons. No candidate step is clipped.

The candidate diagnostic gate passes, but the admission gate is explicitly
false. The revision was designed after the earlier MVP transfer outcomes were
known, so January and D3 cannot validate it. A fixed state coefficient of
`1.0` removes training-regime level shrinkage but does not provide an
asymptotic-stability guarantee. The candidate remains a predictive closure
above, not a replacement for, the conservative graph operator. The report is
`geospatial_kernel_action_innovation_candidate_report.json`.
