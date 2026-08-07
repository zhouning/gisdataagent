#!/usr/bin/env python3
"""Compile the Ningxia workbooks and EA evidence into a runtime baseline.

The baseline is usable for system startup, ingestion and field matching.
Missing physical types, lengths, SRID, values and constraints are verified per
real dataset when it arrives. An ``ea_standard`` signature is optional metadata
for administrative publication, not a global runtime prerequisite.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.standard_contracts import compile_standard_contract_catalog


def _write_report(catalog: dict, path: Path) -> None:
    coverage = catalog.get("coverage") or {}
    resolution_counts = (catalog.get("inventory_resolution") or {}).get("counts") or {}
    ea_contract_count = sum(
        bool(contract.get("ea_evidence"))
        for contract in (catalog.get("contracts") or {}).values()
    )
    lines = [
        "# 宁夏自然资源数据接入基线编译报告",
        "",
        f"- 合同目录：`{catalog.get('contract_id')}`",
        f"- 标准版本：`{catalog.get('standard_version')}`",
        f"- 权威级别：`{catalog.get('authority')}`",
        f"- 发布状态：`{catalog.get('review_status')}`",
        f"- 合同数据集：{coverage.get('contract_dataset_count', 0)}",
        f"- 清单数据项：{coverage.get('inventory_items', 0)}",
        f"- SHP 工作簿字段：{coverage.get('workbook_field_count', 0)} 条 / "
        f"{coverage.get('workbook_contract_dataset_count', 0)} 个图层",
        f"- 清单专题页字段：{coverage.get('inventory_field_count', 0)} 条 / "
        f"{coverage.get('inventory_field_contract_dataset_count', 0)} 个数据集",
        "- 字段证据总数（重合来源并列保留）："
        f"{coverage.get('workbook_field_count', 0) + coverage.get('inventory_field_count', 0)} 条",
        f"- 尚未自动对齐清单项：{coverage.get('unmapped_inventory_count', 0)}",
        f"- 含 EA/标准对比证据的合同：{ea_contract_count}",
        f"- 仅代码前缀相似、需要消歧：{resolution_counts.get('ambiguous_candidate', 0)}",
        f"- 已有字段基线合同：{resolution_counts.get('baseline_contract', 0)}",
        "",
        "## 运行与发布门禁",
        "",
        (
            "本产物把宁夏数据清单、字段明细、标准字段目录、角色契约和 EA 对比结果合并为"
            "运行基线。系统可以据此启动、接入和匹配；真实数据到达后逐数据集核验字段类型、"
            "长度、精度、SRID、值域、主键及质量。只有失败的数据集进入复核或阻断，"
            "不再因为缺少全局 approved 标志阻断整个系统、本体浏览或其他合格数据问数。"
        ),
        "",
        "## 合同字段完整性",
        "",
        "| 数据集 | 字段数 | 必填 | 缺类型 | 缺长度 | 缺精度 | 缺值域 | EA 证据 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for code, contract in sorted((catalog.get("contracts") or {}).items()):
        completeness = contract.get("field_completeness") or {}
        lines.append(
            f"| {code} {contract.get('name', '')} | {completeness.get('field_count', 0)} | "
            f"{completeness.get('required_count', 0)} | "
            f"{completeness.get('missing_type_count', 0)} | "
            f"{completeness.get('missing_length_count', 0)} | "
            f"{completeness.get('missing_precision_count', 0)} | "
            f"{completeness.get('missing_domain_count', 0)} | "
            f"{len(contract.get('ea_evidence') or [])} |"
        )
    lines.extend(["", "## 未自动对齐清单项", ""])
    for item in coverage.get("unmapped_inventory") or []:
        lines.append(f"- `{item.get('name')}`：保留为待人工确认，不猜测标准表代码。")
    if not coverage.get("unmapped_inventory"):
        lines.append("- 无。")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile NX natural-resource runtime data-model baseline"
    )
    parser.add_argument("--role-contracts", required=True, type=Path)
    parser.add_argument("--field-aliases", type=Path)
    parser.add_argument("--value-domains", type=Path)
    parser.add_argument("--field-catalog", type=Path)
    parser.add_argument("--ea-table-comparison", type=Path)
    parser.add_argument("--ea-logical-comparison", type=Path)
    parser.add_argument("--shp-workbook", type=Path)
    parser.add_argument("--inventory-workbook", type=Path)
    parser.add_argument("--standard-version")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    catalog = compile_standard_contract_catalog(
        role_contracts_path=args.role_contracts,
        field_aliases_path=args.field_aliases,
        value_domains_path=args.value_domains,
        field_catalog_path=args.field_catalog,
        ea_table_comparison_path=args.ea_table_comparison,
        ea_logical_comparison_path=args.ea_logical_comparison,
        shp_workbook=args.shp_workbook,
        inventory_workbook=args.inventory_workbook,
        standard_version=args.standard_version,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if args.report:
        _write_report(catalog, args.report)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "report": str(args.report.resolve()) if args.report else None,
                "authority": catalog["authority"],
                "contracts": len(catalog["contracts"]),
                "inventory_items": (catalog.get("data_inventory") or {}).get("item_count", 0),
                "unmapped_inventory": catalog["coverage"]["unmapped_inventory_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
