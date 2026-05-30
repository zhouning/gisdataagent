# @SubAgent Mention Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `@SubAgent` explicit routing to the chat box so expert users can bypass semantic intent classification and directly invoke pipelines, sub-agents, custom skills, or built-in ADK skills.

**Architecture:** A mention parser extracts the leading `@Handle` token from user messages. A mention registry aggregates all invocable targets (4 types) into a normalized lookup. The parser runs before `classify_intent()` in `app.py`; unresolved mentions fall back to the existing semantic router. A new REST endpoint serves RBAC-filtered targets for frontend autocomplete.

**Tech Stack:** Python 3.13 / Starlette / SQLAlchemy (backend), React 18 / TypeScript (frontend), pytest (backend tests)

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `data_agent/mention_registry.py` | Aggregate 4 target types into normalized records; lookup by handle |
| Create | `data_agent/mention_parser.py` | Detect leading `@` mention, extract handle + remaining text, resolve via registry |
| Create | `data_agent/test_mention_routing.py` | All backend unit + integration tests for mention routing |
| Modify | `data_agent/frontend_api.py:3221+` | Add `GET /api/chat/mention-targets` endpoint + Route registration |
| Modify | `data_agent/app.py:2843-2854` | Insert mention parse before `classify_intent()` call |
| Modify | `data_agent/observability.py:138+` | Add `mention_routes` Prometheus counter |
| Modify | `frontend/src/components/ChatPanel.tsx` | Add `@`-triggered autocomplete dropdown + keyboard navigation |
| Modify | `frontend/src/styles/layout.css` | Dropdown styles for mention autocomplete |

---

## Phase 1: Backend Core (mention_registry + mention_parser)

### Task 1: Mention Registry — target aggregation

**Files:**
- Create: `data_agent/mention_registry.py`
- Test: `data_agent/test_mention_routing.py`

- [ ] **Step 1: Write failing tests for registry**

```python
# data_agent/test_mention_routing.py
"""Tests for @SubAgent mention routing."""
import unittest
from unittest.mock import patch, MagicMock


class TestMentionRegistry(unittest.TestCase):
    """Tests for mention_registry.py target aggregation."""

    def test_pipeline_targets_always_present(self):
        from data_agent.mention_registry import build_registry
        registry = build_registry(user_id="testuser", role="admin")
        handles = {t["handle"] for t in registry}
        self.assertIn("General", handles)
        self.assertIn("Governance", handles)
        self.assertIn("Optimization", handles)

    def test_pipeline_target_shape(self):
        from data_agent.mention_registry import build_registry
        registry = build_registry(user_id="testuser", role="admin")
        general = next(t for t in registry if t["handle"] == "General")
        self.assertEqual(general["type"], "pipeline")
        self.assertIn("allowed_roles", general)
        self.assertIn("description", general)
        self.assertEqual(general["required_state_keys"], [])

    def test_sub_agent_targets_present(self):
        from data_agent.mention_registry import build_registry
        registry = build_registry(user_id="testuser", role="admin")
        handles = {t["handle"] for t in registry}
        self.assertIn("DataVisualization", handles)
        self.assertIn("DataProcessing", handles)
        self.assertIn("GovExploration", handles)

    def test_sub_agent_has_required_state(self):
        from data_agent.mention_registry import build_registry
        registry = build_registry(user_id="testuser", role="admin")
        viz = next(t for t in registry if t["handle"] == "DataVisualization")
        self.assertEqual(viz["type"], "sub_agent")
        self.assertIn("processed_data", viz["required_state_keys"])

    def test_builtin_skill_targets(self):
        from data_agent.mention_registry import build_registry
        with patch("data_agent.mention_registry.list_builtin_skills", return_value=[
            {"name": "thematic-mapping", "description": "专题图制作", "type": "builtin_skill"},
        ]):
            registry = build_registry(user_id="testuser", role="admin")
        handles = {t["handle"] for t in registry}
        self.assertIn("thematic-mapping", handles)

    @patch("data_agent.mention_registry.list_custom_skills")
    def test_custom_skill_targets(self, mock_list):
        mock_list.return_value = [
            {"id": 1, "skill_name": "SoilExpert", "description": "土壤分析",
             "owner_username": "testuser", "is_shared": False},
        ]
        from data_agent.mention_registry import build_registry
        registry = build_registry(user_id="testuser", role="admin")
        handles = {t["handle"] for t in registry}
        self.assertIn("SoilExpert", handles)

    def test_lookup_by_handle_case_insensitive(self):
        from data_agent.mention_registry import build_registry, lookup
        registry = build_registry(user_id="testuser", role="admin")
        result = lookup(registry, "general")
        self.assertIsNotNone(result)
        self.assertEqual(result["handle"], "General")

    def test_lookup_unknown_returns_none(self):
        from data_agent.mention_registry import build_registry, lookup
        registry = build_registry(user_id="testuser", role="admin")
        result = lookup(registry, "NonExistentAgent")
        self.assertIsNone(result)

    def test_handle_uniqueness(self):
        from data_agent.mention_registry import build_registry
        registry = build_registry(user_id="testuser", role="admin")
        handles = [t["handle"] for t in registry]
        self.assertEqual(len(handles), len(set(h.lower() for h in handles)))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest data_agent/test_mention_routing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'data_agent.mention_registry'`

