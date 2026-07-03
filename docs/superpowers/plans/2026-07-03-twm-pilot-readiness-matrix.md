# TWM Pilot Readiness Matrix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a strict pilot readiness matrix that aggregates current TWM evidence and blocks production claims when authoritative observed history and policy labels are missing.

**Architecture:** Implement one service method on the existing TWM facade, then expose it through one REST route and one ADK tool. The method reuses `data_foundation_assessment()` and existing roadmap facts; it does not create new model claims.

**Tech Stack:** Python, Starlette route functions, ADK `FunctionTool`, pytest.

---

### Task 1: Service Report Contract

**Files:**
- Modify: `data_agent/test_territory_world_model.py`
- Modify: `data_agent/territory_world_model/service.py`

- [ ] **Step 1: Write failing service tests**

Add tests asserting that `pilot_readiness_matrix_report()` returns schema
`territory_world_model.pilot_readiness_matrix.v1`, six dimensions, aggregate
`blocked`, and a blocked production gate with zero production rows.

- [ ] **Step 2: Run the new tests to verify RED**

Run:

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj /Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_territory_world_model.py::test_pilot_readiness_matrix_blocks_without_authoritative_history -q
```

Expected: fail because `pilot_readiness_matrix_report` does not exist.

- [ ] **Step 3: Implement the minimal service method**

Add `pilot_readiness_matrix_report()` near `roadmap_status_report()`. It should
return dimensions for `data_foundation`, `policy_rules`, `simulator`, `planner`,
`evidence_audit`, and `production_gate`.

- [ ] **Step 4: Run service tests to verify GREEN**

Run the same pytest command. Expected: pass.

### Task 2: Route and Tool Exposure

**Files:**
- Modify: `data_agent/api/territory_world_model_routes.py`
- Modify: `data_agent/toolsets/territory_world_model_tools.py`
- Modify: `data_agent/test_territory_world_model.py`

- [ ] **Step 1: Write failing route/tool tests**

Add tests for `twm_pilot_readiness_matrix` route and tool.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj /Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_territory_world_model.py::test_pilot_readiness_matrix_route_returns_json data_agent/test_territory_world_model.py::test_twm_pilot_readiness_matrix_tool_returns_report -q
```

Expected: fail because the route/tool do not exist.

- [ ] **Step 3: Implement route and tool**

Add:

- `GET /api/twm/pilot-readiness-matrix`
- `twm_pilot_readiness_matrix()`

- [ ] **Step 4: Run route/tool tests to verify GREEN**

Run the same pytest command. Expected: pass.

### Task 3: Regression Verification

**Files:**
- Existing focused TWM tests.

- [ ] **Step 1: Run focused readiness and roadmap tests**

Run:

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj /Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_territory_world_model.py -k "roadmap_status or pilot_readiness_matrix or toolset_lists" -q
```

Expected: pass.

- [ ] **Step 2: Run syntax check**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m compileall -q data_agent/territory_world_model data_agent/api/territory_world_model_routes.py data_agent/toolsets/territory_world_model_tools.py
```

Expected: exit code 0.

