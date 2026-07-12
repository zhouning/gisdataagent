# Traditional Cultural Heritage and Place Context Demand 16 Design

**Date:** 2026-07-12  
**Branch:** `feat/traditional-cultural-heritage-demand16`  
**Product:** 文化遗产与场所语境证据（需求16）

## 1. Objective

Implement demand 16 as an evidence-bounded traditional GIS product using the verified Chongqing facility inventory. The product supports cultural-place inventory, evidence stratification, spatial distribution, administrative coverage, ambiguity diagnosis and data-acquisition priorities. It does not claim authoritative heritage designation, cultural value, protection quality, actual use or intervention effects.

## 2. Technical Route

The first release uses traditional GIS because the available evidence is a point-in-time POI inventory. UWM is explicitly not used until calibrated temporal observations exist for cultural-asset state transitions, restoration, closure, reopening, use change, visitor or community activity, protection interventions and resulting outcomes.

The selected approach is a stratified evidence architecture:

1. `confirmed_cultural_place_evidence`: source classifications explicitly support a cultural-place category;
2. `heritage_candidate_leads`: names indicate a possible heritage relationship but the source classification does not support confirmation;
3. `excluded_ambiguous_records`: commercial, residential, transport, generic-address and other records that must not be promoted by keywords;
4. `heritage_evidence_readiness`: administrative coverage, evidence gaps and verification priorities.

The word `confirmed` means confirmed as a cultural-place POI under the source classification, not confirmed as a legally designated cultural heritage asset.

## 3. Real Evidence Foundation

Primary source:

```text
/private/tmp/traditional_livability_phase1a_final2/uwm_traditional_livability_facility_product.json
```

Verified observations:

- schema: `uwm.traditional_livability.facility_product.v1`;
- facility records: 76,292;
- explicitly classified temple records: approximately 81;
- explicitly classified cultural-relic or historic-site records: approximately 71;
- explicitly classified museum records: approximately 27 across source taxonomies;
- explicitly classified exhibition/gallery records: approximately 26;
- explicitly classified church records: approximately 12;
- explicitly classified memorial-hall records: approximately 4;
- many additional keyword matches are ordinary villages, banks, parking, hotels, stores, residences, government offices or generic addresses.

Final counts must be produced by the implemented classifier and independently verified; approximate exploration counts are not product claims.

## 4. Classification Contract

### 4.1 Confirmed Cultural-Place Evidence

Classification requires an explicit allow-listed source category. Canonical categories are:

```text
museum
memorial_hall
cultural_relic_site
religious_place
cultural_center
exhibition_gallery
historic_place_context
```

Examples of acceptable source evidence include explicit museum, memorial hall, cultural relic/historic site, temple, church, cultural center, exhibition hall or gallery categories.

A record must not enter this view solely because its name contains a cultural keyword.

### 4.2 Heritage Candidate Leads

A record may enter `heritage_candidate_leads` when:

- its name contains a narrowly defined heritage indicator such as `遗址`, `故居`, `古镇`, `古街`, `文物`, `纪念碑`, `纪念馆`, `博物馆`, `寺`, `庙`, or `教堂`;
- its source category is not sufficient for confirmed cultural-place classification;
- it is not captured by a mandatory exclusion rule.

Candidate leads have:

```text
candidate_status=requires_authoritative_verification
legal_heritage_status=null
```

They cannot contribute to confirmed-place counts or confirmed administrative coverage.

### 4.3 Mandatory Exclusions

Keyword matching cannot override an explicit incompatible category. Mandatory exclusions include:

- village, road, residential compound and ordinary address names;
- banks, ATMs and financial outlets;
- parking, gates, stations, fuel facilities and transport assets;
- hotels, restaurants, stores, markets and ordinary commercial facilities;
- companies and generic business services;
- schools, hospitals and government offices unless the explicit source category itself is a supported cultural-place category;
- records representing management offices, ticket offices, shops or entrances rather than the cultural place itself;
- null, malformed or coordinate-invalid records for map publication.

Each exclusion records a deterministic `exclusion_reason`.

## 5. Claim Boundaries

Mandatory interpretation flags:

```text
cultural_place_poi_not_legal_heritage_designation=true
religious_place_not_automatic_protected_relic=true
name_keyword_only_candidate_lead=true
poi_presence_not_opening_or_operation=true
place_count_not_cultural_value=true
spatial_distribution_not_protection_quality=true
relative_gap_not_cultural_resource_deprivation=true
candidate_lead_not_authoritative_inventory=true
```

