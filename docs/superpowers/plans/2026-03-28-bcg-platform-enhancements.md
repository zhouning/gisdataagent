# BCG Platform Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 5 BCG-recommended platform capabilities (Prompt Registry, Model Gateway, Context Manager, Enhanced Taxonomy, Eval Scenarios) to transform Data Agent into a reusable enterprise platform.

**Architecture:** Build on existing foundations (eval_history.py, token_tracker.py, prompts/__init__.py, defect_taxonomy.yaml). All enhancements are additive with fallback mechanisms. No breaking changes.

**Tech Stack:** Python 3.13, PostgreSQL 16, SQLAlchemy, existing ADK agents

**Safety Strategy:**
- All DB migrations use `IF NOT EXISTS` (idempotent)
- All new modules have fallback to existing behavior
- Comprehensive tests before integration
- Frequent commits with rollback points

---

## File Structure

### New Files (8 total)
```
data_agent/
├── prompt_registry.py              # Prompt version control (150 lines)
├── model_gateway.py                # Task-aware model routing (200 lines)
├── context_manager.py              # Pluggable context providers (250 lines)
├── eval_scenario.py                # Scenario-based evaluation (200 lines)
├── test_prompt_registry.py         # Unit tests (100 lines)
├── test_model_gateway.py           # Unit tests (100 lines)
├── test_context_manager.py         # Unit tests (100 lines)
└── test_eval_scenario.py           # Unit tests (100 lines)
```

### Modified Files (7 total)
```
data_agent/
├── prompts/__init__.py             # Add DB fallback (+20 lines)
├── token_tracker.py                # Add scenario/project columns (+30 lines)
├── agent.py                        # Enhance get_model_for_tier (+15 lines)
├── eval_history.py                 # Add scenario support (+20 lines)
├── standard_registry.py            # Add detection_method queries (+30 lines)
├── app.py                          # Integrate context_manager (+40 lines)
└── frontend_api.py                 # Add 8 new endpoints (+150 lines)

standards/
└── defect_taxonomy.yaml            # Add 3 fields per defect (+90 lines)
```

### Migrations (3 files)
```
data_agent/migrations/
├── 045_prompt_registry.sql
├── 046_model_gateway.sql
└── 047_eval_scenarios.sql
```

---

## Phase 1: Database Migrations (Safe Foundation)

### Task 1: Migration 045 - Prompt Registry Table

**Files:**
- Create: `data_agent/migrations/045_prompt_registry.sql`

- [ ] **Step 1: Write migration SQL**

```sql
-- Migration 045: Prompt Registry
-- Adds version control for built-in agent prompts

CREATE TABLE IF NOT EXISTS agent_prompt_versions (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(50) NOT NULL,
    prompt_key VARCHAR(100) NOT NULL,
    version INTEGER NOT NULL,
    environment VARCHAR(20) NOT NULL DEFAULT 'prod',
    prompt_text TEXT NOT NULL,
    change_reason TEXT,
    created_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW(),
    deployed_at TIMESTAMP,
    is_active BOOLEAN DEFAULT false,
    CONSTRAINT unique_prompt_version UNIQUE(domain, prompt_key, environment, version)
);

CREATE INDEX IF NOT EXISTS idx_prompt_versions_active
ON agent_prompt_versions(domain, prompt_key, environment, is_active)
WHERE is_active = true;

COMMENT ON TABLE agent_prompt_versions IS 'Version control for built-in agent prompts with environment isolation';
```

- [ ] **Step 2: Test migration locally**

Run:
```bash
cd D:/adk
.venv/Scripts/python.exe -c "
from data_agent.db_engine import get_engine
from sqlalchemy import text
engine = get_engine()
with open('data_agent/migrations/045_prompt_registry.sql') as f:
    sql = f.read()
with engine.connect() as conn:
    conn.execute(text(sql))
    conn.commit()
    result = conn.execute(text(\"SELECT COUNT(*) FROM agent_prompt_versions\"))
    print(f'Table created, row count: {result.scalar()}')
"
```

Expected: "Table created, row count: 0"

- [ ] **Step 3: Verify table structure**

Run:
```bash
.venv/Scripts/python.exe -c "
from data_agent.db_engine import get_engine
from sqlalchemy import text
engine = get_engine()
with engine.connect() as conn:
    result = conn.execute(text(\"\"\"
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'agent_prompt_versions'
        ORDER BY ordinal_position
    \"\"\"))
    for row in result:
        print(f'{row[0]}: {row[1]}')
"
```

Expected: List of 11 columns (id, domain, prompt_key, version, environment, prompt_text, change_reason, created_by, created_at, deployed_at, is_active)

- [ ] **Step 4: Commit migration**

```bash
git add data_agent/migrations/045_prompt_registry.sql
git commit -m "feat: add prompt_versions table for version control"
```

---

### Task 2: Migration 046 - Model Gateway Enhancements

**Files:**
- Create: `data_agent/migrations/046_model_gateway.sql`

- [ ] **Step 1: Write migration SQL**

```sql
-- Migration 046: Model Gateway
-- Adds scenario/project attribution to token usage

ALTER TABLE agent_token_usage
ADD COLUMN IF NOT EXISTS scenario VARCHAR(100),
ADD COLUMN IF NOT EXISTS project_id VARCHAR(100),
ADD COLUMN IF NOT EXISTS task_type VARCHAR(50);

CREATE INDEX IF NOT EXISTS idx_token_usage_scenario
ON agent_token_usage(scenario, created_at DESC)
WHERE scenario IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_token_usage_project
ON agent_token_usage(project_id, created_at DESC)
WHERE project_id IS NOT NULL;

COMMENT ON COLUMN agent_token_usage.scenario IS 'Scenario identifier (e.g., surveying_qc, finance_audit)';
COMMENT ON COLUMN agent_token_usage.project_id IS 'Project identifier for cost attribution';
COMMENT ON COLUMN agent_token_usage.task_type IS 'Task type for routing analysis';
```

- [ ] **Step 2: Test migration locally**

