# Qwen3.6 Harness Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the CQ full-mode NL2Semantic2SQL harness family-aware for Qwen3.6 so Qwen is compared after a dedicated harness pass instead of only under the Gemma-tuned path.

**Architecture:** Keep baseline unchanged. Reuse the existing direct NL2Semantic2SQL workflow for local Ollama families, but make its family selection, prompt wording, correction tags, and benchmark direct-path gate aware of Qwen. Add deterministic postprocessing for malformed semicolon tails that appeared in Qwen outputs.

**Tech Stack:** Python, pytest, LiteLLM/Ollama, existing `data_agent` NL2SQL modules.

---

### Task 1: Direct Path Gate

**Files:**
- Modify: `scripts/nl2sql_bench_cq/run_cq_eval.py`
- Test: `data_agent/test_nl2sql_cq_eval_gemma.py`

- [x] Add a failing test proving Qwen family/model uses the direct NL2Semantic2SQL path.
- [x] Update `_should_use_direct_full_path()` to include Qwen local Ollama models.
- [x] Run the focused CQ eval harness tests.

### Task 2: Family-Aware Direct Harness

**Files:**
- Modify: `data_agent/nl2sql_executor.py`
- Test: `data_agent/test_nl2sql_executor.py`

- [x] Add failing tests proving `run_nl2semantic2sql()` passes the active family to `build_nl2sql_context()`.
- [x] Add a Qwen-specific prompt test checking for stricter SQL-only, geometry-column, geography-predicate, and refusal instructions.
- [x] Generalize Gemma-named helper internals without breaking existing Gemma tests.

### Task 3: Qwen Semicolon Tail Repair

**Files:**
- Modify: `data_agent/sql_postprocessor.py`
- Test: `data_agent/test_sql_postprocessor.py`

- [x] Add failing tests for `LIMIT ...; AND ...` and `; WHERE ...` malformed tails.
- [x] Strip invalid trailing clauses before parsing and record a correction tag.
- [x] Run focused postprocessor tests.

### Task 4: Verification and Smoke

**Files:**
- Use existing runner: `family13_qwen36_35b_host228_runner.py`

- [x] Run focused unit tests for changed modules.
- [x] Run a targeted Qwen full smoke on representative failed CQ questions.
- [x] If smoke improves or is neutral with fewer invalid SQL failures, run full Qwen full-mode benchmark on host228.
