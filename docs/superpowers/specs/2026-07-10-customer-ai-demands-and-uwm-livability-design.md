# Customer AI Demands and UWM Livability Design

Date: 2026-07-10

## 1. Source of Truth

This design is grounded in the complete contents of:

- `/Users/zhouning/Downloads/宜居性专项分析.docx`
- `/Users/zhouning/Downloads/客户侧25个AI应用需求的回复.docx`

The source documents define:

- LIV 2.0 scenarios S1, S2, S4, S6 and S7;
- 25 customer AI demands with data requirements, analysis requirements and expected outputs;
- red-font advanced analysis requirements that must not be treated as complete merely because data query, statistics or map display exists.

The customer demands are the fixed requirement set. The implementation chooses the most appropriate technical route for each demand. It must not implement the same requirement twice merely to demonstrate a contrast between traditional analysis and UWM.

## 2. Design Principles

### 2.1 One Primary Route per Requirement

Each LIV scenario and each of the 25 demands has one primary product route:

- traditional urban livability analysis;
- UWM urban livability analysis;
- planning and land intelligence;
- infrastructure and asset intelligence;
- population and demand analysis;
- economy and investment analysis;
- impact and implementation orchestration.

A primary route may consume outputs from another capability, but a complete second implementation must not be created solely for comparison.

### 2.2 Use UWM Only for World-Model Problems

UWM is required when the demand materially depends on one or more of:

- future-state prediction;
- action-conditioned state transition;
- counterfactual comparison;
- disturbance and recovery dynamics;
- spatial spillover;
- multi-step action planning;
- uncertainty-aware policy evaluation.

Static inventory, current-state diagnosis, buffer analysis, network accessibility, rule evaluation, semantic classification and deterministic location-allocation should use established GIS, statistics, rules or optimization methods unless the requirement explicitly needs dynamic world evolution.

### 2.3 Evidence Before Presentation

No page or API may represent the following as implemented merely because a card, route or static artifact exists:

- policy outcome superiority;
- future intervention benefit;
- causal effect;
- cross-city generalization;
- financial feasibility;
- authoritative regulatory compliance.

Every output must expose its data basis, method, uncertainty, blockers and maximum supported claim.

### 2.4 Current Empirical Scene

The available empirical data foundation is primarily the Chongqing planning sample and existing Chongqing UWM artifacts. LIV 2.0 scenario contracts are general, but current computed outputs must be labelled as Chongqing results. Khalifa City examples in the requirement document must not be presented as executed customer results without the corresponding customer data.

## 3. LIV 2.0 Scenario Ownership

| Scenario | Primary route | Method | Acceptance boundary |
|---|---|---|---|
| S1 District facility assessment | Traditional livability | FP/FPP rules, inventory, service areas, quantity/distribution gap matrix | Must report metric source and unavailable FP/FPP standards |
| S2 Land-use or facility change | UWM livability | versioned state, canonical parcel/facility action, counterfactual transition, evidence gate | Must recompute affected state and cannot rely on a fixed benefit label |
| S4 Project livability assessment | Traditional livability | activity classification, demand alignment, duplicate supply, existing-resource conflict, rule aggregation | Must remain a project alignment assessment unless future impact is explicitly requested |
| S6 Out-of-scope facility assessment | Traditional livability | semantic mapping to 43 classes, 150 m conflict analysis, route to S1 | Must report unresolved category mapping rather than guess |
| S7 Facility siting | Traditional livability | candidate filtering, land-use suitability, network service-area gain, location-allocation ranking | Must not claim long-term policy benefit or UWM superiority |

## 4. Livability Demand Ownership

### 4.1 Traditional Urban Livability Analysis

The existing `城市宜居性分析（传统方法）` product route owns the following demands.

