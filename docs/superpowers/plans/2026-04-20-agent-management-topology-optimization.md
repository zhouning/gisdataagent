# Agent Alias Management + Topology Tab Optimization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增智能体管理 tab（AgentsTab）支持 @mention 目标的别名/pin/hide；优化拓扑 tab 节点精简 + 详情面板增强 + 支持 Custom Skills。

**Architecture:** 后端：新增 `agent_aliases` 表（migration 058）+ 4 个 REST 端点；扩展 `mention_registry.py` 支持别名匹配 + DB 合并。前端：新增 `AgentsTab.tsx`；重写 `TopologyTab.tsx` 节点组件，精简节点内容到详情面板。ChatPanel 的 mention dropdown 数据源统一到 `/api/agents/mention-targets`。

**Tech Stack:** PostgreSQL + SQLAlchemy + Starlette (后端) / React 18 + TypeScript + @xyflow/react (前端) / pytest (测试)

**Spec:** `docs/superpowers/specs/2026-04-20-agent-management-topology-optimization-design.md`

---

## File Structure

**新建后端：**
- `data_agent/migrations/058_agent_aliases.sql` — 建表 SQL
- `data_agent/api/agent_management_routes.py` — 4 个 REST 端点 + DB helpers

**修改后端：**
- `data_agent/mention_registry.py` — 别名匹配 + DB 合并
- `data_agent/api/topology_routes.py` — 增加 `mentionable` / `pipeline_label` / custom skills
- `data_agent/frontend_api.py` — 挂载新路由

**新建前端：**
- `frontend/src/components/datapanel/AgentsTab.tsx` — 智能体管理 UI

**修改前端：**
- `frontend/src/components/datapanel/TopologyTab.tsx` — 节点精简 + 详情增强 + 刷新按钮
- `frontend/src/components/DataPanel.tsx` — 注册 AgentsTab
- `frontend/src/components/ChatPanel.tsx` — dropdown 数据源切换 + 别名匹配

**测试：**
- `data_agent/test_agent_aliases.py` — 别名 CRUD + lookup + mention_registry 合并
- `data_agent/test_topology_enhancements.py` — 拓扑 API mentionable / pipeline_label / custom skills

---

## Task 1: 创建 `agent_aliases` 表 migration

**Files:**
- Create: `data_agent/migrations/058_agent_aliases.sql`

- [ ] **Step 1: 创建 migration SQL 文件**

```sql
-- Migration 058: Agent aliases for @mention routing (v24.0)
-- Per-user aliases, display names, pin/hide flags for mention targets.

CREATE TABLE IF NOT EXISTS agent_aliases (
    id SERIAL PRIMARY KEY,
    handle VARCHAR(100) NOT NULL,
    aliases TEXT[] DEFAULT '{}',
    display_name VARCHAR(100),
    pinned BOOLEAN DEFAULT false,
    hidden BOOLEAN DEFAULT false,
    user_id VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_agent_aliases_handle_user UNIQUE (handle, user_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_aliases_user ON agent_aliases(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_aliases_handle ON agent_aliases(handle);
```

- [ ] **Step 2: 运行 migration 并验证**

启动 app 或手动调用 migration runner。验证：

```bash
.venv/Scripts/python.exe -c "from data_agent.migration_runner import apply_pending_migrations; apply_pending_migrations()"
```

预期：看到 `[Migrations] Applied 058_agent_aliases`。

在 psql 中验证：

```sql
\d agent_aliases
```

预期：表存在，含 5 个索引（PK + unique + user_id + handle + 约束）。

- [ ] **Step 3: 提交**

```bash
git add data_agent/migrations/058_agent_aliases.sql
git commit -m "feat(db): add agent_aliases table for @mention alias management"
```

---

## Task 2: agent_aliases 的 DB helpers（读 + 写）

**Files:**
- Create: `data_agent/api/agent_management_routes.py`
- Test: `data_agent/test_agent_aliases.py`

- [ ] **Step 1: 写失败的测试（DB helpers）**

```python
# data_agent/test_agent_aliases.py
import pytest
from unittest.mock import patch, MagicMock


def _fake_engine_with_result(rows):
    engine = MagicMock()
    conn = MagicMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    conn.execute.return_value = result
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    engine.connect.return_value = conn
    engine.begin.return_value = conn
    return engine, conn


def test_list_aliases_returns_user_rows():
    from data_agent.api.agent_management_routes import list_aliases_for_user
    engine, conn = _fake_engine_with_result([
        {
            "handle": "DataExploration",
            "aliases": ["数据探查"],
            "display_name": "数据探查",
            "pinned": True,
            "hidden": False,
        }
    ])
    with patch("data_agent.api.agent_management_routes.get_engine", return_value=engine):
        result = list_aliases_for_user("alice")
    assert len(result) == 1
    assert result[0]["handle"] == "DataExploration"
    assert result[0]["aliases"] == ["数据探查"]
    assert result[0]["pinned"] is True


def test_upsert_alias_inserts_or_updates():
    from data_agent.api.agent_management_routes import upsert_alias
    engine, conn = _fake_engine_with_result([])
    with patch("data_agent.api.agent_management_routes.get_engine", return_value=engine):
        upsert_alias("alice", "DataExploration",
                     aliases=["数据探查", "探查"],
                     display_name="数据探查智能体")
    # Should have executed an INSERT ... ON CONFLICT
    call_args = conn.execute.call_args
    sql_text = str(call_args[0][0])
    assert "INSERT INTO agent_aliases" in sql_text
    assert "ON CONFLICT" in sql_text


def test_set_flag_pin_updates_row():
    from data_agent.api.agent_management_routes import set_flag
    engine, conn = _fake_engine_with_result([])
    with patch("data_agent.api.agent_management_routes.get_engine", return_value=engine):
        set_flag("alice", "DataExploration", "pinned", True)
    call_args = conn.execute.call_args
    sql_text = str(call_args[0][0])
    assert "INSERT INTO agent_aliases" in sql_text
    assert "pinned" in sql_text


def test_list_aliases_no_engine_returns_empty():
    from data_agent.api.agent_management_routes import list_aliases_for_user
    with patch("data_agent.api.agent_management_routes.get_engine", return_value=None):
        assert list_aliases_for_user("alice") == []
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
.venv/Scripts/python.exe -m pytest data_agent/test_agent_aliases.py -v
```

预期：4 个测试全部 FAIL，"No module named 'data_agent.api.agent_management_routes'"。

- [ ] **Step 3: 实现 DB helpers**