Run:
```bash
.venv/Scripts/python.exe -c "
from data_agent.db_engine import get_engine
from sqlalchemy import text
engine = get_engine()
with open('data_agent/migrations/046_model_gateway.sql') as f:
    sql = f.read()
with engine.connect() as conn:
    conn.execute(text(sql))
    conn.commit()
    result = conn.execute(text(\"\"\"
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'agent_token_usage'
        AND column_name IN ('scenario', 'project_id', 'task_type')
    \"\"\"))
    cols = [row[0] for row in result]
    print(f'Added columns: {cols}')
"
```

Expected: "Added columns: ['scenario', 'project_id', 'task_type']"

- [ ] **Step 3: Verify backward compatibility**

Run:
```bash
.venv/Scripts/python.exe -c "
from data_agent.token_tracker import record_usage
# Test old signature still works
record_usage('test_user', 'optimization', 1000, 500, 'gemini-2.5-flash')
print('Old signature works')
"
```

Expected: "Old signature works" (no errors)

- [ ] **Step 4: Commit migration**

```bash
git add data_agent/migrations/046_model_gateway.sql
git commit -m "feat: add scenario/project columns to token_usage"
```

---

### Task 3: Migration 047 - Eval Scenarios Table

**Files:**
- Create: `data_agent/migrations/047_eval_scenarios.sql`

- [ ] **Step 1: Write migration SQL**

```sql
-- Migration 047: Eval Scenarios
-- Adds scenario-based evaluation datasets

CREATE TABLE IF NOT EXISTS agent_eval_datasets (
    id SERIAL PRIMARY KEY,
    scenario VARCHAR(100) NOT NULL,
    name VARCHAR(200) NOT NULL,
    version VARCHAR(50) DEFAULT '1.0',
    description TEXT,
    test_cases JSONB NOT NULL,
    created_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT unique_dataset UNIQUE(scenario, name, version)
);

CREATE INDEX IF NOT EXISTS idx_eval_datasets_scenario
ON agent_eval_datasets(scenario);

-- Enhance existing eval_history table
ALTER TABLE agent_eval_history
ADD COLUMN IF NOT EXISTS scenario VARCHAR(100),
ADD COLUMN IF NOT EXISTS dataset_id INTEGER REFERENCES agent_eval_datasets(id),
ADD COLUMN IF NOT EXISTS metrics JSONB;

COMMENT ON TABLE agent_eval_datasets IS 'Golden test datasets per scenario';
COMMENT ON COLUMN agent_eval_history.scenario IS 'Scenario identifier for scenario-specific evaluation';
COMMENT ON COLUMN agent_eval_history.metrics IS 'Scenario-specific metrics (e.g., defect_f1, fix_success_rate)';
```

- [ ] **Step 2: Test migration locally**

Run:
```bash
.venv/Scripts/python.exe -c "
from data_agent.db_engine import get_engine
from sqlalchemy import text
engine = get_engine()
with open('data_agent/migrations/047_eval_scenarios.sql') as f:
    sql = f.read()
with engine.connect() as conn:
    conn.execute(text(sql))
    conn.commit()
    # Verify new table
    result = conn.execute(text('SELECT COUNT(*) FROM agent_eval_datasets'))
    print(f'Datasets table: {result.scalar()} rows')
    # Verify enhanced columns
    result = conn.execute(text(\"\"\"
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'agent_eval_history'
        AND column_name IN ('scenario', 'dataset_id', 'metrics')
    \"\"\"))
    cols = [row[0] for row in result]
    print(f'Enhanced eval_history: {cols}')
"
```

Expected: "Datasets table: 0 rows" and "Enhanced eval_history: ['scenario', 'dataset_id', 'metrics']"

- [ ] **Step 3: Verify backward compatibility**

Run:
```bash
.venv/Scripts/python.exe -c "
from data_agent.eval_history import record_eval_result
# Test old signature still works
record_eval_result('general', 0.85, 0.90, 'PASS', num_tests=10, num_passed=9)
print('Old signature works')
"
```

Expected: "Old signature works"

- [ ] **Step 4: Commit migration**

```bash
git add data_agent/migrations/047_eval_scenarios.sql
git commit -m "feat: add eval_datasets table and enhance eval_history"
```

---

## Phase 2: Core Modules (Isolated, Testable)

### Task 4: Prompt Registry Module

**Files:**
- Create: `data_agent/prompt_registry.py`
- Create: `data_agent/test_prompt_registry.py`

- [ ] **Step 1: Write failing test for get_prompt with DB fallback**

```python
# data_agent/test_prompt_registry.py
import pytest
from unittest.mock import patch, MagicMock
from data_agent.prompt_registry import PromptRegistry

def test_get_prompt_db_unavailable_falls_back_to_yaml():
    """When DB unavailable, should fall back to YAML"""
    registry = PromptRegistry()

    # Mock DB to raise exception
    with patch('data_agent.prompt_registry.get_engine', return_value=None):
        # Should fall back to YAML (via prompts/__init__.py)
        with patch('data_agent.prompts.load_prompts') as mock_load:
            mock_load.return_value = {"test_key": "test prompt from yaml"}
            result = registry.get_prompt("general", "test_key", env="prod")
            assert result == "test prompt from yaml"
            mock_load.assert_called_once_with("general")

def test_get_prompt_from_db_when_available():
    """When DB available and has active version, use DB"""
    registry = PromptRegistry()

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = ("prompt from db",)
    mock_conn.execute.return_value = mock_result
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch('data_agent.prompt_registry.get_engine', return_value=mock_engine):
        result = registry.get_prompt("general", "test_key", env="prod")
        assert result == "prompt from db"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest data_agent/test_prompt_registry.py::test_get_prompt_db_unavailable_falls_back_to_yaml -v`

Expected: FAIL with "ModuleNotFoundError: No module named 'data_agent.prompt_registry'"

- [ ] **Step 3: Write minimal PromptRegistry implementation**

