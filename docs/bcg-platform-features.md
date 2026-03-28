# BCG Platform Features - User Guide

**Version**: 15.8
**Date**: 2026-03-28

## Overview

Data Agent v15.8 adds enterprise-grade platform capabilities based on BCG's "Building Effective Enterprise Agents" framework. These features transform the system into a reusable platform for multiple deployment scenarios.

---

## 1. Prompt Registry

**Purpose**: Version control for agent prompts with environment isolation.

**Key Features**:
- Environment isolation: dev, staging, prod
- Version history with rollback capability
- DB-backed with YAML fallback

**API Endpoints**:
```bash
# List prompt versions
GET /api/prompts/versions?domain=general&env=prod

# Deploy version to environment
POST /api/prompts/deploy
{
  "version_id": 123,
  "target_env": "prod"
}
```

**Python Usage**:
```python
from data_agent.prompt_registry import PromptRegistry

registry = PromptRegistry()

# Get prompt (tries DB first, falls back to YAML)
prompt = registry.get_prompt("general", "system_prompt", env="prod")

# Create new version
version_id = registry.create_version(
    domain="general",
    prompt_key="system_prompt",
    prompt_text="Updated prompt...",
    env="dev",
    change_reason="Improved clarity"
)

# Deploy to production
registry.deploy(version_id, "prod")

# Rollback if needed
registry.rollback("general", "system_prompt", env="prod")
```

---

## 2. Model Gateway

**Purpose**: Task-aware model routing with cost optimization.

**Key Features**:
- 3 models: gemini-2.0-flash, 2.5-flash, 2.5-pro
- Automatic selection based on task type, context size, quality requirement, budget
- Cost tracking by scenario/project

**API Endpoints**:
```bash
# List available models
GET /api/gateway/models

# Get cost summary
GET /api/gateway/cost-summary?days=30
```

**Python Usage**:
```python
from data_agent.model_gateway import ModelRouter

router = ModelRouter()

# Get optimal model for task
model_name = router.route(
    task_type="qc_detection",
    context_tokens=50000,
    quality_requirement="high",
    budget_per_call_usd=0.05
)
# Returns: "gemini-2.5-flash" or "gemini-2.5-pro"
```

---

## 3. Context Manager

**Purpose**: Pluggable context providers with token budget enforcement.

**Key Features**:
- Pluggable providers (semantic layer, knowledge base, etc.)
- Token budget enforcement
- Relevance-based prioritization

**API Endpoints**:
```bash
# Preview context blocks
GET /api/context/preview?task_type=qc&step=detection
```

**Python Usage**:
```python
from data_agent.context_manager import ContextManager

manager = ContextManager()

# Prepare context for task
blocks = manager.prepare(
    task_type="qc_detection",
    step="defect_classification",
    user_context={"user_id": "user123"}
)

# blocks = [ContextBlock(source, content, relevance, tokens), ...]
```

---

## 4. Eval Scenario Framework

**Purpose**: Scenario-based evaluation with custom metrics.

**Key Features**:
- Scenario-specific metrics (e.g., defect F1 for QC)
- Golden test dataset management
- Evaluation history tracking

**API Endpoints**:
```bash
# List scenarios
GET /api/eval/scenarios

# Create dataset
POST /api/eval/datasets
{
  "scenario": "surveying_qc",
  "name": "QC Test Set v1",
  "test_cases": [...]
}

# Run evaluation
POST /api/eval/run
{
  "dataset_id": 123,
  "scenario": "surveying_qc"
}
```

**Python Usage**:
```python
from data_agent.eval_scenario import SurveyingQCScenario, EvalDatasetManager

# Create dataset
manager = EvalDatasetManager()
dataset_id = manager.create_dataset(
    scenario="surveying_qc",
    name="QC Test Set v1",
    test_cases=[
        {
            "id": "case1",
            "actual": {"defects": [{"code": "FMT-001"}]},
            "expected": {"defects": [{"code": "FMT-001"}]}
        }
    ]
)

# Run evaluation
evaluator = SurveyingQCScenario()
metrics = evaluator.evaluate(actual_output, expected_output)
# Returns: {"defect_precision": 1.0, "defect_recall": 1.0, "defect_f1": 1.0, "fix_success_rate": 0.5}
```

---

## 5. Enhanced Token Tracking

**Purpose**: Cost attribution by scenario and project.

**Python Usage**:
```python
from data_agent.token_tracker import record_usage

# Record usage with scenario/project
record_usage(
    username="user123",
    pipeline_type="governance",
    input_tokens=1000,
    output_tokens=500,
    model_name="gemini-2.5-flash",
    scenario="surveying_qc",
    project_id="pilot_project_001"
)
```

---

## 6. Enhanced Eval History

**Purpose**: Scenario-based evaluation tracking.

**Python Usage**:
```python
from data_agent.eval_history import record_eval_result

# Record evaluation with scenario
record_eval_result(
    pipeline="governance",
    overall_score=0.95,
    pass_rate=0.90,
    verdict="PASS",
    scenario="surveying_qc",
    dataset_id=123,
    metrics={"defect_f1": 0.95, "fix_success_rate": 0.85}
)
```

---

## Database Schema

**New Tables** (migrations 045-047):

1. `agent_prompt_versions` - Prompt version control
2. `agent_eval_datasets` - Golden test datasets
3. Enhanced `agent_token_usage` - Added scenario, project_id columns
4. Enhanced `agent_eval_history` - Added scenario, dataset_id, metrics columns

---

## Safety & Fallbacks

All features include fallback mechanisms:
- **Prompt Registry**: Falls back to YAML when DB unavailable
- **Model Gateway**: Falls back to tier-based selection if routing fails
- **Context Manager**: Returns empty list if providers fail
- **Eval Framework**: Graceful degradation on DB errors

All enhancements are **backward compatible** with optional parameters.

---

## Use Cases

### Surveying QC Pilot Project
- Use **Eval Scenario Framework** for defect detection metrics
- Use **Model Gateway** for cost-optimized model selection
- Use **Token Tracking** with `scenario="surveying_qc"` for cost attribution
- Use **Prompt Registry** to iterate on QC prompts in dev before prod deployment

### Multi-Project Deployment
- Use **project_id** in token tracking for per-project cost analysis
- Use **Context Manager** to inject project-specific context
- Use **Prompt Registry** environments for staging/prod isolation

---

## Next Steps

1. Run migrations: `alembic upgrade head` (or restart app to auto-apply)
2. Test API endpoints with Postman/curl
3. Create first prompt version in dev environment
4. Create evaluation dataset for your scenario
5. Monitor cost summary dashboard

For implementation details, see `docs/bcg-enterprise-agents-analysis.md` and `docs/superpowers/specs/2026-03-28-bcg-platform-enhancements-design.md`.
