# Customer Demand Phase 0 Safe Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely integrate the customer-demand worktree into the mobility-aware UWM branch and expose an executable registry with one primary route for every LIV scenario and customer demand.

**Architecture:** Preserve the dirty worktree before integration. A backend registry becomes the single source of truth; traditional and UWM APIs receive non-overlapping filtered views, while a readiness API and tab expose all 30 rows without treating registration or UI coverage as business completion.

**Tech Stack:** Python 3.11, Starlette, pytest, React, TypeScript, Git worktrees.

---

## Scope

This plan implements Phase 0 only from `docs/superpowers/specs/2026-07-10-customer-ai-demands-and-uwm-livability-design.md`.

It does not implement S1/S2/S4/S6/S7 algorithms, new UWM dynamics, the Geospatial World Model Kernel, or new non-livability tabs. Each of those receives a separate plan after this integration gate passes.

## Files

- Create `data_agent/uwm/livability_requirement_registry.py`: canonical ownership and readiness registry.
- Create `data_agent/api/uwm_ai_demand_readiness_routes.py`: read-only registry API.
- Create `frontend/src/components/datapanel/AiDemandReadinessTab.tsx`: ownership/readiness UI.
- Modify `data_agent/uwm/__init__.py`: registry exports without removing mobility exports.
- Modify `data_agent/frontend_api.py`: API registration.
- Modify `data_agent/uwm/traditional_livability_analysis.py`: traditional ownership view.
- Modify `data_agent/api/uwm_livability_decision_routes.py`: UWM ownership view.
- Modify `frontend/src/components/DataPanel.tsx`: readiness tab registration.
- Create or modify the corresponding `data_agent/test_uwm_*.py` tests.
- Create `docs/reports/uwm_customer_demand_phase0_integration_2026-07-10.md`: preservation and verification evidence.

### Task 1: Preserve the Dirty Requirement Worktree

**Files:**
- Create: `/private/tmp/uwm-livability-requirement-split-2026-07-10.patch`
- Create: `/private/tmp/uwm-livability-requirement-split-2026-07-10-status.txt`
- Create: `/private/tmp/uwm-livability-requirement-split-2026-07-10-files.tar.gz`
- Create: `docs/reports/uwm_customer_demand_phase0_integration_2026-07-10.md`

- [ ] **Step 1: Capture status and a binary-safe patch**

```bash
git -C .worktrees/uwm-livability-requirement-split status --short \
  > /private/tmp/uwm-livability-requirement-split-2026-07-10-status.txt
git -C .worktrees/uwm-livability-requirement-split diff --binary \
  > /private/tmp/uwm-livability-requirement-split-2026-07-10.patch
```

Expected: both files are non-empty.

- [ ] **Step 2: Archive the modified source files**

```bash
tar -czf /private/tmp/uwm-livability-requirement-split-2026-07-10-files.tar.gz \
  -C .worktrees/uwm-livability-requirement-split \
  data_agent/uwm/livability_requirement_registry.py \
  data_agent/test_uwm_livability_requirement_registry.py \
  data_agent/test_uwm_ai_demand_readiness_routes.py \
  data_agent/test_uwm_ai_demand_readiness_frontend_contract.py \
  frontend/src/components/datapanel/AiDemandReadinessTab.tsx \
  frontend/src/components/datapanel/LivabilityWorldModelTab.tsx \
  frontend/src/components/datapanel/TraditionalLivabilityTab.tsx \
  frontend/src/styles/layout.css
```

Expected: `tar -tzf /private/tmp/uwm-livability-requirement-split-2026-07-10-files.tar.gz` lists all eight files.

- [ ] **Step 3: Write the preservation report**

Create the report with:

```markdown
# UWM Customer Demand Phase 0 Integration

Date: 2026-07-10

## Source Branches

- Integration branch: `feat/v12-extensible-platform`
- Requirement worktree: `.worktrees/uwm-livability-requirement-split`
- Requirement branch head before integration: `e1ea8c9`
- Mobility-aware UWM head before design commit: `1d5e924`

## Preservation

- Status: `/private/tmp/uwm-livability-requirement-split-2026-07-10-status.txt`
- Patch: `/private/tmp/uwm-livability-requirement-split-2026-07-10.patch`
- Source archive: `/private/tmp/uwm-livability-requirement-split-2026-07-10-files.tar.gz`

## Integration Rule

The requirement branch is implementation input, not a blind merge. The
canonical registry follows the confirmed one-primary-route design and retains
the mobility-aware UWM exports already present on the integration branch.
```