```python
# data_agent/prompt_registry.py
"""
Prompt Registry - Version control for built-in agent prompts.
Extends prompts/__init__.py with DB-backed versioning.
Falls back to YAML when DB unavailable.
"""
from sqlalchemy import text
from .db_engine import get_engine
from .observability import get_logger

logger = get_logger("prompt_registry")

class PromptRegistry:
    """Manages prompt versions with environment isolation"""

    def get_prompt(self, domain: str, prompt_key: str, env: str = "prod") -> str:
        """
        Get prompt with environment awareness.
        Priority: DB (env-specific) → YAML fallback
        """
        engine = get_engine()
        if engine:
            try:
                with engine.connect() as conn:
                    result = conn.execute(text("""
                        SELECT prompt_text FROM agent_prompt_versions
                        WHERE domain = :domain
                          AND prompt_key = :key
                          AND environment = :env
                          AND is_active = true
                        LIMIT 1
                    """), {"domain": domain, "key": prompt_key, "env": env})
                    row = result.fetchone()
                    if row:
                        logger.debug(f"Loaded prompt {domain}.{prompt_key} from DB ({env})")
                        return row[0]
            except Exception as e:
                logger.warning(f"DB prompt load failed, falling back to YAML: {e}")

        # Fallback to YAML
        from . import prompts
        return prompts.load_prompts(domain)[prompt_key]

    def create_version(self, domain: str, prompt_key: str, prompt_text: str,
                       env: str = "dev", change_reason: str = "",
                       created_by: str = "system") -> int:
        """Create new version, auto-increment version number"""
        engine = get_engine()
        if not engine:
            raise RuntimeError("Database not available")

        with engine.connect() as conn:
            # Get next version number
            result = conn.execute(text("""
                SELECT COALESCE(MAX(version), 0) + 1
                FROM agent_prompt_versions
                WHERE domain = :domain AND prompt_key = :key AND environment = :env
            """), {"domain": domain, "key": prompt_key, "env": env})
            next_version = result.scalar()

            # Insert new version
            result = conn.execute(text("""
                INSERT INTO agent_prompt_versions
                (domain, prompt_key, version, environment, prompt_text, change_reason, created_by)
                VALUES (:domain, :key, :ver, :env, :text, :reason, :by)
                RETURNING id
            """), {
                "domain": domain, "key": prompt_key, "ver": next_version,
                "env": env, "text": prompt_text, "reason": change_reason, "by": created_by
            })
            conn.commit()
            version_id = result.scalar()
            logger.info(f"Created prompt version {domain}.{prompt_key} v{next_version} ({env})")
            return version_id

    def deploy(self, version_id: int, target_env: str) -> dict:
        """Deploy version to target environment"""
        engine = get_engine()
        if not engine:
            raise RuntimeError("Database not available")

        with engine.connect() as conn:
            # Get version details
            result = conn.execute(text("""
                SELECT domain, prompt_key, version, prompt_text
                FROM agent_prompt_versions WHERE id = :id
            """), {"id": version_id})
            row = result.fetchone()
            if not row:
                raise ValueError(f"Version {version_id} not found")

            domain, prompt_key, version, prompt_text = row

            # Deactivate current active version in target env
            conn.execute(text("""
                UPDATE agent_prompt_versions
                SET is_active = false
                WHERE domain = :domain AND prompt_key = :key
                  AND environment = :env AND is_active = true
            """), {"domain": domain, "key": prompt_key, "env": target_env})

            # Check if version already exists in target env
            result = conn.execute(text("""
                SELECT id FROM agent_prompt_versions
                WHERE domain = :domain AND prompt_key = :key
                  AND environment = :env AND version = :ver
            """), {"domain": domain, "key": prompt_key, "env": target_env, "ver": version})
            existing = result.fetchone()

            if existing:
                # Activate existing version
                conn.execute(text("""
                    UPDATE agent_prompt_versions
                    SET is_active = true, deployed_at = NOW()
                    WHERE id = :id
                """), {"id": existing[0]})
                new_id = existing[0]
            else:
                # Create new version in target env
                result = conn.execute(text("""
                    INSERT INTO agent_prompt_versions
                    (domain, prompt_key, version, environment, prompt_text, is_active, deployed_at)
                    VALUES (:domain, :key, :ver, :env, :text, true, NOW())
                    RETURNING id
                """), {
                    "domain": domain, "key": prompt_key, "ver": version,
                    "env": target_env, "text": prompt_text
                })
                new_id = result.scalar()

            conn.commit()
            logger.info(f"Deployed {domain}.{prompt_key} v{version} to {target_env}")
            return {"version_id": new_id, "environment": target_env}

    def rollback(self, domain: str, prompt_key: str, env: str = "prod") -> str:
        """Rollback to previous version"""
        engine = get_engine()
        if not engine:
            raise RuntimeError("Database not available")

        with engine.connect() as conn:
            # Get previous version
            result = conn.execute(text("""
                SELECT id, version FROM agent_prompt_versions
                WHERE domain = :domain AND prompt_key = :key AND environment = :env
                  AND is_active = false
                ORDER BY version DESC LIMIT 1
            """), {"domain": domain, "key": prompt_key, "env": env})
            row = result.fetchone()
            if not row:
                raise ValueError(f"No previous version found for {domain}.{prompt_key} in {env}")

            prev_id, prev_version = row

            # Deactivate current
            conn.execute(text("""
                UPDATE agent_prompt_versions
                SET is_active = false
                WHERE domain = :domain AND prompt_key = :key
                  AND environment = :env AND is_active = true
            """), {"domain": domain, "key": prompt_key, "env": env})

            # Activate previous
            conn.execute(text("""
                UPDATE agent_prompt_versions
                SET is_active = true, deployed_at = NOW()
                WHERE id = :id
            """), {"id": prev_id})

            conn.commit()
            logger.info(f"Rolled back {domain}.{prompt_key} to v{prev_version} in {env}")
            return f"v{prev_version}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest data_agent/test_prompt_registry.py -v`

Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add data_agent/prompt_registry.py data_agent/test_prompt_registry.py
git commit -m "feat: add PromptRegistry with DB fallback"
```

---

### Task 5: Model Gateway Module

**Files:**
- Create: `data_agent/model_gateway.py`
- Create: `data_agent/test_model_gateway.py`

- [ ] **Step 1: Write minimal ModelRegistry and ModelRouter**

```python
# data_agent/model_gateway.py
"""
Model Gateway - Task-aware model routing with cost attribution.
Extends existing MODEL_TIER_MAP with capability metadata.
"""
from .observability import get_logger

