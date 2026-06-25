# TWM Spatial Policy Rule Derivation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `to_spatial_policy_rule` so standards-platform versions can generate disabled, review-required TWM policy-rule candidates.

**Architecture:** Implement one focused derivation strategy under `data_agent/standards_platform/derivation/strategies/`. It reads bound standard data elements, applies conservative spatial-policy heuristics, inserts TWM rule artifacts, and records `std_derived_link` lineage. A small migration widens the link target-kind CHECK constraint.

**Tech Stack:** Python, SQLAlchemy text SQL, PostgreSQL JSONB, existing standards-platform derivation runner, pytest.

---

## Files

- Create: `data_agent/standards_platform/derivation/strategies/spatial_policy_rule.py`
- Create: `data_agent/standards_platform/tests/test_spatial_policy_rule_strategy.py`
- Create: `data_agent/migrations/091_twm_spatial_policy_rule_derivation.sql`
- Modify: `data_agent/standards_platform/derivation/runner.py`
- Modify: `data_agent/standards_platform/tests/test_derivation_runner.py`

## Task 1: RED Tests

- [ ] **Step 1: Add focused failing strategy tests**

Create `data_agent/standards_platform/tests/test_spatial_policy_rule_strategy.py` with tests for active runner status, candidate creation, non-spatial skip, and re-run stale behavior.

- [ ] **Step 2: Update runner status expectation**

Update `test_get_strategy_status_lists_six` to expect seven active strategies, including `to_spatial_policy_rule`.

- [ ] **Step 3: Run RED verification**

Run:

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj /Users/zhouning/gisdataagent/.venv/bin/pytest -q data_agent/standards_platform/tests/test_spatial_policy_rule_strategy.py data_agent/standards_platform/tests/test_derivation_runner.py::test_get_strategy_status_lists_six
```

Expected: fails because `spatial_policy_rule.py` and runner registration do not exist yet.

## Task 2: Schema Widening

- [ ] **Step 1: Add migration 091**

Create `data_agent/migrations/091_twm_spatial_policy_rule_derivation.sql` that drops and recreates `std_derived_link_target_kind_check`, preserving existing values and adding `spatial_policy_rule`.

- [ ] **Step 2: Verify migration syntax**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m compileall -q data_agent/standards_platform/derivation
```

Expected: exit code 0.

## Task 3: Strategy Implementation

- [ ] **Step 1: Implement `SpatialPolicyRuleStrategy`**

Create a strategy class with `name = "to_spatial_policy_rule"` and a `run(version_id, by_user)` method. It must:

- load document metadata;
- select bound `std_data_element` rows;
- filter candidates using conservative role and geometry heuristics;
- ensure one draft `twm_rule_set` per source version;
- insert one disabled `twm_policy_rule` per candidate;
- insert active `std_derived_link` rows;
- stale previous active links for the same document and strategy.

- [ ] **Step 2: Register strategy**

Modify `runner.py` to import and register `SpatialPolicyRuleStrategy`, and add a UI description.

- [ ] **Step 3: Run GREEN verification**

Run:

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj /Users/zhouning/gisdataagent/.venv/bin/pytest -q data_agent/standards_platform/tests/test_spatial_policy_rule_strategy.py data_agent/standards_platform/tests/test_derivation_runner.py::test_get_strategy_status_lists_six
```

Expected: all targeted tests pass.

## Task 4: Regression Check

- [ ] **Step 1: Run nearby derivation tests**

Run:

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj /Users/zhouning/gisdataagent/.venv/bin/pytest -q data_agent/standards_platform/tests/test_derivation_runner.py data_agent/standards_platform/tests/test_data_model_strategy.py data_agent/standards_platform/tests/test_qc_rule_strategy.py
```

Expected: pass or skip only for unavailable DB.

- [ ] **Step 2: Inspect git diff**

Run:

```bash
git diff -- data_agent/standards_platform/derivation data_agent/standards_platform/tests data_agent/migrations docs/superpowers/specs/2026-06-23-twm-spatial-policy-rule-derivation-design.md docs/superpowers/plans/2026-06-23-twm-spatial-policy-rule-derivation.md
```

Expected: scoped changes only; pre-existing docx change remains untouched.