```python
# data_agent/api/agent_management_routes.py
"""
Agent Management API — alias/display_name/pin/hide for @mention targets.
"""
from typing import Optional
from sqlalchemy import text
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..db_engine import get_engine
from ..observability import get_logger
from .helpers import _get_user_from_request, _set_user_context

logger = get_logger("agent_management")


def list_aliases_for_user(user_id: str) -> list[dict]:
    """Return all alias records for a user."""
    engine = get_engine()
    if engine is None:
        return []
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT handle, aliases, display_name, pinned, hidden
                FROM agent_aliases
                WHERE user_id = :user_id
            """), {"user_id": user_id})
            rows = result.mappings().all()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("list_aliases_for_user failed: %s", e)
        return []


def upsert_alias(
    user_id: str,
    handle: str,
    aliases: Optional[list[str]] = None,
    display_name: Optional[str] = None,
) -> None:
    """Insert or update alias/display_name for (user_id, handle)."""
    engine = get_engine()
    if engine is None:
        return
    aliases = aliases or []
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO agent_aliases (user_id, handle, aliases, display_name, updated_at)
                VALUES (:user_id, :handle, :aliases, :display_name, CURRENT_TIMESTAMP)
                ON CONFLICT (handle, user_id) DO UPDATE SET
                    aliases = EXCLUDED.aliases,
                    display_name = EXCLUDED.display_name,
                    updated_at = CURRENT_TIMESTAMP
            """), {
                "user_id": user_id,
                "handle": handle,
                "aliases": aliases,
                "display_name": display_name,
            })
    except Exception as e:
        logger.error("upsert_alias failed: %s", e)
        raise


def set_flag(user_id: str, handle: str, flag: str, value: bool) -> None:
    """Set pinned or hidden flag for a handle. flag must be 'pinned' or 'hidden'."""
    if flag not in ("pinned", "hidden"):
        raise ValueError(f"Invalid flag: {flag}")
    engine = get_engine()
    if engine is None:
        return
    try:
        with engine.begin() as conn:
            conn.execute(text(f"""
                INSERT INTO agent_aliases (user_id, handle, {flag}, updated_at)
                VALUES (:user_id, :handle, :value, CURRENT_TIMESTAMP)
                ON CONFLICT (handle, user_id) DO UPDATE SET
                    {flag} = EXCLUDED.{flag},
                    updated_at = CURRENT_TIMESTAMP
            """), {
                "user_id": user_id,
                "handle": handle,
                "value": value,
            })
    except Exception as e:
        logger.error("set_flag failed: %s", e)
        raise
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
.venv/Scripts/python.exe -m pytest data_agent/test_agent_aliases.py -v
```

预期：4 个测试全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add data_agent/api/agent_management_routes.py data_agent/test_agent_aliases.py
git commit -m "feat(api): add agent alias DB helpers with upsert + flag logic"
```

---

## Task 3: 扩展 mention_registry 支持 DB 合并 + 别名匹配

**Files:**
- Modify: `data_agent/mention_registry.py`
- Test: `data_agent/test_agent_aliases.py` (追加测试)

- [ ] **Step 1: 写失败的测试（mention_registry 合并 + lookup 扩展）**

在 `data_agent/test_agent_aliases.py` 文件末尾追加：

```python
def test_build_registry_merges_aliases_from_db():
    from data_agent import mention_registry

    fake_aliases = [{
        "handle": "DataExploration",
        "aliases": ["数据探查", "探查"],
        "display_name": "数据探查",
        "pinned": True,
        "hidden": False,
    }]
    with patch("data_agent.mention_registry._load_user_aliases", return_value=fake_aliases):
        registry = mention_registry.build_registry(user_id="alice", role="analyst")
    target = next(t for t in registry if t["handle"] == "DataExploration")
    assert target["aliases"] == ["数据探查", "探查"]
    assert target["display_name"] == "数据探查"
    assert target["pinned"] is True
    assert target["hidden"] is False


def test_build_registry_no_db_aliases_defaults():
    from data_agent import mention_registry
    with patch("data_agent.mention_registry._load_user_aliases", return_value=[]):
        registry = mention_registry.build_registry(user_id="alice", role="analyst")
    target = next(t for t in registry if t["handle"] == "DataExploration")
    assert target["aliases"] == []
    assert target["pinned"] is False
    assert target["hidden"] is False


def test_lookup_matches_alias():
    from data_agent import mention_registry
    registry = [{
        "handle": "DataExploration",
        "aliases": ["数据探查", "探查"],
        "display_name": "数据探查",
        "pinned": False, "hidden": False,
        "type": "sub_agent",
    }]
    assert mention_registry.lookup(registry, "数据探查")["handle"] == "DataExploration"
    assert mention_registry.lookup(registry, "探查")["handle"] == "DataExploration"
    assert mention_registry.lookup(registry, "DataExploration")["handle"] == "DataExploration"
    assert mention_registry.lookup(registry, "nonexistent") is None


def test_lookup_handle_takes_priority_over_alias():
    from data_agent import mention_registry
    registry = [
        {"handle": "A", "aliases": ["shared"], "display_name": "", "pinned": False, "hidden": False, "type": "sub_agent"},
        {"handle": "B", "aliases": ["shared"], "display_name": "shared", "pinned": False, "hidden": False, "type": "sub_agent"},
        {"handle": "shared", "aliases": [], "display_name": "", "pinned": False, "hidden": False, "type": "sub_agent"},
    ]
    # Exact handle "shared" wins over alias match and display_name match
    assert mention_registry.lookup(registry, "shared")["handle"] == "shared"
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
.venv/Scripts/python.exe -m pytest data_agent/test_agent_aliases.py -v -k "build_registry or lookup"
```

预期：4 个新测试 FAIL（`_load_user_aliases` 不存在；`lookup` 不支持别名；`build_registry` 不返回 aliases/display_name/pinned/hidden）。

- [ ] **Step 3: 修改 mention_registry.py**

替换 `D:/adk/data_agent/mention_registry.py` 全部内容：

```python
"""Mention Registry — aggregates all invocable targets for @SubAgent routing."""
from typing import Optional

try:
    from .capabilities import list_builtin_skills
except Exception:
    list_builtin_skills = None  # type: ignore[assignment]

try:
    from .custom_skills import list_custom_skills
except Exception:
    list_custom_skills = None  # type: ignore[assignment]

_PIPELINE_TARGETS = [
    {"handle": "General", "label": "General", "type": "pipeline",
     "description": "通用分析与查询", "allowed_roles": ["admin", "analyst", "viewer"],
     "required_state_keys": [], "pipeline": "GENERAL"},
    {"handle": "Governance", "label": "Governance", "type": "pipeline",
     "description": "数据治理与质量审计", "allowed_roles": ["admin", "analyst"],
     "required_state_keys": [], "pipeline": "GOVERNANCE"},
    {"handle": "Optimization", "label": "Optimization", "type": "pipeline",
     "description": "空间优化与DRL布局", "allowed_roles": ["admin", "analyst"],
     "required_state_keys": [], "pipeline": "OPTIMIZATION"},
]

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


def _load_user_aliases(user_id: str) -> list[dict]:
    """Load alias rows for a user from DB. Returns [] if DB unavailable."""
    try:
        from .api.agent_management_routes import list_aliases_for_user
        return list_aliases_for_user(user_id)
    except Exception:
        return []


def _apply_alias_defaults(target: dict) -> dict:
    """Ensure every target has aliases/display_name/pinned/hidden fields."""
    target.setdefault("aliases", [])
    target.setdefault("display_name", "")
    target.setdefault("pinned", False)
    target.setdefault("hidden", False)
    return target