logger = get_logger("model_gateway")

class ModelRegistry:
    """Registry of available models with metadata"""

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
            "capabilities": ["reasoning", "analysis", "generation", "classification"],
        },
        "gemini-2.5-pro": {
            "tier": "premium",
            "cost_per_1k_input": 1.25,
            "cost_per_1k_output": 5.00,
            "latency_p50_ms": 2500,
            "max_context_tokens": 2000000,
            "capabilities": ["complex_reasoning", "planning", "coding", "analysis"],
        },
    }

    @classmethod
    def get_model_info(cls, model_name: str) -> dict:
        """Get model metadata"""
        return cls.models.get(model_name, {})

    @classmethod
    def list_models(cls) -> list[dict]:
        """List all models with metadata"""
        return [{"name": k, **v} for k, v in cls.models.items()]


class ModelRouter:
    """Task-aware model selection"""

    def route(self, task_type: str = None, context_tokens: int = 0,
              quality_requirement: str = "standard",
              budget_per_call_usd: float = None) -> str:
        """
        Select optimal model based on constraints.
        Returns: model_name
        """
        candidates = list(ModelRegistry.models.keys())

        # Filter by context size
        if context_tokens > 0:
            candidates = [
                m for m in candidates
                if ModelRegistry.models[m]["max_context_tokens"] >= context_tokens
            ]

        # Filter by capability
        if task_type:
            candidates = [
                m for m in candidates
                if task_type in ModelRegistry.models[m]["capabilities"]
            ]

        # Filter by budget
        if budget_per_call_usd:
            # Estimate tokens (rough: 1 call ≈ 2000 input + 500 output)
            candidates = [
                m for m in candidates
                if self._estimate_cost(m, 2000, 500) <= budget_per_call_usd
            ]

        if not candidates:
            logger.warning("No models match constraints, falling back to standard")
            return "gemini-2.5-flash"

        # Select by quality tier
        tier_preference = {"fast": 0, "standard": 1, "premium": 2}
        target_tier = tier_preference.get(quality_requirement, 1)

        # Find closest tier
        best = min(candidates, key=lambda m: abs(
            tier_preference.get(ModelRegistry.models[m]["tier"], 1) - target_tier
        ))

        logger.info(f"Routed to {best} (task={task_type}, quality={quality_requirement})")
        return best

    def _estimate_cost(self, model_name: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost for a model"""
        info = ModelRegistry.models[model_name]
        return (input_tokens * info["cost_per_1k_input"] +
                output_tokens * info["cost_per_1k_output"]) / 1000
```

- [ ] **Step 2: Write tests**

```python
# data_agent/test_model_gateway.py
import pytest
from data_agent.model_gateway import ModelRegistry, ModelRouter

def test_model_registry_list():
    models = ModelRegistry.list_models()
    assert len(models) == 3
    assert any(m["name"] == "gemini-2.5-flash" for m in models)

def test_router_task_capability_match():
    router = ModelRouter()
    # "classification" is in flash and standard, not pro
    result = router.route(task_type="classification", quality_requirement="fast")
    assert result == "gemini-2.0-flash"

def test_router_context_size_filter():
    router = ModelRouter()
    # All models support 1M tokens
    result = router.route(context_tokens=500000, quality_requirement="standard")
    assert result == "gemini-2.5-flash"

def test_router_fallback_when_no_match():
    router = ModelRouter()
    # Non-existent capability
    result = router.route(task_type="nonexistent_capability")
    assert result == "gemini-2.5-flash"  # fallback
```

- [ ] **Step 3: Run tests**

Run: `.venv/Scripts/python.exe -m pytest data_agent/test_model_gateway.py -v`

Expected: 4 PASS

- [ ] **Step 4: Commit**

```bash
git add data_agent/model_gateway.py data_agent/test_model_gateway.py
git commit -m "feat: add ModelGateway with task-aware routing"
```

---

### Task 6: Context Manager Module

**Files:**
- Create: `data_agent/context_manager.py`
- Create: `data_agent/test_context_manager.py`

- [ ] **Step 1: Write minimal ContextManager with providers**

```python
# data_agent/context_manager.py
"""
Context Manager - Pluggable context providers with token budget.
Orchestrates semantic layer, KB, standards, and case library.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from .observability import get_logger

logger = get_logger("context_manager")

@dataclass
class ContextBlock:
    """Single unit of context"""
    source: str
    content: str
    token_count: int
    relevance_score: float
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
        try:
            from .semantic_layer import resolve_semantic_context
            import json
            query = user_context.get("query", "")
            if not query:
                return []
            semantic = resolve_semantic_context(query)
            content = json.dumps(semantic, ensure_ascii=False)
            return [ContextBlock(
                source="semantic_layer",
                content=content,
                token_count=len(content) // 4,
                relevance_score=1.0,
                compressible=False
            )]
        except Exception as e:
            logger.warning(f"SemanticProvider failed: {e}")
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
            try:
                blocks = provider.get_context(task_type, step, user_context)
                candidates.extend(blocks)
            except Exception as e:
                logger.warning(f"Provider {name} failed: {e}")

        # Sort by relevance
        candidates.sort(key=lambda b: b.relevance_score, reverse=True)

        # Greedy selection within budget
        selected = []
        budget = self.max_tokens
        for block in candidates:
            if block.token_count <= budget:
                selected.append(block)
                budget -= block.token_count

        logger.info(f"Selected {len(selected)} context blocks, {self.max_tokens - budget} tokens")
        return selected

    def format_context(self, blocks: list[ContextBlock]) -> str:
        """Format blocks into prompt-ready text"""
        if not blocks:
            return ""
        sections = []
        for block in blocks:
            sections.append(f"[{block.source}]\n{block.content}\n")
        return "\n".join(sections)
```

- [ ] **Step 2: Write tests**

```python
# data_agent/test_context_manager.py
import pytest
from data_agent.context_manager import ContextManager, ContextBlock, ContextProvider

class MockProvider(ContextProvider):
    def __init__(self, blocks):
        self.blocks = blocks

    def get_context(self, task_type, step, user_context):
        return self.blocks

def test_context_manager_token_budget():
    mgr = ContextManager(max_tokens=100)
    mgr.register_provider("mock", MockProvider([
        ContextBlock("source1", "a" * 200, 50, 1.0),
        ContextBlock("source2", "b" * 200, 40, 0.9),
        ContextBlock("source3", "c" * 200, 30, 0.8),
    ]))

    selected = mgr.prepare("test", "step1", {})
    # Should select first 2 blocks (50 + 40 = 90 < 100)
    assert len(selected) == 2
    assert selected[0].source == "source1"
    assert selected[1].source == "source2"

def test_context_manager_relevance_sort():
    mgr = ContextManager(max_tokens=1000)
    mgr.register_provider("mock", MockProvider([
        ContextBlock("low", "content", 10, 0.5),
        ContextBlock("high", "content", 10, 0.9),
        ContextBlock("medium", "content", 10, 0.7),
    ]))

    selected = mgr.prepare("test", "step1", {})
    # Should be sorted by relevance
    assert selected[0].source == "high"
    assert selected[1].source == "medium"
    assert selected[2].source == "low"

def test_context_manager_format():
    mgr = ContextManager()
    blocks = [
        ContextBlock("source1", "content1", 10, 1.0),
        ContextBlock("source2", "content2", 10, 0.9),
    ]
    formatted = mgr.format_context(blocks)
    assert "[source1]" in formatted
    assert "content1" in formatted
    assert "[source2]" in formatted
```

- [ ] **Step 3: Run tests**

Run: `.venv/Scripts/python.exe -m pytest data_agent/test_context_manager.py -v`

Expected: 3 PASS

- [ ] **Step 4: Commit**

```bash
git add data_agent/context_manager.py data_agent/test_context_manager.py
git commit -m "feat: add ContextManager with pluggable providers"
```

---

### Task 7: Eval Scenario Module

**Files:**
- Create: `data_agent/eval_scenario.py`
- Create: `data_agent/test_eval_scenario.py`

- [ ] **Step 1: Write minimal EvalScenario base + SurveyingQC**

```python
# data_agent/eval_scenario.py
"""
Eval Scenario Framework - Scenario-based evaluation with custom metrics.
"""
from abc import ABC, abstractmethod
from sqlalchemy import text
from .db_engine import get_engine
from .observability import get_logger

logger = get_logger("eval_scenario")


class EvalScenario(ABC):
    """Base class for scenario-specific evaluation"""
    scenario: str = "base"

    @abstractmethod
    def evaluate(self, actual_output: dict, expected_output: dict) -> dict:
        """Returns: {"metric_name": float, ...}"""
        pass


class SurveyingQCScenario(EvalScenario):
    """测绘质检评估场景"""
    scenario = "surveying_qc"

    def evaluate(self, actual_output, expected_output):
        """
        Metrics:
        - defect_precision, defect_recall, defect_f1
        - fix_success_rate
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
                       test_cases: list[dict], version: str = "1.0",
                       description: str = "", created_by: str = "system") -> int:
        """Create new dataset, returns dataset_id"""
        engine = get_engine()
        if not engine:
            raise RuntimeError("Database not available")

        import json
        with engine.connect() as conn:
            result = conn.execute(text("""
                INSERT INTO agent_eval_datasets
                (scenario, name, version, description, test_cases, created_by)
                VALUES (:scenario, :name, :ver, :desc, :cases, :by)
                RETURNING id
            """), {
                "scenario": scenario, "name": name, "ver": version,
                "desc": description, "cases": json.dumps(test_cases),
                "by": created_by
            })
            conn.commit()
            dataset_id = result.scalar()
            logger.info(f"Created dataset {name} ({scenario}) with {len(test_cases)} cases")
            return dataset_id

    def get_dataset(self, dataset_id: int) -> dict:
        """Load dataset with all test cases"""
        engine = get_engine()
        if not engine:
            raise RuntimeError("Database not available")

        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT scenario, name, version, description, test_cases, created_at
                FROM agent_eval_datasets WHERE id = :id
            """), {"id": dataset_id})
            row = result.fetchone()
            if not row:
                raise ValueError(f"Dataset {dataset_id} not found")

            import json
            return {
                "id": dataset_id,
                "scenario": row[0],
                "name": row[1],
                "version": row[2],
                "description": row[3],
                "test_cases": json.loads(row[4]),
                "created_at": row[5].isoformat() if row[5] else None,
            }

    def list_datasets(self, scenario: str = None) -> list[dict]:
        """List available datasets"""
        engine = get_engine()
        if not engine:
            return []

        with engine.connect() as conn:
            if scenario:
                result = conn.execute(text("""
                    SELECT id, scenario, name, version, created_at
                    FROM agent_eval_datasets
                    WHERE scenario = :scenario
                    ORDER BY created_at DESC
                """), {"scenario": scenario})
            else:
                result = conn.execute(text("""
                    SELECT id, scenario, name, version, created_at
                    FROM agent_eval_datasets
                    ORDER BY created_at DESC
                """))

            return [{
                "id": r[0], "scenario": r[1], "name": r[2],
                "version": r[3],
                "created_at": r[4].isoformat() if r[4] else None,
            } for r in result]
