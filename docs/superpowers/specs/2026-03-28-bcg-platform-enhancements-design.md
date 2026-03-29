# BCG Platform Enhancements - Design Spec

**Date**: 2026-03-28
**Status**: Draft
**Author**: Based on BCG《Building Effective Enterprise Agents》analysis
**Target**: Data Agent v15.7 → v16.0

---

## Executive Summary

This spec implements 5 BCG-recommended platform capabilities to transform Data Agent from a "测绘质检试点" into a **reusable enterprise agent platform**. All enhancements build on existing foundations rather than greenfield development.

**Scope**: Phase 1 Full (1-3 months)
- Prompt Registry (version control + environment isolation)
- Model Gateway (task-aware routing + FinOps attribution)
- Context Manager (pluggable providers + token budget)
- Enhanced Defect Taxonomy (detection methods + test cases)
- Eval Scenario Framework (scenario-based metrics)

**Out of Scope**: A/B testing, canary deployment, edge-center coordination, CV model training.

---

## Background

### BCG Analysis Key Findings

From `docs/bcg-enterprise-agents-analysis.md`:

1. **Evaluation is the #1 gap**: "没有评估体系，无法向客户证明质检准确率"
2. **Prompt management is critical**: "质检规则会频繁迭代，没有版本管理会导致'改了A坏了B'"
3. **AI Gateway enables multi-scenario**: "不同客户对成本/质量/延迟的权衡不同"
4. **Context engineering is performance lever**: "测绘质检涉及大量标准文档，需要智能注入"
5. **Scenario templates enable reuse**: "测绘质检只是第一个试点，需要可复用的平台能力"

### Existing Foundations (v15.7)

| Component | Status | Location |
|-----------|--------|----------|
| Eval history storage | ✅ Exists | `eval_history.py` (236 lines) |
| Failure-to-eval loop | ✅ Exists | `failure_to_eval.py` (134 lines) |
| Token tracking + cost | ✅ Exists | `token_tracker.py` (303 lines) |
| Defect taxonomy | ✅ Exists | `standards/defect_taxonomy.yaml` (320 lines) |
| Prompt YAML loading | ✅ Exists | `prompts/__init__.py` (48 lines) |
| Skill versioning | ✅ Exists | `agent_skill_versions` table |
| Model tier routing | ✅ Exists | `get_model_for_tier()` in agent.py |
| Semantic context | ✅ Exists | `semantic_layer.py` |
| KB context | ✅ Exists | `knowledge_base.py` |

**Key insight**: We're enhancing, not rebuilding. Reuse existing patterns (e.g., `agent_skill_versions` → `agent_prompt_versions`).

---

## Design Principles

1. **Minimal code**: Reuse existing patterns, avoid over-abstraction
2. **Backward compatible**: All changes must not break existing pipelines
3. **Database-first**: Persistent state in PostgreSQL, not in-memory
4. **Scenario-agnostic**: Platform capabilities work for any vertical (测绘/金融/制造)
5. **Fail-safe**: Graceful degradation when DB unavailable (fall back to YAML/defaults)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    User Request (app.py)                     │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
         ┌───────────────────────────────┐
         │   Context Manager (NEW)       │
         │  - Semantic Provider          │
         │  - KB Provider                │
         │  - Standards Provider         │
         │  - Case Library Provider      │
         └───────────────┬───────────────┘
                         │ context_blocks
                         ▼
         ┌───────────────────────────────┐
         │   Model Gateway (NEW)         │
         │  - Task-aware routing         │
         │  - Cost attribution           │
         └───────────────┬───────────────┘
                         │ model_name
                         ▼
         ┌───────────────────────────────┐
         │   Prompt Registry (NEW)       │
         │  - Version control            │
         │  - Environment isolation      │
         └───────────────┬───────────────┘
                         │ prompt_text
                         ▼
         ┌───────────────────────────────┐
         │   Agent Execution             │
         │  (existing pipelines)         │
         └───────────────┬───────────────┘
                         │ result
                         ▼
         ┌───────────────────────────────┐
         │   Eval Scenario (NEW)         │
         │  - Scenario-based metrics     │
         │  - Golden dataset mgmt        │
         └───────────────────────────────┘
