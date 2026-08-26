from __future__ import annotations

import hashlib
import json
from pathlib import Path

from openpyxl import Workbook

from data_agent.uwm.abu_dhabi_flood.customer_arrival_preflight import (
    render_customer_arrival_preflight_markdown,
    run_customer_arrival_preflight,
)


def _receipt_files(root: Path) -> tuple[Path, Path]:
    data = root / "authoritative.txt"
    data.write_text("customer-delivery", encoding="utf-8")
    register = root / "issue-register.json"
    register.write_text(
        json.dumps(
            {
                "schema": "gwm.abu_dhabi_flood.customer_swmm_engineering_issue_register.v1",
                "issues": [{"issue_id": "SWMM-ENG-099", "priority": "P1", "title": "授权资料确认"}],
            }
        ),
        encoding="utf-8",
    )
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "客户回执"
    headers = [
        "问题编号",
        "客户交付状态",
        "客户文件名/私有路径",
        "数据来源单位/责任方",
        "版本或快照编号",
        "有效时间/事件范围",
        "水平坐标系（CRS）",
        "垂直基准",
        "单位",
        "质量标识/缺测说明",
        "许可或交付授权",
        "SHA-256",
        "客户备注",
    ]
    for _ in range(3):
        sheet.append([])
    sheet.append(headers)
    sheet.append(
        [
            "SWMM-ENG-099",
            "已提供待验收",
            str(data),
            "Abu Dhabi authority",
            "v1",
            "2024-04",
            "EPSG:32640",
            "local datum",
            "native",
            "complete",
            "customer authority",
            hashlib.sha256(data.read_bytes()).hexdigest(),
            "received",
        ]
    )
    workbook_path = root / "customer-receipt.xlsx"
    workbook.save(workbook_path)
    return workbook_path, register


def test_empty_arrival_preflight_is_explicitly_waiting(tmp_path: Path):
    payload = run_customer_arrival_preflight(output_root=tmp_path / "preflight")
    assert payload["status"] == "preflight_complete"
    assert payload["next_gate"] == "customer_network_compile"
    assert payload["stages"]["receipt"]["status"] == "not_requested"
    assert all(value is False for value in payload["model_gate_summary"].values())
    assert (tmp_path / "preflight/abu_dhabi_customer_arrival_preflight.json").is_file()


def test_receipt_and_event_preflight_do_not_open_model_gates(tmp_path: Path):
    workbook, register = _receipt_files(tmp_path)
    event_csv = tmp_path / "rainfall.csv"
    event_csv.write_text(
        "timestamp,value\n2024-04-16T00:00:00Z,0\n2024-04-16T01:00:00Z,2\n",
        encoding="utf-8",
    )
    event_metadata = tmp_path / "rainfall.json"
    event_metadata.write_text(
        json.dumps(
            {
                "source_owner": "Abu Dhabi authority",
                "version_or_snapshot": "event-v1",
                "valid_time_start": "2024-04-16T00:00:00Z",
                "valid_time_end": "2024-04-16T01:00:00Z",
                "timezone": "UTC",
                "units": "mm/hour",
                "quality_flags": "complete",
                "license_or_reuse_authority": "customer authority",
                "sha256": hashlib.sha256(event_csv.read_bytes()).hexdigest(),
                "customer_authoritative": True,
                "event_id": "april-2024",
            }
        ),
        encoding="utf-8",
    )
    payload = run_customer_arrival_preflight(
        output_root=tmp_path / "preflight",
        receipt_workbook=workbook,
        issue_register=register,
        data_roots=[tmp_path],
        event_csv=event_csv,
        event_metadata=event_metadata,
        event_kind="rainfall",
        validate_event=True,
    )
    assert payload["stages"]["receipt"]["status"] == "accepted"
    assert payload["stages"]["event"]["status"] == "accepted"
    assert payload["next_gate"] == "customer_network_compile"
    assert payload["model_gate_summary"]["traditional_model_admitted"] is False
    assert payload["model_gate_summary"]["gwm_training_admitted"] is False
    markdown = render_customer_arrival_preflight_markdown(payload)
    assert "工程校准：关闭" in markdown


def test_gdb_is_waiting_for_explicit_compile_flag(tmp_path: Path):
    gdb = tmp_path / "customer.gdb"
    gdb.mkdir()
    payload = run_customer_arrival_preflight(output_root=tmp_path / "preflight", gdb_path=gdb)
    assert payload["stages"]["network"]["status"] == "ready_to_compile"
    assert payload["next_gate"] == "customer_network_compile"
