# ADR-073: Admit event-local lag support, reject common support

## Status

Accepted

## Context

ADR-072 admitted `ReleaseExcitationIdentifiability` as an input-only operator.
Four blind Stage 31 events all had detectable downstream response, but only one
resolved an exact hour. The shared 6-hour argmax was insufficient to represent
the broad 5-versus-6-hour correlation peaks.

Stage 32 addresses that representational problem. A Geospatial Kernel needs a
typed relation that preserves temporal uncertainty rather than forcing every
response into one scalar delay. It also needs a rule for deciding whether
event-local support transfers across events.

The propositions are distinct:

1. a release event has enough input excitation for a blind experiment;
2. its downstream response has a nonempty empirical lag-support set;
3. that support can be attached to a located source-target graph relation;
4. all blind events share at least one supported lag;
5. empirical lag is physical or hydraulic travel time; and
6. the relation may drive a deterministic runtime transition.

Stage 32 tests propositions 2 through 4. It does not assume propositions 5 or
6.

## Decision drivers

- Operator code, thresholds, and event rules must be frozen before new outcome
  values are acquired.
- Event selection must use public CWMS release values only.
- Lag uncertainty must be a discrete set, not a scalar argmax with discarded
  alternatives.
- Support must require both an absolute response threshold and a frozen loss
  from the best candidate.
- Missing observations must reduce real pair counts; they must not be filled or
  interpolated.
- A graph relation may be admitted only for an event with detectable response.
- Common support requires the intersection of every blind event's support set
  to be nonempty.
- A failed event must invalidate common support rather than trigger post-outcome
  threshold tuning.
- Empirical lag must remain distinct from physical travel time, hydraulic edge
  time, and runtime delay.
- Smith Fork observations must retain the Stage 30 graph-state contract and
  no-fill semantics.

## Typed operator

`EmpiricalLagSupport` consumes 13 ordered correlation records for integer lags
`0..12`. Each record contains:

- lag in hours;
- real aligned pair count; and
- Pearson correlation or `null` when variance is insufficient.

The frozen response gate requires:

| Measure | Requirement |
|---|---:|
| Best Pearson correlation | at least 0.8 |
| Best lag | interior to 0..12 |
| Best-lag pair count | at least 60 |

When the response passes, a lag enters the discrete support set only when it
has at least 60 real pairs, correlation at least `0.8`, and correlation loss
from the best lag no greater than `0.02`.

The operator returns the entire set. A singleton can answer an event-local
exact-hour query. A multi-hour set refuses that query. An empty set records a
failed response gate. Every form refuses conversion to physical travel time or
runtime delay.

`EmpiricalGraphRelationLagSupport` adds spatial semantics:

- source boundary: `CETT1-CENTER_HILL`;
- source role: `operational_tailwater_zone`;
- target site: `USGS-03424860`;
- target COMID: `18421703`; and
- relation role: `empirical_downstream_response`.

The binding is permitted for support-aware temporal reasoning and relation
diagnostics. It explicitly refuses hydraulic edge travel time and deterministic
runtime transition consumers.

The operator file was frozen with SHA-256
`43d561732f0aba563ea5a1138fd748a5017fdfde9c2b850ac4327e3a1e2ec4fc`.
The Stage 31 release-support operator remained frozen at
`6dd4266e60c569bb19f7b79387d2d6cf9da06ee81c68d886e74cc0d6564226eb`.

## Frozen blind protocol

The selection plan was frozen before release acquisition with SHA-256
`dc43874cb02b865cca760d21dfa7352db7e85e73329c414f65af5168bf491282`.
It fixed:

- both operator artifacts and all thresholds;
- a minimum adjacent step of `50 m3/s`;
- a minimum 72-hour release range of `100 m3/s`;
- exclusion of all Stage 28 through Stage 31 event neighborhoods by 90 days;
- four events separated by at least 180 days;
- deterministic release-only ranking; and
- no direction or antecedent-flow quota.

