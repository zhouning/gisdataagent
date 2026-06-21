# TWM 与 GeoSOS/FLUS 的学术定位比较

更新日期：2026-06-20

本文给出 GIS Data Agent 中 Territory World Model, TWM 与 GeoSOS/FLUS 的学术论文式比较。相比面向业务用户的解释，本文重点放在研究问题、状态表征、动力学建模、因果校准、证据门控和创新边界上，可用于论文引言、相关工作、技术白皮书或答辩材料。

## Abstract

GeoSOS/FLUS represents a mature family of land-use simulation and spatial optimization methods. It couples cellular automata, artificial neural networks, human-natural driving factors, adaptive inertia, land-use competition and scenario demand allocation to simulate future land-use patterns. In contrast, TWM is positioned as a governance-oriented geospatial world model for territorial planning. It represents the territorial system as hierarchical GIS object-relation-rule-evidence states, predicts action-conditioned future state, constraint risk, planning utility and uncertainty, and upgrades planning claims only through spatial causal calibration and evidence-gated validation.

The essential distinction is therefore not whether both systems can simulate spatial change. The distinction is the decision object: GeoSOS/FLUS models land-use type transitions, whereas TWM models the consequences and validity boundaries of planning, approval, protection and development actions under rules, evidence and audit requirements.

## 1. Research Question

GeoSOS/FLUS addresses the following type of research question:

> Given historical land-use patterns, driving factors, neighborhood effects, demands and scenarios, how will multiple land-use types be allocated or transformed in the future?

TWM addresses a different question:

> Given a hierarchical territorial GIS state and a proposed action, what future state, constraint risk, planning utility and uncertainty may arise, and is there enough evidence to upgrade the result into an operational planning claim?

This shift changes the model object from land-use transition to action-conditioned governance inference.

## 2. Methodological Positioning

GeoSOS is a geographical simulation and optimization system that integrates cellular automata, agent-based models and swarm intelligence models for geographical process simulation and spatial optimization. FLUS is the land-use simulation branch of this family. It uses ANN-derived suitability, CA allocation, adaptive inertia and competition mechanisms to simulate multi-type land-use scenarios.

TWM is not a direct replacement of FLUS. It is a broader world-model architecture for natural-resource governance and territorial planning. FLUS can be treated as a classical land-use transition baseline or as one candidate transition backend, while TWM defines the wider governance loop:

```text
hierarchical GIS state
  -> action-conditioned simulator
  -> rule/constraint risk
  -> causal/evidence calibration
  -> planner consumer
  -> audit and review tasks
```

## 3. State Representation

### GeoSOS/FLUS

GeoSOS/FLUS typically represents the study area through raster cells, land-use categories, driving-factor layers, neighborhood configuration, conversion constraints and scenario demand. Its core spatial state is therefore a land-use allocation state.

### TWM

TWM represents the territorial system as hierarchical object-relation-rule-evidence states:

- `parcel`, `block`, `township`, `county`
- `project`, `approval_record`, `planning_zone`
- `policy_rule`, `rule_hit`, `evidence_item`, `review_task`
- overlap, adjacency, containment, project-parcel, project-rule and evidence-support relations

This representation is designed for land administration, territorial planning supervision, project approval review, protected-area governance and auditability.

## 4. Dynamics

### GeoSOS/FLUS Dynamics

FLUS simulates land-use change through CA-based allocation, suitability estimation, adaptive inertia and inter-class competition. It primarily models how land-use types compete and transition across space under scenario demands and driving factors.

### TWM Dynamics

TWM models action-conditioned territorial dynamics:

```text
p(
  future_state,
  constraint_risk,
  planning_utility_delta,
  uncertainty
  | current_hierarchical_gis_state, action, scenario, evidence
)
```

The action may be a planning, approval, protection, construction, remediation or inspection action. This makes action a first-class causal and operational condition rather than a background scenario parameter.

## 5. Validation Boundary

GeoSOS/FLUS is usually validated as a spatial simulation model using historical land-use maps, spatial agreement, figure-of-merit style metrics and scenario plausibility.

TWM requires a stricter validation boundary because its outputs are closer to operational governance claims. A TWM forecast must carry:

