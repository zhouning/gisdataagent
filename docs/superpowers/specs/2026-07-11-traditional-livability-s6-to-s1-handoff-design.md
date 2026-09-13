# Traditional Livability S6 to S1 Handoff Design

## Purpose

Complete the LIV 2.0 traditional-method workflow from an out-of-taxonomy facility proposal in S6 to an evidence-bounded S1 district facility assessment. The workflow must preserve the original proposal, semantic evidence, human confirmation, authoritative dictionary and metric versions, spatial screening result and administrative context. It must never convert a semantic suggestion or a sampled facility inventory into an unsupported compliance conclusion.

This feature remains a deterministic traditional GIS and rule-analysis workflow. Recomputing a current snapshot after inserting one proposed facility is a static what-if comparison, not a UWM state transition, rollout or policy-effect forecast.

## Scope

The first executable geography continues to use the verified Heping Village and Banzhu Village planning samples in Fulu Town, Bishan District. The implementation must remain reusable for other administrative areas when equivalent authoritative facility, population, FP/FPP standard and geometry products are supplied.

Included:

- create a stable S6-to-S1 handoff contract;
- bind the handoff to the exact S6 request, semantic candidate, confirmation and analysis digest;
- validate whether the confirmed facility class has usable S1 metric definitions;
- extend S1 from count-only diagnostics to explicit FP, FPP and 2×2 synthesis contracts;
- compare a current baseline snapshot with a proposed-facility static snapshot;
- expose backend APIs and a frontend workflow for generating and executing the handoff;
- preserve evidence, completeness, uncertainty and maximum-claim boundaries in every result.

Excluded:

- UWM temporal rollout or neighbourhood adaptation;
- population growth, induced demand or future travel behaviour;
- automatic approval or statutory compatibility decisions;
- invented service radii, capacities, GFA, population or FP/FPP thresholds;
- treating the S6 150-metre screening buffer as an S1 service area;
- silently updating the authoritative facility dictionary from a human confirmation.

## Ownership

| Component | Requirement owner | Method |
|---|---|---|
| S6 semantic resolution | LIV 2.0 S6 | controlled dictionary/rule matching plus explicit human confirmation |
| S6 spatial screening | LIV 2.0 S6 | projected deterministic geometry |
| S6-to-S1 handoff | Traditional livability orchestration | immutable evidence-bound request contract |
| S1 FP evaluation | LIV 2.0 S1 | authoritative deterministic spatial metric |
| S1 FPP evaluation | LIV 2.0 S1 | authoritative deterministic quantity/area/capacity metric |
| FP/FPP synthesis | LIV 2.0 S1 | versioned authoritative 2×2 decision matrix |
| Baseline/proposal comparison | Traditional livability | static snapshot recomputation |

## Existing Foundation

The implementation reuses:

- `traditional_livability_s6_semantics.py` for evidence-labelled semantic candidates and confirmation validation;
- `traditional_livability_s6.py` for dual-channel 150-metre projected screening;
- `traditional_livability_facility_dictionary.py` for fail-closed dictionary and compatibility contracts;
- `traditional_livability_facility_product.py` for normalized facility and population products;
- `traditional_livability_s1.py` for current count-based supply diagnostics;
- the existing traditional livability API and `TraditionalLivabilityS6Panel.tsx`.

The current S1 count-per-10,000 metric is retained as one possible FPP metric. It is not relabelled as full LIV 2.0 compliance unless an authoritative standard explicitly defines it as the applicable FPP measure.

## Handoff Contract

Create a pure contract builder and validator with schema:

`uwm.traditional_livability.s6_s1_handoff.v1`

Required fields:

- `handoff_id` and `created_at`;
- `source_s6_analysis_id`;
- `source_s6_analysis_digest` computed from the canonical analysis payload;
- original facility name, raw type and use description;
- proposal input mode and normalized proposed geometry;
- planning area and administrative identifiers;
- confirmed standard class ID and label;
- confirmation actor, timestamp and reason;
- semantic candidate evidence and match method;
- facility dictionary schema, version and content digest;
- compatibility matrix version when available;
- S6 status, maximum claim level and applied rule IDs;
- source resource bundle ID and completeness flags;
- requested S1 metric profile;
- validation blockers and handoff readiness.