- [ ] **Step 4: Verify and commit the preservation report**

```bash
test -s /private/tmp/uwm-livability-requirement-split-2026-07-10.patch
test -s /private/tmp/uwm-livability-requirement-split-2026-07-10-status.txt
tar -tzf /private/tmp/uwm-livability-requirement-split-2026-07-10-files.tar.gz >/dev/null
git diff --check -- docs/reports/uwm_customer_demand_phase0_integration_2026-07-10.md
git add docs/reports/uwm_customer_demand_phase0_integration_2026-07-10.md
git commit -m "docs: record UWM requirement worktree preservation"
```

### Task 2: Implement the Canonical Unique-Ownership Registry

**Files:**
- Create: `data_agent/uwm/livability_requirement_registry.py`
- Create: `data_agent/test_uwm_livability_requirement_registry.py`
- Modify: `data_agent/uwm/__init__.py`

- [ ] **Step 1: Write failing registry tests**

Create tests containing these exact ownership maps:

```python
EXPECTED_SCENARIO_ROUTES = {
    "S1": "traditional_livability",
    "S2": "uwm_livability",
    "S4": "traditional_livability",
    "S6": "traditional_livability",
    "S7": "traditional_livability",
}

EXPECTED_DEMAND_ROUTES = {
    "1": "planning_land", "2": "planning_land", "3": "planning_land",
    "4": "infrastructure_assets", "5": "infrastructure_assets",
    "6": "population_demand", "7": "uwm_livability",
    "8": "traditional_livability", "9": "traditional_livability",
    "10": "traditional_livability", "11": "uwm_livability",
    "12": "traditional_livability", "13": "traditional_livability",
    "14": "traditional_livability", "15": "traditional_livability",
    "16": "traditional_livability", "17": "infrastructure_assets",
    "18": "infrastructure_assets", "19": "uwm_livability",
    "20": "economy_investment", "21": "traditional_livability",
    "22": "planning_land", "23": "economy_investment",
    "24": "impact_implementation", "25": "impact_implementation",
}
```

Add tests that assert:

```python
registry = build_livability_requirement_registry()
assert len(registry["livability_scenarios"]) == 5
assert len(registry["customer_ai_demands"]) == 25
assert LIVABILITY_SCENARIO_PRIMARY_ROUTES == EXPECTED_SCENARIO_ROUTES
assert CUSTOMER_DEMAND_PRIMARY_ROUTES == EXPECTED_DEMAND_ROUTES
assert validate_livability_requirement_registry(registry) == {
    "valid": True,
    "errors": [],
}
```

Iterate all seven routes through `requirement_coverage_for_route()` and assert every scenario/demand appears exactly once. Also assert demand 23 has `data_support == "requires_customer_data"`, no implemented outputs, and the registry claim boundary has `registration_is_not_implementation=True` and `observed_policy_outcome_superiority_claim=False`.

- [ ] **Step 2: Run the test and verify failure**

```bash
PYTHONPATH=. .venv/bin/pytest data_agent/test_uwm_livability_requirement_registry.py -q
```

Expected: import failure because the module is absent.

- [ ] **Step 3: Implement registry constants and validators**

Create:

```python
UWM_LIVABILITY_REQUIREMENT_REGISTRY_SCHEMA = "uwm.customer_ai_requirement_registry.v2"

SOURCE_DOCUMENTS = [
    "/Users/zhouning/Downloads/宜居性专项分析.docx",
    "/Users/zhouning/Downloads/客户侧25个AI应用需求的回复.docx",
]

PRIMARY_ROUTES = {
    "traditional_livability",
    "uwm_livability",
    "planning_land",
    "infrastructure_assets",
    "population_demand",
    "economy_investment",
    "impact_implementation",
}
```

