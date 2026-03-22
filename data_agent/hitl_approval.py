"""
Human-in-the-Loop (HITL) Approval Plugin for GIS Data Agent.

Uses ADK BasePlugin.before_tool_callback() to intercept high-risk tool
calls before execution.  In a Chainlit session the user sees an approval
dialog; in evaluation / test mode the call is auto-approved.

Environment variables
---------------------
HITL_ENABLED        : "true" (default) or "false"
HITL_BLOCK_LEVEL    : minimum level that triggers blocking approval
                      "critical" (default) | "high" | "medium"
HITL_TIMEOUT        : seconds to wait for user response (default 120)
"""

from __future__ import annotations

import os
from enum import IntEnum
from typing import Any, Callable, Optional

from google.adk.plugins.base_plugin import BasePlugin

# ---------------------------------------------------------------------------
# Risk level enumeration
# ---------------------------------------------------------------------------

class RiskLevel(IntEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3


# ---------------------------------------------------------------------------
# Risk registry — maps tool names to risk metadata
# ---------------------------------------------------------------------------

_RISK_REGISTRY: dict[str, dict[str, Any]] = {
    # CRITICAL — destructive DB / model operations
    "import_to_postgis": {
        "level": RiskLevel.CRITICAL,
        "description": "将空间数据导入 PostGIS 数据库",
        "impact": "写入数据库表 {table}",
        "escalation_rules": [
            {"condition": lambda args: str(args.get("if_exists", "")).lower() == "replace",
             "extra_warning": "if_exists=replace 将先删除现有表再重建，原有数据将丢失！"},
        ],
    },
    "optimize_land_use_drl": {
        "level": RiskLevel.CRITICAL,
        "description": "运行深度强化学习优化土地利用布局",
        "impact": "DRL 模型将修改地块分类属性",
    },
    "delete_user_file": {
        "level": RiskLevel.CRITICAL,
        "description": "删除用户文件（本地及云端）",
        "impact": "永久删除文件 {file_path}",
    },
    # HIGH — field / sharing / team mutations
    "add_field": {
        "level": RiskLevel.HIGH,
        "description": "向要素类添加新字段",
        "impact": "添加字段 {field_name}",
    },
    "calculate_field": {
        "level": RiskLevel.HIGH,
        "description": "批量计算并覆盖字段值",
        "impact": "覆盖字段 {field_name} 的值",
    },
    "share_table": {
        "level": RiskLevel.HIGH,
        "description": "将数据表设为公开共享",
        "impact": "共享表 {table_name}",
    },
    "delete_team": {
        "level": RiskLevel.HIGH,
        "description": "删除团队及所有成员关系",
        "impact": "删除团队 {team_name}",
    },
    "remove_from_team": {
        "level": RiskLevel.HIGH,
        "description": "从团队中移除成员",
        "impact": "从团队移除 {username}",
    },
    # MEDIUM — catalog / memory / semantic mutations
    "delete_data_asset": {
        "level": RiskLevel.MEDIUM,
        "description": "删除数据目录中的资产记录",
        "impact": "删除资产 {asset_id}",
    },
    "delete_memory": {
        "level": RiskLevel.MEDIUM,
        "description": "删除空间记忆条目",
        "impact": "删除记忆 {memory_id}",
    },
    "delete_template": {
        "level": RiskLevel.MEDIUM,
        "description": "删除分析模板",
        "impact": "删除模板 {template_id}",
    },
    "register_semantic_annotation": {
        "level": RiskLevel.MEDIUM,
        "description": "修改语义本体注解",
        "impact": "注册语义注解",
    },
    "register_semantic_domain": {
        "level": RiskLevel.MEDIUM,
        "description": "注册新的语义域",
        "impact": "注册语义域 {domain_name}",
    },
}


def get_risk_registry() -> dict[str, dict[str, Any]]:
    """Return a shallow copy of the risk registry (for testing / inspection)."""
    return dict(_RISK_REGISTRY)


# ---------------------------------------------------------------------------
# Risk assessment
# ---------------------------------------------------------------------------

def assess_risk(tool_name: str, tool_args: dict) -> Optional[dict]:
    """Evaluate the risk of a tool call.

    Returns ``None`` if the tool is not in the registry, otherwise a dict::

        {
            "tool": str,
            "level": RiskLevel,
            "description": str,
            "impact": str,          # with arg interpolation
            "extra_warnings": list[str],
        }
    """
    entry = _RISK_REGISTRY.get(tool_name)
    if entry is None:
        return None

    impact_template = entry.get("impact", "")
    try:
        impact = impact_template.format(**tool_args)
    except (KeyError, IndexError):
        impact = impact_template

    extra_warnings: list[str] = []
    for rule in entry.get("escalation_rules", []):
        try:
            if rule["condition"](tool_args):
                extra_warnings.append(rule["extra_warning"])
        except Exception:
            pass

    return {
        "tool": tool_name,
        "level": entry["level"],
        "description": entry["description"],
        "impact": impact,
        "extra_warnings": extra_warnings,
    }


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

def _parse_block_level() -> RiskLevel:
    raw = os.environ.get("HITL_BLOCK_LEVEL", "critical").strip().lower()
    mapping = {"low": RiskLevel.LOW, "medium": RiskLevel.MEDIUM,
               "high": RiskLevel.HIGH, "critical": RiskLevel.CRITICAL}
    return mapping.get(raw, RiskLevel.CRITICAL)


HITL_ENABLED: bool = os.environ.get("HITL_ENABLED", "true").strip().lower() not in ("false", "0", "no")


# ---------------------------------------------------------------------------
# HITL Approval Plugin
# ---------------------------------------------------------------------------

class HITLApprovalPlugin(BasePlugin):
    """ADK plugin that intercepts high-risk tools for human approval.

    Integration::

        plugin = HITLApprovalPlugin()
        plugin.set_approval_function(my_async_fn)
        runner = Runner(..., plugins=[plugin])

    The approval function signature::

        async def approval_fn(content: str) -> object | None

    It should return an object with ``payload["value"]`` equal to
    ``"APPROVE"`` or ``"REJECT"``, or ``None`` on timeout.
    """

    def __init__(self) -> None:
        super().__init__(name="hitl_approval")
        self._approval_fn: Optional[Callable] = None
        self._block_level: RiskLevel = _parse_block_level()

    # -- Dependency injection --------------------------------------------------

    def set_approval_function(self, fn: Optional[Callable]) -> None:
        """Inject the async UI approval function (e.g. Chainlit AskActionMessage)."""
        self._approval_fn = fn

    # -- BasePlugin callback ---------------------------------------------------

    async def before_tool_callback(
        self,
        *,
        tool: Any,
        tool_args: dict,
        tool_context: Any,
    ) -> Optional[dict]:
        """Intercept tool execution for HITL approval.

        Returns ``None`` to allow execution, or a ``dict`` to block it.
        """
        if not HITL_ENABLED:
            return None

        tool_name = tool.name if hasattr(tool, "name") else str(tool)
        risk = assess_risk(tool_name, tool_args)
        if risk is None:
            return None

        # Below blocking threshold — log only, allow
        if risk["level"] < self._block_level:
            self._record_audit(tool_name, tool_args, risk, "auto_approved", "below_threshold")
            return None

        # No approval function (eval / test mode) — auto-approve
        if self._approval_fn is None:
            self._record_audit(tool_name, tool_args, risk, "auto_approved", "no_approval_fn")
            return None

        # Build approval message
        message = self._build_approval_message(risk)

        # Call the async approval function
        try:
            response = await self._approval_fn(message)
        except Exception as exc:
            # Approval mechanism failed — degrade to auto-approve
            print(f"[HITL] Approval function error, auto-approving: {exc}")
            self._record_audit(tool_name, tool_args, risk, "auto_approved", "approval_error")
            return None

        # Timeout — AskActionMessage returns None
        if response is None:
            self._record_audit(tool_name, tool_args, risk, "auto_approved", "timeout")
            return None

        # Parse response
        value = _extract_action_value(response)
        if value == "APPROVE":
            self._record_audit(tool_name, tool_args, risk, "approved", "user")
            return None
        else:
            self._record_audit(tool_name, tool_args, risk, "rejected", "user")
            return {
                "status": "blocked",
                "reason": f"用户拒绝执行高风险操作: {risk['description']}",
                "tool": tool_name,
            }

    # -- Internal helpers ------------------------------------------------------

    @staticmethod
    def _build_approval_message(risk: dict) -> str:
        level_labels = {
            RiskLevel.MEDIUM: "中等风险",
            RiskLevel.HIGH: "高风险",
            RiskLevel.CRITICAL: "极高风险",
        }
        level_label = level_labels.get(risk["level"], "风险")
        lines = [
            f"**{level_label}操作审批**",
            "",
            f"**工具**: `{risk['tool']}`",
            f"**说明**: {risk['description']}",
            f"**影响**: {risk['impact']}",
        ]
        for warning in risk.get("extra_warnings", []):
            lines.append(f"**警告**: {warning}")
        lines.append("")
        lines.append("是否批准执行？")
        return "\n".join(lines)

    @staticmethod
    def _record_audit(
        tool_name: str,
        tool_args: dict,
        risk: dict,
        decision: str,
        reason: str,
    ) -> None:
        """Record HITL decision to audit log (non-fatal)."""
        try:
            from data_agent.audit_logger import record_audit, ACTION_HITL_APPROVAL
            from data_agent.user_context import current_user_id

            username = current_user_id.get("system")
            record_audit(
                username=username,
                action=ACTION_HITL_APPROVAL,
                status=decision,
                details={
                    "tool": tool_name,
                    "risk_level": risk["level"].name,
                    "reason": reason,
                    "impact": risk.get("impact", ""),
                },
            )
        except Exception:
            pass  # Audit failure must not block execution


def _extract_action_value(response: Any) -> str:
    """Extract the action value from a Chainlit AskActionResponse or similar."""
    # Chainlit AskActionResponse has .payload dict
    if hasattr(response, "payload") and isinstance(response.payload, dict):
        return response.payload.get("value", "REJECT")
    # Dict-like response
    if isinstance(response, dict):
        payload = response.get("payload", response)
        if isinstance(payload, dict):
            return payload.get("value", "REJECT")
    # String response
    if isinstance(response, str):
        return response.upper() if response.upper() in ("APPROVE", "REJECT") else "REJECT"
    return "REJECT"


# ---------------------------------------------------------------------------
# HITL Decision Tracking (DB persistence)
# ---------------------------------------------------------------------------

T_HITL_DECISIONS = "agent_hitl_decisions"


def ensure_hitl_table():
    """Create HITL decisions table if not exists."""
    from .db_engine import get_engine
    engine = get_engine()
    if not engine:
        return
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_HITL_DECISIONS} (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(100) NOT NULL,
                    tool_name VARCHAR(200) NOT NULL,
                    risk_level VARCHAR(20) DEFAULT 'LOW',
                    decision VARCHAR(20) DEFAULT 'REJECT',
                    reason TEXT DEFAULT '',
                    impact TEXT DEFAULT '',
                    tool_args JSONB DEFAULT '{{}}',
                    response_time_ms INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS idx_hitl_decisions_user
                ON {T_HITL_DECISIONS} (username, created_at DESC)
            """))
            conn.commit()
    except Exception:
        pass


def record_hitl_decision(
    username: str, tool_name: str, risk_level: str,
    decision: str, reason: str = "", impact: str = "",
    tool_args: dict = None, response_time_ms: int = 0,
) -> None:
    """Record HITL decision to DB. Non-fatal."""
    from .db_engine import get_engine
    engine = get_engine()
    if not engine:
        return
    try:
        import json
        with engine.connect() as conn:
            conn.execute(text(f"""
                INSERT INTO {T_HITL_DECISIONS}
                (username, tool_name, risk_level, decision, reason, impact, tool_args, response_time_ms)
                VALUES (:u, :t, :r, :d, :reason, :impact, :args, :rt)
            """), {
                "u": username, "t": tool_name, "r": risk_level,
                "d": decision, "reason": reason, "impact": impact,
                "args": json.dumps(tool_args or {}, default=str),
                "rt": response_time_ms,
            })
            conn.commit()
    except Exception:
        pass


def get_hitl_stats(days: int = 30) -> dict:
    """Get HITL decision statistics for the dashboard.

    Returns:
        {total, approved, rejected, approval_rate, avg_response_ms,
         by_risk_level, by_tool, recent_decisions}
    """
    from .db_engine import get_engine
    engine = get_engine()
    if not engine:
        return {"total": 0, "approved": 0, "rejected": 0, "approval_rate": 0,
                "avg_response_ms": 0, "by_risk_level": {}, "by_tool": [],
                "recent_decisions": []}
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            # Totals
            row = conn.execute(text(f"""
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN decision = 'APPROVE' THEN 1 ELSE 0 END) AS approved,
                       SUM(CASE WHEN decision = 'REJECT' THEN 1 ELSE 0 END) AS rejected,
                       AVG(response_time_ms) AS avg_rt
                FROM {T_HITL_DECISIONS}
                WHERE created_at >= NOW() - make_interval(days => :d)
            """), {"d": days}).fetchone()
            total = row[0] or 0
            approved = row[1] or 0
            rejected = row[2] or 0
            avg_rt = int(row[3] or 0)

            # By risk level
            risk_rows = conn.execute(text(f"""
                SELECT risk_level, COUNT(*) AS cnt,
                       SUM(CASE WHEN decision = 'APPROVE' THEN 1 ELSE 0 END) AS app
                FROM {T_HITL_DECISIONS}
                WHERE created_at >= NOW() - make_interval(days => :d)
                GROUP BY risk_level
            """), {"d": days}).fetchall()
            by_risk = {r[0]: {"total": r[1], "approved": r[2]} for r in risk_rows}

            # By tool (top 10)
            tool_rows = conn.execute(text(f"""
                SELECT tool_name, COUNT(*) AS cnt,
                       SUM(CASE WHEN decision = 'APPROVE' THEN 1 ELSE 0 END) AS app
                FROM {T_HITL_DECISIONS}
                WHERE created_at >= NOW() - make_interval(days => :d)
                GROUP BY tool_name ORDER BY cnt DESC LIMIT 10
            """), {"d": days}).fetchall()
            by_tool = [{"tool": r[0], "total": r[1], "approved": r[2]} for r in tool_rows]

            # Recent decisions
            recent_rows = conn.execute(text(f"""
                SELECT username, tool_name, risk_level, decision, reason,
                       response_time_ms, created_at
                FROM {T_HITL_DECISIONS}
                ORDER BY created_at DESC LIMIT 20
            """)).fetchall()
            recent = [{
                "username": r[0], "tool": r[1], "risk_level": r[2],
                "decision": r[3], "reason": r[4],
                "response_ms": r[5],
                "time": r[6].isoformat() if r[6] else None,
            } for r in recent_rows]

            return {
                "total": total,
                "approved": approved,
                "rejected": rejected,
                "approval_rate": round(approved / total * 100, 1) if total > 0 else 0,
                "avg_response_ms": avg_rt,
                "by_risk_level": by_risk,
                "by_tool": by_tool,
                "recent_decisions": recent,
            }
    except Exception as e:
        return {"total": 0, "approved": 0, "rejected": 0, "approval_rate": 0,
                "avg_response_ms": 0, "by_risk_level": {}, "by_tool": [],
                "recent_decisions": [], "error": str(e)}


def get_risk_registry() -> list[dict]:
    """Return the current risk registry as a list for API/UI consumption."""
    return [
        {
            "tool_name": name,
            "level": meta["level"].name,
            "level_value": int(meta["level"]),
            "description": meta.get("description", ""),
            "impact": meta.get("impact", ""),
        }
        for name, meta in _RISK_REGISTRY.items()
    ]
