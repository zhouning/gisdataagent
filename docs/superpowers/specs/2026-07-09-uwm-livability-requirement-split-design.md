# UWM Livability Requirement Split Design

Date: 2026-07-09

## Context

The implementation must respond to two customer requirement documents:

- `/Users/zhouning/Downloads/宜居性专项分析.docx`
- `/Users/zhouning/Downloads/客户侧25个AI应用需求的回复.docx`

The livability document defines five LIV 2.0 scenarios: S1 district facility assessment, S2 land-use/facility-change impact assessment, S4 project livability assessment, S6 out-of-scope facility assessment, and S7 facility siting. The 25-demand document states that 7, 8, 15, and 21 can be fully included in the livability case; 1-6, 9-14, 16, and 17 can be partially satisfied by phase-1 data access/query/statistics; and 18-20 plus 22-25 are outside phase-1 scope and should be phase-2 standalone cases.

The existing product already has two tabs:

- `城市宜居性分析（传统方法）`
- `城市宜居性分析（UWM）`

The current gap is that customer requirements are not first-class executable contracts. The traditional tab exposes static weighted ranking. The UWM tab exposes decision artifacts and evidence gates. Neither tab currently makes the scenario-to-method split explicit enough for production-facing use.

## Design Goal

Create a requirement-driven livability implementation that makes each customer demand inspectable by method, data support, evidence level, and production blockers.

The result must not overclaim. It can show that UWM is stronger than traditional methods on action-conditioned, rollout, spillover, uncertainty, and planning tasks using real local artifacts. It must not claim production policy-outcome superiority until authoritative policy outcome and governance gates pass.

## Alternatives Considered

### A. Add labels directly in the frontend tabs

This is fast but weak. It would make the UI look clearer while leaving the backend contract unchanged. It would not prevent future code paths from mixing static analysis, UWM claims, and phase-2 requirements.

### B. Add a backend requirement registry and drive both tabs from it

This is the selected approach. A backend registry makes the method split testable, reusable by APIs, and visible in the UI. It also allows pytest to enforce that S2 and dynamic S7 are not accidentally downgraded into traditional static analysis.

### C. Build all 25 demands as separate feature modules now

This is too broad for the current step and would dilute the livability work. Many non-livability demands require separate data sources, business rules, and model algorithms. They should be exposed as readiness/capability items first, then implemented as separate cases.

## Architecture

Add a new backend module:

- `data_agent/uwm/livability_requirement_registry.py`

The registry returns a stable JSON-compatible contract with three groups:

1. `livability_scenarios`
   - S1, S2, S4, S6, S7 from LIV 2.0.
   - Each scenario has `traditional_support`, `uwm_support`, `recommended_tab`, `required_outputs`, `data_basis`, `production_blockers`, and `claim_boundary`.

2. `customer_ai_demands`
   - Items 1-25 from the customer response document.
   - Each item has `phase`, `livability_relevance`, `current_data_support`, `traditional_capabilities`, `uwm_capabilities`, `standalone_tab_candidate`, and `implementation_status`.

3. `method_split`
   - Traditional method handles static current-state diagnosis: counts, buffers/service areas, FP/FPP-style gaps, current coverage, current shortage ranking, current map layers, and rule-based static suggestions.
   - UWM handles world-model tasks: action-conditioned transition, land-use/facility-change counterfactuals, rollout, spatial spillover, uncertainty, policy/action sequence planning, learned value/policy evidence, and evidence-gated superiority claims.

## Traditional Livability Tab Scope

The traditional tab must support only current-state analysis.

Supported scenario coverage:

- S1: district facility gap assessment when data contains region, facility category, quantity/distribution metrics, and FP/FPP-style thresholds or proxy service coverage.
- S4: project fit assessment only for static resource conflict, duplicate supply, or current service demand alignment. It must not estimate future impact.
- S6: out-of-scope facility assessment only for static category mapping and conflict/buffer checks. If category mapping is not available, the response must say the full "classify then S1" chain is not ready.
- S7: facility siting only as static candidate ranking by current service gap and current coverage improvement proxy. It must not claim optimized future benefit.

Traditional output additions:

- `requirement_registry.method_split.traditional`
- `scenario_coverage`
- `customer_demand_coverage`
- `unsupported_dynamic_requirements`
- `method_boundary`

The existing map endpoint stays static. It should not emit rollout, predicted delta, simulator trace, planner trace, or policy superiority claims.

## UWM Livability Tab Scope

The UWM tab must support only tasks that require the geospatial world-model architecture.

Supported scenario coverage:

- S2: land-use/facility-change impact assessment as action-conditioned before/after counterfactual.
- S4: future contribution of a project only when represented as actions and evaluated through simulator/planner traces.
- S7: dynamic siting and intervention prioritization with rollout, spatial spillover, uncertainty, and multi-step planning.
- Demand 24/25 dynamic parts: impact assessment, priority scoring, implementation sequence, and roadmap only when backed by UWM traces and evidence gates.

UWM output additions:

- `requirement_registry.method_split.uwm`
- `uwm_only_scenario_coverage`
- `customer_demand_coverage`
- `production_world_model_readiness`
- `production_blockers`
- `observed_policy_outcome_superiority_claim`
- `empirical_superiority_claim`

The tab must continue to expose renderer, simulator, planner, evidence readiness, spatial causal contracts, full-admin action inventory, and governance blocking gates.