Use the exact route maps from Step 1. Define all 30 rows with:

```python
{
    "id": "23",
    "title": "财务与投资分析",
    "primary_route": "economy_investment",
    "required_method": "deterministic_financial_model",
    "implementation_level": "data_contract_required",
    "data_support": "requires_customer_data",
    "route_availability": "planned",
    "implemented_outputs": [],
    "production_blockers": [
        "boq", "capital_cost", "operating_cost", "revenue", "cash_flow"
    ],
}
```

Set `route_availability="existing"` only for traditional and UWM livability routes. Implement:

```python
def build_livability_requirement_registry() -> dict[str, Any]: ...
def requirement_coverage_for_route(registry: dict[str, Any], route: str) -> dict[str, Any]: ...
def validate_livability_requirement_registry(payload: dict[str, Any]) -> dict[str, Any]: ...
```

The validator must enforce the exact five scenario IDs, demand IDs 1–25, no duplicate IDs, valid routes, valid route availability, list-valued `implemented_outputs`, and list-valued `production_blockers`.

- [ ] **Step 4: Merge exports without removing mobility support**

Add registry imports and `__all__` entries to `data_agent/uwm/__init__.py`, while retaining:

```python
UWM_FULL_ADMIN_MOBILITY_GRAPH_SCHEMA
build_full_admin_mobility_graph
validate_full_admin_mobility_graph
write_full_admin_mobility_graph_snapshot
```

- [ ] **Step 5: Run registry and mobility tests**

```bash
PYTHONPATH=. .venv/bin/pytest \
  data_agent/test_uwm_livability_requirement_registry.py \
  data_agent/test_uwm_full_admin_mobility_graph.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add data_agent/uwm/livability_requirement_registry.py \
  data_agent/test_uwm_livability_requirement_registry.py \
  data_agent/uwm/__init__.py
git commit -m "feat: add canonical customer demand ownership registry"
```

### Task 3: Add the Readiness API

**Files:**
- Create: `data_agent/api/uwm_ai_demand_readiness_routes.py`
- Create: `data_agent/test_uwm_ai_demand_readiness_routes.py`
- Modify: `data_agent/frontend_api.py`

- [ ] **Step 1: Write failing route tests**

Tests must assert GET registration at `/api/uwm/ai-demand-readiness` and this payload contract:

```python
payload = routes.load_uwm_ai_demand_readiness_payload()
assert len(payload["livability_scenarios"]) == 5
assert len(payload["customer_ai_demands"]) == 25
assert payload["summary"]["registered_requirement_count"] == 30
assert payload["summary"]["existing_route_count"] == 2
assert payload["summary"]["planned_route_count"] == 5
assert payload["claim_boundary"]["registration_is_not_implementation"] is True
assert payload["claim_boundary"]["observed_policy_outcome_superiority_claim"] is False
```

- [ ] **Step 2: Run and verify failure**

```bash
PYTHONPATH=. .venv/bin/pytest data_agent/test_uwm_ai_demand_readiness_routes.py -q
```

Expected: module import failure.

- [ ] **Step 3: Implement the route**

Create a read-only Starlette route with:

```python
UWM_AI_DEMAND_READINESS_API_SCHEMA = "uwm.ai_demand_readiness_api.v2"

def load_uwm_ai_demand_readiness_payload() -> dict[str, Any]:
    registry = build_livability_requirement_registry()
    route_rows = [
        {
            "route": route,
            "availability": "existing" if route in {
                "traditional_livability", "uwm_livability"
            } else "planned",
        }
        for route in registry["primary_routes"]
    ]
    rows = registry["livability_scenarios"] + registry["customer_ai_demands"]
    return {
        "schema": UWM_AI_DEMAND_READINESS_API_SCHEMA,
        "source_documents": registry["source_documents"],
        "livability_scenarios": registry["livability_scenarios"],
        "customer_ai_demands": registry["customer_ai_demands"],
        "primary_routes": route_rows,
        "summary": {
            "registered_requirement_count": len(rows),
            "existing_route_count": sum(row["availability"] == "existing" for row in route_rows),
            "planned_route_count": sum(row["availability"] == "planned" for row in route_rows),
            "production_complete_count": sum(
                row["implementation_level"] == "production_complete" for row in rows
            ),
        },
        "claim_boundary": registry["claim_boundary"],
    }
```

