# Traditional Livability S4 Project Alignment Design

## Purpose

Implement LIV 2.0 S4 as a deterministic, evidence-bounded project-use assessment for real planning parcels in Heping Village and Banzhu Village, Fulu Town. A user selects a real parcel and submits one or more proposed uses with GFA. The product evaluates each use against semantic classification, parcel-direct evidence, S1 demand evidence and S6 150-metre spatial evidence.

S4 is a traditional GIS/rule orchestration product. It is not a UWM future-state model, project approval engine, subjective weighted score or LLM-generated alignment opinion.

## Ownership and Boundary

| Item | Decision |
|---|---|
| Requirement owner | Traditional livability, LIV 2.0 S4 |
| Executed geography | Heping and Banzhu village planning samples only |
| Project input | Real planning parcel plus user-entered multi-use GFA schedule |
| Spatial model | Parcel-direct relationship plus 150 m projected screening |
| Demand evidence | S1 authoritative gap when available; otherwise inventory background and `not_assessed` |
| Semantic/compatibility evidence | Versioned authoritative dictionary/rules or request-scoped human confirmation |
| Current maximum claim | Preliminary evidence analysis requiring human review |
| Explicitly excluded | Approval, development permission, statutory setback, facility capacity inferred from GFA, UWM prediction |

## Selected Approach

Use controlled semantic classification, multi-source evidence orchestration and tiered conclusions. Reject fixed subjective scoring and direct LLM evaluation because neither can establish traceable demand, compatibility or resource-encroachment evidence.

## Input Contract

The request contains:

- `analysis_area_id`;
- `planning_parcel_id`;
- `project_name`;
- `project_description`;
- one or more `uses`, each containing `use_name`, `raw_use_type`, `use_description`, `gfa_m2`, optional `confirmed_standard_class_id`, optional `human_confirmation` and a stable use ID generated or validated by the server.

GFA must be a finite positive number. Zero, negative, NaN, infinity, malformed values and duplicate use IDs fail closed. Raw submitted values, normalized values, authenticated actor and canonical request digest are retained for audit.

The system does not include a fixed school/office example as executable data. Project schedules are supplied by the user or future authoritative project-submission sources.

## Semantic Resolution

Reuse `traditional_livability_facility_dictionary.py` and `traditional_livability_s6_semantics.py`. Do not create another facility taxonomy.

Each use is resolved through authoritative exact aliases, controlled rules, internal suggestions or request-scoped human confirmation. Conflicting evidence and unresolved uses require review. The API overwrites client actor identity with the authenticated username.

## Evidence Channels

### Parcel-direct evidence

Assess the target parcel before neighbourhood proximity:

- raw/current/planned land-use code and name;
- controlled resource-domain interpretation and evidence;
- explicitly stated planning status or `status_unknown`;
- project-class versus parcel/resource compatibility rules;
- explicitly represented replacement, removal or coverage of a livability resource.

Presence on public-service land alone is not encroachment. `livability_resource_encroachment_risk` requires an applicable authoritative rule or an explicit replacement/removal action. Otherwise return `potential_encroachment_review_required`.

### 150-metre evidence

Reuse the S6 projected engine and server-validated resource snapshot. Screen:

- same/related current facilities;
- planning resources;
- unresolved current facilities and planning resources;
- applicable compatibility rules.

The threshold is a static projected screening distance, not a statutory setback, safety distance, walking distance or service area.

### S1 demand evidence

`demand_supported` requires an applicable authoritative FP/FPP gap or another versioned authoritative demand rule. Inventory count and facilities per 10,000 residents are background evidence only when S1 remains `not_assessed`.

### Duplicate-supply evidence

Formal `duplicate_supply_risk` requires a confirmed class, nearby same-class supply and an authoritative duplication/capacity/service-area rule. Without capacity and service standards, return `nearby_same_class_supply_detected` and require review.

## Per-Use Status

Allowed current evidence statuses are:

- `provisionally_supported`;
- `nearby_supply_review_required`;
- `potential_encroachment_review_required`;
- `mixed_evidence_review_required`;
- `unresolved_review_required`;
- `insufficient_evidence`.

Evidence priority is authoritative incompatibility/encroachment, authoritative demand gap, authoritative compatibility, parcel-direct relationship, 150 m proximity, internal semantic suggestion and unresolved evidence. Conflicting evidence is retained, not numerically cancelled. Any material conflict prevents a full-alignment claim.