| Demand | Theme | Primary methods |
|---|---|---|
| 8 | Mobility, walkability and accessibility | walking network, travel time, transit coverage, service areas, accessibility gaps |
| 9 | Public space and placemaking | POI/AOI, public-space distribution, accessibility, quality indicators, opportunity mapping |
| 10 | Safety, security and comfort | road safety, crossing, lighting, shade, heat comfort and accessibility diagnostics |
| 12 | Social infrastructure and community facilities | facility inventory, population demand, capacity, service areas, lifecycle and component status |
| 13 | Housing and community composition | housing stock, population structure, density, household composition and static supply-demand gaps |
| 14 | Economic vitality and daily convenience | activity diversity, POI mix, daily services, spatial vitality and convenience gaps |
| 15 | Community voice and sentiment | text classification, sentiment, topic clustering, spatial aggregation and traceable source evidence |
| 16 | Culture, identity and district character | heritage resources, cultural facilities, spatial narrative and place-character evidence |
| 21 | Government institutions and public services | institution inventory, service coverage, population-service ratios and administrative gaps |

This route also owns S1, S4, S6 and S7.

The traditional route may use GIS network optimization and deterministic what-if calculations when these are the direct established solution to the requirement. It must not emit UWM simulator traces, learned policy claims or policy-outcome claims.

### 4.2 UWM Urban Livability Analysis

The existing `城市宜居性分析（UWM）` product route owns the following demands.

| Demand | Theme | Required UWM capability |
|---|---|---|
| 7 | Livability and community needs | current state, 24-month/five-year state forecast, target-state gap, intervention planning |
| 11 | Environmental quality and climate comfort | dynamic heat, air-quality, green-infrastructure and microclimate transitions under actions and scenarios |
| 19 | Resilience and future readiness | disturbance scenarios, propagation, recovery trajectories, robust intervention planning |

This route also owns S2.

UWM consumes reliable current-state outputs from accessibility, population, facility, environment and planning analysis rather than reimplementing those static analyses inside the UWM page.

The required UWM runtime chain is:

```text
Observed and curated data
  -> Versioned Urban State Graph
  -> Canonical Urban Action
  -> Action-conditioned Hybrid Dynamics
  -> Future State / Counterfactual / Stress Rollout
  -> Planner or Policy Evaluator
  -> Uncertainty, Evidence and Claim Boundary
```

## 5. Non-Livability Demand Ownership

### 5.1 Planning and Land Intelligence

Primary demands:

- 1 Area and district identification;
- 2 Master planning;
- 3 Land and parcel status;
- 22 Design parameters and development requirements.

This capability should reuse TWM state, planning-version comparison, parcel analysis, spatial overlay, standards and rule evaluation. It should become a dedicated `城市规划与土地` tab when the integrated backend contract is ready.

Demand 22 must distinguish approved DCR parameters from generated recommendations. DCR+ output requires an explicit rule basis, provenance and human-review boundary. An LLM must not invent regulatory values.

### 5.2 Infrastructure and Asset Intelligence

Primary demands:

- 4 Infrastructure and municipal networks;
- 5 Assets;
- 17 Digital and smart-district readiness;
- 18 Operations and service quality.

This should become a dedicated `基础设施与资产` tab. Initial implementation may use observed roads, buildings and public facilities, but underground networks, ownership, capacity, condition, work orders, SLA and maintenance cost require customer or authoritative data.

### 5.3 Population and Demand Analysis

Primary demand:

- 6 Population and demographic structure.

This should become a `人口与需求` tab backed by administrative population, spatial population proxies, age structures, growth scenarios and facility-demand conversion. Proxy and downscaled population must remain explicitly labelled.

### 5.4 Economy and Investment Analysis

Primary demands:

- 20 DED licences and economic activities;
- 23 Financial and investment analysis.

This should become an `经济与投资` tab. POI, search index and mobility can support proxy activity analysis, but they cannot substitute for authoritative DED licences, BOQ, capital cost, operating cost, revenue, cash flow, ROI or IRR.

Demand 23 should initially provide a validated input contract and deterministic financial calculation engine. It must not generate fabricated financial results when authoritative values are absent.

### 5.5 Impact and Implementation Orchestration

Primary demands:

- 24 Impact assessment and prioritization;
- 25 Recommendations and implementation roadmap.