```

- [ ] **Step 2: Write tests**

```python
# data_agent/test_eval_scenario.py
import pytest
from data_agent.eval_scenario import SurveyingQCScenario

def test_surveying_qc_perfect_match():
    scenario = SurveyingQCScenario()
    actual = {"defects": [{"code": "FMT-001"}, {"code": "PRE-002"}]}
    expected = {"defects": [{"code": "FMT-001"}, {"code": "PRE-002"}]}

    metrics = scenario.evaluate(actual, expected)
    assert metrics["defect_precision"] == 1.0
    assert metrics["defect_recall"] == 1.0
    assert metrics["defect_f1"] == 1.0

def test_surveying_qc_partial_match():
    scenario = SurveyingQCScenario()
    actual = {"defects": [{"code": "FMT-001"}, {"code": "FMT-999"}]}  # 1 correct, 1 false positive
    expected = {"defects": [{"code": "FMT-001"}, {"code": "PRE-002"}]}  # 1 missed

    metrics = scenario.evaluate(actual, expected)
    # TP=1, FP=1, FN=1
    # Precision = 1/2 = 0.5, Recall = 1/2 = 0.5, F1 = 0.5
    assert metrics["defect_precision"] == 0.5
    assert metrics["defect_recall"] == 0.5
    assert metrics["defect_f1"] == 0.5

