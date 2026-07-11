# Traditional Public Space and Placemaking Demand 9 Design

Date: 2026-07-11

## 1. Purpose

This design implements customer demand 9, public space and placemaking, inside `城市宜居性分析（传统方法）`. The first release is an evidence-bounded public-space inventory, distribution and relative opportunity product. It must not manufacture public-space quality, vitality, attractiveness, comfort or intervention-effect scores from POI labels.

The product diagnoses the current observed inventory and available spatial evidence. It does not model action-conditioned temporal evolution, public-space activation, behavioural response or policy outcomes, so UWM is not the primary route for this release.

## 2. Source Requirement

Demand 9 requests:

- parks and plazas;
- shaded seating;
- waterfront accessibility;
- gathering spaces;
- landscape quality;
- street vitality;
- street furniture;
- visual comfort;
- community spaces;
- analysis of quality, distribution, availability, attractiveness, comfort and accessibility;
- identification of placemaking, activation, shaded gathering and pleasant-place gaps;
- public-space quality assessment, placemaking opportunity map, open-space gap analysis and prioritized interventions.

The current Chongqing evidence supports only a bounded subset. The product therefore retains the complete requirement as a readiness matrix rather than silently treating missing observations as zero.

## 3. Technical Ownership

Primary route: `traditional_livability`.

Supported methods:

- deterministic semantic classification;
- source-backed public-space inventory;
- administrative aggregation;
- category presence and diversity;
- spatial distribution mapping;
- relative evidence-gap ranking;
- manual field-review and data-enrichment candidates;
- explicit evidence and claim gates.

UWM becomes appropriate only after time-indexed use, environment or intervention observations support state transitions, behavioural response, spatial spillovers, counterfactual activation or multi-step planning. Static POI counts must not be relabelled as a world model.

## 4. Existing Evidence Foundation

The first release reuses verified artifacts rather than performing a new uncontrolled scrape:

- the S1/S6 facility product with 76,292 source-backed facility records;
- the demand-12/21 administrative facility evidence foundation;
- demand-8 accessibility artifacts as a separate township-scale source;
- demand-11 environmental state artifacts as a separate environmental source;
- existing administrative geometry where available.

Observed public-space-related facility classes include:

- `green_space.park`: 317 records;
- `culture.facility`: 57 records;
- `sports.facility`: 241 records before strict demand-9 filtering.

These are product observations from a sampled facility foundation, not a complete authoritative municipal inventory.

## 5. Strict Inclusion Contract

The product uses an allow-list, not broad keyword expansion.

### 5.1 Core Open-Space Categories

Eligible examples:

- park;
- urban plaza;
- botanical garden;
- zoo where explicitly classified as a public visitor space;
- park/plaza mixed records;
- named community public-space records where source classification is explicit.

### 5.2 Civic and Cultural Gathering Categories

Eligible examples:

- public library;
- museum;
- science and technology museum;
- explicitly classified public cultural venue.

These are a distinct `civic_cultural_space` category and are not counted as open green space.

### 5.3 Recreation Categories

Only explicitly mapped public or civic sports venues may enter `public_recreation_space`.

The following source records are excluded unless independent evidence changes their classification:

- internet cafés;
- KTV;
- private entertainment venues;
- resorts;
- commercial wellness venues;
- generic leisure-place labels;
- cinemas;
- records whose public accessibility or spatial role cannot be established.

Excluded records remain auditable in classification statistics but do not enter public-space rankings.

## 6. Product Contract

Schema: `traditional_livability.public_space_opportunity.v1`.

The immutable bundle contains:

```text
overview.json
spaces.json
admin_units.json
channel_readiness.json
map.json
```

Each canonical space record includes:

```text
space_id
name
raw_primary_class
raw_secondary_class
raw_tertiary_class
canonical_space_category
longitude
latitude
admin_unit_id
source_dataset
source_record_id
classification_method
public_access_status
opening_hours
quality_score
vitality_score
shade_evidence
seating_evidence
waterfront_access_evidence
source_trace
limitations
```

Unsupported public access, opening hours, quality, vitality, shade, seating and waterfront fields remain null.

## 7. Administrative Contract

Administrative aggregation stays at the evidence-supported county/district level unless a traceable lower-level crosswalk becomes available.

Each administrative row includes:

```text
admin_unit_id
county
core_open_space_count
civic_cultural_space_count
public_recreation_space_count
space_category_count
relative_public_space_evidence_gap_rank
relative_gap_reasons
source_trace
limitations
```

Township accessibility and environmental nodes may be referenced as separate evidence sources but are not joined to county-level public-space rows through name inference or centroid assumptions.

## 8. Channel Readiness

Each source-requirement channel has one status:

```text
implemented
proxy_only
unavailable
```