- [ ] **Step 3: Implement mention_registry.py**

```python
# data_agent/mention_registry.py
"""Mention Registry — aggregates all invocable targets for @SubAgent routing."""
from typing import Optional

# --- Pipeline targets (static) ---
_PIPELINE_TARGETS = [
    {
        "handle": "General",
        "label": "General",
        "type": "pipeline",
        "description": "通用分析与查询",
        "allowed_roles": ["admin", "analyst", "viewer"],
        "required_state_keys": [],
        "pipeline": "GENERAL",
    },
    {
        "handle": "Governance",
        "label": "Governance",
        "type": "pipeline",
        "description": "数据治理与质量审计",
        "allowed_roles": ["admin", "analyst"],
        "required_state_keys": [],
        "pipeline": "GOVERNANCE",
    },
    {
        "handle": "Optimization",
        "label": "Optimization",
        "type": "pipeline",
        "description": "空间优化与DRL布局",
        "allowed_roles": ["admin", "analyst"],
        "required_state_keys": [],
        "pipeline": "OPTIMIZATION",
    },
]

# --- Sub-agent targets (static, derived from agent.py definitions) ---
_SUB_AGENT_TARGETS = [
    {"handle": "DataExploration", "label": "DataExploration", "type": "sub_agent",
     "description": "数据探查与画像", "allowed_roles": ["admin", "analyst"],
     "required_state_keys": [], "pipeline": "OPTIMIZATION"},
    {"handle": "DataProcessing", "label": "DataProcessing", "type": "sub_agent",
     "description": "数据处理与清洗", "allowed_roles": ["admin", "analyst"],
     "required_state_keys": ["data_profile"], "pipeline": "OPTIMIZATION"},
    {"handle": "DataAnalysis", "label": "DataAnalysis", "type": "sub_agent",
     "description": "空间分析与统计", "allowed_roles": ["admin", "analyst"],
     "required_state_keys": ["processed_data"], "pipeline": "OPTIMIZATION"},
    {"handle": "DataVisualization", "label": "DataVisualization", "type": "sub_agent",
     "description": "地图渲染、图表生成、3D可视化", "allowed_roles": ["admin", "analyst"],
     "required_state_keys": ["processed_data"], "pipeline": "OPTIMIZATION"},
    {"handle": "DataSummary", "label": "DataSummary", "type": "sub_agent",
     "description": "分析结果汇总", "allowed_roles": ["admin", "analyst"],
     "required_state_keys": ["processed_data"], "pipeline": "OPTIMIZATION"},
    {"handle": "GovExploration", "label": "GovExploration", "type": "sub_agent",
     "description": "治理数据探查", "allowed_roles": ["admin", "analyst"],
     "required_state_keys": [], "pipeline": "GOVERNANCE"},
    {"handle": "GovProcessing", "label": "GovProcessing", "type": "sub_agent",
     "description": "治理数据处理", "allowed_roles": ["admin", "analyst"],
     "required_state_keys": ["data_profile"], "pipeline": "GOVERNANCE"},
    {"handle": "GovernanceReporter", "label": "GovernanceReporter", "type": "sub_agent",
     "description": "治理报告生成", "allowed_roles": ["admin", "analyst"],
     "required_state_keys": ["processed_data"], "pipeline": "GOVERNANCE"},
    {"handle": "GeneralProcessing", "label": "GeneralProcessing", "type": "sub_agent",
     "description": "通用数据处理", "allowed_roles": ["admin", "analyst", "viewer"],
     "required_state_keys": [], "pipeline": "GENERAL"},
    {"handle": "GeneralViz", "label": "GeneralViz", "type": "sub_agent",
     "description": "通用可视化", "allowed_roles": ["admin", "analyst", "viewer"],
     "required_state_keys": ["processed_data"], "pipeline": "GENERAL"},
]


def build_registry(user_id: str, role: str) -> list[dict]:
    targets = list(_PIPELINE_TARGETS) + list(_SUB_AGENT_TARGETS)
    # Built-in ADK skills
    try:
        from .capabilities import list_builtin_skills
        for skill in list_builtin_skills():
            targets.append({
                "handle": skill["name"],
                "label": skill["name"],
                "type": "adk_skill",
                "description": skill.get("description", ""),
                "allowed_roles": ["admin", "analyst"],
                "required_state_keys": [],
                "source": "builtin",
            })
    except Exception:
        pass
    # Custom skills visible to user
    try:
        from .custom_skills import list_custom_skills
        from .user_context import current_user_id
        prev = current_user_id.get(None)
        current_user_id.set(user_id)
        try:
            for skill in list_custom_skills(include_shared=True):
                targets.append({
                    "handle": skill["skill_name"],
                    "label": skill["skill_name"],
                    "type": "custom_skill",
                    "description": skill.get("description", ""),
                    "allowed_roles": ["admin", "analyst"],
                    "required_state_keys": [],
                    "skill_id": skill.get("id"),
                    "user_owned": skill.get("owner_username") == user_id,
                })
        finally:
            if prev is not None:
                current_user_id.set(prev)
    except Exception:
        pass
    # Deduplicate by lowercase handle (first wins)
    seen = set()
    unique = []
    for t in targets:
        key = t["handle"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(t)
    return unique


def lookup(registry: list[dict], handle: str) -> Optional[dict]:
    handle_lower = handle.lower()
    for t in registry:
        if t["handle"].lower() == handle_lower:
            return t
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest data_agent/test_mention_routing.py::TestMentionRegistry -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add data_agent/mention_registry.py data_agent/test_mention_routing.py
git commit -m "feat: add mention registry for @SubAgent target aggregation"
```