def test_surveying_qc_fix_success_rate():
    scenario = SurveyingQCScenario()
    actual = {"defects": [
        {"code": "FMT-001", "fixed": True},
        {"code": "PRE-002", "fixed": False},
    ]}
    expected = {"defects": [
        {"code": "FMT-001", "auto_fixable": True},
        {"code": "PRE-002", "auto_fixable": True},
    ]}

    metrics = scenario.evaluate(actual, expected)
    # 1 fixed out of 2 fixable = 0.5
    assert metrics["fix_success_rate"] == 0.5
```

- [ ] **Step 3: Run tests**

Run: `.venv/Scripts/python.exe -m pytest data_agent/test_eval_scenario.py -v`

Expected: 3 PASS

- [ ] **Step 4: Commit**

```bash
git add data_agent/eval_scenario.py data_agent/test_eval_scenario.py
git commit -m "feat: add EvalScenario framework with SurveyingQC"
```

---

## Phase 3: Integration (Wire Everything Together)

### Task 8: Enhance Existing Modules

**Files to modify:**
- `data_agent/prompts/__init__.py`
- `data_agent/token_tracker.py`
- `data_agent/agent.py`
- `data_agent/eval_history.py`
- `data_agent/standard_registry.py`

- [ ] **Step 1: Enhance prompts/__init__.py with DB fallback**

Add at top of `data_agent/prompts/__init__.py`:

```python
_registry = None

def get_prompt(domain: str, key: str) -> str:
    """Enhanced to check DB first, fall back to YAML"""
    global _registry
    if _registry is None:
        try:
            from .prompt_registry import PromptRegistry
            _registry = PromptRegistry()
        except Exception:
            _registry = False  # Mark as unavailable

    # Try DB first if available
    if _registry:
        try:
            return _registry.get_prompt(domain, key, env="prod")
        except Exception:
            pass  # Fall through to YAML

    # Fall back to YAML
    return load_prompts(domain)[key]
```

- [ ] **Step 2: Enhance token_tracker.py record_usage signature**

Modify `record_usage()` in `data_agent/token_tracker.py`:

```python
def record_usage(username: str, pipeline_type: str,
                 input_tokens: int, output_tokens: int,
                 model_name: str,
                 scenario: str = None,      # NEW
                 project_id: str = None,    # NEW
                 task_type: str = None):    # NEW
    """Enhanced with scenario/project attribution"""
    # ... existing code ...
    # In INSERT statement, add new columns:
    conn.execute(text(f"""
        INSERT INTO {T_TOKEN_USAGE}
        (username, pipeline_type, model_name, input_tokens, output_tokens, total_tokens,
         scenario, project_id, task_type)
        VALUES (:u, :p, :m, :i, :o, :t, :s, :proj, :task)
    """), {
        "u": username, "p": pipeline_type, "m": model_name,
        "i": input_tokens, "o": output_tokens, "t": total_tokens,
        "s": scenario, "proj": project_id, "task": task_type
    })
```

- [ ] **Step 3: Enhance agent.py get_model_for_tier**

Modify `get_model_for_tier()` in `data_agent/agent.py`:

```python
def get_model_for_tier(base_tier: str = "standard",
                       task_type: str = None,
                       context_tokens: int = 0):
    """Enhanced with task-aware routing"""
    from .user_context import current_model_tier

    tier = current_model_tier.get() or base_tier

    # If task_type provided, use smart routing
    if task_type:
        try:
            from .model_gateway import ModelRouter
            router = ModelRouter()
            model_name = router.route(
                task_type=task_type,
                context_tokens=context_tokens,
                quality_requirement=tier
            )
        except Exception:
            # Fallback to tier map
            model_name = MODEL_TIER_MAP.get(tier, MODEL_STANDARD)
    else:
        model_name = MODEL_TIER_MAP.get(tier, MODEL_STANDARD)

    return _create_model_with_retry(model_name)
```

- [ ] **Step 4: Enhance eval_history.py record_eval_result**

Modify `record_eval_result()` in `data_agent/eval_history.py`:

```python
def record_eval_result(
    pipeline: str,
    overall_score: float,
    pass_rate: float,
    verdict: str,
    num_tests: int = 0,
    num_passed: int = 0,
    model: str = "",
    details: dict = None,
    run_id: str = None,
    scenario: str = None,        # NEW
    dataset_id: int = None,      # NEW
    metrics: dict = None,        # NEW
) -> Optional[int]:
    """Enhanced with scenario support"""
    # ... existing code ...
    # In INSERT statement, add new columns:
    result = conn.execute(text(f"""
        INSERT INTO {T_EVAL_HISTORY}
        (run_id, pipeline, model, git_commit, git_branch,
         overall_score, pass_rate, verdict, num_tests, num_passed, details,
         scenario, dataset_id, metrics)
        VALUES (:rid, :p, :m, :gc, :gb, :score, :pr, :v, :nt, :np, :d,
                :scenario, :dataset_id, :metrics)
        RETURNING id
    """), {
        # ... existing params ...
        "scenario": scenario,
        "dataset_id": dataset_id,
        "metrics": json.dumps(metrics or {}, default=str),
    })
```

- [ ] **Step 5: Test all enhancements don't break existing code**

Run full test suite:
```bash
.venv/Scripts/python.exe -m pytest data_agent/ --ignore=data_agent/test_knowledge_agent.py -q
```

Expected: All existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add data_agent/prompts/__init__.py data_agent/token_tracker.py data_agent/agent.py data_agent/eval_history.py
git commit -m "feat: integrate new modules into existing code"
```

