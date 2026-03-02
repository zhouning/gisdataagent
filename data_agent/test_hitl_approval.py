"""Tests for HITL Approval Plugin (data_agent.hitl_approval).

Covers:
- Risk assessment for all registry levels
- Impact template interpolation & escalation rules
- Plugin callback behaviour (allow, block, auto-approve, degrade)
- Audit integration
- Registry completeness
"""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from data_agent.hitl_approval import (
    HITLApprovalPlugin,
    HITL_ENABLED,
    RiskLevel,
    _extract_action_value,
    assess_risk,
    get_risk_registry,
)


# ===================================================================
# Risk Assessment
# ===================================================================

class TestRiskAssessment:
    """Test the assess_risk() function."""

    def test_unknown_tool_returns_none(self):
        assert assess_risk("some_random_tool", {}) is None

    def test_critical_tool_detected(self):
        result = assess_risk("import_to_postgis", {"table": "parcels"})
        assert result is not None
        assert result["level"] == RiskLevel.CRITICAL
        assert "parcels" in result["impact"]

    def test_high_tool_detected(self):
        result = assess_risk("add_field", {"field_name": "new_col"})
        assert result is not None
        assert result["level"] == RiskLevel.HIGH
        assert "new_col" in result["impact"]

    def test_medium_tool_detected(self):
        result = assess_risk("delete_memory", {"memory_id": "42"})
        assert result is not None
        assert result["level"] == RiskLevel.MEDIUM
        assert "42" in result["impact"]

    def test_impact_template_missing_key(self):
        """When tool_args lacks the template key, raw template is returned."""
        result = assess_risk("import_to_postgis", {})
        assert result is not None
        assert "{table}" in result["impact"]

    def test_escalation_rule_fires(self):
        result = assess_risk("import_to_postgis", {"table": "t", "if_exists": "replace"})
        assert result is not None
        assert len(result["extra_warnings"]) == 1
        assert "replace" in result["extra_warnings"][0]

    def test_escalation_rule_no_fire(self):
        result = assess_risk("import_to_postgis", {"table": "t", "if_exists": "append"})
        assert result is not None
        assert len(result["extra_warnings"]) == 0

    def test_drl_tool_critical(self):
        result = assess_risk("optimize_land_use_drl", {})
        assert result["level"] == RiskLevel.CRITICAL

    def test_delete_user_file_critical(self):
        result = assess_risk("delete_user_file", {"file_path": "/tmp/foo.shp"})
        assert result["level"] == RiskLevel.CRITICAL
        assert "foo.shp" in result["impact"]

    def test_share_table_high(self):
        result = assess_risk("share_table", {"table_name": "shared_tbl"})
        assert result["level"] == RiskLevel.HIGH


# ===================================================================
# Risk Registry
# ===================================================================

class TestRiskRegistry:
    """Test the integrity of the risk registry."""

    def test_registry_not_empty(self):
        registry = get_risk_registry()
        assert len(registry) >= 13

    def test_all_entries_have_required_fields(self):
        registry = get_risk_registry()
        for name, entry in registry.items():
            assert "level" in entry, f"{name} missing 'level'"
            assert "description" in entry, f"{name} missing 'description'"
            assert isinstance(entry["level"], RiskLevel), f"{name} level not RiskLevel"

    def test_registry_returns_copy(self):
        r1 = get_risk_registry()
        r2 = get_risk_registry()
        r1["fake_tool"] = {"level": RiskLevel.LOW}
        assert "fake_tool" not in r2


# ===================================================================
# Plugin Behaviour
# ===================================================================