---

### Task 2: Mention Parser — extract leading @handle

**Files:**
- Create: `data_agent/mention_parser.py`
- Test: `data_agent/test_mention_routing.py` (append)

- [ ] **Step 1: Write failing tests for parser**

Append to `data_agent/test_mention_routing.py`:

```python
class TestMentionParser(unittest.TestCase):
    """Tests for mention_parser.py leading @handle extraction."""

    def test_leading_mention_extracted(self):
        from data_agent.mention_parser import parse_mention
        result = parse_mention("@DataVisualization 把刚才结果做热力图")
        self.assertEqual(result["handle"], "DataVisualization")
        self.assertEqual(result["remaining"], "把刚才结果做热力图")

    def test_no_mention_returns_none(self):
        from data_agent.mention_parser import parse_mention
        result = parse_mention("请帮我分析这个数据")
        self.assertIsNone(result)

    def test_non_leading_mention_ignored(self):
        from data_agent.mention_parser import parse_mention
        result = parse_mention("请帮我 @DataVisualization 画图")
        self.assertIsNone(result)

    def test_mention_with_hyphen(self):
        from data_agent.mention_parser import parse_mention
        result = parse_mention("@thematic-mapping 生成专题图")
        self.assertEqual(result["handle"], "thematic-mapping")
        self.assertEqual(result["remaining"], "生成专题图")

    def test_mention_only_no_text(self):
        from data_agent.mention_parser import parse_mention
        result = parse_mention("@General")
        self.assertEqual(result["handle"], "General")
        self.assertEqual(result["remaining"], "")

    def test_mention_with_extra_spaces(self):
        from data_agent.mention_parser import parse_mention
        result = parse_mention("  @Governance  检查拓扑错误  ")
        self.assertEqual(result["handle"], "Governance")
        self.assertEqual(result["remaining"], "检查拓扑错误")

    def test_resolve_valid_mention(self):
        from data_agent.mention_parser import parse_mention, resolve_mention
        from data_agent.mention_registry import build_registry
        registry = build_registry(user_id="testuser", role="admin")
        parsed = parse_mention("@General 查询数据")
        target = resolve_mention(parsed, registry)
        self.assertIsNotNone(target)
        self.assertEqual(target["type"], "pipeline")

    def test_resolve_unknown_mention_returns_none(self):
        from data_agent.mention_parser import parse_mention, resolve_mention
        from data_agent.mention_registry import build_registry
        registry = build_registry(user_id="testuser", role="admin")
        parsed = parse_mention("@UnknownAgent 做点什么")
        target = resolve_mention(parsed, registry)
        self.assertIsNone(target)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest data_agent/test_mention_routing.py::TestMentionParser -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'data_agent.mention_parser'`

- [ ] **Step 3: Implement mention_parser.py**

```python
# data_agent/mention_parser.py
"""Mention Parser — detect and extract leading @handle from user messages."""
import re
from typing import Optional

_MENTION_RE = re.compile(r"^\s*@([\w\-]+)\s*(.*)", re.DOTALL)


def parse_mention(text: str) -> Optional[dict]:
    """Parse a leading @handle from message text.

    Returns {"handle": str, "remaining": str} or None if no leading mention.
    Only the first token after @ is treated as routing syntax.
    """
    m = _MENTION_RE.match(text)
    if not m:
        return None
    return {
        "handle": m.group(1),
        "remaining": m.group(2).strip(),
    }


def resolve_mention(parsed: Optional[dict], registry: list[dict]) -> Optional[dict]:
    """Resolve a parsed mention against the registry.

    Returns the matching target dict or None.
    """
    if not parsed:
        return None
    from .mention_registry import lookup
    return lookup(registry, parsed["handle"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest data_agent/test_mention_routing.py::TestMentionParser -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add data_agent/mention_parser.py data_agent/test_mention_routing.py
git commit -m "feat: add mention parser for leading @handle extraction"
```