The event manifest was then frozen with SHA-256
`d66df4681831774b55bde7b156b52be3673e129b31b601bcff038fcb3ea6b17d`.
The observation request plan was frozen with SHA-256
`f1e5f2e7d6f0183023f29b960deb8ce0a41c38542e2f9e8dbb0dd5a223026af5`.

The common-support test was predeclared as the intersection of all four event
sets. It cannot discard a failed event or retune the `0.8` and `0.02`
thresholds after observation.

## Public-data acquisition

No private or user-supplied data was used. One public USACE CWMS request
downloaded `1,244,077` bytes and reproduced the five-year release pool. After
frozen exclusions, release thresholds, and input support, 401 candidates
remained.

The selected events were:

| Rank | Step time | Direction | Support | Volume | Condition |
|---:|---|---|---:|---:|---:|
| 1 | 2022-02-02 19:00Z | decrease | 12 h | 24.533 | 16.310 |
| 2 | 2022-09-19 15:00Z | increase | 12 h | 16.346 | 9.086 |
| 3 | 2023-09-11 15:00Z | increase | 12 h | 12.017 | 7.217 |
| 4 | 2021-06-25 16:00Z | increase | 7 h | 7.030 | 3.302 |

Only after both operators, events, and eight observation URLs were frozen did
the protocol download `1,125,222` bytes of public USGS Stonewall and Smith Fork
values. All nine source objects retain SHA-256 identity and TLS hostname
verification.

## Blind results

| Rank | Real outlet hours | Best lag | Best r | Support set | Detectable |
|---:|---:|---:|---:|---|---|
| 1 | 84/84 | 6 h | 0.853397 | `{5,6,7}` | yes |
| 2 | 84/84 | 6 h | 0.867272 | `{6,7}` | yes |
| 3 | 77/84 | 7 h | 0.856126 | `{7}` | yes |
| 4 | 84/84 | 7 h | 0.747652 | empty | no |

The seven missing hours in event 3 remain missing. UTC-aligned correlation
pairs fall from 72 to 65 or 66 depending on lag, but remain above the frozen
minimum of 60. No synthetic value enters the result.

The first three events receive event-local graph relation bindings. The fourth
does not because its best correlation is below `0.8`. Its empty set is evidence
against the current common-support claim, not a value to omit.

The intersection across all four sets is empty. Therefore Stage 32 rejects
common empirical lag support for the current Center Hill-to-Stonewall relation.
It also continues to reject physical travel time, hydraulic edge time, and a
runtime propagation operator.

## Graph observations

Smith Fork observations remain support-aware graph states at station
`USGS-03424730`, COMID `18421273`. The four windows retain `74`, `84`, `84`,
and `81` complete approved hours. Ten missing hours in the first event and
three in the fourth remain absent.

These values do not represent tributary-mouth flux, all lateral inflow, or a
conservation closure term. Stage 32 preserves those typed refusals.

## Considered options

### Option 1: Keep one scalar best lag per event

This hides broad response peaks and makes the result look more certain than the
data support.

### Option 2: Convert every near-best lag range into a continuous interval

This implies support between discrete tested candidates and behaves poorly if
future sets are noncontiguous. The evidence is natively discrete.

### Option 3: Remove the weak fourth event or lower the response threshold

Either action uses the observed outcome to manufacture a positive result and
breaks the frozen blind protocol.

### Option 4: Admit event-local sets and reject common support

This preserves the three positive local results, the one negative result, and
the exact predeclared cross-event test.

## Decision

Adopt Option 4.

Admit `EmpiricalLagSupport` as the typed representation of event-local,
observation-derived temporal support. Admit graph-relation bindings for the
first three detectable events only.

Reject a common empirical lag-support set across the four blind events. Do not
promote any event-local set to physical travel time, hydraulic edge travel
time, or a deterministic runtime transition. Continue to admit Smith Fork only
as an observed graph node state.

