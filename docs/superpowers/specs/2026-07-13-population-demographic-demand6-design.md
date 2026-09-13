# Population and Demographic Readiness Design — Demand 6

## Goal

Implement an evidence-bounded population and demographic readiness product that separates observed spatial population evidence from unavailable demographic structure and uncalibrated UWM future dynamics.

## Existing Evidence

The product may reference the verified Chongqing district population 2021 product, GHSL 2020 population raster/admin alignment, and population downscaling proxy. These sources may support evidence inventory and spatial proxy diagnostics only. They do not establish current authoritative population, gender, nationality, citizenship, household composition, births, deaths, migration or future growth.

## Product Contract

Schema: `uwm.population_demographic_readiness.v1`.

Maximum claim: `observed_population_evidence_catalog_demographic_contract_and_uwm_population_dynamics_readiness`.

Evidence classes:

- district population 2021 source product;
- GHSL population 2020 spatial proxy;
- GHSL administrative alignment;
- fitted population downscaling proxy.

Demographic channels remain unavailable unless authoritative evidence is supplied: current total population, sex/gender, age, nationality, citizen/non-citizen, household composition, household size, births, deaths, in/out migration, floating population, employment/student status and service-demand cohorts.

## Traditional GIS Boundary

Traditional GIS may inventory sources, expose spatial grain and vintage, compare proxy coverage, and define administrative/spatial joins. It must not treat raster/downscaled proxy values as current official population or demographic structure.

## UWM Kernel Boundary

Population state materialization, cohort transition, births/deaths, migration, household transition, planning response, service-demand propagation, growth forecasting, counterfactual rollout and uncertainty calibration remain closed. One cross-sectional district observation and a 2020 spatial proxy cannot calibrate demographic dynamics.

## Outputs

Publish `overview.json`, `evidence_products.json`, `demographic_channels.json`, `data_contracts.json`, `population_gate.json` and `map.json`; expose six authenticated API endpoints and an independent population-readiness tab.

## Claim Boundaries

- population proxy is not authoritative population;
- district total is not demographic structure;
- 2020 raster is not current population;
- downscaling is not census enumeration;
- missing subgroup data is not zero population;
- one cross-section is not a growth trend;
- planning capacity is not observed migration response;
- a dynamics contract is not a calibrated forecast.