---

## Phase 2: Backend Integration (app.py + REST endpoint + observability)

### Task 3: Integrate mention routing into app.py message handler

**Files:**
- Modify: `data_agent/app.py:2843-2854`
- Test: `data_agent/test_mention_routing.py` (append)

- [ ] **Step 1: Write failing integration tests**

Append to `data_agent/test_mention_routing.py`:

```python
class TestMentionDispatch(unittest.TestCase):
    """Tests for RBAC enforcement and state validation in mention dispatch."""

    def test_viewer_blocked_from_governance_mention(self):
        from data_agent.mention_registry import build_registry
        from data_agent.mention_parser import parse_mention, resolve_mention
        registry = build_registry(user_id="viewer1", role="viewer")
        parsed = parse_mention("@Governance 检查数据")
        target = resolve_mention(parsed, registry)
        self.assertIsNotNone(target)
        self.assertNotIn("viewer", target["allowed_roles"])

    def test_viewer_allowed_general_mention(self):
        from data_agent.mention_registry import build_registry
        from data_agent.mention_parser import parse_mention, resolve_mention
        registry = build_registry(user_id="viewer1", role="viewer")
        parsed = parse_mention("@General 查询数据")
        target = resolve_mention(parsed, registry)
        self.assertIsNotNone(target)
        self.assertIn("viewer", target["allowed_roles"])

    def test_sub_agent_state_check_missing(self):
        from data_agent.mention_registry import build_registry
        from data_agent.mention_parser import parse_mention, resolve_mention
        registry = build_registry(user_id="testuser", role="admin")
        parsed = parse_mention("@DataVisualization 画热力图")
        target = resolve_mention(parsed, registry)
        self.assertIsNotNone(target)
        self.assertIn("processed_data", target["required_state_keys"])

    def test_unknown_mention_fallback(self):
        from data_agent.mention_registry import build_registry
        from data_agent.mention_parser import parse_mention, resolve_mention
        registry = build_registry(user_id="testuser", role="admin")
        parsed = parse_mention("@FakeAgent 做点什么")
        target = resolve_mention(parsed, registry)
        self.assertIsNone(target)
```

- [ ] **Step 2: Run tests to verify they pass** (these use existing modules)

Run: `.venv/Scripts/python.exe -m pytest data_agent/test_mention_routing.py::TestMentionDispatch -v`
Expected: All 4 tests PASS

- [ ] **Step 3: Modify app.py — insert mention routing before classify_intent**

In `data_agent/app.py`, locate the block at line ~2843 (`# --- Template Apply: skip intent classification if pending template ---`). Insert the mention routing block **before** the template check. The new code goes after the ArcPy/language hint injection (around line 2842) and before line 2843:

```python
    # --- @SubAgent Mention Routing (v24.0) ---
    _mention_target = None
    _mention_remaining = None
    try:
        from data_agent.mention_parser import parse_mention, resolve_mention
        from data_agent.mention_registry import build_registry
        _parsed = parse_mention(user_text)
        if _parsed:
            _registry = build_registry(user_id, role)
            _mention_target = resolve_mention(_parsed, _registry)
            if _mention_target:
                _mention_remaining = _parsed["remaining"]
                logger.info("[Trace:%s] Mention detected: @%s type=%s",
                            trace_id, _mention_target["handle"], _mention_target["type"])
                try:
                    from data_agent.observability import mention_routes
                    mention_routes.labels(
                        target_type=_mention_target["type"],
                        handle=_mention_target["handle"],
                        status="matched",
                    ).inc()
                except Exception:
                    pass
            else:
                logger.info("[Trace:%s] Mention @%s unresolved, falling back to semantic router",
                            trace_id, _parsed["handle"])
                try:
                    from data_agent.observability import mention_routes
                    mention_routes.labels(
                        target_type="unknown", handle=_parsed["handle"], status="unknown",
                    ).inc()
                except Exception:
                    pass
    except Exception as _mention_err:
        logger.debug("[MentionRouting] Parse error: %s", _mention_err)

    if _mention_target:
        # RBAC check
        if role not in _mention_target["allowed_roles"]:
            try:
                record_audit(user_id, ACTION_RBAC_DENIED, status="denied", details={
                    "role": role, "mention": _mention_target["handle"],
                })
                from data_agent.observability import mention_routes
                mention_routes.labels(
                    target_type=_mention_target["type"],
                    handle=_mention_target["handle"],
                    status="unauthorized",
                ).inc()
            except Exception:
                pass
            await cl.Message(
                content=t("rbac.denied", role=role, intent=_mention_target["handle"])
            ).send()
            return

        _mt_type = _mention_target["type"]
        if _mt_type == "pipeline":
            intent = _mention_target["pipeline"]
            intent_reason = f"@{_mention_target['handle']} 显式路由"
            router_tokens = 0
            if _mention_remaining:
                full_prompt = _mention_remaining
        elif _mt_type == "sub_agent":
            # State dependency check
            session = await session_service.get_session(
                app_name="data_agent_ui", user_id=user_id, session_id=session_id)
            state = session.state if session else {}
            missing = [k for k in _mention_target.get("required_state_keys", [])
                       if not state.get(k)]
            if missing:
                try:
                    from data_agent.observability import mention_routes
                    mention_routes.labels(
                        target_type="sub_agent",
                        handle=_mention_target["handle"],
                        status="missing_state",
                    ).inc()
                except Exception:
                    pass
                await cl.Message(
                    content=f"@{_mention_target['handle']} 需要 `{'`, `'.join(missing)}`，"
                            f"但当前会话中不存在。请先运行前置处理步骤。"
                ).send()
                return
            # Direct sub-agent execution
            from data_agent.agent import _make_agent_by_name
            selected_agent = _make_agent_by_name(_mention_target["handle"])
            if not selected_agent:
                await cl.Message(content=f"❌ 无法实例化子代理 @{_mention_target['handle']}").send()
                return
            pipeline_type = _mention_target.get("pipeline", "general").lower()
            pipeline_name = f"@{_mention_target['handle']} (直接调用)"
            intent = _mention_target.get("pipeline", "GENERAL")
            intent_reason = f"@{_mention_target['handle']} 显式路由"
            router_tokens = 0
            if _mention_remaining:
                full_prompt = _mention_remaining
            # Skip to pipeline execution (jump past classify_intent)
            await cl.Message(
                content=t("routing.intent_recognized", intent=intent, pipeline_name=pipeline_name),
                metadata={"routing_info": {
                    "intent": intent, "pipeline": pipeline_type,
                    "pipeline_name": pipeline_name, "reason": intent_reason,
                }},
            ).send()
            cl.user_session.set("pipeline_type", pipeline_type)
            await _execute_pipeline(
                user_id, session_id, role, full_prompt, uploaded_files,
                pipeline_type, pipeline_name, intent, selected_agent,
                router_tokens=0, extra_parts=extra_parts,
            )
            return
        elif _mt_type == "custom_skill":
            from data_agent.custom_skills import get_custom_skill, build_custom_agent
            skill = get_custom_skill(_mention_target["skill_id"])
            if skill:
                selected_agent = build_custom_agent(skill)
                pipeline_type = "custom"
                pipeline_name = f"Custom Skill: {_mention_target['handle']}"
                intent = "CUSTOM"
                intent_reason = f"@{_mention_target['handle']} 显式路由"
                router_tokens = 0
                if _mention_remaining:
                    full_prompt = _mention_remaining
                _custom_skill_agent = selected_agent
                _custom_skill_name = _mention_target["handle"]
            else:
                _mention_target = None  # fall through to semantic router
        elif _mt_type == "adk_skill":
            from data_agent.toolsets.skill_bundles import build_skill_toolset
            from google.adk.agents import LlmAgent
            from data_agent.agent import get_model_for_tier
            _skill_ts = build_skill_toolset(_mention_target["handle"])
            selected_agent = LlmAgent(
                name=f"SkillAgent_{_mention_target['handle'].replace('-', '_')}",
                instruction=f"你是 {_mention_target['handle']} 技能专家。使用 load_skill 加载技能后按指令执行。",
                model=get_model_for_tier("standard"),
                tools=[_skill_ts],
                output_key="skill_output",
            )
            pipeline_type = "general"
            pipeline_name = f"ADK Skill: {_mention_target['handle']}"
            intent = "GENERAL"
            intent_reason = f"@{_mention_target['handle']} 显式路由"
            router_tokens = 0
            if _mention_remaining:
                full_prompt = _mention_remaining
            await cl.Message(
                content=t("routing.intent_recognized", intent=intent, pipeline_name=pipeline_name),
                metadata={"routing_info": {
                    "intent": intent, "pipeline": pipeline_type,
                    "pipeline_name": pipeline_name, "reason": intent_reason,
                }},
            ).send()
            cl.user_session.set("pipeline_type", pipeline_type)
            await _execute_pipeline(
                user_id, session_id, role, full_prompt, uploaded_files,
                pipeline_type, pipeline_name, intent, selected_agent,
                router_tokens=0, extra_parts=extra_parts,
            )
            return
    # --- End @SubAgent Mention Routing ---
```

- [ ] **Step 4: Add `_make_agent_by_name` factory to agent.py**

Append to `data_agent/agent.py` (after the existing factory functions, around line 835):