---

### Task 9: Add API Endpoints

**Files:**
- Modify: `data_agent/frontend_api.py`

- [ ] **Step 1: Add 8 new endpoints (minimal implementation)**

Add to `data_agent/frontend_api.py`:

```python
# === Prompt Registry Endpoints ===
@app.get("/api/prompts/versions")
async def _api_prompt_versions(domain: str = None, key: str = None):
    """List prompt versions"""
    from .prompt_registry import PromptRegistry
    from .db_engine import get_engine
    from sqlalchemy import text

    engine = get_engine()
    if not engine:
        return {"error": "Database unavailable"}

    with engine.connect() as conn:
        if domain and key:
            result = conn.execute(text("""
                SELECT id, domain, prompt_key, version, environment, is_active, created_at
                FROM agent_prompt_versions
                WHERE domain = :d AND prompt_key = :k
                ORDER BY version DESC
            """), {"d": domain, "k": key})
        else:
            result = conn.execute(text("""
                SELECT id, domain, prompt_key, version, environment, is_active, created_at
                FROM agent_prompt_versions
                ORDER BY created_at DESC LIMIT 50
            """))

        return {"versions": [{
            "id": r[0], "domain": r[1], "prompt_key": r[2],
            "version": r[3], "environment": r[4], "is_active": r[5],
            "created_at": r[6].isoformat() if r[6] else None
        } for r in result]}

@app.post("/api/prompts/deploy")
async def _api_prompt_deploy(version_id: int, target_env: str):
    """Deploy prompt version to environment"""
    from .prompt_registry import PromptRegistry
    registry = PromptRegistry()
    try:
        result = registry.deploy(version_id, target_env)
        return {"status": "success", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# === Model Gateway Endpoints ===
@app.get("/api/gateway/models")
async def _api_gateway_models():
    """List available models with metadata"""
    from .model_gateway import ModelRegistry
    return {"models": ModelRegistry.list_models()}

@app.get("/api/gateway/cost-summary")
async def _api_gateway_cost_summary(scenario: str = None, project_id: str = None, days: int = 30):
    """Cost breakdown by scenario/project"""
    from .db_engine import get_engine
    from sqlalchemy import text

    engine = get_engine()
    if not engine:
        return {"error": "Database unavailable"}

    with engine.connect() as conn:
        filters = []
        params = {"days": days}

        if scenario:
            filters.append("scenario = :scenario")
            params["scenario"] = scenario
        if project_id:
            filters.append("project_id = :project_id")
            params["project_id"] = project_id

        where_clause = " AND " + " AND ".join(filters) if filters else ""

        result = conn.execute(text(f"""
            SELECT
                scenario,
                project_id,
                model_name,
                COUNT(*) as call_count,
                SUM(input_tokens) as total_input,
                SUM(output_tokens) as total_output
            FROM agent_token_usage
            WHERE created_at >= NOW() - make_interval(days => :days)
            {where_clause}
            GROUP BY scenario, project_id, model_name
            ORDER BY call_count DESC
        """), params)

        from .token_tracker import calculate_cost_usd
        summary = []
        for r in result:
            cost = calculate_cost_usd(r[3], r[4], r[2])
            summary.append({
                "scenario": r[0], "project_id": r[1], "model_name": r[2],
                "call_count": r[3], "total_input": r[3], "total_output": r[4],
                "cost_usd": cost
            })

        return {"summary": summary}

# === Context Manager Endpoint ===
@app.get("/api/context/preview")
async def _api_context_preview(task_type: str, step: str, query: str):
    """Preview context blocks for debugging"""
    from .context_manager import ContextManager, SemanticProvider

    mgr = ContextManager(max_tokens=100000)
    mgr.register_provider("semantic", SemanticProvider())

    blocks = mgr.prepare(task_type, step, {"query": query})

    return {
        "blocks": [{
            "source": b.source,
            "token_count": b.token_count,
            "relevance_score": b.relevance_score,
            "content_preview": b.content[:200] + "..." if len(b.content) > 200 else b.content
        } for b in blocks],
        "total_tokens": sum(b.token_count for b in blocks)
    }

# === Eval Scenario Endpoints ===
@app.post("/api/eval/datasets")
async def _api_eval_dataset_create(scenario: str, name: str, test_cases: list[dict]):
    """Create evaluation dataset"""
    from .eval_scenario import EvalDatasetManager
    mgr = EvalDatasetManager()
    try:
        dataset_id = mgr.create_dataset(scenario, name, test_cases)
        return {"status": "success", "dataset_id": dataset_id}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/eval/run")
async def _api_eval_run(dataset_id: int):
    """Execute evaluation run (placeholder)"""
    from .eval_scenario import EvalDatasetManager
    mgr = EvalDatasetManager()
    try:
        dataset = mgr.get_dataset(dataset_id)
        # TODO: Actual eval execution in future PR
        return {
            "status": "success",
            "message": f"Eval run queued for dataset {dataset['name']}",
            "test_case_count": len(dataset["test_cases"])
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/eval/scenarios")
async def _api_eval_scenarios():
    """List available evaluation scenarios"""
    return {
        "scenarios": [
            {"id": "surveying_qc", "name": "测绘质检", "metrics": ["defect_f1", "fix_success_rate"]},
            {"id": "general", "name": "通用场景", "metrics": ["accuracy", "latency"]},
        ]
    }
```

- [ ] **Step 2: Test endpoints manually**

Start server:
```bash
$env:PYTHONPATH="D:\adk"
chainlit run data_agent/app.py
```

Test with curl:
```bash
# Test models endpoint
curl http://localhost:8000/api/gateway/models

# Test scenarios endpoint
curl http://localhost:8000/api/eval/scenarios
```

- [ ] **Step 3: Commit**

```bash
git add data_agent/frontend_api.py
git commit -m "feat: add 8 new API endpoints for platform features"
```

---

### Task 10: Enhance Defect Taxonomy

**Files:**
- Modify: `data_agent/standards/defect_taxonomy.yaml`
- Modify: `data_agent/standard_registry.py`