Register the route through `data_agent/frontend_api.py` after the UWM livability decision routes.

- [ ] **Step 4: Run tests and commit**

```bash
PYTHONPATH=. .venv/bin/pytest data_agent/test_uwm_ai_demand_readiness_routes.py -q
git add data_agent/api/uwm_ai_demand_readiness_routes.py \
  data_agent/test_uwm_ai_demand_readiness_routes.py data_agent/frontend_api.py
git commit -m "feat: expose customer demand ownership readiness API"
```

### Task 4: Bind Existing Livability APIs to Non-Overlapping Ownership

**Files:**
- Modify: `data_agent/uwm/traditional_livability_analysis.py`
- Modify: `data_agent/test_uwm_traditional_livability_analysis.py`
- Modify: `data_agent/api/uwm_livability_decision_routes.py`
- Modify: `data_agent/test_uwm_livability_decision_routes.py`

- [ ] **Step 1: Write failing ownership tests**

Traditional assertions:

```python
coverage = result["requirement_ownership"]
assert coverage["primary_route"] == "traditional_livability"
assert {row["id"] for row in coverage["livability_scenarios"]} == {"S1", "S4", "S6", "S7"}
assert {row["id"] for row in coverage["customer_ai_demands"]} == {
    "8", "9", "10", "12", "13", "14", "15", "16", "21"
}
assert result["method_boundary"]["world_model_transition_claim"] is False
```

UWM assertions:

```python
coverage = payload["requirement_ownership"]
assert coverage["primary_route"] == "uwm_livability"
assert {row["id"] for row in coverage["livability_scenarios"]} == {"S2"}
assert {row["id"] for row in coverage["customer_ai_demands"]} == {"7", "11", "19"}
assert payload["observed_policy_outcome_superiority_claim"] is False
assert payload["empirical_superiority_claim"] is False
```

- [ ] **Step 2: Run and verify failure**

```bash
PYTHONPATH=. .venv/bin/pytest \
  data_agent/test_uwm_traditional_livability_analysis.py \
  data_agent/test_uwm_livability_decision_routes.py -q
```

Expected: missing `requirement_ownership` failures.

- [ ] **Step 3: Attach filtered views**

Both implementations must call:

```python
registry = build_livability_requirement_registry()
requirement_ownership = requirement_coverage_for_route(registry, ROUTE_NAME)
```

Return `requirement_ownership` from each payload. Traditional analysis must keep `world_model_transition_claim=False` and `policy_outcome_claim=False`. UWM must retain false observed-policy and empirical-superiority claims.

- [ ] **Step 4: Run tests and commit**

```bash
PYTHONPATH=. .venv/bin/pytest \
  data_agent/test_uwm_traditional_livability_analysis.py \
  data_agent/test_uwm_livability_decision_routes.py -q
git add data_agent/uwm/traditional_livability_analysis.py \
  data_agent/test_uwm_traditional_livability_analysis.py \
  data_agent/api/uwm_livability_decision_routes.py \
  data_agent/test_uwm_livability_decision_routes.py
git commit -m "feat: bind livability APIs to unique requirement ownership"
```

### Task 5: Add the AI Demand Ownership Matrix Tab

**Files:**
- Create: `frontend/src/components/datapanel/AiDemandReadinessTab.tsx`
- Modify: `frontend/src/components/DataPanel.tsx`
- Create: `data_agent/test_uwm_ai_demand_readiness_frontend_contract.py`

- [ ] **Step 1: Write failing frontend contract tests**

Assert tab registration after `uwm_livability`, API usage, and presence of:

```text
primary_route
implementation_level
data_support
route_availability
implemented_outputs
production_blockers
registration_is_not_implementation
production_complete_count
observed_policy_outcome_superiority_claim
```

Also assert the obsolete fields `complete_in_livability_case_count` and `phase1_partial_count` are absent.

- [ ] **Step 2: Run and verify failure**

