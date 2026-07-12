# Traditional Daily Convenience and Business Activity Evidence Demand 14 Design

Date: 2026-07-12

## 1. Purpose

This design implements an evidence-bounded subset of customer demand 14, economic vitality and daily convenience, inside `城市宜居性分析（传统方法）`.

The product is named `日常便利与商业活动证据（需求14）`. It provides a strictly classified daily-service inventory, administrative distribution, category diversity, existing accessibility context and relative evidence gaps. Business and company POIs remain a separate activity inventory and must not be converted into employment, revenue, demand or economic-vitality outcomes.

## 2. Source Requirement

Demand 14 requests:

- retail;
- fresh-food supermarkets;
- cafés;
- pharmacies;
- local services;
- markets;
- employment accessibility;
- home-enterprise potential;
- commercial-activity gaps;
- local entrepreneurship opportunities;
- daily convenience, commercial coverage, employment accessibility, local economic activity and basic-service proximity analysis;
- daily-convenience assessment, local economic profile, commercial-coverage map and prioritized economic-activation opportunities.

The current evidence supports inventory, category composition, spatial distribution and selected accessibility proxies. It does not support observed economic performance or entrepreneurship outcomes.

## 3. Technical Ownership

Primary route: `traditional_livability`.

Supported methods:

- deterministic POI classification;
- daily-service inventory;
- business-activity inventory;
- administrative aggregation;
- category presence and diversity;
- exact reuse of existing accessibility evidence where identifiers match;
- relative evidence-gap ranking;
- classification and data-completion review queues;
- explicit evidence and claim gates.

UWM is not used for the first release because there are no calibrated business openings/closures, demand transitions, employment dynamics, intervention responses or counterfactual economic outcomes.

## 4. Existing Evidence Foundation

The first release reuses:

- the verified S1/S6 facility product with 76,292 source-backed records;
- raw primary and secondary POI classifications;
- the demand-8 mobility/accessibility product with 1,017 administrative units;
- verified administrative and source metadata.

Relevant observed primary-class counts include:

- shopping services: 2,324;
- shopping: 718;
- catering services: 639;
- food: 163;
- life services: 1,344;
- financial and insurance services: 838;
- finance: 19;
- healthcare services: 834;
- medical: 645;
- companies and enterprises: 4,977.

These counts are observations from a sampled facility product, not a complete business register.

## 5. Product Views

One bundle exposes two separate views:

```text
daily_convenience
business_activity_evidence
```

They share source trace but do not share outcome interpretations.

### 5.1 Daily Convenience View

Eligible categories:

- convenience store;
- supermarket;
- fresh-food or comprehensive market;
- pharmacy;
- café;
- basic restaurant/fast food where explicitly classified;
- postal service;
- laundry;
- repair service;
- telecommunications service outlet;
- bank branch;
- ATM as a distinct access-point subtype;
- other explicitly approved essential local services.

### 5.2 Business Activity Evidence View

Eligible evidence categories:

- company POI;
- factory or industrial enterprise POI;
- business/industrial park POI;
- logistics enterprise POI;
- selected retail and service establishments.

Mandatory interpretation:

```text
company_poi_not_employment_count=true
poi_presence_not_observed_business_operation=true
business_inventory_not_economic_performance=true
```

## 6. Strict Classification Rules

The product uses exact normalized allow-lists and deny/ambiguity rules.

### 6.1 Daily Convenience Inclusion Examples

- `便民商店/便利店`, `便利店`;
- `超级市场`, `超市`;
- `综合市场`, explicitly identified fresh-food markets;
- `医药保健销售店`, `药店`;
- `咖啡厅`, explicitly identified café;
- `快餐厅`, `小吃快餐店`;
- `邮局`, `洗衣店`, `维修站点`, `电讯营业厅`;
- `银行`;
- `自动提款机` as `atm_access_point`, not a bank branch.