Forbidden claims and fields include:

```text
legal_heritage_level
cultural_value_score
authenticity_score
integrity_score
protection_quality_score
visitor_attractiveness_score
community_identity_score
activation_potential_score
investment_priority_score
policy_effect_score
```

No inferred opening status, visitor count, operating status, accessibility, safety, capacity, service radius or cultural significance is permitted.

## 6. Administrative Aggregation

Administrative attachment uses only the facility product's explicit normalized administrative code. No name, centroid, row-order or proximity join may create administrative membership.

Each administrative row reports separately:

- confirmed cultural-place count and canonical category counts;
- candidate-lead count;
- excluded ambiguous count;
- source-dataset coverage;
- category diversity;
- relative evidence-gap rank;
- evidence-gap reasons;
- authoritative verification priorities.

Missing administrative evidence remains null or an explicit unmatched status. It is not converted to zero unless the source inventory is documented as complete for that administrative scope.

## 7. Evidence-Gap Ranking

`relative_cultural_heritage_evidence_gap_rank` ranks evidence readiness, not cultural value or cultural deprivation.

Deterministic priority order:

1. no confirmed cultural-place evidence;
2. high candidate-to-confirmed imbalance;
3. fewer confirmed canonical categories;
4. lower source-dataset diversity;
5. more unmatched or malformed records;
6. stable administrative-ID tie-break.

Recommended acquisition actions may include authoritative heritage-register linkage, opening/operation verification, geometry capture, legal status verification, protection-state survey and longitudinal activity collection. Recommendations are data-acquisition priorities, not development or investment recommendations.

## 8. Product Contract

Schema:

```text
traditional_livability.cultural_heritage_place_evidence.v1
```

Immutable bundle:

```text
overview.json
places.json
admin_units.json
channel_readiness.json
map.json
```

Place rows include:

```text
place_id
name
canonical_category
evidence_tier
candidate_status
legal_heritage_status
raw_primary_class
raw_secondary_class
raw_tertiary_class
longitude
latitude
admin_unit_id
source_dataset
source_record_id
classification_basis
claim_boundary
```

## 9. Channel Readiness

### Implemented

- cultural-place POI classification;
- cultural-place spatial distribution;
- administrative inventory aggregation;
- ambiguity and exclusion diagnostics;
- relative evidence-readiness ranking.

### Proxy Only

- heritage candidate leads;
- administrative cultural-place coverage based on the available POI inventory.

### Unavailable

- authoritative legal heritage designation and level;
- authenticity, integrity and cultural significance;
- opening hours, operation and public access;
- visitor counts and actual use;
- community identity and participation;
- protection condition and restoration quality;
- cultural economy, employment and revenue;
- activation potential and investment priority;
- intervention response and causal policy effects.

Unavailable channels have `value=null`.

## 10. API and User Interface

Five authenticated read-only endpoints under:

```text
/api/uwm/traditional-livability/cultural-heritage
```

Endpoints expose overview, filtered places, administrative units, individual administrative unit and map payload.

The UI is an independent `文化遗产与场所` tab because demand 16 is not limited to livability scoring. It displays evidence tiers, strict category counts, candidate/exclusion diagnostics, administrative evidence-gap ranking, unavailable channels and separate map layers. It must never label candidate leads as confirmed heritage.

## 11. UWM Upgrade Gate

A later cultural-heritage UWM Kernel requires, at minimum:

- stable asset identity across multiple dates;
- observed cultural-asset condition states;
- restoration, closure, reopening and use-change events;
- visitor, event or community-activity time series;
- explicit interventions with timing and scope;
- sufficient observations to calibrate transition and response uncertainty;
- held-out evaluation of predicted transitions and intervention effects.

Until these conditions are satisfied, the system exposes a closed UWM readiness gate rather than a fabricated simulator.

## 12. Verification and Ledger Target

Independent verification must reject:

- keyword-only promotion to confirmed evidence;
- village, bank, parking, hotel, store or ordinary-address false positives;
- non-null unavailable channel values;
- inferred legal heritage status;
- forbidden value or policy scores;
- administrative joins not supported by explicit codes;
- bundle-ID mismatch;
- fabricated-value counts above zero.

Demand 16 ledger target:

```text
status=implemented_evidence_bounded
max_claim_level=cultural_place_inventory_candidate_leads_and_heritage_evidence_readiness
```
