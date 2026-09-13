from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_agent.uwm.development_control import build_development_control_product


ASSET_SPECS = (
    ("gb-t-21010-2017", "土地利用现状分类（GB/T 21010-2017）", "reference_standard", "data_agent/standards/gb_t_21010_2017.yaml", "2017"),
    ("dltb-2023", "地类图斑字段规范", "technical_data_standard", "data_agent/standards/dltb_2023.yaml", "2023"),
    ("one-map-unified-planning", "自然资源一张图统一规划数据库结构", "technical_data_standard", "data_agent/standards/compiled_docx/04_统一规划.yaml", "compiled"),
    ("one-map-use-control", "自然资源一张图用途管制数据库结构", "technical_data_standard", "data_agent/standards/compiled_docx/06_用途管制1128V2.yaml", "compiled"),
    ("one-map-development-use", "自然资源一张图开发利用数据库结构", "technical_data_standard", "data_agent/standards/compiled_docx/07_开发利用.yaml", "compiled"),
    ("standard-registry", "标准注册与字段校验能力", "quality_or_validation_rule", "data_agent/standard_registry.py", "repository"),
    ("standards-api", "标准查询与校验接口", "quality_or_validation_rule", "data_agent/api/standards_routes.py", "repository"),
    ("twm-rule-evaluator", "TWM规则评估契约", "planning_rule_contract", "data_agent/territory_world_model/rule_evaluator.py", "repository"),
    ("spatial-policy-rule-derivation", "空间政策规则候选派生契约", "planning_rule_contract", "data_agent/standards_platform/derivation/strategies/spatial_policy_rule.py", "repository"),
)


def _assets(repo_root: Path):
    assets = []
    for asset_id, title, asset_class, source_path, version in ASSET_SPECS:
        if not (repo_root / source_path).is_file():
            continue
        assets.append({
            "rule_asset_id": asset_id,
            "title": title,
            "rule_asset_class": asset_class,
            "source_path": source_path,
            "version": version,
            "authority_status": "repository_source_backed_not_site_approval",
            "execution_status": "reference_only",
            "max_claim_level": "catalog_validation_or_rule_contract_only",
            "limitations": ["not_approved_site_specific_dcr", "not_project_approval_basis"],
        })
    return assets


def _write(product, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_id = product["bundle_id"]
    payloads = {
        "overview.json": {key: value for key, value in product.items() if key not in {"rule_assets", "dcr_channels", "data_contracts", "execution_gate"}},
        "rule_assets.json": {"schema": "uwm.development_control_rule_assets.v1", "bundle_id": bundle_id, "rule_assets": product["rule_assets"]},
        "dcr_channels.json": {"schema": "uwm.development_control_channels.v1", "bundle_id": bundle_id, "dcr_channels": product["dcr_channels"]},
        "data_contracts.json": {"schema": "uwm.development_control_contracts.v1", "bundle_id": bundle_id, "data_contracts": product["data_contracts"]},
        "execution_gate.json": {"schema": "uwm.development_control_execution_gate.v1", "bundle_id": bundle_id, "execution_gate": product["execution_gate"]},
        "map.json": {"schema": "uwm.development_control_map.v1", "bundle_id": bundle_id, "layers": []},
    }
    for name, payload in payloads.items():
        temporary = output_dir / f".{name}.tmp"
        temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        temporary.replace(output_dir / name)


def build_product(*, repo_root: Path, output_dir: Path):
    assets = _assets(repo_root)
    product = build_development_control_product(rule_assets=assets, source_artifacts=[asset["source_path"] for asset in assets])
    _write(product, output_dir)
    return product


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    product = build_product(repo_root=args.repo_root, output_dir=args.output_dir)
    print(json.dumps({"bundle_id": product["bundle_id"], "summary": product["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