### 6.2 Excluded from Daily Convenience

- home-building and construction-material markets;
- automobile sales and repair unless separately requested;
- KTV, internet cafés and commercial entertainment;
- resorts, hotels and tourism accommodation;
- funeral services;
- bath/massage and ambiguous wellness venues;
- generic shopping-related places;
- generic life-service places;
- `其他`, null or unspecified category labels;
- residential areas misclassified as shops or food;
- enterprise/company POIs.

Excluded records remain auditable but do not enter convenience rankings.

### 6.3 Financial-Service Interpretation

Bank branches and ATMs are separate subtypes.

The product reports:

```text
bank_branch_count
atm_access_point_count
financial_access_point_count
```

`financial_access_point_count` may sum both access-point types, but it must not be labelled as financial institution count.

## 7. Product Contract

Schema: `traditional_livability.daily_convenience_business_evidence.v1`.

The immutable bundle contains:

```text
overview.json
places.json
admin_units.json
channel_readiness.json
map.json
```

Each canonical place includes:

```text
place_id
name
raw_primary_class
raw_secondary_class
raw_tertiary_class
canonical_category
view_membership
longitude
latitude
admin_unit_id
classification_decision
classification_reason
source_dataset
source_record_id
operating_status
opening_hours
employment_count
revenue
transaction_volume
customer_visits
service_capacity
source_trace
limitations
```

Unsupported operation and economic fields remain null.

## 8. Administrative Contract

Each administrative row includes:

```text
admin_unit_id
county
township
daily_convenience_counts
daily_convenience_category_count
business_activity_counts
business_activity_category_count
service_accessibility_context
relative_daily_convenience_evidence_gap_rank
relative_gap_reasons
classification_review_priority
field_collection_priorities
source_trace
limitations
```

Accessibility fields are reused only for exact matching administrative identifiers. Missing matches remain null.

## 9. Channel Readiness

Statuses:

```text
implemented
proxy_only
unavailable
```

### 9.1 Implemented

- source-backed daily-service inventory;
- source-backed business-activity inventory;
- strict semantic classification;
- administrative distribution;
- category diversity;
- classification inclusion/exclusion audit;
- exact-ID accessibility reuse;
- relative evidence-gap ranking;
- source trace and blockers.

### 9.2 Proxy Only

- daily convenience represented by observed service presence and diversity;
- commercial coverage represented by sampled POI distribution;
- basic-service proximity represented by existing demand-8 accessibility proxies;
- business activity represented by observed business-related POIs;
- field-review priority represented by deterministic missing-evidence rules.

Every proxy output carries:

```text
relative_gap_not_authoritative_market_shortage=true
poi_presence_not_observed_business_operation=true
company_poi_not_employment_count=true
economic_performance_claim=false
```

### 9.3 Unavailable

- authoritative business licence and DED records;
- operating/closed status;
- opening hours;
- revenue, sales and transaction volume;
- customer visits and footfall;
- employment positions and worker counts;
- observed employment accessibility;
- service capacity;
- household consumption frequency;
- business vacancy;
- shop survival and churn;
- home-enterprise potential;
- market demand;
- entrepreneurship opportunity and success probability;
- land value and rent;
- investment return;
- causal economic-activation effects;
- future commercial demand.

Unavailable values remain null.

## 10. Relative Daily-Convenience Evidence Gap

The product ranks evidence-supported convenience gaps, not economic deprivation.

Ordering uses:

1. zero essential daily-service categories;
2. absence of convenience store/supermarket/market/pharmacy evidence;
3. lower daily-convenience category diversity;
4. lower eligible daily-service count;
5. missing exact-ID accessibility evidence;
6. stable administrative identifier tie-breaker.

The rank is named:

```text
relative_daily_convenience_evidence_gap
```

Forbidden interpretations:

- authoritative retail shortage;
- household unmet demand;
- low economic vitality;
- high unemployment;
- investment priority;
- business opportunity profitability.