class TestHITLPlugin:
    """Test the HITLApprovalPlugin callback logic."""

    def _make_tool(self, name: str):
        return SimpleNamespace(name=name)

    async def _call(self, plugin, tool_name, tool_args=None):
        """Helper to call the async before_tool_callback."""
        return await plugin.before_tool_callback(
            tool=self._make_tool(tool_name),
            tool_args=tool_args or {},
            tool_context=None,
        )

    @patch.dict(os.environ, {"HITL_ENABLED": "true", "HITL_BLOCK_LEVEL": "critical"})
    def test_low_risk_tool_passes_through(self):
        """Non-registry tool should be allowed (returns None)."""
        plugin = HITLApprovalPlugin()
        result = asyncio.run(self._call(plugin, "describe_data"))
        assert result is None

    @patch.dict(os.environ, {"HITL_ENABLED": "true", "HITL_BLOCK_LEVEL": "critical"})
    def test_below_threshold_auto_approves(self):
        """HIGH tool with CRITICAL threshold -> auto-approve (None)."""
        plugin = HITLApprovalPlugin()
        plugin._block_level = RiskLevel.CRITICAL
        result = asyncio.run(self._call(plugin, "add_field", {"field_name": "x"}))
        assert result is None

    @patch.dict(os.environ, {"HITL_ENABLED": "true", "HITL_BLOCK_LEVEL": "critical"})
    def test_no_approval_fn_auto_approves(self):
        """CRITICAL tool with no approval function -> auto-approve."""
        plugin = HITLApprovalPlugin()
        plugin._block_level = RiskLevel.CRITICAL
        result = asyncio.run(self._call(plugin, "import_to_postgis", {"table": "t"}))
        assert result is None

    @patch.dict(os.environ, {"HITL_ENABLED": "true", "HITL_BLOCK_LEVEL": "critical"})
    def test_approved_returns_none(self):
        """User approves -> returns None (allow execution)."""
        plugin = HITLApprovalPlugin()
        plugin._block_level = RiskLevel.CRITICAL

        async def fake_approve(content):
            return SimpleNamespace(payload={"value": "APPROVE"})

        plugin.set_approval_function(fake_approve)
        result = asyncio.run(self._call(plugin, "import_to_postgis", {"table": "t"}))
        assert result is None

    @patch.dict(os.environ, {"HITL_ENABLED": "true", "HITL_BLOCK_LEVEL": "critical"})
    def test_rejected_returns_blocked_dict(self):
        """User rejects -> returns dict with status=blocked."""
        plugin = HITLApprovalPlugin()
        plugin._block_level = RiskLevel.CRITICAL

        async def fake_reject(content):
            return SimpleNamespace(payload={"value": "REJECT"})

        plugin.set_approval_function(fake_reject)
        result = asyncio.run(self._call(plugin, "import_to_postgis", {"table": "t"}))
        assert isinstance(result, dict)
        assert result["status"] == "blocked"
        assert result["tool"] == "import_to_postgis"

    def test_disabled_skips_all(self):
        """HITL_ENABLED=false -> always returns None."""
        from data_agent import hitl_approval
        old_val = hitl_approval.HITL_ENABLED
        hitl_approval.HITL_ENABLED = False
        try:
            plugin = HITLApprovalPlugin()
            plugin._block_level = RiskLevel.LOW
            result = asyncio.run(self._call(plugin, "import_to_postgis", {"table": "t"}))
            assert result is None
        finally:
            hitl_approval.HITL_ENABLED = old_val

    @patch.dict(os.environ, {"HITL_ENABLED": "true", "HITL_BLOCK_LEVEL": "critical"})
    def test_approval_fn_exception_degrades(self):
        """If approval function raises, degrade to auto-approve."""
        plugin = HITLApprovalPlugin()
        plugin._block_level = RiskLevel.CRITICAL

        async def exploding_fn(content):
            raise RuntimeError("Chainlit context lost")

        plugin.set_approval_function(exploding_fn)
        result = asyncio.run(self._call(plugin, "import_to_postgis", {"table": "t"}))
        assert result is None  # auto-approved on error

    @patch.dict(os.environ, {"HITL_ENABLED": "true", "HITL_BLOCK_LEVEL": "high"})
    def test_high_threshold_blocks_high_tools(self):
        """When HITL_BLOCK_LEVEL=high, HIGH tools trigger approval."""
        plugin = HITLApprovalPlugin()
        plugin._block_level = RiskLevel.HIGH

        async def fake_reject(content):
            return SimpleNamespace(payload={"value": "REJECT"})

        plugin.set_approval_function(fake_reject)
        result = asyncio.run(self._call(plugin, "add_field", {"field_name": "x"}))
        assert isinstance(result, dict)
        assert result["status"] == "blocked"


# ===================================================================
# Action Value Extraction
# ===================================================================

class TestExtractActionValue:
    """Test _extract_action_value with various response shapes."""

    def test_simplenamespace_payload(self):
        resp = SimpleNamespace(payload={"value": "APPROVE"})
        assert _extract_action_value(resp) == "APPROVE"

    def test_dict_payload(self):
        assert _extract_action_value({"payload": {"value": "REJECT"}}) == "REJECT"

    def test_flat_dict(self):
        assert _extract_action_value({"value": "APPROVE"}) == "APPROVE"

    def test_string_approve(self):
        assert _extract_action_value("approve") == "APPROVE"

    def test_string_reject(self):
        assert _extract_action_value("reject") == "REJECT"

    def test_none_returns_reject(self):
        assert _extract_action_value(42) == "REJECT"


# ===================================================================
# Approval Message
# ===================================================================

class TestApprovalMessage:
    """Test the approval message builder."""

    def test_critical_message_content(self):
        risk = assess_risk("import_to_postgis", {"table": "parcels", "if_exists": "replace"})
        msg = HITLApprovalPlugin._build_approval_message(risk)
        assert "极高风险" in msg
        assert "import_to_postgis" in msg
        assert "replace" in msg
        assert "批准" in msg or "是否" in msg

    def test_high_message_label(self):
        risk = assess_risk("add_field", {"field_name": "col"})
        msg = HITLApprovalPlugin._build_approval_message(risk)
        assert "高风险" in msg


# ===================================================================
# Audit Integration
# ===================================================================

class TestAuditIntegration:
    """Test audit logging integration."""

    def test_action_constant_exists(self):
        from data_agent.audit_logger import ACTION_HITL_APPROVAL, ACTION_LABELS
        assert ACTION_HITL_APPROVAL == "hitl_approval"
        assert ACTION_HITL_APPROVAL in ACTION_LABELS

    @patch("data_agent.audit_logger.record_audit")
    def test_record_audit_called_on_auto_approve(self, mock_record):
        """When _record_audit is called, audit_logger.record_audit is invoked."""
        plugin = HITLApprovalPlugin()
        risk = assess_risk("add_field", {"field_name": "x"})
        plugin._record_audit("add_field", {"field_name": "x"}, risk, "auto_approved", "below_threshold")
        mock_record.assert_called_once()


# ===================================================================
# RiskLevel enum
# ===================================================================

class TestRiskLevel:
    """Test RiskLevel ordering."""

    def test_ordering(self):
        assert RiskLevel.LOW < RiskLevel.MEDIUM < RiskLevel.HIGH < RiskLevel.CRITICAL

    def test_name(self):
        assert RiskLevel.CRITICAL.name == "CRITICAL"