```

---

## Component 1: Prompt Registry

### Problem Statement

**Current state**:
- Built-in prompts in `prompts/*.yaml` have `_version` metadata but no DB tracking
- User skills in `agent_custom_skills` have DB versioning via `agent_skill_versions`
- No environment isolation (dev/staging/prod all use same YAML)
- No rollback capability for built-in prompts
- No audit trail of who changed what

**BCG requirement**: "Prompt生命周期管理 — 版本控制 + 环境隔离 + A/B测试"

**Scope for v16.0**: Version control + environment isolation + rollback. A/B testing deferred to v17.0.

### Design

#### New Module: `prompt_registry.py`

```python
class PromptRegistry:
    """
    Extends prompts/__init__.py with DB-backed versioning.
    Falls back to YAML when DB unavailable.
    """

    def get_prompt(self, domain: str, key: str, env: str = "prod") -> str:
        """
        Get prompt with environment awareness.
        Priority: DB (env-specific) → YAML fallback
        """

    def create_version(self, domain: str, key: str,
                       prompt_text: str, env: str = "dev",
                       change_reason: str = "") -> int:
        """Create new version, auto-increment version number"""

    def deploy(self, version_id: int, target_env: str) -> dict:
        """Deploy version to target environment (dev→staging→prod)"""

    def rollback(self, domain: str, key: str, env: str = "prod") -> str:
        """Rollback to previous version"""

    def compare(self, version_a: int, version_b: int) -> dict:
        """Diff two versions"""
```

#### Database Schema (Migration 045)

```sql
CREATE TABLE agent_prompt_versions (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(50) NOT NULL,        -- "optimization", "governance", etc.
    prompt_key VARCHAR(100) NOT NULL,   -- "quality_check", "report_gen", etc.
    version INTEGER NOT NULL,
    environment VARCHAR(20) NOT NULL,   -- "dev", "staging", "prod"
    prompt_text TEXT NOT NULL,
    change_reason TEXT,
    created_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW(),
    deployed_at TIMESTAMP,
    is_active BOOLEAN DEFAULT false,
    UNIQUE(domain, prompt_key, environment, version)
);

CREATE INDEX idx_prompt_versions_active
ON agent_prompt_versions(domain, prompt_key, environment, is_active);
```

#### Integration Points

**1. Enhance `prompts/__init__.py`**:
```python
# Add at top
_registry = None

def get_prompt(domain: str, key: str) -> str:
    """Enhanced to check DB first, fall back to YAML"""
    global _registry
    if _registry is None:
        from .prompt_registry import PromptRegistry
        _registry = PromptRegistry()

    # Try DB first (prod environment)
    try:
        return _registry.get_prompt(domain, key, env="prod")
    except Exception:
        # Fall back to YAML
        return load_prompts(domain)[key]
```

**2. New API endpoints in `frontend_api.py`**:
```python
@app.get("/api/prompts/versions")
async def _api_prompt_versions(domain: str = None, key: str = None):
    """List prompt versions with filters"""

@app.post("/api/prompts/deploy")
async def _api_prompt_deploy(version_id: int, target_env: str):
    """Deploy prompt version to environment"""
```

#### Backward Compatibility

- Existing code calling `get_prompt(domain, key)` works unchanged
- YAML files remain source of truth for initial load
- DB unavailable → automatic fallback to YAML
- No breaking changes to agent.py or custom_skills.py

### Testing Strategy

**Unit tests** (`test_prompt_registry.py`):
- Version creation + auto-increment
- Environment isolation (dev/staging/prod)
- Rollback to previous version
- Fallback to YAML when DB unavailable

**Integration tests**:
- Deploy dev → staging → prod workflow
- Concurrent version creation (race condition)
- Agent execution with DB-backed prompts

---

## Component 2: Model Gateway

### Problem Statement

**Current state**:
- `get_model_for_tier()` uses ContextVar override or base tier
- `token_tracker.py` has MODEL_PRICING but no task-aware routing
- No per-project or per-scenario cost attribution
- No capability metadata (which models support which tasks)

**BCG requirement**: "统一AI Gateway — 模型注册表 + 智能路由 + FinOps成本归因"

### Design

#### New Module: `model_gateway.py`

```python
class ModelRegistry:
    """
    Wraps existing MODEL_TIER_MAP + MODEL_PRICING with metadata.
    """
    models = {
        "gemini-2.0-flash": {
            "tier": "fast",
            "cost_per_1k_input": 0.10,
            "cost_per_1k_output": 0.40,
            "latency_p50_ms": 800,
            "max_context_tokens": 1000000,
            "capabilities": ["classification", "extraction", "summarization"],
        },
        "gemini-2.5-flash": {
            "tier": "standard",
            "cost_per_1k_input": 0.15,
            "cost_per_1k_output": 0.60,
            "latency_p50_ms": 1200,
            "max_context_tokens": 2000000,
            "capabilities": ["reasoning", "analysis", "generation"],
        },
        "gemini-2.5-pro": {
            "tier": "premium",
            "cost_per_1k_input": 1.25,
            "cost_per_1k_output": 5.00,
            "latency_p50_ms": 2500,
            "max_context_tokens": 2000000,
            "capabilities": ["complex_reasoning", "planning", "coding"],
        },
    }

class ModelRouter:
    """
    Task-aware model selection.
    """
    def route(self, task_type: str, context_tokens: int = 0,
              quality_requirement: str = "standard",
              budget_per_call_usd: float = None) -> str:
        """
        Select optimal model based on:
        1. Task type → capability match
        2. Context size → max_context_tokens filter
        3. Quality requirement → tier preference
        4. Budget constraint → cost filter

        Returns: model_name
        """
```

#### Database Enhancement (Migration 046)

```sql
-- Add columns to existing agent_token_usage table
ALTER TABLE agent_token_usage
ADD COLUMN IF NOT EXISTS scenario VARCHAR(100),
ADD COLUMN IF NOT EXISTS project_id VARCHAR(100),
ADD COLUMN IF NOT EXISTS task_type VARCHAR(50);

CREATE INDEX IF NOT EXISTS idx_token_usage_scenario
ON agent_token_usage(scenario, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_token_usage_project
ON agent_token_usage(project_id, created_at DESC);
```

#### Integration Points

**1. Enhance `agent.py` `get_model_for_tier()`**:
```python
def get_model_for_tier(base_tier: str = "standard",
                       task_type: str = None,
                       context_tokens: int = 0):
    """Enhanced with task-aware routing"""
    from .user_context import current_model_tier
    from .model_gateway import ModelRouter

    tier = current_model_tier.get() or base_tier

    # If task_type provided, use smart routing
    if task_type:
        router = ModelRouter()
        model_name = router.route(
            task_type=task_type,
            context_tokens=context_tokens,
            quality_requirement=tier
        )
    else:
        # Fallback to existing tier map
        model_name = MODEL_TIER_MAP.get(tier, MODEL_STANDARD)

    return _create_model_with_retry(model_name)
```

**2. Enhance `token_tracker.py` `record_usage()`**:
```python
def record_usage(username: str, pipeline_type: str,
                 input_tokens: int, output_tokens: int,
                 model_name: str,
                 scenario: str = None,      # NEW
                 project_id: str = None,    # NEW
                 task_type: str = None):    # NEW
    """Enhanced with scenario/project attribution"""
```

**3. New API endpoints**:
```python
@app.get("/api/gateway/models")
async def _api_gateway_models():
    """List available models with metadata"""

@app.get("/api/gateway/cost-summary")
async def _api_gateway_cost_summary(
    scenario: str = None,
    project_id: str = None,
    days: int = 30
):
    """Cost breakdown by scenario/project"""
```

### Testing Strategy

**Unit tests** (`test_model_gateway.py`):
- ModelRouter.route() with various constraints
- Cost calculation with scenario attribution
- Capability matching (task_type → model selection)

**Integration tests**:
- End-to-end: request → route → execute → record cost
- Cost summary API with scenario filters

---

## Component 3: Context Manager

### Problem Statement

**Current state**:
- Context injection is ad-hoc: `resolve_semantic_context()`, KB search, inline standard loading
- No centralized token budget control
- No pluggable provider architecture
- No scenario-aware context selection

**BCG requirement**: "上下文工程 — 动态注入 + 压缩策略 + Token预算控制"

### Design

#### New Module: `context_manager.py`

```python
@dataclass
class ContextBlock:
    """Single unit of context"""
    source: str              # "semantic_layer", "kb", "standards", "cases"
    content: str
    token_count: int
    relevance_score: float   # 0.0-1.0
    compressible: bool = True

class ContextProvider(ABC):
    """Base class for context providers"""
    @abstractmethod
    def get_context(self, task_type: str, step: str,
                    user_context: dict) -> list[ContextBlock]:
        pass

class SemanticProvider(ContextProvider):
    """Wraps existing semantic_layer.py"""
    def get_context(self, task_type, step, user_context):
        from .semantic_layer import resolve_semantic_context
        semantic = resolve_semantic_context(user_context.get("query", ""))
        return [ContextBlock(
            source="semantic_layer",
            content=json.dumps(semantic, ensure_ascii=False),
            token_count=len(semantic) // 4,  # rough estimate
            relevance_score=1.0,
            compressible=False
        )]

class KBProvider(ContextProvider):
    """Wraps existing knowledge_base.py search"""
    def get_context(self, task_type, step, user_context):
        from .knowledge_base import search_kb
        query = user_context.get("query", "")
        kb_name = user_context.get("kb_name", "default")
        results = search_kb(query, kb_name, top_k=5)
        return [ContextBlock(
            source="kb",
            content=r["content"],
            token_count=len(r["content"]) // 4,
            relevance_score=r["score"],
            compressible=True
        ) for r in results]

class StandardsProvider(ContextProvider):
    """Loads defect taxonomy / QC standards"""
    def get_context(self, task_type, step, user_context):
        if task_type == "surveying_qc" and step == "data_audit":
            from .standard_registry import load_standard
            taxonomy = load_standard("defect_taxonomy")
            return [ContextBlock(
                source="standards",
                content=yaml.dump(taxonomy, allow_unicode=True),
                token_count=len(str(taxonomy)) // 4,
                relevance_score=1.0,
                compressible=False
            )]
        return []

class CaseLibraryProvider(ContextProvider):
    """Loads relevant QC cases from KB"""
    def get_context(self, task_type, step, user_context):
        if task_type == "surveying_qc":
            from .knowledge_base import search_cases
            product_type = user_context.get("product_type", "DLG")
            cases = search_cases(product_type=product_type, limit=3)
            return [ContextBlock(
                source="case_library",
                content=format_case(c),
                token_count=len(format_case(c)) // 4,
                relevance_score=0.8,
                compressible=True
            ) for c in cases]
        return []

class ContextManager:
    """Orchestrates all providers with token budget"""
    def __init__(self, max_tokens: int = 100000):
        self.max_tokens = max_tokens
        self.providers = {}

    def register_provider(self, name: str, provider: ContextProvider):
        self.providers[name] = provider

    def prepare(self, task_type: str, step: str,
                user_context: dict) -> list[ContextBlock]:
        """
        Collect context from all providers, sort by relevance,
        enforce token budget.
        """
        candidates = []
        for name, provider in self.providers.items():
            blocks = provider.get_context(task_type, step, user_context)
            candidates.extend(blocks)

        # Sort by relevance
        candidates.sort(key=lambda b: b.relevance_score, reverse=True)

        # Greedy selection within budget
        selected = []
        budget = self.max_tokens
        for block in candidates:
            if block.token_count <= budget:
                selected.append(block)
                budget -= block.token_count

        return selected

    def format_context(self, blocks: list[ContextBlock]) -> str:
        """Format blocks into prompt-ready text"""
        sections = []
        for block in blocks:
            sections.append(f"[{block.source}]\n{block.content}\n")
        return "\n".join(sections)
```

#### Integration Points

**1. Enhance `app.py` before pipeline dispatch**:
```python
# Around line 2790 (before pipeline execution)
from .context_manager import ContextManager, SemanticProvider, KBProvider

context_mgr = ContextManager(max_tokens=100000)
context_mgr.register_provider("semantic", SemanticProvider())
context_mgr.register_provider("kb", KBProvider())

# Prepare context
context_blocks = context_mgr.prepare(
    task_type="surveying_qc",  # from intent classification
    step="data_audit",
    user_context={"query": user_text, "product_type": "DLG"}
)
context_prefix = context_mgr.format_context(context_blocks)

# Inject into agent instruction (prepend to existing prompt)
```

**2. New API endpoint**:
```python
@app.get("/api/context/preview")
async def _api_context_preview(
    task_type: str,
    step: str,
    query: str
):
    """Preview context blocks for debugging"""
```

#### No Migration Needed

Context manager is stateless — no new DB tables.

### Testing Strategy

**Unit tests** (`test_context_manager.py`):
- Token budget enforcement
- Relevance-based sorting
- Provider registration
- Greedy selection algorithm

**Integration tests**:
- End-to-end with real semantic_layer + KB
- Token count accuracy

---

## Component 4: Enhanced Defect Taxonomy

### Problem Statement

**Current state**:
- `defect_taxonomy.yaml` has `auto_fixable` + `fix_strategy`
- Missing: `detection_method`, `test_cases`, `frequency`

**BCG requirement**: "缺陷分类法深度集成 — 检测方法 + 评估用例 + 频率数据"

### Design

#### Enhance `standards/defect_taxonomy.yaml`

Add 3 new fields per defect:

```yaml
defects:
  - code: FMT-001
    category: format_error
    severity: B
    name: 坐标系定义错误
    product_types: [CAD, DLG, DEM, DOM, vector, 3D_MODEL]
    auto_fixable: true
    fix_strategy: crs_auto_detect_and_set
    # === NEW FIELDS ===
    detection_method: rule              # rule | cv_model | llm | hybrid
    detection_config:
      type: crs_mismatch
      check: "data.crs != project.crs"
    frequency: high                     # high | medium | low | rare
    test_cases:
      - id: FMT_001_TC01
        description: "EPSG:4326数据混入EPSG:3857项目"
        input_file: "fixtures/fmt_001_case1.shp"
        expected_detection: true
        expected_fix: true
```

#### Enhance `standard_registry.py`

```python
@dataclass
class DefectType:
    code: str
    category: str
    severity: str
    name: str
    product_types: list[str]
    auto_fixable: bool = False
    fix_strategy: str = ""
    # NEW
    detection_method: str = "rule"
    detection_config: dict = None
    frequency: str = "medium"
    test_cases: list[dict] = None

class DefectTaxonomy:
    def get_by_detection_method(self, method: str) -> list[DefectType]:
        """Filter defects by detection method"""

    def get_high_frequency(self) -> list[DefectType]:
        """Get high-frequency defects for prioritization"""

    def get_test_cases(self, defect_code: str) -> list[dict]:
        """Get evaluation test cases for a defect"""
```

#### Integration Points

**1. Context Manager integration**:
```python
class StandardsProvider(ContextProvider):
    def get_context(self, task_type, step, user_context):
        if step == "data_audit":
            # Only inject defects with available detection methods
            available_tools = user_context.get("available_tools", [])
            if "cv-service-mcp" in available_tools:
                methods = ["rule", "cv_model"]
            else:
                methods = ["rule"]

            taxonomy = DefectTaxonomy()
            relevant_defects = [
                d for d in taxonomy.defects
                if d.detection_method in methods
            ]
            return [ContextBlock(...)]
```

**2. Eval Scenario integration** (see Component 5):
```python
class SurveyingQCScenario:
    def load_test_cases(self):
        """Load test cases from taxonomy"""
        taxonomy = DefectTaxonomy()
        all_cases = []
        for defect in taxonomy.defects:
            all_cases.extend(defect.test_cases or [])
        return all_cases
```

#### No Migration Needed

Taxonomy is YAML-based, no DB changes.

### Testing Strategy

**Unit tests**:
- YAML parsing with new fields
- Filter by detection_method
- Test case extraction

**Integration tests**:
- Context injection with method filtering
- Eval scenario test case loading

---

## Component 5: Eval Scenario Framework

### Problem Statement

**Current state**:
- `evals/` has 4 pipeline-based test suites (optimization, governance, general, planner)
- `eval_history.py` stores results but no scenario dimension
- No QC-specific metrics (defect F1, fix success rate)
- No golden dataset management API

**BCG requirement**: "场景化评估 — 按场景组织测试集 + 场景特定指标"

### Design

#### New Module: `eval_scenario.py`

```python
class EvalScenario(ABC):
    """Base class for scenario-specific evaluation"""
    scenario: str = "base"

    @abstractmethod
    def evaluate(self, actual_output: dict, expected_output: dict) -> dict:
        """
        Returns: {"metric_name": float, ...}
        """
        pass

class SurveyingQCScenario(EvalScenario):
    """测绘质检评估场景"""
    scenario = "surveying_qc"

    def evaluate(self, actual_output, expected_output):
        """
        Metrics:
        - defect_precision: TP / (TP + FP)
        - defect_recall: TP / (TP + FN)
        - defect_f1: 2 * P * R / (P + R)
        - fix_success_rate: fixed / fixable
        """
        actual_defects = set(d["code"] for d in actual_output.get("defects", []))
        expected_defects = set(d["code"] for d in expected_output.get("defects", []))

        tp = len(actual_defects & expected_defects)
        fp = len(actual_defects - expected_defects)
        fn = len(expected_defects - actual_defects)

        precision = tp / (tp + fp) if (tp + fp) else 0
        recall = tp / (tp + fn) if (tp + fn) else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

        # Fix success rate
        fixed = len([d for d in actual_output.get("defects", []) if d.get("fixed")])
        fixable = len([d for d in expected_output.get("defects", []) if d.get("auto_fixable")])
        fix_rate = fixed / fixable if fixable else 0

        return {
            "defect_precision": round(precision, 3),
            "defect_recall": round(recall, 3),
            "defect_f1": round(f1, 3),
            "fix_success_rate": round(fix_rate, 3),
        }

class EvalDatasetManager:
    """Manage golden test datasets per scenario"""

    def create_dataset(self, scenario: str, name: str,
                       test_cases: list[dict]) -> int:
        """Create new dataset, returns dataset_id"""

    def get_dataset(self, dataset_id: int) -> dict:
        """Load dataset with all test cases"""

    def list_datasets(self, scenario: str = None) -> list[dict]:
        """List available datasets"""

    def add_test_case(self, dataset_id: int, test_case: dict):
        """Append test case to existing dataset"""
```

#### Database Schema (Migration 047)

```sql
CREATE TABLE agent_eval_datasets (
    id SERIAL PRIMARY KEY,
    scenario VARCHAR(100) NOT NULL,
    name VARCHAR(200) NOT NULL,
    version VARCHAR(50) DEFAULT '1.0',
    description TEXT,
    test_cases JSONB NOT NULL,
    created_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(scenario, name, version)
);

CREATE INDEX idx_eval_datasets_scenario
ON agent_eval_datasets(scenario);

-- Enhance existing agent_eval_history table
ALTER TABLE agent_eval_history
ADD COLUMN IF NOT EXISTS scenario VARCHAR(100),
ADD COLUMN IF NOT EXISTS dataset_id INTEGER REFERENCES agent_eval_datasets(id);
```

#### Integration Points

**1. Enhance `eval_history.py`**:
```python
def record_eval_result(
    pipeline: str,
    overall_score: float,
    pass_rate: float,
    verdict: str,
    scenario: str = None,        # NEW
    dataset_id: int = None,      # NEW
    metrics: dict = None,        # NEW (scenario-specific metrics)
    ...
):
    """Enhanced with scenario support"""
```

**2. Integrate with `failure_to_eval.py`**:
```python
def convert_failure_to_testcase(
    user_query: str,
    expected_tool: str = "",
    failure_description: str = "",
    pipeline: str = "general",
    scenario: str = None,        # NEW
):
    """Scenario-tagged test case generation"""
```

**3. New API endpoints**:
```python
@app.post("/api/eval/datasets")
async def _api_eval_dataset_create(
    scenario: str,
    name: str,
    test_cases: list[dict]
):
    """Create evaluation dataset"""

@app.post("/api/eval/run")
async def _api_eval_run(
    dataset_id: int,
    agent_config: dict = None
):
    """Execute evaluation run"""

@app.get("/api/eval/scenarios")
async def _api_eval_scenarios():
    """List available evaluation scenarios"""
```

### Testing Strategy

**Unit tests** (`test_eval_scenario.py`):
- SurveyingQCScenario.evaluate() with various inputs
- Defect F1 calculation edge cases
- Dataset CRUD operations

**Integration tests**:
- End-to-end eval run with golden dataset
- Scenario-specific metrics in eval_history

---

## Implementation Plan

### Phase 1: Foundation (Week 1-2)

**Week 1**: Prompt Registry + Model Gateway
- Migration 045 (prompt_versions table)
- Migration 046 (token_usage enhancements)
- `prompt_registry.py` (~150 lines)
- `model_gateway.py` (~200 lines)
- Enhance `prompts/__init__.py`, `token_tracker.py`, `agent.py`
- 4 new API endpoints
- Unit tests

**Week 2**: Context Manager
- `context_manager.py` (~250 lines)
- 4 provider implementations
- Integrate into `app.py`
- 1 new API endpoint
- Unit tests

### Phase 2: Scenario Support (Week 3-4)

**Week 3**: Enhanced Defect Taxonomy
- Update `standards/defect_taxonomy.yaml` (add 3 fields × 30 defects)
- Enhance `standard_registry.py` DefectType dataclass
- Add query methods
- Unit tests

**Week 4**: Eval Scenario Framework
- Migration 047 (eval_datasets table)
- `eval_scenario.py` (~200 lines)
- Enhance `eval_history.py`
- 3 new API endpoints
- Unit tests

### Phase 3: Integration & Testing (Week 5-6)

**Week 5**: Integration
- Wire all components together
- Frontend updates (4 new tabs/sections)
- End-to-end testing

**Week 6**: Documentation & Polish
- Update CLAUDE.md
- API documentation
- Migration guide
- Performance testing

---

## Success Metrics

### Technical Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Prompt version control coverage | 100% of built-in prompts | Count in agent_prompt_versions |
| Model routing accuracy | >90% task-capability match | Manual review of 100 requests |
| Context token budget adherence | <5% over-budget cases | Monitor context_manager logs |
| Eval scenario coverage | 1 scenario (surveying_qc) | Count in agent_eval_datasets |
| Test case count | ≥50 golden cases | Count in eval_datasets |

### Business Metrics (Post-deployment)

| Metric | Target | Timeline |
|--------|--------|----------|
| 测绘质检 defect F1 | ≥0.75 | 1 month after deployment |
| Cost per QC task | <$0.50 USD | Ongoing via model_gateway |
| Prompt iteration velocity | 2x faster (rollback enabled) | 2 months |
| New scenario onboarding time | <2 weeks | Next scenario pilot |

---

## Risk Mitigation

### Risk 1: Database Migration Failures

**Mitigation**:
- All migrations use `IF NOT EXISTS` (idempotent)
- Test migrations on staging DB first
- Rollback scripts prepared

### Risk 2: Backward Compatibility Breaks

**Mitigation**:
- All enhancements are additive (no breaking changes)
- Fallback mechanisms (DB unavailable → YAML)
- Comprehensive integration tests

### Risk 3: Performance Degradation

**Mitigation**:
- Context manager token budget prevents runaway context
- Model gateway caches routing decisions
- Prompt registry uses indexed queries

### Risk 4: Complexity Creep

**Mitigation**:
- Strict scope: no A/B testing, no canary deployment in v16.0
- Reuse existing patterns (e.g., agent_skill_versions → agent_prompt_versions)
- Code review for over-abstraction

---

## Open Questions

1. **Context compression strategy**: Should we implement LLM-based summarization for compressible blocks, or defer to v17.0?
   - **Recommendation**: Defer. Use simple truncation for v16.0.

2. **Prompt approval workflow**: Should built-in prompts require approval like custom skills?
   - **Recommendation**: No. Built-in prompts are code-level changes (require git commit). Only user skills need approval.

3. **Model gateway fallback**: What happens if optimal model is unavailable (quota exceeded)?
   - **Recommendation**: Fall back to next-best model in same tier, log warning.

4. **Eval dataset versioning**: Should datasets have versions like prompts?
   - **Recommendation**: Yes, but simple (version string in table, no separate versions table).

---

## Appendix A: File Manifest

### New Files (4 modules + 4 tests)

```
data_agent/
├── prompt_registry.py          (~150 lines)
├── model_gateway.py            (~200 lines)
├── context_manager.py          (~250 lines)
├── eval_scenario.py            (~200 lines)
├── test_prompt_registry.py     (~100 lines)
├── test_model_gateway.py       (~100 lines)
├── test_context_manager.py     (~100 lines)
└── test_eval_scenario.py       (~100 lines)
```

### Modified Files (7 files)

```
data_agent/
├── prompts/__init__.py         (+20 lines)
├── token_tracker.py            (+30 lines)
├── agent.py                    (+15 lines)
├── eval_history.py             (+20 lines)
├── standard_registry.py        (+30 lines)
├── app.py                      (+40 lines)
└── frontend_api.py             (+150 lines, 8 endpoints)

standards/
└── defect_taxonomy.yaml        (+90 lines, 3 fields × 30 defects)
```

### Migrations (3 files)

```
data_agent/migrations/
├── 045_prompt_registry.sql
├── 046_model_gateway.sql
└── 047_eval_scenarios.sql
```

### Total LOC Estimate

- New code: ~1,200 lines
- Modified code: ~305 lines
- Tests: ~400 lines
- **Total: ~1,900 lines**

---

## Appendix B: API Endpoints Summary

| Endpoint | Method | Purpose | Component |
|----------|--------|---------|-----------|
| `/api/prompts/versions` | GET | List prompt versions | Prompt Registry |
| `/api/prompts/deploy` | POST | Deploy prompt to env | Prompt Registry |
| `/api/gateway/models` | GET | List models + metadata | Model Gateway |
| `/api/gateway/cost-summary` | GET | Cost by scenario/project | Model Gateway |
| `/api/context/preview` | GET | Preview context blocks | Context Manager |
| `/api/eval/datasets` | POST | Create eval dataset | Eval Scenario |
| `/api/eval/run` | POST | Execute eval run | Eval Scenario |
| `/api/eval/scenarios` | GET | List scenarios | Eval Scenario |

**Total**: 8 new endpoints

---

## Appendix C: Database Schema Summary

### New Tables (2)

1. `agent_prompt_versions` (Migration 045)
   - Stores prompt version history per environment
   - ~10 columns, 2 indexes

2. `agent_eval_datasets` (Migration 047)
   - Stores golden test datasets per scenario
   - ~8 columns, 1 index

### Enhanced Tables (2)

1. `agent_token_usage` (Migration 046)
   - Add: `scenario`, `project_id`, `task_type`
   - Add: 2 indexes

2. `agent_eval_history` (Migration 047)
   - Add: `scenario`, `dataset_id`, `metrics`
   - No new indexes (existing index sufficient)

---

**End of Design Spec**

**Next Steps**:
1. Review this spec
2. Approve or request changes
3. Proceed to implementation plan (writing-plans skill)

