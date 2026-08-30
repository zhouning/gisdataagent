from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from docx import Document

from data_agent.platform_contracts import canonical_json_fingerprint
from scripts.audit_chongqing_jqdltb_semantic_candidates import (
    _extract_dltb_standard,
    _field_profile,
    _xml_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs/reports/jqdltb_semantic_candidate_audit_2026-08-26.json"


def test_standard_extraction_requires_production_year_note(tmp_path: Path) -> None:
    document = Document()
    table = document.add_table(rows=4, cols=9)
    table.rows[0].cells[0].text = "序号"
    table.rows[0].cells[1].text = "字段名称"
    table.rows[0].cells[2].text = "字段代码"
    table.rows[1].cells[0].text = "27"
    table.rows[1].cells[1].text = "数据年份"
    table.rows[1].cells[2].text = "SJNF"
    table.rows[1].cells[3].text = "Int"
    table.rows[1].cells[4].text = "4"
    table.rows[1].cells[7].text = "M"
    table.rows[1].cells[8].text = "见本表注13"
    table.rows[2].cells[0].text = "28"
    table.rows[2].cells[1].text = "描述说明"
    table.rows[2].cells[2].text = "MSSM"
    table.rows[2].cells[3].text = "Char"
    table.rows[2].cells[4].text = "2"
    table.rows[2].cells[7].text = "M"
    table.rows[3].cells[0].text = "注13：数据年份为数据生产的年份。"
    path = tmp_path / "standard.docx"
    document.save(path)

    evidence = _extract_dltb_standard(path)

    assert evidence["fields"]["SJNF"]["definition"] == "数据年份为数据生产的年份"
    assert evidence["fields"]["SJNF"]["constraint"] == "M"
    assert evidence["fields"]["MSSM"]["type"] == "Char"
    assert evidence["fields"]["MSSM"]["length"] == "2"
    assert evidence["notes"]["mssm_value_domain_present"] is False


def test_field_and_xml_evidence_do_not_infer_semantics(tmp_path: Path) -> None:
    profile = _field_profile(pd.DataFrame({"PZWH": [None, "", "A", "A"]}), "PZWH")
    xml = tmp_path / "JQDLTB.shp.xml"
    xml.write_text(
        "<metadata><Esri><CreaDate>20191107</CreaDate></Esri>"
        '<Process Date="20180307">edit</Process>'
        '<Process Date="20191107">edit</Process>'
        "<attr><attrlabl>PZWH</attrlabl></attr></metadata>",
        encoding="utf-8",
    )

    evidence = _xml_evidence(xml)

    assert profile["non_blank_count"] == 2
    assert profile["distinct_non_null"] == 2
    assert evidence["arcgis_process_years"] == ["2018", "2019"]
    assert evidence["production_year_value_present"] is False
    assert evidence["semantic_definition_present"] is False


def test_frozen_semantic_candidate_report_is_read_only_and_blocked() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    payload = dict(report)
    fingerprint = payload.pop("report_sha256")

    assert fingerprint == canonical_json_fingerprint(payload)
    assert report["identities"]["feature_count"] == 1555
    assert report["standard_evidence"]["definition"]["fields"]["SJNF"][
        "definition"
    ] == "数据年份为数据生产的年份"
    assert report["standard_evidence"]["definition"]["notes"][
        "mssm_value_domain_present"
    ] is False
    assert report["source_evidence"]["candidate_field_profiles"]["PZWH"][
        "non_blank_count"
    ] == 10
    assert report["source_evidence"]["candidate_field_profiles"]["SM"][
        "non_blank_count"
    ] == 0
    assert report["decisions"] == {
        "MSSM": "blocked_no_authoritative_derivation",
        "SJNF": "blocked_no_authoritative_derivation",
    }
    assert all(value is False for value in report["governance"].values())