Formal `fully_aligned`, `partially_aligned` and `not_aligned` conclusions are enabled only when all required authoritative taxonomy, demand and compatibility contracts are ready and applicable. Under current data conditions the project-level result is a preliminary alignment analysis requiring human review.

## GFA Contract

GFA is used only for:

- each use's GFA and share of total project GFA;
- GFA totals and shares by evidence status;
- evidence coverage and unresolved shares.

GFA is not facility capacity, demand, compliant scale, floor-area-ratio compliance or an automatic alignment weight. Total and grouped GFA must reconcile exactly within a documented floating-point tolerance.

## Modules

### `traditional_livability_s4_project.py`

- normalize and validate project/use input;
- generate stable project/use identities;
- preserve raw and normalized audit fields;
- calculate canonical digest and GFA totals.

### `traditional_livability_s4.py`

- orchestrate semantic, parcel, S1 and S6 evidence;
- produce per-use assessments without duplicating S6 geometry logic;
- calculate GFA evidence summaries;
- enforce project-level claim boundaries.

Reuse the S1 and S6 server snapshots. All evidence-bearing snapshots require schema and canonical digest validation at runtime.

## API

### `GET /api/uwm/traditional-livability/s4/resources`

Return selectable two-village parcels, minimal read-only dictionary classes, authority readiness, S1/S6 data support, inventory completeness and production blockers. Missing/invalid required resource snapshots return HTTP 503.

### `POST /api/uwm/traditional-livability/s4/analyze`

Validate the project request, bind the authenticated actor, load only server-controlled snapshots, run the S4 engine and return HTTP 400 for input validation errors. Valid analyses with evidence limitations return HTTP 200. The endpoint never reads Downloads/shapefiles or persists user classifications as authority.

## Output Contract

`uwm.traditional_livability.s4_project_assessment.v1` contains:

- normalized and audited project input;
- `project_summary` and maximum claim level;
- `use_assessments` with semantic, parcel, S1 and S6 evidence;
- `gfa_evidence_summary` with reconciling totals/shares;
- parcel-direct and 150 m evidence;
- unresolved objects;
- applied and non-applicable rule IDs;
- production blockers and claim boundary;
- compact hit rows and capped display GeoJSON.

## UI and Map

Add an independent `S4 项目宜居性评估` section to the traditional livability tab.

Left column:

- planning area and real parcel selection;
- project name/description;
- dynamic use rows with name, raw type, description and GFA;
- semantic candidate review and dictionary-gated human confirmation;
- analyze action and validation messages.

Right column:

- preliminary project state;
- GFA evidence composition;
- per-use evidence table;
- parcel-direct, S1 and 150 m evidence;
- unresolved objects, blockers and claim boundary.

Map layers:

- target project parcel;
- 150 m screening area;
- parcel-contained livability resources;
- nearby same/related facilities;
- nearby planning resources;
- unresolved planning and facility objects.

All map geometry must come from the engine. UI copy must not claim approval, prohibition, statutory distance, capacity compliance or formal alignment without the corresponding authoritative evidence.

## Production Blockers

Surface where applicable:

- authoritative 43-class dictionary missing/incomplete;
- authoritative FP/FPP demand thresholds missing;
- authoritative project-use/parcel compatibility matrix missing;
- facility capacity, operating status and service area missing;
- explicit resource-removal/replacement action missing;
- source planning status unknown;
- facility inventory sampled/incomplete;
- project DCR, FAR, ownership, BOQ and finance inputs missing;
- geography limited to two village samples.

## Acceptance Criteria

1. Real Heping/Banzhu parcels and multi-use GFA schedules are supported.
2. Invalid GFA and duplicate use identities fail closed.
3. Every use retains semantic, parcel, S1 and S6 evidence channels.
4. Missing demand standards prevent a formal demand-gap conclusion.
5. Missing compatibility/capacity rules prevent formal duplicate-supply or encroachment conclusions.
6. GFA is used only for composition and reconciles with project total.
7. Conflicting evidence cannot be cancelled through weighting.
8. Human confirmation is authenticated and request-scoped.
9. Runtime snapshots are schema- and digest-validated.
10. API errors, evidence-limited results and snapshot failures use the documented HTTP semantics.
11. Frontend and map use only engine evidence and preserve prohibited-claim wording boundaries.
12. Unit, route, frontend-contract, real-data and production-build verification pass.