- [ ] **Step 1: Add 3 new fields to first 5 defects in taxonomy YAML**

Edit `data_agent/standards/defect_taxonomy.yaml`, add to FMT-001 through FMT-005:

```yaml
  - code: FMT-001
    # ... existing fields ...
    # === NEW FIELDS ===
    detection_method: rule
    detection_config:
      type: crs_mismatch
      check: "data.crs != project.crs"
    frequency: high
```

(Repeat for FMT-002 through FMT-005 with appropriate values)

- [ ] **Step 2: Enhance DefectType dataclass in standard_registry.py**

Add to `data_agent/standard_registry.py`:

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
```

Add query methods to DefectTaxonomy class:

```python
class DefectTaxonomy:
    # ... existing methods ...

    def get_by_detection_method(self, method: str) -> list[DefectType]:
        """Filter defects by detection method"""
        return [d for d in self.defects if d.detection_method == method]

    def get_high_frequency(self) -> list[DefectType]:
        """Get high-frequency defects for prioritization"""
        return [d for d in self.defects if d.frequency == "high"]
```

- [ ] **Step 3: Test taxonomy loading**

Run:
```bash
.venv/Scripts/python.exe -c "
from data_agent.standard_registry import load_standard
taxonomy = load_standard('defect_taxonomy')
print(f'Loaded {len(taxonomy.get('defects', []))} defects')
first = taxonomy['defects'][0]
print(f'First defect has detection_method: {first.get('detection_method', 'MISSING')}')
"
```

Expected: "Loaded 30 defects" and "First defect has detection_method: rule"

- [ ] **Step 4: Commit**

```bash
git add data_agent/standards/defect_taxonomy.yaml data_agent/standard_registry.py
git commit -m "feat: enhance defect taxonomy with detection_method and frequency"
```

---

## Phase 4: Documentation & Validation

### Task 11: Update Documentation

**Files:**
- Modify: `CLAUDE.md`
- Create: `docs/bcg-platform-features.md`

- [ ] **Step 1: Update CLAUDE.md with new modules**

Add to CLAUDE.md under "Key Modules" section:

```markdown
| `prompt_registry.py` | Prompt version control with environment isolation | NEW v16.0 |
| `model_gateway.py` | Task-aware model routing + FinOps attribution | NEW v16.0 |
| `context_manager.py` | Pluggable context providers with token budget | NEW v16.0 |
| `eval_scenario.py` | Scenario-based evaluation framework | NEW v16.0 |
```

- [ ] **Step 2: Create feature documentation**

Create `docs/bcg-platform-features.md` with usage examples (keep minimal, ~100 lines)

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/bcg-platform-features.md
git commit -m "docs: add BCG platform features documentation"
```

---

### Task 12: Final Integration Test

- [ ] **Step 1: Run full test suite**

```bash
.venv/Scripts/python.exe -m pytest data_agent/ --ignore=data_agent/test_knowledge_agent.py -v
```

Expected: All tests pass (including 12 new tests)

- [ ] **Step 2: Test migrations are idempotent**

Run migrations twice:
```bash
.venv/Scripts/python.exe -c "
from data_agent.db_engine import get_engine
from sqlalchemy import text
engine = get_engine()
for migration in ['045_prompt_registry.sql', '046_model_gateway.sql', '047_eval_scenarios.sql']:
    with open(f'data_agent/migrations/{migration}') as f:
        sql = f.read()
    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()
    print(f'{migration} applied successfully')
"
```

Run again (should not error):
```bash
# Same command - should succeed with no errors
```

- [ ] **Step 3: Smoke test new endpoints**

```bash
# Start server
$env:PYTHONPATH="D:\adk"
chainlit run data_agent/app.py

# In another terminal, test all 8 endpoints
curl http://localhost:8000/api/gateway/models
curl http://localhost:8000/api/eval/scenarios
curl http://localhost:8000/api/prompts/versions
# ... etc
```

- [ ] **Step 4: Create final commit**

```bash
git add -A
git commit -m "feat: BCG platform enhancements v16.0 complete

- Prompt Registry: version control + environment isolation
- Model Gateway: task-aware routing + FinOps attribution
- Context Manager: pluggable providers + token budget
- Enhanced Defect Taxonomy: detection methods + frequency
- Eval Scenario Framework: scenario-based metrics

Total: 4 new modules, 3 migrations, 8 API endpoints, 12 tests
"
```

---

## Success Criteria

- [ ] All 3 migrations applied successfully
- [ ] All 12 new tests pass
- [ ] All existing tests still pass (no regressions)
- [ ] 8 new API endpoints respond correctly
- [ ] Documentation updated
- [ ] No breaking changes to existing code

---

## Rollback Plan

If anything breaks:

1. **Rollback migrations**:
```sql
DROP TABLE IF EXISTS agent_prompt_versions;
DROP TABLE IF EXISTS agent_eval_datasets;
ALTER TABLE agent_token_usage DROP COLUMN IF EXISTS scenario;
ALTER TABLE agent_token_usage DROP COLUMN IF EXISTS project_id;
ALTER TABLE agent_token_usage DROP COLUMN IF EXISTS task_type;
ALTER TABLE agent_eval_history DROP COLUMN IF EXISTS scenario;
ALTER TABLE agent_eval_history DROP COLUMN IF EXISTS dataset_id;
ALTER TABLE agent_eval_history DROP COLUMN IF EXISTS metrics;
```

2. **Revert code**:
```bash
git revert HEAD~N  # N = number of commits to revert
```

3. **Remove new files**:
```bash
rm data_agent/prompt_registry.py
rm data_agent/model_gateway.py
rm data_agent/context_manager.py
rm data_agent/eval_scenario.py
rm data_agent/test_*.py  # new test files
```

---

**End of Implementation Plan**

**Estimated Effort**:
- Phase 1 (Migrations): 2 hours
- Phase 2 (Core Modules): 8 hours
- Phase 3 (Integration): 4 hours
- Phase 4 (Documentation): 2 hours
- **Total: ~16 hours (2 days)**

**Next Step**: Execute this plan task-by-task using `superpowers:executing-plans` skill.


