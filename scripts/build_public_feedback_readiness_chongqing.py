from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from data_agent.uwm.public_feedback_readiness import build_public_feedback_readiness_product


CAPABILITY_SPECS = (
    ("agent-feedback-store", "Agent回答反馈存储与处理", "platform_agent_feedback", "data_agent/feedback.py", "agent_response_votes_not_urban_public_opinion"),
    ("agent-feedback-api", "Agent反馈鉴权接口", "platform_agent_feedback_api", "data_agent/api/feedback_routes.py", "platform_feedback_api_not_customer_feedback_ingestion"),
    ("agent-feedback-ui", "Agent反馈管理页面", "platform_agent_feedback_ui", "frontend/src/components/datapanel/FeedbackTab.tsx", "admin_feedback_ui_not_public_consultation_portal"),
    ("batch-geocoding", "地址地理编码与置信度处理", "geocoding_capability", "data_agent/geocoding.py", "geocoding_capability_not_geocoded_feedback_observation"),
    ("knowledge-base-text", "文本分块、向量化与检索", "text_semantic_capability", "data_agent/knowledge_base.py", "embedding_capability_not_issue_or_sentiment_result"),
    ("semantic-ontology", "语义本体与概念映射", "semantic_taxonomy_capability", "data_agent/fusion/semantic_ontology.py", "ontology_capability_not_customer_issue_taxonomy"),
    ("feedback-readiness-contract", "公众反馈观测与UWM交接契约", "feedback_observation_contract", "data_agent/uwm/public_feedback_readiness.py", "contract_not_public_feedback_observation"),
)


def _capabilities(repo_root: Path):
    rows = []
    for capability_id, title, capability_type, source_path, limitation in CAPABILITY_SPECS:
        if not (repo_root / source_path).is_file(): continue
        rows.append({"capability_id": capability_id, "title": title, "capability_type": capability_type, "source_path": source_path, "status": "implemented_capability", "max_claim_level": "platform_processing_capability_only", "limitations": [limitation, "not_authoritative_customer_feedback_corpus"]})
    return rows


def _write(product, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True); bundle_id = product["bundle_id"]
    payloads = {
        "overview.json": {key: value for key, value in product.items() if key not in {"capabilities", "feedback_channels", "data_contracts", "analysis_gate"}},
        "capabilities.json": {"schema": "uwm.public_feedback_capabilities.v1", "bundle_id": bundle_id, "capabilities": product["capabilities"]},
        "feedback_channels.json": {"schema": "uwm.public_feedback_channels.v1", "bundle_id": bundle_id, "feedback_channels": product["feedback_channels"]},
        "data_contracts.json": {"schema": "uwm.public_feedback_contracts.v1", "bundle_id": bundle_id, "data_contracts": product["data_contracts"]},
        "analysis_gate.json": {"schema": "uwm.public_feedback_analysis_gate.v1", "bundle_id": bundle_id, "analysis_gate": product["analysis_gate"]},
        "map.json": {"schema": "uwm.public_feedback_map.v1", "bundle_id": bundle_id, "layers": []},
    }
    for name, payload in payloads.items():
        temporary = output_dir / f".{name}.tmp"; temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))); temporary.replace(output_dir / name)


def build_product(*, repo_root: Path, output_dir: Path):
    capabilities = _capabilities(repo_root)
    product = build_public_feedback_readiness_product(capabilities=capabilities, source_artifacts=[row["source_path"] for row in capabilities])
    _write(product, output_dir); return product


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--repo-root", type=Path, required=True); parser.add_argument("--output-dir", type=Path, required=True); args = parser.parse_args()
    product = build_product(repo_root=args.repo_root, output_dir=args.output_dir); print(json.dumps({"bundle_id": product["bundle_id"], "summary": product["summary"]}, ensure_ascii=False))


if __name__ == "__main__": main()