- evidence coverage
- rule support
- action-mask status
- uncertainty
- causal calibration diagnostics
- review status
- claim-upgrade boundary

If the evidence is synthetic, not-for-production, weakly balanced, spatially unsupported or causally underidentified, TWM should return `review` rather than upgrade the result to a production claim.

## 6. Causal Calibration

GeoSOS/FLUS can incorporate human and natural effects through driving factors and scenario assumptions. However, this does not by itself identify the causal effect of a planning or approval intervention.

TWM explicitly separates correlation-based prediction from action-effect calibration. Its causal layer may use:

- treated/control approval or supervision records
- spatial fixed effects
- neighbor matching
- covariate balance checks
- spatial interference diagnostics
- geographic holdout diagnostics

This is important because a land-use pattern that historically correlates with development pressure is not equivalent to the causal effect of approving a specific project.

## 7. Planner Relationship

GeoSOS explicitly couples simulation and optimization, including CA, MAS and swarm intelligence based strategies.

TWM treats planner as a consumer of the simulator rather than as the world model itself. Beam search, MPC-style search or constrained rollout can rank candidate plans, but their utility scores must be constrained by:

- simulator outputs
- rule and action masks
- causal calibration
- uncertainty
- evidence gate
- audit requirements

This design avoids conflating an optimization routine with a world-model claim.

## 8. Comparison Matrix

| Dimension | GeoSOS/FLUS | TWM |
|---|---|---|
| Research object | Land-use type transition and allocation | Action-conditioned territorial governance state |
| Spatial unit | Raster cell / land-use type | Hierarchical GIS object and relation |
| Input emphasis | Driving factors, neighborhood, scenario demand | Action, scenario, rules, evidence, governance records |
| Dynamics | CA allocation, ANN suitability, inertia, competition | Multi-head action-conditioned dynamics |
| Output | Future land-use map and scenario allocation | Future state, constraint risk, utility, uncertainty, evidence gate |
| Optimization | Coupled with MAS/SI/ACO-like optimization | Planner as evidence-gated simulator consumer |
| Causal status | Scenario simulation and calibrated prediction | Explicit spatial observational calibration and review boundary |
| Governance readiness | Useful for planning scenarios and land-use trends | Designed for rule review, audit, evidence and decision traceability |

## 9. Recommended Novelty Claim

Do not claim:

> TWM is the first geospatial simulation model.

A defensible claim is:

> TWM is a governance-oriented geospatial world model that integrates hierarchical GIS object-relation-rule-evidence states, action-conditioned territorial dynamics, multi-head planning outputs, spatial causal calibration and evidence-gated claim validation into an auditable loop for territorial planning.

Chinese version:

> TWM 的创新不是首次实现地理空间模拟，而是首次系统地把层级 GIS 对象-关系-规则-证据状态、行动条件动力学、空间因果校准、证据门控和规划消费闭环组织成面向国土空间治理的可审计世界模型。

## 10. Practical Research Implication

For pure land-use pattern simulation, TWM should be compared against FLUS, PLUS, CLUE-S, CA-Markov and related baselines.

For natural-resource governance tasks, the stronger comparison should include:

- project approval risk review
- permanent basic farmland occupation review
- ecological redline conflict review
- urban development boundary consistency
- evidence-backed planning scenario review
- counterfactual impact of governance actions
- audit-traceable decision support

This distinction prevents category errors. FLUS is a strong baseline for land-use simulation; TWM targets a broader and more decision-oriented governance world-model problem.

## References And Source Basis

- GeoSOS homepage: `http://www.geosimulation.cn/index.html`
- GeoSOS-FLUS page: `http://www.geosimulation.cn/FLUS.html`
- GeoSOS publications: `http://www.geosimulation.cn/Publications.html`
- Liu et al. 2017. A future land use simulation model (FLUS) for simulating multiple land use scenarios by coupling human and natural effects. Landscape and Urban Planning.
- Li et al. 2011. Coupling simulation and optimization to solve planning problems in a fast developing area. Annals of the Association of American Geographers.
- GIS Data Agent TWM implementation: `data_agent/territory_world_model/`
- GIS Data Agent TWM toolset: `data_agent/toolsets/territory_world_model_tools.py`