```python
# --- Direct sub-agent lookup for @mention routing ---
_AGENT_MAP = {
    "DataExploration": lambda: _make_planner_exploration("MentionExploration"),
    "DataProcessing": lambda: _make_planner_processing("MentionProcessing"),
    "DataAnalysis": lambda: _make_planner_analysis("MentionAnalysis"),
    "DataVisualization": lambda: _make_planner_visualization("MentionVisualization"),
    "DataSummary": lambda: LlmAgent(
        name="MentionSummary", instruction=_load_prompt("optimization")["summary"],
        model="gemini-2.5-flash", output_key="final_summary",
        tools=[ExplorationToolset(), FileToolset()],
    ),
    "GovExploration": lambda: _make_planner_exploration("MentionGovExploration"),
    "GovProcessing": lambda: _make_planner_processing("MentionGovProcessing"),
    "GovernanceReporter": lambda: LlmAgent(
        name="MentionGovReporter", instruction=_load_prompt("governance")["reporter"],
        model="gemini-2.5-flash", output_key="governance_report",
        tools=[ExplorationToolset(), FileToolset(), DatabaseToolset()],
    ),
    "GeneralProcessing": lambda: _make_planner_processing("MentionGeneralProcessing"),
    "GeneralViz": lambda: _make_planner_visualization("MentionGeneralViz"),
}


def _make_agent_by_name(name: str):
    """Create a fresh agent instance for direct @mention invocation.

    Returns None if the name is not a known sub-agent.
    ADK requires separate instances (one-parent constraint).
    """
    factory = _AGENT_MAP.get(name)
    return factory() if factory else None
```

- [ ] **Step 5: Run all mention tests**

Run: `.venv/Scripts/python.exe -m pytest data_agent/test_mention_routing.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add data_agent/app.py data_agent/agent.py data_agent/test_mention_routing.py
git commit -m "feat: integrate @mention routing into app.py message handler"
```

---

### Task 4: REST endpoint + observability

**Files:**
- Modify: `data_agent/frontend_api.py`
- Modify: `data_agent/observability.py`
- Test: `data_agent/test_mention_routing.py` (append)

- [ ] **Step 1: Write failing test for the endpoint**

Append to `data_agent/test_mention_routing.py`:

```python
class TestMentionTargetsAPI(unittest.TestCase):
    """Tests for GET /api/chat/mention-targets endpoint."""

    def _run_async(self, coro):
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError("closed")
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)

    def _make_request(self):
        req = MagicMock()
        req.cookies = {}
        req.query_params = {}
        req.path_params = {}
        req.method = "GET"
        return req

    def _make_user(self, identifier="testuser", role="analyst"):
        user = MagicMock()
        user.identifier = identifier
        user.metadata = {"role": role}
        return user

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_unauthorized(self, _mock):
        from data_agent.frontend_api import _api_mention_targets
        resp = self._run_async(_api_mention_targets(self._make_request()))
        self.assertEqual(resp.status_code, 401)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_returns_targets(self, mock_user):
        mock_user.return_value = self._make_user(role="admin")
        from data_agent.frontend_api import _api_mention_targets
        with patch("data_agent.mention_registry.list_custom_skills", return_value=[]):
            resp = self._run_async(_api_mention_targets(self._make_request()))
        self.assertEqual(resp.status_code, 200)
        import json
        body = json.loads(resp.body)
        self.assertIn("targets", body)
        handles = [t["handle"] for t in body["targets"]]
        self.assertIn("General", handles)
        self.assertIn("DataVisualization", handles)

    @patch("data_agent.frontend_api._get_user_from_request")
    def test_viewer_sees_allowed_flag(self, mock_user):
        mock_user.return_value = self._make_user(role="viewer")
        from data_agent.frontend_api import _api_mention_targets
        with patch("data_agent.mention_registry.list_custom_skills", return_value=[]):
            resp = self._run_async(_api_mention_targets(self._make_request()))
        import json
        body = json.loads(resp.body)
        gov = next((t for t in body["targets"] if t["handle"] == "Governance"), None)
        self.assertIsNotNone(gov)
        self.assertFalse(gov["allowed"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest data_agent/test_mention_routing.py::TestMentionTargetsAPI -v`
Expected: FAIL — `ImportError: cannot import name '_api_mention_targets'`

- [ ] **Step 3: Add Prometheus counter to observability.py**

In `data_agent/observability.py`, after the existing `intent_classification` counter (around line 203), add:

```python
mention_routes = _safe_counter(
    "agent_mention_routes_total", "Mention routing events",
    ["target_type", "handle", "status"],
)
```

Also add a structured log helper for the five observability fields from the spec. Append after the counter:

```python
def log_mention_event(logger, trace_id: str, *,
                      mention_detected: bool,
                      mention_target_type: str = "",
                      mention_target_handle: str = "",
                      mention_resolution_status: str = "",
                      mention_fallback_to_semantic_router: bool = False):
    """Structured log for mention routing observability (spec §12)."""
    logger.info(
        "[Trace:%s] mention_detected=%s target_type=%s handle=%s "
        "resolution=%s fallback=%s",
        trace_id, mention_detected, mention_target_type,
        mention_target_handle, mention_resolution_status,
        mention_fallback_to_semantic_router,
    )
```

- [ ] **Step 4: Add endpoint to frontend_api.py**

