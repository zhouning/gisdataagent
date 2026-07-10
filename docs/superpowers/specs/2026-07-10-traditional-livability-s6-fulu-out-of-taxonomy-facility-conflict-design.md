# Traditional Livability S6 Fulu Out-of-Taxonomy Facility Conflict Design

## Purpose

Implement LIV 2.0 S6 as an evidence-bounded traditional GIS screening product for proposed facilities outside the authoritative 43-class facility taxonomy. The first executable geography is limited to the local planning samples for Heping Village and Banzhu Village, Fulu Town, Bishan District. The product must accept real user inputs rather than replay a fixed traditional-market example.

S6 has two distinct stages:

1. propose a traceable semantic classification candidate for an out-of-taxonomy facility;
2. screen the proposed location against planning-resource parcels and current facility objects within a 150-metre projected planar buffer.

Spatial proximity is not, by itself, a regulatory or business conflict. Without an authoritative compatibility rule, the highest permitted conclusion is `potential_conflict_review_required`.

## Ownership and Boundary

| Item | Decision |
|---|---|
| Requirement owner | Traditional livability, LIV 2.0 S6 |
| Executed geography | Heping Village and Banzhu Village, Fulu Town, Bishan District, Chongqing sample data |
| Inputs | Map-selected point or selected planning parcel, plus facility name, raw type and use description |
| Method | Controlled semantic mapping plus deterministic projected spatial screening |
| Screening distance | 150 m projected planar buffer |
| Evidence channels | Planning-resource parcels and current facility POI/AOI, reported separately |
| Target S6 chain | Confirmed taxonomy mapping may be handed to S1 |
| Explicitly excluded | Automatic approval, prohibition, statutory setback, safety distance, walking service area, UWM prediction, LLM-authoritative classification |

S6 is not a UWM scenario. It assesses the current spatial and semantic relationship deterministically. Future state transitions, policy effects, propagation or multi-step intervention planning remain outside this product.

## Design Choice

The selected design is controlled semantic resolution, dual-channel spatial screening and explicit human confirmation.

Rejected alternatives are:

- buffer-only analysis, because it omits the target 43-class-to-S1 chain and encourages proximity to be misreported as conflict;
- automatic LLM classification and conflict decisions, because model inference is not an authoritative taxonomy or compatibility rule and cannot establish an approval conclusion.

An internal mapping or a future language model may suggest candidates, but only an imported authoritative alias/rule match or an explicit human confirmation can establish a confirmed class for downstream use.

## Authoritative Dictionary Contract

`traditional_livability_facility_dictionary.py` loads and validates a versioned external dictionary. It does not synthesize missing LIV 2.0 classes.

The dictionary payload must include:

- schema and dictionary version;
- issuing organisation and source reference;
- effective date or version date;
- exactly enumerated standard classes supplied by the source;
- standard class ID and label;
- authoritative aliases and controlled keywords where provided;
- optional FP/FPP applicability references without inventing thresholds;
- content digest and import timestamp.

The loader reports `dictionary_unavailable`, `dictionary_schema_invalid` or `dictionary_incomplete` rather than substituting the existing internal taxonomy as authoritative. The implementation must not claim that the dictionary contains 43 complete classes unless the imported payload validates that exact count and provenance.

The existing Phase 1A mapping remains an internal product mapping. Its statuses must stay distinguishable from `authoritative_confirmed`.

## Semantic Resolution

`traditional_livability_s6_semantics.py` resolves `facility_name`, `raw_facility_type` and `use_description` in this order:

1. exact authoritative alias match;
2. authoritative controlled-keyword rule match;
3. internal taxonomy or controlled internal rule candidate;
4. unresolved.

Each candidate contains:

- candidate standard class ID and label when available;
- `match_method`;
- source fields and matched terms;
- dictionary/rule version;
- `authority_level`;
- confidence level as an explanatory label, not a calibrated probability;
- whether human confirmation is required.

Internal candidates are always `suggested`. They cannot become `authoritative_confirmed` merely because their string similarity or model score is high.

Human confirmation records the selected standard class, actor identifier, timestamp, original input, candidate evidence and dictionary version. It confirms the analysis input for the current request; it does not silently mutate the authoritative dictionary or create a global alias.

