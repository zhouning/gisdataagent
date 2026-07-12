from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_agent.uwm.financial_readiness import build_financial_readiness_product


ASSET_SPECS = (
    ("unified-property-financial-fields", "统一产权底板财务与经营字段结构", "financial_data_standard", "data_agent/standards/compiled_docx/03_统一产权底板.yaml", "contract_only", "field_definitions_not_customer_financial_observations"),
    ("dependency-roadmap", "依赖感知实施路线图产品", "upstream_program_readiness_product", "data/uwm_public_proxy/chongqing_central/dependency_roadmap_chongqing/overview.json", "reference_only", "roadmap_budgets_dates_benefits_and_returns_are_null"),
    ("cross-domain-impact", "跨领域影响与优先级产品", "upstream_priority_product", "data/uwm_public_proxy/chongqing_central/cross_domain_impact_chongqing/overview.json", "reference_only", "priority_rank_not_cost_benefit_or_investment_return"),
    ("livability-s2-scenario", "UWM地块干预情景产品", "uwm_scenario_capability", "data/uwm_public_proxy/fulu/uwm_livability_s2/overview.json", "reference_only", "scenario_capability_not_customer_approved_financial_handoff"),
    ("financial-readiness-contract", "确定性财务数据与计算门控契约", "financial_calculation_contract", "data_agent/uwm/financial_readiness.py", "contract_only", "contract_not_financial_result"),
)


def _assets(repo_root: Path):
    assets = []
    for asset_id, title, asset_class, source_path, execution_status, limitation in ASSET_SPECS:
        if not (repo_root / source_path).is_file():
            continue
        assets.append({"asset_id": asset_id, "title": title, "asset_class": asset_class, "source_path": source_path, "execution_status": execution_status, "authority_status": "repository_source_backed_not_customer_financial_record", "max_claim_level": "data_contract_or_upstream_capability_only", "limitations": [limitation, "not_monetary_evidence"]})
    return assets


def _write(product, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_id = product["bundle_id"]
    payloads = {
        "overview.json": {key: value for key, value in product.items() if key not in {"evidence_assets", "financial_channels", "data_contracts", "calculation_gate"}},
        "evidence_assets.json": {"schema": "uwm.financial_evidence_assets.v1", "bundle_id": bundle_id, "evidence_assets": product["evidence_assets"]},
        "financial_channels.json": {"schema": "uwm.financial_input_channels.v1", "bundle_id": bundle_id, "financial_channels": product["financial_channels"]},
        "data_contracts.json": {"schema": "uwm.financial_data_contracts.v1", "bundle_id": bundle_id, "data_contracts": product["data_contracts"]},
        "calculation_gate.json": {"schema": "uwm.financial_calculation_gate.v1", "bundle_id": bundle_id, "calculation_gate": product["calculation_gate"], "uwm_handoff_gate": product["uwm_handoff_gate"], "financial_outputs": product["financial_outputs"]},
        "map.json": {"schema": "uwm.financial_readiness_map.v1", "bundle_id": bundle_id, "layers": []},
    }
    for name, payload in payloads.items():
        temporary = output_dir / f".{name}.tmp"
        temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        temporary.replace(output_dir / name)


def build_product(*, repo_root: Path, output_dir: Path):
    assets = _assets(repo_root)
    product = build_financial_readiness_product(evidence_assets=assets, source_artifacts=[asset["source_path"] for asset in assets])
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
