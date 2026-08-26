#!/usr/bin/env python3
"""Accept a private customer SWMM engineering issue workbook fail-closed."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from openpyxl import Workbook

from data_agent.uwm.abu_dhabi_flood.customer_receipt_acceptance import (
    accept_customer_receipt,
    render_acceptance_markdown,
)


def _cell_value(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _write_xlsx(payload: dict, output: Path) -> None:
    workbook = Workbook()
    overview = workbook.active
    overview.title = "验收总览"
    overview.append(["指标", "值"])
    for key, value in payload["summary"].items():
        overview.append([key, _cell_value(value)])
    overview.append([])
    overview.append(["准入开关", "状态"])
    for key, value in payload["admission"].items():
        overview.append([key, _cell_value(value)])
    detail = workbook.create_sheet("逐项验收")
    detail.append(
        [
            "问题编号",
            "优先级",
            "工程问题",
            "客户交付状态",
            "项目审核状态",
            "验收通过",
            "缺失元数据",
            "原因",
            "文件核验",
        ]
    )
    for item in payload["issues"]:
        file_check = (
            "；".join(
                f"{file['submitted_path']}="
                f"{'通过' if file.get('hash_match') else file.get('error', '失败')}"
                for file in item["files"]
            )
            or "未提交"
        )
        detail.append(
            [
                item["issue_id"],
                item["priority"],
                item["title"],
                item["customer_delivery_status"],
                item["project_review_status"],
                "是" if item["accepted"] else "否",
                "；".join(item["missing_metadata"]) or "无",
                "；".join(item["reasons"]) or "无",
                file_check,
            ]
        )
    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for column in sheet.columns:
            values = [len(str(cell.value or "")) for cell in column]
            sheet.column_dimensions[column[0].column_letter].width = min(
                max(max(values, default=10) + 2, 12), 80
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--register", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, action="append", default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    payload = accept_customer_receipt(args.workbook, args.register, args.data_root or None)
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "customer_swmm_engineering_receipt_acceptance.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "customer_swmm_engineering_receipt_acceptance.md").write_text(
        render_acceptance_markdown(payload), encoding="utf-8"
    )
    _write_xlsx(
        payload, output_dir / "阿布扎比城市暴雨内涝世界模型_SWMM工程数据回执自动验收结果.xlsx"
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "summary": payload["summary"],
                "output_dir": str(output_dir),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