## 11. Business Activity Evidence

Business-related records support only:

- observed POI count;
- observed category composition;
- spatial distribution;
- classification review;
- data-source coverage.

The product must not calculate:

- jobs per company;
- employment density;
- company productivity;
- active-enterprise count;
- entrepreneurship potential;
- economic-vitality score.

## 12. Review and Data-Collection Priorities

The product may generate candidates for:

- verifying ambiguous shop/service classifications;
- verifying operating status and opening hours;
- collecting business licences and enterprise lifecycle;
- collecting employment and workplace data;
- collecting sales, transactions and customer visits;
- surveying household daily-service demand;
- collecting vacancy, rent and churn data;
- completing lower-level administrative crosswalks.

These are evidence-acquisition priorities, not economic-activation interventions.

## 13. Map Contract

Separate layers:

- daily convenience places;
- business activity evidence;
- administrative relative convenience evidence gap;
- classification/data-review candidates.

The frontend must not display a red/amber/green economic-vitality map.

## 14. Evidence and Claim Gates

The builder and independent verifier reject:

- deny-listed or ambiguous records entering daily-convenience rankings;
- ATM labelled as bank branch or institution;
- company POI interpreted as employment;
- POI presence interpreted as active operation;
- missing values converted to zero;
- numeric values in unavailable economic fields;
- accessibility joined without exact identifier match;
- economic-vitality, demand, profitability or entrepreneurship scores;
- authoritative shortage or economic-activation wording;
- bundle identifier mismatch;
- implementation status above `implemented_evidence_bounded`.

Claim boundary:

```text
max_claim_level=daily_service_inventory_accessibility_context_and_business_activity_evidence
authoritative_market_shortage_claim=false
observed_business_operation_claim=false
employment_claim=false
economic_performance_claim=false
entrepreneurship_opportunity_claim=false
causal_activation_effect_claim=false
```

## 15. Service and API

Read-only endpoints:

```text
GET /api/uwm/traditional-livability/daily-convenience/overview
GET /api/uwm/traditional-livability/daily-convenience/places
GET /api/uwm/traditional-livability/daily-convenience/admin-units
GET /api/uwm/traditional-livability/daily-convenience/admin-units/{admin_unit_id}
GET /api/uwm/traditional-livability/daily-convenience/map
```

The service loads a prebuilt verified bundle and performs no request-time classification or scoring.

## 16. Frontend

Add `日常便利与商业活动证据（需求14）` inside `城市宜居性分析（传统方法）`.

The panel displays:

- daily-convenience inventory and category composition;
- business-activity evidence as a separate section;
- bank/ATM distinction;
- classification exclusions;
- accessibility match coverage;
- relative daily-convenience evidence-gap ranking;
- unavailable economic channels;
- evidence-acquisition priorities;
- separate map layers.

Prominent statements:

```text
POI存在不代表实际营业
企业POI不代表就业岗位
相对缺口不代表权威市场短缺
```

## 17. Ledger Status

After real product construction and independent verification, demand 14 becomes:

```text
implemented_evidence_bounded
```

Maximum supported claim:

```text
daily_service_inventory_accessibility_context_and_business_activity_evidence
```

The ledger retains operating-status, licence, employment, revenue, demand, entrepreneurship and causal-effect blockers.

## 18. Acceptance Criteria

The implementation is accepted only when:

- all five files share one deterministic bundle ID;
- strict allow/deny classification passes independent verification;
- bank and ATM records remain distinct;
- company POIs never become employment counts;
- unavailable operation/economic fields are null;
- accessibility reuse is exact-ID only;
- rankings are deterministic and evidence-bounded;
- independent verification passes against the real Chongqing bundle;
- API and frontend expose claim boundaries;
- focused Python tests and frontend build pass;
- protected Paper58/TWM files remain untouched;
- the ledger references real artifacts and preserves blockers.