Retain `ReleaseExcitationIdentifiability` for experimental eligibility. Stage
32 shows that input eligibility is necessary but not sufficient for a stable
cross-event response relation.

## Consequences

### Positive

- Lag uncertainty is now executable and inspectable as a typed discrete set.
- Missing observations reduce pair support without silent imputation.
- Three valid local relations are retained without erasing the negative event.
- The cross-event claim fails closed under a predeclared blind test.
- Empirical, spatial, hydraulic, and runtime meanings remain separated.

### Negative

- The current data do not support one reusable Center Hill-to-Stonewall lag
  neighborhood across all eligible release events.
- `ReleaseExcitationIdentifiability` alone does not exclude every weak response.
- The relation remains project-specific and observation-derived.
- No deployable propagation operator is admitted by this stage.

### Risks and mitigations

- A consumer may use the three positive bindings and ignore the fourth event.
  Mitigation: common support is computed by the ledger across every frozen
  event and returns an explicit refusal.
- Missing data may be mistaken for a reason to discard event 3. Mitigation:
  expose per-lag real pair counts and retain the event because all relevant
  counts exceed 60.
- A singleton `{7}` may be called physical travel time. Mitigation: exact-hour
  empirical support and physical-time queries are separate typed methods.
- The weak event may encourage posthoc threshold adjustment. Mitigation: freeze
  the negative result and require a new ADR and independent event protocol for
  any revised operator.

## Kernel versus traditional GIS implementation

Traditional GIS or time-series software can implement the component
calculations: temporal joins, lagged correlation, station-to-COMID attachment,
set intersection, and missing-value accounting.

The Geospatial Kernel implementation adds a different contract:

- operands have spatial roles, source-target direction, time support, and
  provenance;
- operators are frozen before target observation;
- missing support changes admissibility rather than being silently repaired;
- outputs are typed by what they mean and by which consumers may use them;
- cross-event transfer is a separate gate from event-local fit; and
- physical and runtime promotions fail closed without additional evidence.

The numerical correlation is not the Kernel's core. The core is the lawful,
geographically bound transition from evidence to an admissible world-model
relation, including the ability to refuse that transition.

## Evidence

All 32 Stage 32 gates pass:

- all 15 Stage 31 artifacts and both current operators retain frozen hashes;
- one CWMS and eight USGS requests are bounded, public, hash verified, and TLS
  verified;
- operators, event selection, and observation URLs preserve the two-phase
  order;
- real missing hours and per-lag pair counts remain unfilled;
- the three detectable support sets and one empty set reproduce exactly;
- only detectable events receive graph relation bindings;
- the empty intersection and common-support refusal are enforced;
- Smith Fork graph states retain spatial identity and gaps; and
- physical time, hydraulic edge time, mouth flux, and runtime promotion fail
  closed.

The gate report status is
`blind_common_empirical_lag_support_rejected`. Gate success certifies protocol
and refusal integrity; it does not reverse the rejected scientific claim.

## Artifacts

- Lag-support operator:
  `data_agent/uwm/geospatial_kernel_v2/empirical_lag_support.py`
- Acquisition:
  `scripts/acquire_geotransport_stage32_lag_support_events.py`
- Evidence compiler:
  `data_agent/uwm/geospatial_kernel_v2/public_lag_support_evidence.py`
- Evidence ledger:
  `data/geotransport_v0_1/stage32_center_hill_lag_support_events/lag_support_evidence_ledger.json`
- Gate report:
  `benchmarks/geotransport_v0_1/stage32_lag_support_gates.json`
- Data directory:
  `data/geotransport_v0_1/stage32_center_hill_lag_support_events/`

## Related decisions

- ADR-072: Admit release excitation support, not a universal exact lag
- ADR-071: Reject the single-threshold lag rule and admit graph state
- ADR-070: Release-selected blind transfer and observed tributary state
- ADR-023: Geospatial Kernel branching network and tributary boundary