```bash
PYTHONPATH=. .venv/bin/pytest data_agent/test_uwm_ai_demand_readiness_frontend_contract.py -q
```

Expected: missing tab failure.

- [ ] **Step 3: Implement the tab**

Use:

```typescript
type RequirementRow = {
  id: string;
  title: string;
  primary_route: string;
  required_method: string;
  implementation_level: string;
  data_support: string;
  route_availability: 'existing' | 'planned';
  implemented_outputs: string[];
  production_blockers: string[];
};
```

Fetch `/api/uwm/ai-demand-readiness` and render source documents, seven routes, five scenarios, 25 demands, blockers and claim boundaries. Display a prominent warning when `registration_is_not_implementation` is true. Reuse existing component styles; do not copy the dirty worktree's large uncommitted `layout.css` patch in Phase 0.

Register `ai_demand_readiness` with label `AI应用需求矩阵` after `uwm_livability` in `frontend/src/components/DataPanel.tsx`.

- [ ] **Step 4: Run tests, build and commit**

```bash
PYTHONPATH=. .venv/bin/pytest data_agent/test_uwm_ai_demand_readiness_frontend_contract.py -q
cd frontend && npm run build
cd ..
git add frontend/src/components/datapanel/AiDemandReadinessTab.tsx \
  frontend/src/components/DataPanel.tsx \
  data_agent/test_uwm_ai_demand_readiness_frontend_contract.py
git commit -m "feat: add customer AI demand ownership matrix tab"
```

Expected: tests pass and the frontend build exits 0.

### Task 6: Verify and Document Phase 0

**Files:**
- Modify: `docs/reports/uwm_customer_demand_phase0_integration_2026-07-10.md`

- [ ] **Step 1: Run the full Phase 0 regression set**

```bash
PYTHONPATH=. .venv/bin/pytest \
  data_agent/test_uwm_livability_requirement_registry.py \
  data_agent/test_uwm_ai_demand_readiness_routes.py \
  data_agent/test_uwm_ai_demand_readiness_frontend_contract.py \
  data_agent/test_uwm_traditional_livability_analysis.py \
  data_agent/test_uwm_livability_decision_routes.py \
  data_agent/test_uwm_full_admin_mobility_graph.py \
  data_agent/test_uwm_model_based_rl.py \
  data_agent/test_uwm_core_action_conditioned_dynamics_benchmark.py \
  data_agent/test_uwm_core_world_model_policy_improvement_benchmark.py -q
```

Expected: all selected tests pass. Report unrelated failures without repairing them in this phase.

- [ ] **Step 2: Run the frontend build**

```bash
cd frontend && npm run build
```

Expected: exit code 0.

- [ ] **Step 3: Verify runtime invariants**

```bash
PYTHONPATH=. .venv/bin/python - <<'PY'
from collections import Counter
from data_agent.uwm.livability_requirement_registry import (
    build_livability_requirement_registry,
    validate_livability_requirement_registry,
)
registry = build_livability_requirement_registry()
rows = registry["livability_scenarios"] + registry["customer_ai_demands"]
print(validate_livability_requirement_registry(registry))
print("row_count", len(rows))
print("route_counts", dict(Counter(row["primary_route"] for row in rows)))
print("production_complete_count", sum(
    row["implementation_level"] == "production_complete" for row in rows
))
PY
```

Expected: `valid=True`, `row_count 30`, and route counts summing to 30.

- [ ] **Step 4: Record exact verification evidence**

Append the exact pytest result, frontend build result, runtime validation and remaining Phase 1–4 work to the integration report. Do not write estimated pass counts.

- [ ] **Step 5: Check diff and commit the report**

```bash
git diff --check
git status --short
git add docs/reports/uwm_customer_demand_phase0_integration_2026-07-10.md
git commit -m "docs: record customer demand phase0 verification"
```

## Completion Gate

Do not start business algorithms or the kernel until:

- the dirty requirement worktree is preserved;
- all 30 rows have exactly one primary route;
- the two livability APIs expose non-overlapping ownership;
- planned domain routes are not presented as implemented tabs;
- mobility-aware UWM regression tests pass;
- the frontend build succeeds;
- the report contains fresh verification evidence.
