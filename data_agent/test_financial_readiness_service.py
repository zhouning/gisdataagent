import json
from pathlib import Path

import pytest

from data_agent.uwm.financial_readiness_service import FinancialReadinessService


FILES = ("overview", "evidence_assets", "financial_channels", "data_contracts", "calculation_gate", "map")


def test_service_loads_consistent_fail_closed_bundle(tmp_path):
    for name in FILES:
        payload = {"bundle_id": "financial-test"}
        if name == "financial_channels":
            payload["financial_channels"] = {"revenue": {"status": "unavailable", "value": None}}
        if name == "calculation_gate":
            payload["calculation_gate"] = {"status": "closed", "mechanisms": {"npv": "closed"}}
        (tmp_path / f"{name}.json").write_text(json.dumps(payload))
    service = FinancialReadinessService(tmp_path)
    assert service.financial_channels()["financial_channels"]["revenue"]["value"] is None
    assert service.calculation_gate()["calculation_gate"]["status"] == "closed"


def test_service_rejects_mixed_bundles(tmp_path):
    for index, name in enumerate(FILES):
        (tmp_path / f"{name}.json").write_text(json.dumps({"bundle_id": str(index)}))
    with pytest.raises(ValueError, match="financial_readiness_bundle_mismatch"):
        FinancialReadinessService(tmp_path)


def test_real_financial_readiness_service_has_no_financial_results():
    service = FinancialReadinessService(Path("data/uwm_public_proxy/chongqing_central/financial_readiness_chongqing"))
    assert service.overview()["summary"]["evidence_asset_count"] == 4
    assert service.overview()["summary"]["computed_financial_output_count"] == 0
    assert all(channel["value"] is None for channel in service.financial_channels()["financial_channels"].values())
    gate = service.calculation_gate()
    assert gate["calculation_gate"]["status"] == "closed"
    assert gate["uwm_handoff_gate"]["status"] == "closed"
    assert all(value is None for value in gate["financial_outputs"].values())