In `data_agent/frontend_api.py`, add the handler function (before the capabilities section, around line 1392):

```python
# ---------------------------------------------------------------------------
# Mention Targets (v24.0 — @SubAgent routing)
# ---------------------------------------------------------------------------

async def _api_mention_targets(request: Request):
    """GET /api/chat/mention-targets — RBAC-filtered invocable targets for autocomplete."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    from .mention_registry import build_registry
    registry = build_registry(user_id=username, role=role)
    targets = []
    for t in registry:
        targets.append({
            "handle": t["handle"],
            "label": t.get("label", t["handle"]),
            "type": t["type"],
            "description": t.get("description", ""),
            "allowed": role in t.get("allowed_roles", []),
            "allowed_roles": t.get("allowed_roles", []),
            "required_state_keys": t.get("required_state_keys", []),
        })
    return JSONResponse({"targets": targets})
```

Then register the route in the `routes = [...]` list (around line 3257, after the capabilities route):

```python
        Route("/api/chat/mention-targets", endpoint=_api_mention_targets, methods=["GET"]),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest data_agent/test_mention_routing.py::TestMentionTargetsAPI -v`
Expected: All 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add data_agent/frontend_api.py data_agent/observability.py data_agent/test_mention_routing.py
git commit -m "feat: add GET /api/chat/mention-targets endpoint + Prometheus counter"
```

---

## Phase 3: Frontend Autocomplete

### Task 5: ChatPanel @mention autocomplete dropdown

**Files:**
- Modify: `frontend/src/components/ChatPanel.tsx`
- Modify: `frontend/src/styles/layout.css`

Note: No frontend test framework is installed (no vitest/jest in package.json). Verification is manual: start dev server, type `@` in chat, confirm dropdown appears and keyboard navigation works.

- [ ] **Step 1: Add mention state and fetch logic to ChatPanel.tsx**

In `frontend/src/components/ChatPanel.tsx`, add state variables after the existing state declarations (around line 49, after `sessionsLoading`):

```typescript
  // Mention autocomplete state
  const [mentionTargets, setMentionTargets] = useState<Array<{
    handle: string; label: string; type: string;
    description: string; allowed: boolean;
  }>>([]);
  const [showMention, setShowMention] = useState(false);
  const [mentionFilter, setMentionFilter] = useState('');
  const [mentionIndex, setMentionIndex] = useState(0);
  const mentionRef = useRef<HTMLDivElement>(null);
```

Add a fetch function after the `fetchSessions` callback (around line 236):

```typescript
  const fetchMentionTargets = useCallback(async () => {
    try {
      const resp = await fetch('/api/chat/mention-targets', { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setMentionTargets(data.targets || []);
      }
    } catch { /* ignore */ }
  }, []);
```

- [ ] **Step 2: Add mention detection in onChange handler**

Replace the textarea `onChange` handler (line 491) with:

```typescript
            onChange={(e) => {
              const val = e.target.value;
              setInput(val);
              // Detect @mention trigger
              const match = val.match(/^\s*@(\S*)$/);
              if (match) {
                if (mentionTargets.length === 0) fetchMentionTargets();
                setMentionFilter(match[1].toLowerCase());
                setShowMention(true);
                setMentionIndex(0);
              } else if (val.match(/^\s*@\S+\s/)) {
                // User typed space after handle — close dropdown
                setShowMention(false);
              } else if (!val.startsWith('@')) {
                setShowMention(false);
              }
            }}
```

- [ ] **Step 3: Update handleKeyDown for mention navigation**

Replace the `handleKeyDown` function (line 162-164) with:

```typescript
  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (showMention) {
      const filtered = mentionTargets.filter(t =>
        t.handle.toLowerCase().includes(mentionFilter) && t.allowed
      );
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setMentionIndex(i => Math.min(i + 1, filtered.length - 1));
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setMentionIndex(i => Math.max(i - 1, 0));
        return;
      }
      if ((e.key === 'Enter' || e.key === 'Tab') && filtered.length > 0) {
        e.preventDefault();
        const selected = filtered[mentionIndex];
        setInput(`@${selected.handle} `);
        setShowMention(false);
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        setShowMention(false);
        return;
      }
    }
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };
```

- [ ] **Step 4: Add dropdown JSX before the textarea**

In the `chat-input-container` div (around line 459), add the dropdown just before the `<textarea>`:

```tsx
          {showMention && (
            <div className="mention-dropdown" ref={mentionRef}>
              {mentionTargets
                .filter(t => t.handle.toLowerCase().includes(mentionFilter) && t.allowed)
                .map((t, idx) => (
                  <div
                    key={t.handle}
                    className={`mention-item ${idx === mentionIndex ? 'mention-item-active' : ''}`}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      setInput(`@${t.handle} `);
                      setShowMention(false);
                      textareaRef.current?.focus();
                    }}
                  >
                    <span className="mention-handle">@{t.handle}</span>
                    <span className="mention-type">{t.type}</span>
                    <span className="mention-desc">{t.description}</span>
                  </div>
                ))}
              {mentionTargets.filter(t => t.handle.toLowerCase().includes(mentionFilter) && t.allowed).length === 0 && (
                <div className="mention-item mention-empty">无匹配目标</div>
              )}
            </div>
          )}