## Planning Resource Product

`traditional_livability_s6_resources.py` builds a versioned resource snapshot from the two village planning datasets. It reuses the verified per-village planning-area and projected-CRS handling established for S7.

Every planning resource preserves:

- `planning_area_id`;
- source layer and source parcel ID;
- raw land-use code and name;
- geometry in its distance CRS and optional WGS84 display geometry;
- area where valid;
- source-stated current/planned/reserved status;
- controlled resource-domain interpretation and its evidence;
- source manifest reference.

The adapter must not infer `reserved` from a land-use name alone. When the source does not explicitly distinguish current and reserved status, the result is `status_unknown`.

Controlled planning-resource domains may identify candidate public-service, education, healthcare, green/open-space, water, transport, community-service or other relevant land categories only when an explicit code/name rule supports the interpretation. Unknown codes remain unresolved and are reported.

## Current Facility Channel

The facility channel consumes the Phase 1A facility data product. It must preserve:

- source dataset and record ID;
- POI/AOI geometry type and display geometry;
- raw class fields;
- current canonical class and mapping status;
- facility product mapping version;
- inventory sampling/completeness state.

Mapped facilities are screened as current facility evidence. `unmapped` facilities inside the screening range are returned in a separate semantic-unresolved list and are never silently excluded.

When the upstream facility product has `complete_inventory=false`, S6 must state that a no-hit result does not establish the absence of current facilities.

## Spatial Screening

`traditional_livability_s6.py` accepts either:

- `input_mode=point`, with longitude and latitude selected on the map; or
- `input_mode=planning_parcel`, with a parcel ID from the loaded village resource snapshot.

Both modes require:

- `analysis_area_id`;
- `facility_name`;
- `raw_facility_type`;
- `use_description`.

An optional `confirmed_standard_class_id` is accepted only with a valid human-confirmation record or authoritative match evidence.

The engine transforms a point input into the selected village's distance CRS. A parcel input uses the parcel geometry in that same CRS. It then constructs a 150-metre planar buffer around the point or parcel geometry. The distance is a static screening threshold only; it is not a statutory setback, safety buffer, network distance or walking service area.

The engine must never compare objects across planning areas or incompatible distance coordinate systems. Invalid coordinates, parcels outside the selected planning area, missing geometry or unknown parcel IDs fail closed with an exact blocker.

### Planning channel

The planning channel returns intersecting planning-resource parcels. For each hit it reports:

- source parcel identity and raw land-use attributes;
- resource-domain interpretation and status evidence;
- nearest planar distance in metres;
- intersection area in square metres when polygon operations support it;
- source and rule references;
- whether compatibility can be evaluated.

### Current facility channel

The facility channel returns mapped POI/AOI facilities whose geometry or representative point is within the screening range. It reports nearest planar distance, class mapping evidence and source identity. Point and polygon objects remain distinguishable.

### Compatibility evaluation

An optional versioned authoritative compatibility matrix may define proposed-class/resource-class relationships. Every rule must contain a stable rule ID, source, version, relationship and applicability conditions.

Only an applicable authoritative rule permits:

- `confirmed_conflict`; or
- `confirmed_compatible`.

If spatial hits exist but no authoritative relationship rule applies, the result is `potential_conflict_review_required`. No-hit or incomplete-evidence results must retain the limitations of the loaded data.

## Result Contract

The analysis result uses `uwm.traditional_livability.s6_analysis.v1` and contains:

- analysis ID, timestamps and exact executed geography;
- normalized user input and selected input mode;
- semantic candidates, match evidence and optional confirmation record;
- screening provider, distance and distance CRS;
- proposed geometry and 150-metre display buffer;
- separate planning-resource hits and current-facility hits;
- separate unresolved planning/facility objects;
- compatibility rules evaluated and their source IDs;
- data-support and completeness state;
- production blockers and claim boundary;
- optional S1 handoff readiness.

Allowed overall statuses are:

- `no_screening_hit`;
- `potential_conflict_review_required`;
- `confirmed_conflict`;
- `confirmed_compatible`;
- `insufficient_evidence`.

`no_screening_hit` means only that no object was found in the loaded snapshots within the configured screening range. It must not be labelled absolute no-conflict. `confirmed_conflict` and `confirmed_compatible` require cited authoritative rule IDs. Missing dictionaries, compatibility rules or spatial inputs reduce the maximum claim level.