def build_registry(user_id: str, role: str) -> list[dict]:
    targets = list(_PIPELINE_TARGETS) + list(_SUB_AGENT_TARGETS)
    if list_builtin_skills is not None:
        try:
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
    if list_custom_skills is not None:
        try:
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

    # Deduplicate by handle (case-insensitive)
    seen = set()
    unique = []
    for t in targets:
        key = t["handle"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(_apply_alias_defaults(dict(t)))

    # Merge DB-backed aliases/display_name/pinned/hidden
    alias_map = {row["handle"]: row for row in _load_user_aliases(user_id)}
    for t in unique:
        row = alias_map.get(t["handle"])
        if row:
            t["aliases"] = list(row.get("aliases") or [])
            t["display_name"] = row.get("display_name") or ""
            t["pinned"] = bool(row.get("pinned"))
            t["hidden"] = bool(row.get("hidden"))
    return unique


def lookup(registry: list[dict], handle: str) -> Optional[dict]:
    """Match by handle > display_name > alias (case-insensitive)."""
    q = handle.lower()
    # Priority 1: exact handle
    for t in registry:
        if t["handle"].lower() == q:
            return t
    # Priority 2: exact display_name
    for t in registry:
        if (t.get("display_name") or "").lower() == q:
            return t
    # Priority 3: alias match
    for t in registry:
        aliases = t.get("aliases") or []
        if any(a.lower() == q for a in aliases):
            return t
    return None
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
.venv/Scripts/python.exe -m pytest data_agent/test_agent_aliases.py -v
```

预期：全部 8 个测试 PASS。运行现有 mention 测试确保无回归：

```bash
.venv/Scripts/python.exe -m pytest data_agent/test_mention_routing.py -v
```

预期：原有测试仍全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add data_agent/mention_registry.py data_agent/test_agent_aliases.py
git commit -m "feat(mention): merge DB aliases into registry + extend lookup priority"
```

---

## Task 4: Agent Management REST 端点

**Files:**
- Modify: `data_agent/api/agent_management_routes.py`
- Modify: `data_agent/frontend_api.py` (挂载路由)
- Test: `data_agent/test_agent_aliases.py` (追加)

- [ ] **Step 1: 写失败的测试（REST 端点）**

在 `data_agent/test_agent_aliases.py` 末尾追加：

```python
import asyncio
from starlette.requests import Request


def _make_request(path: str, method: str = "GET", body: Optional[dict] = None, path_params: Optional[dict] = None):
    """Build a minimal Starlette Request for handler unit tests."""
    import json
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "query_string": b"",
        "path_params": path_params or {},
    }
    body_bytes = json.dumps(body).encode() if body else b""
    async def receive():
        return {"type": "http.request", "body": body_bytes, "more_body": False}
    return Request(scope, receive=receive)


class _FakeUser:
    def __init__(self, identifier="alice", role="analyst"):
        self.identifier = identifier
        self.metadata = {"role": role}


def test_mention_targets_api_excludes_hidden_by_default():
    from data_agent.api.agent_management_routes import _api_mention_targets
    fake_registry = [
        {"handle": "A", "label": "A", "type": "sub_agent", "description": "",
         "aliases": [], "display_name": "", "pinned": False, "hidden": False,
         "allowed_roles": ["analyst"], "required_state_keys": []},
        {"handle": "B", "label": "B", "type": "sub_agent", "description": "",
         "aliases": [], "display_name": "", "pinned": False, "hidden": True,
         "allowed_roles": ["analyst"], "required_state_keys": []},
    ]
    with patch("data_agent.api.agent_management_routes._get_user_from_request", return_value=_FakeUser()), \
         patch("data_agent.api.agent_management_routes.build_registry", return_value=fake_registry):
        resp = asyncio.run(_api_mention_targets(_make_request("/api/agents/mention-targets")))
    import json
    data = json.loads(resp.body.decode())
    handles = [t["handle"] for t in data["targets"]]
    assert "A" in handles
    assert "B" not in handles  # hidden excluded


def test_mention_targets_api_include_hidden_flag():
    from data_agent.api.agent_management_routes import _api_mention_targets
    fake_registry = [
        {"handle": "A", "label": "A", "type": "sub_agent", "description": "",
         "aliases": [], "display_name": "", "pinned": False, "hidden": True,
         "allowed_roles": ["analyst"], "required_state_keys": []},
    ]
    req_scope = {
        "type": "http", "method": "GET",
        "path": "/api/agents/mention-targets",
        "headers": [], "query_string": b"include_hidden=1", "path_params": {},
    }
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    req = Request(req_scope, receive=receive)
    with patch("data_agent.api.agent_management_routes._get_user_from_request", return_value=_FakeUser()), \
         patch("data_agent.api.agent_management_routes.build_registry", return_value=fake_registry):
        resp = asyncio.run(_api_mention_targets(req))
    import json
    data = json.loads(resp.body.decode())
    assert len(data["targets"]) == 1


def test_set_alias_api_calls_upsert():
    from data_agent.api.agent_management_routes import _api_set_alias
    req = _make_request(
        "/api/agents/DataExploration/alias", method="PUT",
        body={"aliases": ["探查"], "display_name": "数据探查"},
        path_params={"handle": "DataExploration"},
    )
    with patch("data_agent.api.agent_management_routes._get_user_from_request", return_value=_FakeUser()), \
         patch("data_agent.api.agent_management_routes.upsert_alias") as mock_upsert:
        resp = asyncio.run(_api_set_alias(req))
    assert resp.status_code == 200
    mock_upsert.assert_called_once_with(
        "alice", "DataExploration",
        aliases=["探查"], display_name="数据探查",
    )


def test_set_pin_api_calls_set_flag():
    from data_agent.api.agent_management_routes import _api_set_pin
    req = _make_request(
        "/api/agents/DataExploration/pin", method="PUT",
        body={"pinned": True},
        path_params={"handle": "DataExploration"},
    )
    with patch("data_agent.api.agent_management_routes._get_user_from_request", return_value=_FakeUser()), \
         patch("data_agent.api.agent_management_routes.set_flag") as mock_flag:
        resp = asyncio.run(_api_set_pin(req))
    assert resp.status_code == 200
    mock_flag.assert_called_once_with("alice", "DataExploration", "pinned", True)


def test_unauthorized_returns_401():
    from data_agent.api.agent_management_routes import _api_mention_targets
    req = _make_request("/api/agents/mention-targets")
    with patch("data_agent.api.agent_management_routes._get_user_from_request", return_value=None):
        resp = asyncio.run(_api_mention_targets(req))
    assert resp.status_code == 401
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
.venv/Scripts/python.exe -m pytest data_agent/test_agent_aliases.py -v -k "api"
```

预期：5 个测试 FAIL（handler 函数不存在）。

- [ ] **Step 3: 追加 REST handlers 到 `agent_management_routes.py`**

在 `data_agent/api/agent_management_routes.py` 文件末尾追加：

```python
from ..mention_registry import build_registry


async def _api_mention_targets(request: Request):
    """GET /api/agents/mention-targets — RBAC-filtered mention targets with alias/pinned/hidden."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    include_hidden = request.query_params.get("include_hidden") in ("1", "true")

    registry = build_registry(user_id=username, role=role)
    out = []
    for t in registry:
        if t.get("hidden") and not include_hidden:
            continue
        out.append({
            "handle": t["handle"],
            "label": t.get("label", t["handle"]),
            "display_name": t.get("display_name", ""),
            "aliases": t.get("aliases", []),
            "pinned": bool(t.get("pinned", False)),
            "hidden": bool(t.get("hidden", False)),
            "type": t["type"],
            "description": t.get("description", ""),
            "allowed": role in t.get("allowed_roles", []),
            "allowed_roles": t.get("allowed_roles", []),
            "required_state_keys": t.get("required_state_keys", []),
            "pipeline": t.get("pipeline"),
        })
    # Pinned first, then by type, then alphabetic
    type_order = {"pipeline": 0, "sub_agent": 1, "adk_skill": 2, "custom_skill": 3}
    out.sort(key=lambda t: (
        0 if t["pinned"] else 1,
        type_order.get(t["type"], 99),
        t["handle"].lower(),
    ))
    return JSONResponse({"targets": out})


async def _api_set_alias(request: Request):
    """PUT /api/agents/{handle}/alias — set aliases + display_name."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    handle = request.path_params["handle"]
    try:
        body = await request.json()
    except Exception:
        body = {}
    aliases = body.get("aliases") or []
    if not isinstance(aliases, list) or any(not isinstance(a, str) for a in aliases):
        return JSONResponse({"error": "aliases must be a list of strings"}, status_code=400)
    display_name = body.get("display_name")
    if display_name is not None and not isinstance(display_name, str):
        return JSONResponse({"error": "display_name must be a string"}, status_code=400)
    try:
        upsert_alias(username, handle, aliases=aliases, display_name=display_name)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse({"ok": True})


async def _api_set_pin(request: Request):
    """PUT /api/agents/{handle}/pin — toggle pinned flag."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    handle = request.path_params["handle"]
    try:
        body = await request.json()
    except Exception:
        body = {}
    pinned = bool(body.get("pinned", False))
    try:
        set_flag(username, handle, "pinned", pinned)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse({"ok": True, "pinned": pinned})


async def _api_set_hide(request: Request):
    """PUT /api/agents/{handle}/hide — toggle hidden flag."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    handle = request.path_params["handle"]
    try:
        body = await request.json()
    except Exception:
        body = {}
    hidden = bool(body.get("hidden", False))
    try:
        set_flag(username, handle, "hidden", hidden)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse({"ok": True, "hidden": hidden})


def get_agent_management_routes() -> list:
    """Return Starlette routes for agent management."""
    return [
        Route("/api/agents/mention-targets", endpoint=_api_mention_targets, methods=["GET"]),
        Route("/api/agents/{handle}/alias", endpoint=_api_set_alias, methods=["PUT"]),
        Route("/api/agents/{handle}/pin", endpoint=_api_set_pin, methods=["PUT"]),
        Route("/api/agents/{handle}/hide", endpoint=_api_set_hide, methods=["PUT"]),
    ]
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
.venv/Scripts/python.exe -m pytest data_agent/test_agent_aliases.py -v
```

预期：全部 13 个测试 PASS。

- [ ] **Step 5: 挂载路由到 frontend_api.py**

在 `data_agent/frontend_api.py` 中：

在 3244 行附近（与其他 `from .api.*_routes import` 同一区块）追加：

```python
    from .api.agent_management_routes import get_agent_management_routes
```

在路由列表末尾（`*annotation_ws_routes,` 之前）追加：

```python
        # Agent Management (v24.1)
        *get_agent_management_routes(),
```

- [ ] **Step 6: 启动验证**

```bash
cd D:/adk && $env:PYTHONPATH="D:\adk"; .venv/Scripts/python.exe -c "from data_agent.frontend_api import get_frontend_api_routes; routes=get_frontend_api_routes(); paths=[r.path for r in routes if hasattr(r,'path') and 'agents' in r.path]; print('\\n'.join(paths))"
```

预期输出：

```
/api/agents/mention-targets
/api/agents/{handle}/alias
/api/agents/{handle}/pin
/api/agents/{handle}/hide
```

- [ ] **Step 7: 提交**

```bash
git add data_agent/api/agent_management_routes.py data_agent/frontend_api.py data_agent/test_agent_aliases.py
git commit -m "feat(api): add 4 agent management REST endpoints (mention-targets, alias, pin, hide)"
```

---

## Task 5: 扩展拓扑 API — mentionable + pipeline_label + custom skills

**Files:**
- Modify: `data_agent/api/topology_routes.py`
- Test: `data_agent/test_topology_enhancements.py`

- [ ] **Step 1: 写失败的测试**

```python
# data_agent/test_topology_enhancements.py
import asyncio
from unittest.mock import patch, MagicMock
from starlette.requests import Request


def _make_request():
    scope = {"type": "http", "method": "GET", "path": "/api/agent-topology",
             "headers": [], "query_string": b"", "path_params": {}}
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    return Request(scope, receive=receive)


def test_topology_includes_mentionable_field():
    from data_agent.api.topology_routes import _api_agent_topology
    resp = asyncio.run(_api_agent_topology(_make_request()))
    import json
    data = json.loads(resp.body.decode())
    # Every agent should have mentionable boolean
    for a in data["agents"]:
        assert "mentionable" in a
        assert isinstance(a["mentionable"], bool)


def test_topology_includes_pipeline_label():
    from data_agent.api.topology_routes import _api_agent_topology
    resp = asyncio.run(_api_agent_topology(_make_request()))
    import json
    data = json.loads(resp.body.decode())
    for a in data["agents"]:
        assert "pipeline_label" in a


def test_topology_mentionable_matches_sub_agents():
    from data_agent.api.topology_routes import _api_agent_topology
    resp = asyncio.run(_api_agent_topology(_make_request()))
    import json
    data = json.loads(resp.body.decode())
    # DataExploration is a mention target
    de = next((a for a in data["agents"] if a["name"] == "DataExploration"), None)
    assert de is not None
    assert de["mentionable"] is True
    # ParallelDataIngestion is a choreography node, NOT mentionable
    pi = next((a for a in data["agents"] if a["name"] == "ParallelDataIngestion"), None)
    if pi is not None:
        assert pi["mentionable"] is False


def test_topology_includes_custom_skills_section():
    from data_agent.api.topology_routes import _api_agent_topology
    fake_custom = [{"id": 1, "skill_name": "MyCustomSkill", "description": "test",
                    "owner_username": "alice", "toolset_names": ["ExplorationToolset"]}]
    with patch("data_agent.api.topology_routes._list_custom_skills_safe", return_value=fake_custom):
        resp = asyncio.run(_api_agent_topology(_make_request()))
    import json
    data = json.loads(resp.body.decode())
    skill_agents = [a for a in data["agents"] if a["type"] == "CustomSkill"]
    assert len(skill_agents) == 1
    assert skill_agents[0]["name"] == "MyCustomSkill"
    assert skill_agents[0]["mentionable"] is True
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
.venv/Scripts/python.exe -m pytest data_agent/test_topology_enhancements.py -v
```

预期：4 个测试 FAIL。

- [ ] **Step 3: 修改 topology_routes.py**

用以下内容替换整个文件：

```python
"""
Agent Topology API — Visualize multi-agent system structure.

Extracts agent hierarchy from agent.py and exposes as JSON for ReactFlow visualization.
"""
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..observability import get_logger

logger = get_logger("topology_api")

# Handles registered as @mention targets (see mention_registry._SUB_AGENT_TARGETS)
_MENTIONABLE_SUB_AGENTS = {
    "DataExploration", "DataProcessing", "DataAnalysis", "DataVisualization",
    "DataSummary", "GovExploration", "GovProcessing", "GovernanceReporter",
    "GeneralProcessing", "GeneralViz",
}

_PIPELINE_META = {
    "DataPipeline": ("OPTIMIZATION", "空间优化 (Optimization)"),
    "GovernancePipeline": ("GOVERNANCE", "数据治理 (Governance)"),
    "GeneralPipeline": ("GENERAL", "通用分析 (General)"),
}


def _extract_toolset_info(tool):
    """Extract toolset metadata from an ADK tool/toolset object."""
    cls = tool.__class__
    name = cls.__name__
    tool_count = 0
    for attr_name in dir(tool):
        if attr_name.startswith('_'):
            continue
        attr = getattr(tool, attr_name, None)
        if callable(attr) and attr_name not in ('get_tools', 'close'):
            tool_count += 1
    doc = (cls.__doc__ or '').strip().split('\n')[0]
    return {'name': name, 'description': doc, 'tool_count': tool_count}


def _extract_agents(agent, parent_id, agents_out, toolsets_out, seen_toolsets, pipeline_label):
    """Recursively extract agent hierarchy with pipeline_label propagated from root."""
    agent_id = getattr(agent, 'name', str(id(agent)))
    agent_type = agent.__class__.__name__

    # Root of a pipeline? override pipeline_label
    if agent_id in _PIPELINE_META:
        pipeline_label = _PIPELINE_META[agent_id][1]

    tools = []
    agent_tools = getattr(agent, 'tools', None)
    if agent_tools:
        for tool in agent_tools:
            ts_name = tool.__class__.__name__
            tools.append(ts_name)
            if ts_name not in seen_toolsets:
                seen_toolsets.add(ts_name)
                toolsets_out.append(_extract_toolset_info(tool))

    model = None
    if hasattr(agent, 'model') and agent.model:
        model = str(agent.model)

    instruction = None
    if hasattr(agent, 'instruction') and agent.instruction:
        inst = agent.instruction
        if callable(inst):
            inst = "(dynamic)"
        elif len(inst) > 120:
            inst = inst[:120] + '...'
        instruction = inst

    children = []
    sub_agents = getattr(agent, 'sub_agents', None)
    if sub_agents:
        for child in sub_agents:
            child_id = _extract_agents(child, agent_id, agents_out, toolsets_out,
                                       seen_toolsets, pipeline_label)
            children.append(child_id)

    mentionable = agent_id in _MENTIONABLE_SUB_AGENTS or agent_id in _PIPELINE_META

    agents_out.append({
        'id': agent_id,
        'name': agent_id,
        'type': agent_type,
        'parent_id': parent_id,
        'tools': tools,
        'children': children,
        'model': model,
        'instruction_snippet': instruction,
        'mentionable': mentionable,
        'pipeline_label': pipeline_label or "",
    })

    return agent_id


def _list_custom_skills_safe():
    """Return list of custom skills (empty on failure)."""
    try:
        from ..custom_skills import list_custom_skills
        return list_custom_skills(include_shared=True)
    except Exception:
        return []


def _append_custom_skill_agents(agents_out):
    """Append custom skill entries to agents list as synthetic top-level agents."""
    for skill in _list_custom_skills_safe():
        name = skill.get("skill_name") or f"custom_{skill.get('id', '?')}"
        tools = list(skill.get("toolset_names") or [])
        agents_out.append({
            'id': f"custom_{skill.get('id')}",
            'name': name,
            'type': 'CustomSkill',
            'parent_id': None,
            'tools': tools,
            'children': [],
            'model': skill.get("model_tier"),
            'instruction_snippet': (skill.get("description") or "")[:120],
            'mentionable': True,
            'pipeline_label': "自定义技能 (Custom Skills)",
        })


async def _api_agent_topology(request: Request):
    """GET /api/agent-topology — return full agent hierarchy with Custom Skills."""
    try:
        from data_agent.agent import (
            data_pipeline, governance_pipeline, general_pipeline,
        )

        agents = []
        toolsets = []
        seen = set()

        _extract_agents(data_pipeline, None, agents, toolsets, seen, None)
        _extract_agents(governance_pipeline, None, agents, toolsets, seen, None)
        _extract_agents(general_pipeline, None, agents, toolsets, seen, None)
        _append_custom_skill_agents(agents)

        return JSONResponse(content={
            'agents': agents,
            'toolsets': toolsets,
            'pipelines': [
                {'id': data_pipeline.name, 'label': 'Optimization Pipeline (空间优化)', 'color': '#3b82f6'},
                {'id': governance_pipeline.name, 'label': 'Governance Pipeline (数据治理)', 'color': '#f59e0b'},
                {'id': general_pipeline.name, 'label': 'General Pipeline (通用分析)', 'color': '#10b981'},
                {'id': 'CustomSkills', 'label': '自定义技能', 'color': '#a855f7'},
            ],
        })
    except Exception as e:
        logger.error("Agent topology error: %s", e)
        return JSONResponse(content={'error': str(e)}, status_code=500)


def get_topology_routes():
    return [
        Route("/api/agent-topology", endpoint=_api_agent_topology, methods=["GET"]),
    ]
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
.venv/Scripts/python.exe -m pytest data_agent/test_topology_enhancements.py data_agent/test_topology_api.py -v
```

预期：新测试 4 个 PASS，旧测试无回归。

- [ ] **Step 5: 提交**

```bash
git add data_agent/api/topology_routes.py data_agent/test_topology_enhancements.py
git commit -m "feat(topology): add mentionable + pipeline_label + custom skills to agent-topology API"
```

---

## Task 6: 前端 — AgentsTab 组件（骨架 + 列表）

**Files:**
- Create: `frontend/src/components/datapanel/AgentsTab.tsx`

- [ ] **Step 1: 创建 AgentsTab 骨架**

```tsx
// frontend/src/components/datapanel/AgentsTab.tsx
import { useState, useEffect, useMemo, useCallback } from 'react';
import { Search, Pin, EyeOff, Eye } from 'lucide-react';

interface MentionTarget {
  handle: string;
  label: string;
  display_name: string;
  aliases: string[];
  pinned: boolean;
  hidden: boolean;
  type: 'pipeline' | 'sub_agent' | 'adk_skill' | 'custom_skill';
  description: string;
  allowed: boolean;
  pipeline?: string;
}

type FilterKey = 'all' | 'pipeline' | 'sub_agent' | 'adk_skill' | 'custom_skill';

const TYPE_LABELS: Record<string, string> = {
  pipeline: '流水线',
  sub_agent: '子智能体',
  adk_skill: '内置技能',
  custom_skill: '自定义技能',
};

const TYPE_COLORS: Record<string, string> = {
  pipeline: '#3b82f6',
  sub_agent: '#10b981',
  adk_skill: '#f59e0b',
  custom_skill: '#a855f7',
};

export default function AgentsTab() {
  const [targets, setTargets] = useState<MentionTarget[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<FilterKey>('all');
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);

  const fetchTargets = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await fetch('/api/agents/mention-targets?include_hidden=1', { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setTargets(data.targets || []);
      }
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchTargets(); }, [fetchTargets]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return targets.filter(t => {
      if (filter !== 'all' && t.type !== filter) return false;
      if (!q) return true;
      if (t.handle.toLowerCase().includes(q)) return true;
      if (t.display_name.toLowerCase().includes(q)) return true;
      if (t.aliases.some(a => a.toLowerCase().includes(q))) return true;
      return false;
    });
  }, [targets, filter, search]);

  if (loading) return <div className="empty-state">加载中...</div>;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: 12 }}>
      {/* Toolbar */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
        <div style={{ position: 'relative', flex: 1 }}>
          <Search size={14} style={{ position: 'absolute', left: 8, top: 8, color: '#9ca3af' }} />
          <input
            type="text" placeholder="搜索 handle / 显示名 / 别名"
            value={search} onChange={e => setSearch(e.target.value)}
            style={{
              width: '100%', padding: '6px 8px 6px 28px', fontSize: 12,
              border: '1px solid #e5e7eb', borderRadius: 4,
            }}
          />
        </div>
        <span style={{ fontSize: 11, color: '#9ca3af' }}>
          {filtered.length} / {targets.length}
        </span>
      </div>

      {/* Filter chips */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
        {(['all', 'pipeline', 'sub_agent', 'adk_skill', 'custom_skill'] as FilterKey[]).map(k => (
          <button key={k} onClick={() => setFilter(k)}
            style={{
              padding: '3px 10px', fontSize: 11, border: '1px solid #e5e7eb',
              borderRadius: 12, cursor: 'pointer',
              background: filter === k ? '#3b82f6' : '#fff',
              color: filter === k ? '#fff' : '#374151',
            }}>
            {k === 'all' ? '全部' : TYPE_LABELS[k]}
          </button>
        ))}
      </div>

      {/* List */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {filtered.map(t => (
          <AgentCard
            key={t.handle} target={t}
            expanded={expanded === t.handle}
            onToggle={() => setExpanded(expanded === t.handle ? null : t.handle)}
            onChanged={fetchTargets}
          />
        ))}
        {filtered.length === 0 && (
          <div className="empty-state" style={{ padding: 24 }}>无匹配项</div>
        )}
      </div>
    </div>
  );
}

interface AgentCardProps {
  target: MentionTarget;
  expanded: boolean;
  onToggle: () => void;
  onChanged: () => void;
}

function AgentCard({ target, expanded, onToggle, onChanged }: AgentCardProps) {
  const [aliasInput, setAliasInput] = useState(target.aliases.join(', '));
  const [displayName, setDisplayName] = useState(target.display_name);
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      const aliases = aliasInput.split(',').map(a => a.trim()).filter(Boolean);
      await fetch(`/api/agents/${encodeURIComponent(target.handle)}/alias`, {
        method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ aliases, display_name: displayName }),
      });
      onChanged();
    } finally { setSaving(false); }
  };

  const togglePin = async () => {
    await fetch(`/api/agents/${encodeURIComponent(target.handle)}/pin`, {
      method: 'PUT', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pinned: !target.pinned }),
    });
    onChanged();
  };

  const toggleHide = async () => {
    await fetch(`/api/agents/${encodeURIComponent(target.handle)}/hide`, {
      method: 'PUT', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hidden: !target.hidden }),
    });
    onChanged();
  };

  const color = TYPE_COLORS[target.type] || '#6b7280';

  return (
    <div style={{
      border: '1px solid #e5e7eb', borderRadius: 6, marginBottom: 8,
      background: target.hidden ? '#f9fafb' : '#fff',
      opacity: target.hidden ? 0.6 : 1,
    }}>
      <div onClick={onToggle} style={{
        padding: '8px 12px', cursor: 'pointer',
        display: 'flex', alignItems: 'center', gap: 8,
      }}>
        {target.pinned && <Pin size={12} color="#f59e0b" />}
        <span style={{
          background: color, color: '#fff', fontSize: 9, fontWeight: 600,
          padding: '1px 6px', borderRadius: 3,
        }}>{TYPE_LABELS[target.type]}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12, fontWeight: 600 }}>
            {target.display_name || target.handle}
          </div>
          <div style={{ fontSize: 10, color: '#9ca3af' }}>
            @{target.handle}
            {target.aliases.length > 0 && ` · 别名: ${target.aliases.join(', ')}`}
          </div>
        </div>
        <button onClick={e => { e.stopPropagation(); togglePin(); }}
          title={target.pinned ? '取消置顶' : '置顶'}
          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}>
          <Pin size={14} color={target.pinned ? '#f59e0b' : '#9ca3af'} />
        </button>
        <button onClick={e => { e.stopPropagation(); toggleHide(); }}
          title={target.hidden ? '显示' : '隐藏'}
          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}>
          {target.hidden ? <EyeOff size={14} color="#9ca3af" /> : <Eye size={14} color="#9ca3af" />}
        </button>
      </div>

      {expanded && (
        <div style={{ borderTop: '1px solid #f3f4f6', padding: '8px 12px', background: '#fafafa' }}>
          <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 6 }}>
            {target.description || '（无描述）'}
          </div>
          <label style={{ fontSize: 10, color: '#374151', display: 'block', marginTop: 6 }}>
            显示名（中文）
          </label>
          <input value={displayName} onChange={e => setDisplayName(e.target.value)}
            placeholder="例：数据探查"
            style={{ width: '100%', padding: '4px 6px', fontSize: 11,
                     border: '1px solid #e5e7eb', borderRadius: 3 }} />
          <label style={{ fontSize: 10, color: '#374151', display: 'block', marginTop: 6 }}>
            别名（逗号分隔）
          </label>
          <input value={aliasInput} onChange={e => setAliasInput(e.target.value)}
            placeholder="例：探查, 数据探查"
            style={{ width: '100%', padding: '4px 6px', fontSize: 11,
                     border: '1px solid #e5e7eb', borderRadius: 3 }} />
          <button onClick={handleSave} disabled={saving}
            style={{ marginTop: 8, padding: '4px 12px', fontSize: 11,
                     background: '#3b82f6', color: '#fff', border: 'none',
                     borderRadius: 3, cursor: 'pointer' }}>
            {saving ? '保存中...' : '保存'}
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/components/datapanel/AgentsTab.tsx
git commit -m "feat(frontend): add AgentsTab component for alias/pin/hide management"
```

---

## Task 7: 注册 AgentsTab 到 DataPanel

**Files:**
- Modify: `frontend/src/components/DataPanel.tsx`

- [ ] **Step 1: 在 DataPanel.tsx 顶部追加 import（第 35 行附近）**

定位：

```tsx
import TopologyTab from './datapanel/TopologyTab';
```

在其后添加：

```tsx
import AgentsTab from './datapanel/AgentsTab';
```

- [ ] **Step 2: 扩展 TabKey 类型（约第 46 行）**

将：

```tsx
type TabKey = 'files' | ... | 'standards';
```

改为（在 `'standards'` 之后追加 `| 'agents'`）：

```tsx
type TabKey = 'files' | ... | 'standards' | 'agents';
```

- [ ] **Step 3: 在 '智能分析' group 的 tabs 列表追加（约第 85 行）**

定位 `'intelligence'` group 的最后一个 tab（`standards`），其后追加：

```tsx
      { key: 'agents', label: '智能体', icon: <Network size={ICON_SIZE} /> },
```

（Network 已在顶部 import 中。）

- [ ] **Step 4: 在 render 区域追加 tab 渲染（约第 220 行附近）**

定位：

```tsx
{activeTab === 'topology' && <TopologyTab />}
```

在其后添加：

```tsx
{activeTab === 'agents' && <AgentsTab />}
```

- [ ] **Step 5: 构建验证**

```bash
cd D:/adk/frontend && npm run build
```

预期：build 成功，无 TS 错误。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/components/DataPanel.tsx
git commit -m "feat(frontend): register AgentsTab in DataPanel intelligence group"
```

---

## Task 8: ChatPanel mention dropdown 接入新 API + 别名匹配

**Files:**
- Modify: `frontend/src/components/ChatPanel.tsx`

- [ ] **Step 1: 扩展 MentionTarget 类型并切换 API（第 52-60 行附近）**

替换：

```tsx
  const [mentionTargets, setMentionTargets] = useState<Array<{
    handle: string; label: string; type: string;
    description: string; allowed: boolean;
  }>>([]);
```

为：

```tsx
  const [mentionTargets, setMentionTargets] = useState<Array<{
    handle: string; label: string; type: string;
    description: string; allowed: boolean;
    display_name: string; aliases: string[]; pinned: boolean; hidden: boolean;
  }>>([]);
```

- [ ] **Step 2: 切换 fetch URL（第 264 行）**

将：

```tsx
      const resp = await fetch('/api/chat/mention-targets', { credentials: 'include' });
```

改为：

```tsx
      const resp = await fetch('/api/agents/mention-targets', { credentials: 'include' });
```

- [ ] **Step 3: 扩展匹配逻辑（第 174、510、527 行共 3 处）**

定义一个匹配函数（在 `fetchMentionTargets` 之上新增，第 261 行前）：

```tsx
  const matchTarget = useCallback((t: {
    handle: string; display_name: string; aliases: string[]; hidden: boolean; allowed: boolean;
  }, q: string) => {
    if (t.hidden || !t.allowed) return false;
    if (!q) return true;
    if (t.handle.toLowerCase().includes(q)) return true;
    if (t.display_name && t.display_name.toLowerCase().includes(q)) return true;
    if (t.aliases && t.aliases.some(a => a.toLowerCase().includes(q))) return true;
    return false;
  }, []);
```

**替换 3 处过滤：**

（1）第 174 行附近：

```tsx
      const filtered = mentionTargets.filter(t =>
        t.handle.toLowerCase().includes(mentionFilter) && t.allowed
      );
```

改为：

```tsx
      const filtered = mentionTargets.filter(t => matchTarget(t, mentionFilter));
```

（2）第 510 行附近（dropdown filter）：

```tsx
                .filter(t => t.handle.toLowerCase().includes(mentionFilter) && t.allowed)
```

改为：

```tsx
                .filter(t => matchTarget(t, mentionFilter))
                .sort((a, b) => (a.pinned === b.pinned ? 0 : a.pinned ? -1 : 1))
```

（3）第 527 行附近（empty check）：

```tsx
              {mentionTargets.filter(t => t.handle.toLowerCase().includes(mentionFilter) && t.allowed).length === 0 && (
```

改为：

```tsx
              {mentionTargets.filter(t => matchTarget(t, mentionFilter)).length === 0 && (
```

- [ ] **Step 4: dropdown item 显示 display_name（第 522-524 行附近）**

定位：

```tsx
                    <span className="mention-handle">@{t.handle}</span>
                    <span className="mention-type">{t.type}</span>
                    <span className="mention-desc">{t.description}</span>
```

改为：

```tsx
                    <span className="mention-handle">@{t.display_name || t.handle}</span>
                    <span className="mention-type">{t.type}</span>
                    <span className="mention-desc">
                      {t.aliases && t.aliases.length > 0
                        ? `${t.description} · 别名: ${t.aliases.join(', ')}`
                        : t.description}
                    </span>
```

**注意：** 点击选项时插入的字符串保持为 `@${selected.handle}`（handle 才是系统识别的唯一 ID，别名/display_name 仅用于 UI 展示）。

- [ ] **Step 5: 构建验证**

```bash
cd D:/adk/frontend && npm run build
```

预期：build 成功。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/components/ChatPanel.tsx
git commit -m "feat(chat): switch mention dropdown to /api/agents/mention-targets with alias match + pinned sort"
```

---

## Task 9: 精简 TopologyTab 节点 + 增强详情面板 + 刷新按钮

**Files:**
- Modify: `frontend/src/components/datapanel/TopologyTab.tsx`

- [ ] **Step 1: 扩展 AgentInfo interface（第 21-30 行）**

替换：

```tsx
interface AgentInfo {
  id: string;
  name: string;
  type: string;
  parent_id: string | null;
  tools: string[];
  children: string[];
  model?: string;
  instruction_snippet?: string;
}
```

为：

```tsx
interface AgentInfo {
  id: string;
  name: string;
  type: string;
  parent_id: string | null;
  tools: string[];
  children: string[];
  model?: string;
  instruction_snippet?: string;
  mentionable?: boolean;
  pipeline_label?: string;
}
```

- [ ] **Step 2: 精简 AgentNode 组件（第 76-117 行）**

替换整个 `AgentNode` 函数：

```tsx
function AgentNode({ data }: NodeProps) {
  const d = data as any;
  const color = getTypeColor(d.agentType);
  return (
    <div style={{
      background: '#fff',
      border: `2px solid ${color}`,
      borderRadius: 6,
      padding: '6px 10px',
      minWidth: 100,
      fontSize: 11,
      boxShadow: '0 1px 3px rgba(0,0,0,.1)',
    }}>
      <Handle type="target" position={Position.Top} style={{ background: color }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
        <span style={{
          background: color, color: '#fff', borderRadius: 3,
          padding: '0 4px', fontSize: 8, fontWeight: 600,
        }}>
          {getTypeLabel(d.agentType)}
        </span>
        <span style={{ fontWeight: 600, fontSize: 11 }}>{d.label}</span>
        {d.mentionable && (
          <span style={{ color: '#10b981', fontSize: 10, fontWeight: 700 }}>@</span>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} style={{ background: color }} />
    </div>
  );
}
```

- [ ] **Step 3: 缩小 layout 参数（第 170-171 行）**

替换：

```tsx
  const COL_WIDTH = 280;
  const ROW_HEIGHT = 90;
```

为：

```tsx
  const COL_WIDTH = 200;
  const ROW_HEIGHT = 75;
```

- [ ] **Step 4: 节点 data 传入 mentionable / pipeline_label（第 184-190 行 + 219-225 行 2 处）**

两处 `data:` 对象追加两个字段：

```tsx
        data: {
          label: agent.name,
          agentType: agent.type,
          tools: agent.tools,
          model: agent.model,
          instruction_snippet: agent.instruction_snippet,
          mentionable: agent.mentionable,
          pipeline_label: agent.pipeline_label,
        },
```

（对两处 `data:` 对象做同样的追加。）

- [ ] **Step 5: 添加刷新按钮 + 重构 fetch 为 useCallback（第 251-276 行附近）**

替换 useState/useEffect 块和 handleNodeClick 块：

```tsx
export default function TopologyTab() {
  const [data, setData] = useState<TopologyData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<AgentInfo | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [instrExpanded, setInstrExpanded] = useState(false);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  const loadTopology = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch('/api/agent-topology', { credentials: 'include' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const json: TopologyData = await resp.json();
      setData(json);
      const layout = layoutHierarchy(json.agents, json.pipelines);
      setNodes(layout.nodes);
      setEdges(layout.edges);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [setNodes, setEdges]);

  useEffect(() => { loadTopology(); }, [loadTopology]);

  const handleNodeClick = useCallback((_: any, node: Node) => {
    if (data) {
      const agent = data.agents.find(a => a.id === node.id);
      if (agent) {
        setSelectedAgent(agent);
        setInstrExpanded(false);
      }
    }
  }, [data]);
```

- [ ] **Step 6: 在 legend 栏加入刷新按钮（第 325 行附近）**

定位现有的"全屏"按钮 `<button onClick={() => setFullscreen(!fullscreen)} ...>`，在其**前**插入：

```tsx
        <button
          onClick={loadTopology}
          disabled={loading}
          style={{
            background: '#f3f4f6', color: '#374151', border: '1px solid #e5e7eb',
            borderRadius: 4, padding: '2px 8px', fontSize: 11, cursor: 'pointer',
            marginRight: 4,
          }}
          title="刷新拓扑"
        >
          {loading ? '刷新中...' : '刷新'}
        </button>
```

- [ ] **Step 7: 替换详情面板（第 364-399 行）**

替换整个 `{selectedAgent && ( ... )}` 块：

```tsx
      {/* Detail panel */}
      {selectedAgent && (
        <div style={{
          borderTop: '1px solid #e5e7eb', padding: '10px 14px', background: '#f9fafb',
          fontSize: 11, maxHeight: 200, overflowY: 'auto',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontWeight: 700, fontSize: 13 }}>{selectedAgent.name}</span>
              <span style={{
                background: getTypeColor(selectedAgent.type), color: '#fff', fontSize: 9,
                fontWeight: 600, padding: '1px 6px', borderRadius: 3,
              }}>
                {getTypeLabel(selectedAgent.type)}
              </span>
              {selectedAgent.pipeline_label && (
                <span style={{
                  background: '#eef2ff', color: '#4338ca', fontSize: 9,
                  padding: '1px 6px', borderRadius: 3, border: '1px solid #c7d2fe',
                }}>
                  {selectedAgent.pipeline_label}
                </span>
              )}
              {selectedAgent.mentionable && (
                <span style={{
                  background: '#d1fae5', color: '#065f46', fontSize: 9,
                  padding: '1px 6px', borderRadius: 3, border: '1px solid #a7f3d0',
                }}>
                  可 @ 调用
                </span>
              )}
            </div>
            <button onClick={() => setSelectedAgent(null)}
              style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9ca3af', fontSize: 14 }}>
              ✕
            </button>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '80px 1fr', gap: '4px 8px' }}>
            <span style={{ color: '#6b7280' }}>类型</span>
            <span>{selectedAgent.type}</span>
            {selectedAgent.model && <>
              <span style={{ color: '#6b7280' }}>模型</span>
              <span>{selectedAgent.model}</span>
            </>}
            <span style={{ color: '#6b7280' }}>工具集</span>
            <span>
              {selectedAgent.tools.length > 0
                ? selectedAgent.tools.map(t => t.replace('Toolset', '')).join(', ')
                : '无'}
            </span>
            <span style={{ color: '#6b7280' }}>子节点</span>
            <span>
              {selectedAgent.children.length > 0
                ? selectedAgent.children.map(cid => (
                    <button key={cid}
                      onClick={() => {
                        const child = data?.agents.find(a => a.id === cid);
                        if (child) { setSelectedAgent(child); setInstrExpanded(false); }
                      }}
                      style={{
                        background: '#f3f4f6', border: '1px solid #e5e7eb',
                        borderRadius: 3, padding: '1px 5px', margin: '0 3px 2px 0',
                        fontSize: 10, cursor: 'pointer',
                      }}>
                      {cid}
                    </button>
                  ))
                : '无'}
            </span>
          </div>
          {selectedAgent.instruction_snippet && (
            <div style={{ marginTop: 6 }}>
              <button onClick={() => setInstrExpanded(v => !v)}
                style={{
                  background: 'none', border: 'none', color: '#3b82f6',
                  cursor: 'pointer', fontSize: 10, padding: 0,
                }}>
                {instrExpanded ? '▼ 收起指令' : '▶ 展开指令摘要'}
              </button>
              {instrExpanded && (
                <div style={{ marginTop: 4, padding: '6px 8px', background: '#fff',
                              borderRadius: 4, fontSize: 10, color: '#4b5563',
                              border: '1px solid #e5e7eb', whiteSpace: 'pre-wrap' }}>
                  {selectedAgent.instruction_snippet}
                </div>
              )}
            </div>
          )}
        </div>
      )}
```

- [ ] **Step 8: 构建验证**

```bash
cd D:/adk/frontend && npm run build
```

预期：build 成功，无 TS 错误。

- [ ] **Step 9: 手动冒烟测试**

启动 app：

```bash
cd D:/adk && $env:PYTHONPATH="D:\adk"; chainlit run data_agent/app.py -w
```

在浏览器 DataPanel 打开"拓扑" tab，确认：
- 节点只显示类型 badge + 名称（可 @ 的节点显示 `@` 绿色标记）
- 节点之间间距变紧凑
- 点击节点下方详情面板显示完整信息（类型/模型/工具集/子节点/pipeline 标签）
- 点击详情面板里的子节点 chip 切换选中
- 点击"刷新"按钮重新加载
- "指令摘要"按钮点击可折叠展开

- [ ] **Step 10: 提交**

```bash
git add frontend/src/components/datapanel/TopologyTab.tsx
git commit -m "feat(topology): slim nodes + enhanced detail panel + refresh button + mentionable badge"
```

---

## Task 10: 端到端冒烟测试 + 文档更新

**Files:**
- Modify: `CLAUDE.md` (可选：更新 endpoint 数和版本号)

- [ ] **Step 1: 运行后端全量测试**

```bash
cd D:/adk && $env:PYTHONPATH="D:\adk"; .venv/Scripts/python.exe -m pytest data_agent/test_agent_aliases.py data_agent/test_topology_enhancements.py data_agent/test_topology_api.py data_agent/test_mention_routing.py -v
```

预期：全部 PASS，无回归。

- [ ] **Step 2: 前端构建**

```bash
cd D:/adk/frontend && npm run build
```

预期：成功。

- [ ] **Step 3: 手动 UI 测试清单**

启动 app，登录后：

1. 打开 DataPanel → 智能分析组 → "智能体" tab
   - 顶部搜索框可用，分组筛选按钮可切换
   - 点击卡片展开编辑区
   - 输入别名和显示名，点击"保存" → 列表刷新，显示别名
   - 点击 pin 图标 → 卡片置顶
   - 点击眼睛图标 → 卡片变灰（hidden）
2. 打开 DataPanel → 数据资源组 → "拓扑" tab
   - 节点紧凑，只有 badge + 名称
   - 可 @ 调用节点有绿色 `@` 标记
   - 点击节点 → 详情面板显示完整信息
   - 点击子节点 chip → 切换选中
   - 点击刷新按钮 → 重新加载
3. 在聊天框输入 `@` → dropdown 显示设了别名的智能体（显示 display_name）
4. 在聊天框输入 `@探查` → dropdown 过滤出 DataExploration
5. 隐藏的智能体不在 dropdown 中出现

- [ ] **Step 4: 更新 CLAUDE.md endpoint 计数（可选）**

定位 CLAUDE.md 中 `Frontend API (123 REST endpoints ...)` 附近的行，将 123 更新为 127（新增 4 个），或跳过该步。

- [ ] **Step 5: 提交最终修订（如有）**

```bash
git status
# 如有修改：
git add -A && git commit -m "docs: update endpoint count for agent management routes"
```

- [ ] **Step 6: 功能验收**

确认以下 spec 条目全部完成：

- [x] §1.1 agent_aliases 表建表（Task 1）
- [x] §1.2 4 个 REST 端点（Task 4）
- [x] §1.3 mention_registry 别名合并 + lookup 优先级（Task 3）
- [x] §1.4 AgentsTab 前端 UI（Task 6 + 7）
- [x] §1.5 ChatPanel dropdown 联动 + 别名匹配 + pinned 排序（Task 8）
- [x] §2.1 节点精简（Task 9 Step 2）
- [x] §2.2 布局参数调整（Task 9 Step 3）
- [x] §2.3 详情面板增强（Task 9 Step 7）
- [x] §2.4 刷新按钮 + mentionable + pipeline_label + custom skills（Task 5 + Task 9 Step 6）
- [x] §2.5 子节点点击跳转（Task 9 Step 7）

---

## Self-Review Notes

**Spec coverage:** 全部 spec 条目（§1.1-1.5, §2.1-2.5）映射到 Task 1-9；Task 10 做集成验证。

**Scope guardrails（spec §4 "不做的事"）:**
- 别名按用户隔离（Task 1 unique 约束 `(handle, user_id)`）
- 不做拓扑折叠展开
- 编排节点 `mentionable=false`（Task 5 `_MENTIONABLE_SUB_AGENTS` 白名单）
- 同用户内 `(handle, user_id)` unique 即可，不跨用户冲突检测

**Type consistency check:**
- 后端字段命名：`handle, aliases, display_name, pinned, hidden` — Task 1/2/3/4 一致
- 前端 `MentionTarget` interface — Task 6 (AgentsTab) 与 Task 8 (ChatPanel) 相同
- `mentionable, pipeline_label` — Task 5 后端 + Task 9 前端一致
- `lookup()` 优先级：handle > display_name > alias — Task 3 实现与 spec §1.3 一致
- mention 点击插入的字符串始终是 `handle`（后端唯一 ID），display_name 仅展示用 — Task 8 Step 4 显式说明

**Ambiguity resolved:**
- spec 说 migration 064，这里用实际下一个可用编号 058（基于 `ls migrations/`）
- API 路径前缀统一为 `/api/agents/*`（spec §1.2 如此）
- `/api/chat/mention-targets` 保留不删，新端点 `/api/agents/mention-targets` 作为别名感知版（Task 8 只切换 ChatPanel 一处使用）
