from __future__ import annotations

import json

from data_agent.standards_platform.evaluation.cli import run_evaluation
from data_agent.standards_platform.evaluation.schema import DerivationEvalSet


def test_run_evaluation_writes_json_and_markdown(tmp_path, monkeypatch):
    gold = tmp_path / "gold.json"
    json_report = tmp_path / "report.json"
    markdown_report = tmp_path / "report.md"
    gold.write_text('{"dataset_id":"gold-v1","items":[]}', encoding="utf-8")
    monkeypatch.setattr(
        "data_agent.standards_platform.evaluation.cli.extract_prediction_set",
        lambda engine, version_id: DerivationEvalSet.from_mapping({
            "dataset_id": f"predictions:{version_id}",
            "items": [],
        }),
    )

    code = run_evaluation(
        engine=object(),
        version_id="v1",
        gold_path=gold,
        json_report_path=json_report,
        markdown_report_path=markdown_report,
    )

    assert code == 0
    assert json.loads(json_report.read_text(encoding="utf-8"))["passed"] is True
    assert "PASS" in markdown_report.read_text(encoding="utf-8")


def test_run_evaluation_returns_one_when_thresholds_fail(tmp_path, monkeypatch):
    gold = tmp_path / "gold.json"
    gold.write_text(json.dumps({
        "dataset_id": "gold-v1",
        "items": [{
            "strategy": "to_qc_rule",
            "source_key": "data_element:a",
            "target_kind": "qc_rule",
            "target_key": "expected",
        }],
    }), encoding="utf-8")
    monkeypatch.setattr(
        "data_agent.standards_platform.evaluation.cli.extract_prediction_set",
        lambda engine, version_id: DerivationEvalSet.from_mapping({
            "dataset_id": f"predictions:{version_id}",
            "items": [],
        }),
    )

    code = run_evaluation(
        engine=object(),
        version_id="v1",
        gold_path=gold,
    )

    assert code == 1