## Non-Livability Demands

Add a separate tab after the livability tabs:

- `AI应用需求矩阵`

This tab does not implement all 25 demands as business workflows. It exposes what can be implemented from the current data foundation and what requires phase-2 work.

Initial classification:

- Complete in livability case: 7, 8, 15, 21.
- Phase-1 partial data/query/statistics: 1, 2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14, 16, 17.
- Phase-2 standalone case: 18, 19, 20, 22, 23, 24, 25.

Demand 24 and 25 can reference UWM when the user is asking for livability impact and intervention sequencing, but their full customer-scope outputs remain phase-2 because they include finance, design controls, cross-domain implementation planning, and broader governance.

## Data And Evidence Rules

All outputs must be based on existing real local artifacts where available:

- Chongqing central UWM public proxy data root.
- Multisource livability scene.
- Full-admin service accessibility surface.
- Admin spatial graph and geographic similarity graph.
- OSM road/service assets.
- POI/AOI assets.
- CLCD/GHSL alignment.
- OpenAQ/TAP/CHAP/CAMS related environmental artifacts.
- Existing UWM decision, replay, RL, GraphDQN, full-admin decision, and evidence gate artifacts.

Evidence boundaries:

- `production_world_model_ready` remains false until observed mobility/travel-time, station-calibrated observed scene holdout, authoritative policy outcome validation, and planner governance binding gates are satisfied.
- `observed_policy_outcome_superiority_claim` remains false.
- `empirical_superiority_claim` remains false unless the claim is explicitly scoped to non-policy holdout or same-scene simulator replay and labelled accordingly.
- Proxy and fitted data must stay labelled and must not be converted into core production support by UI wording.

## API Changes

Extend existing endpoints:

- `GET /api/uwm/traditional-livability`
  - Include traditional requirement coverage and unsupported UWM-only items.

- `GET /api/uwm/livability-decision`
  - Include UWM requirement coverage, UWM-only scenarios, and production blockers.

Add endpoint:

- `GET /api/uwm/ai-demand-readiness`
  - Returns the 25-demand readiness matrix and tab-target guidance.

The registry module should be pure Python and deterministic. It should not read docx files at runtime. The extracted requirement content is represented as versioned code constants because the source documents are customer requirement baselines, not operational data streams.

## Frontend Changes

Traditional tab:

- Add a compact scenario coverage panel.
- Add a demand coverage panel filtered to static/traditional support.
- Preserve current KPI, ranking, map push, method boundary, and data basis panels.

UWM tab:

- Add a UWM-only scenario coverage panel.
- Add production readiness/blocker panel tied to the evidence readiness payload.
- Keep renderer/simulator/planner, training evidence, spatial causal contract, action inventory, and claim boundary panels.

AI demand readiness tab:

- Add a separate tab in `DataPanel`.
- Show a dense matrix with demand number, theme, livability relevance, current support, target capability, tab target, and blocker.
- Do not present phase-2 demands as implemented.

## Error Handling

If requirement registry construction fails, endpoints return HTTP 500 with a clear error string. Normal operation should be deterministic and not fail on missing optional UWM artifacts because the registry itself is static.

If UWM artifact loading fails, the UWM decision endpoint should keep its current failure behavior. The registry should not mask missing decision data.

If a demand is outside the current method boundary, the payload must mark it unsupported or phase-2 instead of returning a plausible answer.

## Testing

Add backend tests:

- S1 is traditional-supported and not UWM-required for basic static assessment.
- S2 is UWM-required and not traditional-supported for impact claims.
- S4 has split support: static project fit by traditional, future contribution by UWM.
- S6 has partial traditional support and blocked full category-to-S1 chain unless category mapping exists.
- S7 has split support: static ranking by traditional, dynamic rollout/planning by UWM.
- Demands 7, 8, 15, 21 are complete in livability case.
- Demands 1-6, 9-14, 16, 17 are phase-1 partial.
- Demands 18-20, 22-25 are phase-2 standalone.
- UWM decision payload exposes requirement coverage and production blockers without changing observed policy outcome claim flags.
- Traditional payload exposes requirement coverage without rollout/counterfactual fields.
- AI demand readiness route is registered in `frontend_api`.

Update frontend contract tests:

- Traditional tab contains scenario coverage and demand coverage labels.
- UWM tab contains UWM-only scenario coverage and production blocker labels.
- DataPanel registers the AI demand readiness tab after the UWM livability tab.

Run verification:

- `uv run pytest data_agent/test_uwm*.py -q`
- If frontend files change, run the available frontend typecheck/build script after inspecting `package.json`.

## Out Of Scope For This Step

- Downloading or fabricating new customer data.
- Building full production travel-time or OD mobility surfaces.
- Claiming observed policy outcome superiority.
- Replacing the mechanistic simulator with a fully learned production dynamics model.
- Implementing all phase-2 standalone cases end to end.

## Acceptance Criteria

The work is acceptable when:

1. The two livability tabs clearly distinguish traditional static analysis from UWM world-model analysis.
2. Every LIV 2.0 scenario has an explicit method classification and evidence boundary.
3. Every one of the 25 customer AI demands has a current support classification.
4. UWM-only claims remain tied to renderer/simulator/planner evidence and production gates.
5. Existing UWM regression tests pass on real local artifacts.
6. No output claims production-ready world-model status while the hard gates remain blocked.
