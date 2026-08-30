#!/usr/bin/env python3
"""Build the non-promotable JQDLTB Raw-to-ADS semantic candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.jqdltb_semantic_candidate import (
    JqdltbSemanticCandidateConfig,
    build_semantic_candidate,
)
from data_agent.platform_contracts import JqdltbTransformationContract

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = (
    REPO_ROOT / "benchmarks/standard_mapping_chongqing_v0_1/source_onboarding_protocol.json"
)
DEFAULT_DATASET_ROOT = (
    REPO_ROOT
    / ".tmp/twm_standard_1128/自然资源一张图数据库标准1128/"
    "规划院提供数据样例及Demo系统功能演示建议/01数据样例"
)
DEFAULT_AUDIT = REPO_ROOT / "docs/reports/jqdltb_semantic_candidate_audit_2026-08-26.json"
DEFAULT_BASELINE = REPO_ROOT / "config/freezes/ar0-jqdltb-transformation-contract-2026-08-22.json"
DEFAULT_OUTPUT = REPO_ROOT / ".tmp/jqdltb-semantic-candidate"


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _source_path(protocol_path: Path, dataset_root: Path) -> Path:
    protocol = _read_json(protocol_path)
    relative_path = Path(str(protocol["source"]["relative_path"]))
    root = dataset_root.resolve(strict=True)
    source = (root / relative_path).resolve(strict=True)
    if not source.is_relative_to(root):
        raise ValueError("JQDLTB protocol source path escapes dataset root")
    return source


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--semantic-audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--allow-non-shapefile-fixture",
        action="store_true",
        help="permit GeoJSON/CSV only for explicitly synthetic or fixture inputs",
    )
    args = parser.parse_args(argv)

    baseline = JqdltbTransformationContract.model_validate(_read_json(args.baseline))
    if baseline.mode.value != "approval_required":
        raise ValueError("semantic candidate requires the unresolved approval-gated baseline")
    audit = _read_json(args.semantic_audit)
    identities = audit.get("identities")
    if not isinstance(identities, dict):
        raise ValueError("semantic audit identities are missing")
    source = (args.source or _source_path(args.protocol, args.dataset_root)).resolve(strict=True)
    config = JqdltbSemanticCandidateConfig(
        source_path=source,
        output_root=args.output_root.resolve(),
        tenant_id=baseline.tenant_id,
        source_resource_version_id=baseline.source_resource_version_id,
        source_resource_urn=baseline.source_resource_urn,
        archive_sha256=baseline.archive_sha256,
        bundle_sha256=baseline.bundle_sha256,
        standard_version_ref=baseline.standard_version_ref,
        standard_fingerprint=baseline.standard_fingerprint,
        semantic_candidate_audit_path=args.semantic_audit.resolve(strict=True),
        allow_non_shapefile_fixture=args.allow_non_shapefile_fixture,
    )
    result = build_semantic_candidate(config)
    print(json.dumps(result.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