This should become an `影响与实施决策` tab after the contributing domain capabilities exist. It is an orchestration layer, not another world model:

```text
UWM livability effects
+ planning constraints
+ infrastructure capacity
+ asset condition
+ population and equity
+ economy and finance
+ implementation dependencies
-> prioritization and roadmap
```

Missing domain evidence must be visible and must lower or block the resulting recommendation grade.

## 6. Data Foundation Design

### 6.1 Available Inputs

The current Chongqing planning sample includes:

- DEM and land cover;
- OSM roads;
- Gaode POI;
- Baidu AOI;
- building footprints and floor morphology;
- administrative population;
- planning documents, tables, land-use adjustments and project lists;
- historical and cultural districts;
- mobile signalling;
- search-index data;
- existing UWM environmental, air-quality, mobility and spatial graph artifacts.

### 6.2 Required Curated Pipeline

The implementation must not treat the 447 MB source archive as a production runtime database. It must build:

```text
raw source archive
  -> immutable inventory and checksum
  -> layer/table profiling
  -> CRS and temporal normalization
  -> semantic and facility-class mapping
  -> quality and coverage audit
  -> curated domain products
  -> state input snapshots
  -> provenance manifest
```

Every required data field must be classified as:

- `available_observed`;
- `available_proxy`;
- `derivable`;
- `requires_customer_data`;
- `not_supported`.

### 6.3 Known Data Blockers

The current data does not establish:

- Khalifa City parcels or facility inventories;
- the authoritative LIV 2.0 43-class dictionary and FP/FPP standards;
- customer community-voice records;
- complete municipal utility networks and capacities;
- authoritative asset ownership and maintenance records;
- DED licences;
- MEPS/BDMS approved internal facility compositions;
- approved DCR and cost schedules;
- BOQ, revenue, cash flow, ROI or IRR inputs;
- observed outcomes from implemented urban interventions.

## 7. Geospatial World Model Architecture

### 7.1 Shared Kernel Direction

UWM evolution should align with the shared Geospatial World Model Kernel:

- versioned spatiotemporal state graph;
- canonical action;
- canonical transition;
- transition-origin classification;
- provenance and evidence ledger;
- uncertainty representation;
- claim-level derivation;
- TWM/UWM adapters.

The first kernel integration must not immediately replace existing UWM simulators and planners. Existing implementations become backends behind canonical contracts.

### 7.2 Hybrid Dynamics

UWM must not depend only on a simulator that generates its own training and evaluation transitions. The target dynamics architecture is:

```text
Hybrid Dynamics
├── deterministic geospatial transitions
│   ├── service-area and accessibility recomputation
│   ├── parcel/facility state change
│   └── rule and feasibility effects
├── process and mechanism models
│   ├── heat and microclimate
│   ├── air quality
│   └── spatial spillover
├── learned observed-state dynamics
│   ├── temporal prediction
│   └── learned residual dynamics
└── causal intervention effects
    └── enabled only when identification evidence supports them
```

Every transition must identify whether it is observed, deterministic, mechanism-simulated, synthetic, expert-elicited, learned from observed state history or causally identified.

### 7.3 Claim Boundaries

The system may support claims such as:

- deterministic accessibility change under a specified network and facility action;
- observed-state temporal prediction performance;
- simulator-internal planning improvement under a bounded mechanism model;
- stress-scenario robustness within an explicit scenario definition.

It must not support claims such as:

- observed policy outcome superiority without outcome data;
- causal livability improvement from simulator replay alone;
- production readiness from synthetic or proxy data;
- cross-city generalization from a same-scene holdout.

## 8. Existing Branch Integration

Two relevant lines currently exist:

- `feat/v12-extensible-platform` contains the latest mobility-aware UWM work;
- `feat/uwm-livability-requirement-split` contains the requirement registry, API and frontend readiness work and also has uncommitted changes.

Integration must:

1. preserve the uncommitted worktree changes before any merge or cherry-pick;
2. review and test each requirement-branch commit;
3. change the registry from duplicate traditional/UWM coverage to one `primary_route` per requirement;
4. retain blockers and evidence-level visibility;
5. integrate without reverting mobility-aware UWM changes or unrelated user work.

## 9. Delivery Phases

### Phase 0: Safe Integration and Executable Requirement Matrix

- preserve and review requirement worktree changes;
- integrate the requirement registry, API and frontend readiness capabilities;
- represent all five LIV scenarios and all 25 demands;
- assign one primary route to each requirement;
- expose data support, implementation status, blockers and evidence level;
- ensure UI readiness is not presented as business-function completion.

Acceptance criteria:

- all 30 requirement rows have a unique primary route;
- no requirement is marked implemented solely by a frontend component;
- current branch retains mobility-aware UWM behavior;
- targeted backend and frontend contract tests pass.

### Phase 1: Traditional Livability Completion

- implement S1, S4, S6 and S7;
- implement demand 8 network accessibility;
- implement demand 12 facility inventory, capacity and service gaps;
- implement demand 21 public-service coverage;
- implement supported observed/proxy portions of demands 9, 10, 13, 14 and 16;
- provide an explicit input contract for demand 15 if community text is absent.

Acceptance criteria:

- every result is computed from curated data and traceable rules;
- S7 uses actual candidate filtering and network/location-allocation analysis;
- missing LIV standards or customer fields produce blockers, not invented values;
- no traditional route emits UWM or causal claims.

### Phase 2: UWM Livability Completion

- implement S2 through canonical parcel/facility actions and counterfactual transitions;
- implement demand 7 forecast, target-state gap and intervention planning;
- deepen demand 11 environmental hybrid dynamics;
- implement demand 19 disturbance, recovery and robust planning;
- begin shared kernel contracts and UWM adapters.

Acceptance criteria:

- UWM outputs include state version, action, backend, future state, uncertainty and evidence;
- deterministic, simulated and observed transitions are distinguishable;
- planner evaluation includes static, no-action and action-ablation baselines;
- no policy outcome claim is made without observed outcomes.

### Phase 3: High-Feasibility Non-Livability Capabilities

Priority order:

1. planning and land demands 1, 2 and 3;
2. population demand 6;
3. observed-data portions of infrastructure and asset demands 4 and 5;
4. readiness/data contracts for demands 17, 18, 20, 22 and 23.

Acceptance criteria:

- new tabs correspond to coherent business workflows, not individual cards;
- each route declares authoritative, proxy and missing data;
- advanced red-font analysis remains blocked until its required data and rules exist.

### Phase 4: Impact and Implementation Orchestration

- implement demands 24 and 25 only after domain outputs are available;
- add cross-domain dependency, cost, benefit, risk and evidence aggregation;
- produce prioritization and roadmap outputs with human-review gates.

Acceptance criteria:

- recommendations link to their domain evidence;
- missing finance, planning or infrastructure inputs reduce the result grade;
- implementation order is derived from explicit dependencies and constraints.

## 10. Non-Goals

This design does not authorize:

- implementing every demand through both traditional and UWM routes;
- adding a separate tab for every individual requirement;
- presenting the Khalifa City examples as executed results;
- generating authoritative FP/FPP, DCR, DED, BOQ or financial values;
- using simulator replay as observed intervention validation;
- merging or discarding the dirty requirement worktree without preserving it;
- replacing all existing TWM/UWM runtimes with a new kernel in one step.

## 11. Success Definition

The implementation succeeds when GIS Data Agent provides a coherent product architecture in which:

1. every source requirement has one clear technical owner;
2. traditional GIS and analytical methods solve current-state and deterministic problems directly;
3. UWM is reserved for genuine action-conditioned, future, counterfactual and resilience problems;
4. non-livability demands are implemented through coherent reusable domain capabilities;
5. data and evidence limitations are visible at runtime;
6. world-model claims are backed by explicit state, action, transition, uncertainty and evidence contracts;
7. the product demonstrates real computed capability rather than a readiness dashboard presented as completion.