The handoff is immutable. Changing facility text, selected class, location, planning area, confirmation reason, dictionary version or source S6 result requires a new handoff.

The server computes the S6 analysis digest and binds the authenticated actor. Client-supplied actor IDs or digests are ignored.

## Handoff Readiness Rules

`ready_for_s1` is true only when:

1. the S6 request and analysis validate;
2. a standard class is authoritatively resolved or explicitly confirmed for this request;
3. the confirmation is bound to the current proposal and candidate;
4. the target administrative area is known;
5. the facility dictionary version and digest validate;
6. at least one authoritative S1 metric definition applies to the confirmed class;
7. all required source fields for that metric are present.

The following conditions block S1 execution rather than degrade silently:

- unresolved facility class;
- stale or mismatched confirmation;
- missing administrative target;
- missing or invalid authoritative metric profile;
- service-area metric without an authoritative service-area rule;
- quantity, area or capacity metric without the required input field;
- mismatched product, dictionary, standard or matrix versions.

Incomplete facility inventory does not necessarily block calculation, but it lowers the permitted conclusion to a bounded diagnostic and adds an explicit completeness warning.

## S1 Metric Profile Contract

Create a versioned S1 standard profile schema:

`uwm.traditional_livability.s1_metric_profile.v1`

Each authoritative class profile contains:

- standard class ID;
- issuing organisation, source reference, effective date and version;
- applicable dimensions: `FP`, `FPP` or both;
- metric definitions with unit, comparator and threshold;
- required source fields;
- spatial method and service-area parameters when FP applies;
- aggregation geography;
- 2×2 synthesis matrix reference when both dimensions apply;
- content digest.

Supported FPP metric implementations are limited to source-backed definitions such as:

- facility count;
- facilities per population denominator;
- total facility area;
- capacity per population denominator.

Supported FP implementations are limited to source-backed deterministic methods such as:

- population or demand geometry covered by an authoritative Euclidean service radius;
- administrative subunits containing at least the defined facility presence;
- network service areas only when an authoritative network and impedance rule are supplied.

The engine must not infer a service radius from the S6 screening distance or from neighbouring facility distances.

## S1 Kernel

Extend S1 through focused modules rather than turning `traditional_livability_s1.py` into a monolith:

- profile validation and canonical digest;
- FP evaluator;
- FPP evaluator;
- 2×2 synthesis;
- baseline/proposal comparison orchestrator.

Every dimension result contains:

- `status`: `meets`, `does_not_meet` or `unresolved`;
- observed value and unit when computable;
- threshold, comparator and authority reference;
- numerator, denominator and geometry evidence references;
- calculation method;
- completeness and uncertainty labels;
- blockers;
- maximum claim level.

When both FP and FPP apply, the synthesis engine reads a versioned matrix. It does not hard-code customer conclusions without an evidence reference. If the matrix is unavailable, both dimension results remain visible and the combined status is `unresolved`.

## Static Baseline and Proposed Snapshot

The handoff execution produces two independent S1 assessments:

- `baseline`: current facility product unchanged;
- `proposal_snapshot`: the confirmed proposed facility inserted as a clearly labelled proposed record.

The proposal record contains only source-backed attributes. Missing area or capacity remains missing. A proposal can therefore change a count or coverage metric while leaving area or capacity metrics unresolved.

The comparison reports:

- changed dimension values;
- changed compliance statuses;
- positive, negative or unchanged gap values;
- affected administrative and demand units;
- reasons a dimension remained unresolved;
- whether the comparison is valid under the same profile and source bundle.

The maximum permitted claim is `deterministic_static_proposal_comparison`. UI and API wording must not call it a forecast, rollout, simulation of adaptation or predicted policy outcome.

## API Design

Extend the existing traditional livability router with:

- `POST /api/uwm/traditional-livability/s6/handoffs`
  - reruns or validates the referenced S6 analysis server-side;
  - binds the actor and creates the immutable handoff;
  - returns readiness and blockers.