```

- [ ] **Step 5: Run tests to verify no regressions**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ChatPanel.tsx
git commit -m "feat: add @mention autocomplete dropdown to ChatPanel"
```

---

### Task 6: Mention dropdown CSS styles

**Files:**
- Modify: `frontend/src/styles/layout.css`

- [ ] **Step 1: Add dropdown styles**

Append to `frontend/src/styles/layout.css` (before the responsive media query section, around line 1268):

```css
/* --- @Mention Autocomplete Dropdown --- */
.mention-dropdown {
  position: absolute;
  bottom: 100%;
  left: 0;
  right: 0;
  max-height: 240px;
  overflow-y: auto;
  background: var(--bg-secondary, #1e1e2e);
  border: 1px solid var(--border, #333);
  border-radius: 8px;
  box-shadow: 0 -4px 16px rgba(0,0,0,0.3);
  z-index: 100;
  margin-bottom: 4px;
}
.mention-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 13px;
  transition: background 0.1s;
}
.mention-item:hover, .mention-item-active {
  background: var(--bg-hover, #2a2a3e);
}
.mention-handle {
  font-weight: 600;
  color: var(--primary, #7c6ef0);
  min-width: 120px;
}
.mention-type {
  font-size: 11px;
  color: var(--text-muted, #888);
  background: var(--bg-tertiary, #2a2a3e);
  padding: 1px 6px;
  border-radius: 4px;
  min-width: 60px;
  text-align: center;
}
.mention-desc {
  color: var(--text-secondary, #aaa);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mention-empty {
  color: var(--text-muted, #888);
  font-style: italic;
  cursor: default;
}
```

Also add `position: relative;` to `.chat-input-container` if not already present. Find `.chat-input-container` in layout.css and ensure it has:

```css
.chat-input-container {
  position: relative;
  /* ... existing styles ... */
}
```

- [ ] **Step 2: Build frontend to verify**

Run: `cd frontend && npm run build`
Expected: Build succeeds with no errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/styles/layout.css
git commit -m "feat: add CSS styles for @mention autocomplete dropdown"
```

---

## Phase 4: Verification & Cleanup

### Task 7: Full test suite run + manual verification

**Files:**
- No new files

- [ ] **Step 1: Run full mention routing test suite**

Run: `.venv/Scripts/python.exe -m pytest data_agent/test_mention_routing.py -v`
Expected: All tests PASS (21+ tests across 4 test classes)

- [ ] **Step 2: Run existing test suite to check for regressions**

Run: `.venv/Scripts/python.exe -m pytest data_agent/test_frontend_api.py data_agent/test_custom_skills.py data_agent/test_skills.py -v --tb=short`
Expected: No regressions

- [ ] **Step 3: Build frontend**

Run: `cd frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 4: Manual verification checklist**

Start the app: `$env:PYTHONPATH="D:\adk"; chainlit run data_agent/app.py -w`

Verify:
1. Type `@` in chat box → dropdown appears with targets
2. Type `@Gov` → dropdown filters to Governance
3. Arrow keys navigate, Enter/Tab selects
4. Esc closes dropdown
5. Send `@General 查询数据` → routes to General pipeline (no LLM classification)
6. Send `@Governance 检查数据` as admin → routes to Governance pipeline
7. Send `@Governance 检查数据` as viewer → RBAC denial message
8. Send `@FakeAgent 做点什么` → falls back to semantic router
9. Normal messages without `@` → semantic router works as before
10. `@DataVisualization 画图` without prior processing → missing state error

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: @SubAgent mention routing — complete implementation

- mention_registry.py: 4-type target aggregation (pipeline/sub-agent/custom-skill/adk-skill)
- mention_parser.py: leading @handle extraction with fallback
- app.py: pre-routing integration before classify_intent()
- frontend_api.py: GET /api/chat/mention-targets (RBAC-filtered)
- ChatPanel.tsx: @-triggered autocomplete dropdown with keyboard navigation
- observability.py: mention_routes Prometheus counter
- 21+ unit/integration tests"
```

---

## Summary

| Phase | Tasks | What ships |
|-------|-------|-----------|
| 1 | Task 1-2 | `mention_registry.py` + `mention_parser.py` + 17 tests |
| 2 | Task 3-4 | `app.py` integration + REST endpoint + Prometheus counter + 7 tests |
| 3 | Task 5-6 | ChatPanel autocomplete + CSS styles |
| 4 | Task 7 | Full verification + final commit |

Each phase produces working, testable software. Phase 1 can be shipped independently as a backend-only feature (mention parsing works even without the frontend dropdown — the backend will resolve `@` mentions from plain text).