The S1 handoff is available only after a standard class is confirmed. If authoritative FP/FPP standards remain unavailable, S1 continues to return inventory metrics and `not_assessed`; S6 must not fabricate an S1 compliance result.

## Offline Build and Runtime API

`build_traditional_livability_s6_fulu.py` reads the verified local planning sources and the Phase 1A facility product offline, then writes a validated S6 resource snapshot and build manifest. It records planning coverage, per-village CRS, facility-product sampling state, unresolved class counts and all source references.

Runtime GET requests must not read `Downloads`, shapefiles or other source GIS archives and must not build spatial indexes on demand.

### Endpoints

- `GET /api/uwm/traditional-livability/s6/resources`
  - loads the offline resource snapshot;
  - returns available planning areas, selectable parcels, source coverage and blockers;
  - returns HTTP 503 when the snapshot is missing, unreadable or schema-invalid.
- `GET /api/uwm/traditional-livability/s6/dictionary`
  - reports dictionary and compatibility-matrix versions and availability;
  - may return a ready HTTP response with `dictionary_unavailable`, allowing spatial screening while preventing authoritative classification claims.
- `POST /api/uwm/traditional-livability/s6/analyze`
  - validates the request and analyzes only server-loaded snapshots;
  - returns semantic candidates, dual-channel spatial hits and evidence-bounded status;
  - never writes request content into an authoritative dictionary.

The API should follow the existing S1/S7 fail-closed snapshot pattern and expose the routes through both backend and frontend route registries.

## UI and Map Interaction

Add an independent `S6 超范围设施评估` section to the traditional livability tab. The analysis-led two-column layout contains:

- left: planning-area selector, point/parcel mode selector, parcel selector when applicable, facility name, raw type, use description, semantic candidates, human confirmation control and analyze action;
- right: evidence-bounded result, planning-resource hits, current-facility hits, unresolved objects, completeness warnings, rule gaps and production blockers.

Map interaction supports selecting a proposed point and displaying:

- proposed point or selected parcel;
- `150 米空间初筛范围`;
- hit planning-resource parcels;
- hit current facilities;
- semantic-unresolved facilities.

Only objects from the active planning area are loaded for analysis. UI and map copy must not use `禁止建设`, `审批通过`, `法定退界`, `安全距离` or `步行服务区` unless a future authoritative source explicitly supports that claim. Without a compatibility rule, the result label is `潜在冲突、需人工复核`.

## Production Blockers

The product must surface, where applicable:

- authoritative LIV 2.0 43-class dictionary missing or incomplete;
- authoritative alias/keyword provenance missing;
- authoritative facility compatibility matrix missing;
- authoritative FP/FPP thresholds missing for S1 handoff;
- planning current/reserved status not explicitly available;
- facility capacity and operating status missing;
- upstream facility inventory sampled or incomplete;
- local planning data limited to Heping and Banzhu villages;
- point/polygon positional accuracy not established for regulatory-distance use.

## Acceptance Criteria

1. Point and planning-parcel inputs both execute against real two-village resource snapshots and are not fixed examples.
2. All buffers and reported distances are calculated in the selected village's projected distance CRS; cross-village analysis is rejected.
3. Planning-resource hits and current-facility hits remain separate evidence channels.
4. Missing authoritative dictionary prevents an authoritative standard-class conclusion while allowing clearly labelled spatial screening.
5. Missing compatibility rules prevent `confirmed_conflict` and `confirmed_compatible`.
6. `unmapped` facilities and unresolved planning codes inside the screening range are returned explicitly.
7. Sampled facility inventory is shown as incomplete and limits the interpretation of no-hit results.
8. Planning status is `status_unknown` unless directly supported by source data.
9. Missing or invalid resource snapshots return HTTP 503; invalid analysis requests fail closed with exact blockers.
10. S1 handoff requires a confirmed class and preserves S1's existing `not_assessed` behavior when FP/FPP standards are absent.
11. Backend unit tests, route tests, frontend contract tests and the frontend production build pass.
12. Real-data verification reports actual two-village object counts, unresolved counts, dictionary/rule availability and all claim limitations.