- `GET /api/uwm/traditional-livability/s6/handoffs/{handoff_id}`
  - enforces actor ownership and returns 404 for other users.

- `POST /api/uwm/traditional-livability/s6/handoffs/{handoff_id}/execute-s1`
  - validates product and profile bundle versions;
  - returns baseline, proposal snapshot and comparison.

- `GET /api/uwm/traditional-livability/s1/profiles`
  - returns available authoritative profiles and unavailable/blocker states.

Run storage may initially be process-local, following existing scenario-service ownership patterns, but IDs, digests and actor checks are mandatory.

## Frontend Design

Extend `TraditionalLivabilityS6Panel.tsx` without duplicating S1 as a separate fake workflow.

The panel adds:

1. **Handoff readiness**
   - confirmed class;
   - applicable FP/FPP dimensions;
   - dictionary/profile versions;
   - blockers and completeness warnings.

2. **Create S1 handoff**
   - enabled only after a valid current confirmation;
   - confirmation resets when facility text, location, parcel, planning area or selected class changes.

3. **Execute S1 assessment**
   - displays baseline and proposal values side by side;
   - displays FP, FPP and combined status separately;
   - shows unresolved dimensions rather than hiding them.

4. **Map evidence**
   - proposed facility geometry;
   - current facilities used by the metric;
   - authoritative service geometry or demand units when available;
   - affected administrative units;
   - map layers supplied by the backend engine, not recomputed in React.

## Data and Evidence Boundary

The first product may use the existing Fulu facility and planning snapshots, but the UI must expose whether the inventory is sampled or complete. A sampled inventory can demonstrate the workflow and local evidence hits; it cannot establish that the whole administrative area has no facility gap.

Authoritative FP/FPP profiles are imported products. When no customer-authoritative profile is available, the API may expose example/internal profiles only if they are clearly labelled `internal_method_profile` and their results are limited to `proxy_diagnostic`. They must not produce an authoritative compliance status.

No new population, facility area, capacity or network values are fabricated for acceptance tests. Tests use explicit fixtures; real-product verification reports missing fields as blockers.

## Error Handling

- malformed request: HTTP 422 with field-level blockers;
- stale confirmation or digest mismatch: HTTP 409;
- unknown or cross-user handoff: HTTP 404;
- unavailable metric profile: normal evidence-bounded payload with `ready_for_s1=false` when listing or creating, and HTTP 409 when execution is requested;
- product/version mismatch: HTTP 409;
- internal contract failure: HTTP 500 with a stable error code, without leaking another actor's data.

## Testing

Backend tests cover:

- canonical handoff digest stability;
- server actor binding and cross-user isolation;
- confirmation invalidation after any proposal change;
- authoritative and human-confirmed semantic paths;
- missing profile and missing required-field blockers;
- FP-only, FPP-only and dual-dimension profiles;
- versioned 2×2 synthesis and missing-matrix behaviour;
- baseline/proposal count and coverage changes;
- area/capacity remaining unresolved when proposal attributes are absent;
- sampled-inventory claim limitation;
- S6 150-metre buffer never reused as an S1 radius;
- backend-generated map evidence;
- API registration and frontend contract labels.

Real-product verification uses at least one Heping Village and one Banzhu Village proposal. It records actual available metrics and blockers and must not require both examples to reach a compliance conclusion.

## Acceptance Criteria

The feature is complete when:

1. a current S6 result can generate an immutable, actor-owned S1 handoff;
2. stale confirmation, changed inputs and version mismatches fail closed;
3. S1 evaluates only source-backed FP/FPP dimensions;
4. the 2×2 conclusion is produced only from a validated matrix;
5. baseline and proposed snapshots are compared deterministically;
6. sampled or incomplete data visibly limits the conclusion;
7. the frontend executes the entire workflow without deriving spatial evidence itself;
8. all outputs identify the workflow as traditional static analysis, not UWM;
9. focused backend tests and the frontend production build pass;
10. existing S1, S6, S7 and UWM S2 regressions remain green.
