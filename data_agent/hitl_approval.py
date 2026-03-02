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
