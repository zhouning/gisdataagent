# World Model v2.1 ADK Toolset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose World Model v2.1 as ADK tools so local Gemma4:26b can be tested on tool selection and tool invocation.

**Architecture:** Add a focused `WorldModelV21Toolset` that wraps the existing `WorldModelV21Service` and returns compact JSON strings. Register the toolset in the same agent locations as v1/v2 world-model tools, without changing Paper9 planning logic or frontend/API behavior.

**Tech Stack:** Google ADK `FunctionTool` and `LongRunningFunctionTool`, existing `BaseToolset`, pytest, Paper9 `farmland_mpc` service adapter.

---

### Task 1: Toolset Tests

**Files:**
- Create: `data_agent/test_world_model_v21_tools.py`

- [x] **Step 1: Write failing tests**

Add tests that import `WorldModelV21Toolset`, call `get_tools()`, and call `world_model_v21_status()` / `_world_model_v21_plan_sync()` with a fake service.

- [x] **Step 2: Verify tests fail**

Run: `python -m pytest data_agent/test_world_model_v21_tools.py -q -p no:cacheprovider`
Expected: import failure because `data_agent.toolsets.world_model_v21_tools` does not exist yet.

### Task 2: Toolset Implementation

**Files:**
- Create: `data_agent/toolsets/world_model_v21_tools.py`
- Modify: `data_agent/toolsets/__init__.py`

- [x] **Step 1: Implement status tool**

Create `world_model_v21_status()` that returns `json.dumps(get_world_model_v21_service().status(), ensure_ascii=False, default=str)`.

- [x] **Step 2: Implement planning tool**

Create `_world_model_v21_plan_sync(...)` and async `world_model_v21_plan(...)`. It must accept string-friendly ADK parameters, normalize them into the service payload, call `run_plan(..., user_id="agent_world_model_v21")`, remove `map_config`, and return JSON.

- [x] **Step 3: Implement toolset class**

Return `FunctionTool(world_model_v21_status)` and `LongRunningFunctionTool(world_model_v21_plan)` from `WorldModelV21Toolset.get_tools()`, honoring the inherited `tool_filter`.

- [x] **Step 4: Export toolset**

Import `WorldModelV21Toolset` from `data_agent/toolsets/__init__.py`.

- [x] **Step 5: Verify tests pass**

Run: `python -m pytest data_agent/test_world_model_v21_tools.py -q -p no:cacheprovider`
Expected: all tests pass.

### Task 3: Agent Registration Tests

**Files:**
- Modify: `data_agent/test_multi_agent_collaboration.py`
- Add or modify focused assertions in `data_agent/test_world_model_v21_tools.py`

- [x] **Step 1: Write failing registration assertions**

Assert `WorldModelV21Toolset` is exported and present in `general_processing_agent.tools`; assert `AnalystAgent` can also access it.

- [x] **Step 2: Verify failure**

Run the focused tests. Expected: failure because agent imports and tools do not include v2.1 yet.

### Task 4: Agent Registration Implementation

**Files:**
- Modify: `data_agent/agent.py`

- [x] **Step 1: Import toolset**

Add `from .toolsets.world_model_v21_tools import WorldModelV21Toolset`.

- [x] **Step 2: Add to general processing tools**

Add `WorldModelV21Toolset(tool_filter=intent_tool_predicate)` next to `WorldModelV2Toolset`.

- [x] **Step 3: Add to analyst tools**

Add `WorldModelV21Toolset()` next to the other world-model tools in `_make_analyst`.

- [x] **Step 4: Verify registration tests pass**

Run focused pytest commands and fix only v2.1 registration issues.

### Task 5: End-to-End Verification

**Files:**
- No production code changes unless verification finds a real defect.

- [x] **Step 1: Run backend/toolset tests**

Run: `python -m pytest data_agent/test_world_model_v21.py data_agent/test_world_model_v21_routes.py data_agent/test_world_model_v21_tools.py -q --basetemp data_agent\uploads\pytest_tmp_wm_v21_toolset -p no:cacheprovider`

- [x] **Step 2: Run real-data tool-level test**

Call `_world_model_v21_plan_sync()` with Buchanan VA restoration `prepared_dir` and `ensemble_dir`, `horizon=2`, `top_k=5`, `n_episodes=1`, `continuation="greedy"`, and confirm JSON contains `status="ok"`, `steps_run=50`, `n_selected=50`, and positive `total_reward`.

- [x] **Step 3: Check local Gemma4 availability**

Query the configured local Ollama endpoints for a Gemma4:26b model. If available, run a constrained tool-calling probe using the project model gateway or the closest available local model harness; if unavailable, report the exact connectivity or model-list blocker.

- [x] **Step 4: Commit**

Commit the toolset, registration, tests, and this plan as one focused change.