### 8.1 Implemented

- source-backed public-space inventory;
- strict semantic classification;
- county/district distribution;
- supported category diversity;
- point map layer;
- transparent classification exclusions;
- evidence and source trace;
- relative evidence-gap ranking.

### 8.2 Proxy Only

- open-space availability represented by observed inventory presence;
- placemaking opportunity represented by relative evidence gaps and missing evidence;
- public-space diversity represented by supported category diversity;
- field-review priority represented by deterministic review rules.

Every proxy result carries:

```text
relative_proxy_not_authoritative_standard=true
observed_public_space_use=false
observed_quality=false
policy_outcome_claim=false
```

### 8.3 Unavailable

- authoritative public-access status;
- opening hours and temporal availability;
- landscape quality;
- street vitality and pedestrian counts;
- attractiveness and actual use;
- shade and tree-canopy-at-space observations;
- shaded seating;
- street furniture;
- visual comfort;
- waterfront entrances and actual waterfront accessibility;
- universal accessibility;
- safety and lighting;
- authoritative service areas;
- authoritative per-capita open-space indicators;
- intervention cost, benefit and causal effect;
- future public-space demand.

Unavailable channels remain null and are never assigned zero.

## 9. Relative Opportunity Logic

The product does not create a hidden public-space quality score.

The relative evidence-gap order is:

1. zero core open-space records;
2. zero supported public-space records across all eligible categories;
3. lower supported category diversity;
4. lower core open-space count;
5. lower total eligible-space count;
6. stable administrative identifier tie-breaker.

Reasons are included in every row. The rank is named:

```text
relative_public_space_evidence_gap
```

It is not named public-space shortage, quality deficit, per-capita deficit or investment priority.

## 10. Manual Review Candidates

The product may generate deterministic candidates for:

- inventory completion where no eligible spaces are observed;
- classification review where excluded or ambiguous records are common;
- field verification of public access and opening hours;
- collection of shade, seating, furniture, lighting and accessibility evidence;
- waterfront entrance and path mapping;
- lower-level administrative crosswalk completion.

Candidates are data and planning-review queues, not recommended construction projects.

## 11. Evidence and Claim Gates

The builder and independent verifier reject:

- internet cafés, KTV, resorts or generic commercial entertainment entering eligible public-space categories;
- facilities without source trace;
- duplicate canonical space identifiers;
- assumed public access or opening hours;
- numeric quality, vitality, shade, seating or comfort values without source evidence;
- township/county joins without an explicit crosswalk;
- bundle identifier mismatch;
- authoritative shortage, quality, priority or policy-effect wording;
- implementation status above `implemented_evidence_bounded` while required channels remain unavailable.

Claim boundary:

```text
max_claim_level=observed_inventory_and_relative_public_space_evidence_gap
authoritative_public_space_shortage_claim=false
observed_quality_claim=false
observed_use_or_vitality_claim=false
causal_intervention_effect_claim=false
future_demand_claim=false
```

## 12. Service and API

Read-only endpoints:

```text
GET /api/uwm/traditional-livability/public-space/overview
GET /api/uwm/traditional-livability/public-space/spaces
GET /api/uwm/traditional-livability/public-space/admin-units
GET /api/uwm/traditional-livability/public-space/admin-units/{admin_unit_id}
GET /api/uwm/traditional-livability/public-space/map
```

The service loads a prebuilt verified bundle. It does not classify or recalculate the product during requests.

## 13. Frontend

Add `公共空间与场所营造（需求9）` inside `城市宜居性分析（传统方法）`.

The panel displays:

- eligible public-space inventory count;
- category composition;
- excluded-record statistics;
- district/county relative evidence-gap ranking;
- channel readiness and blockers;
- manual review candidates;
- source-backed point map layer.

Quality, vitality, shade, seating, waterfront accessibility and public-use cards display `数据未就绪`, never zero or inferred scores.

## 14. Ledger Status

After real product construction and independent verification, demand 9 becomes:

```text
implemented_evidence_bounded
```

Maximum supported claim:

```text
public_space_inventory_distribution_and_relative_evidence_gap
```

The ledger retains all quality, vitality, accessibility, public-use and intervention-effect blockers.

## 15. Acceptance Criteria

The implementation is accepted only when:

- all five files share one deterministic bundle ID;
- every included space passes the strict allow-list;
- all excluded commercial recreation classes remain outside eligible rankings;
- every space has source and classification trace;
- unsupported fields are null;
- administrative rankings are deterministic and reasoned;
- no unverified cross-level spatial join occurs;
- the independent verifier passes against the real Chongqing bundle;
- API and frontend expose evidence boundaries;
- focused Python tests and frontend production build pass;
- the ledger references real artifacts and preserves remaining blockers.

