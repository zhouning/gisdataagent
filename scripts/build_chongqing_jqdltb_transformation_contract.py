#!/usr/bin/env python3
"""Build the approval-required JQDLTB transformation contract.

This command only compiles immutable identities and the unresolved business
choices. It never changes the source bundle and never writes a product layer.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

from data_agent.platform_contracts import (
    JqdltbTransformationMode,
    build_jqdltb_transformation_contract,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "config/freezes/ar0-first-vertical-slice-2026-08-22.json"


def build_contract(manifest_path: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    evidence = manifest["evidence"]
    identities = manifest["identities"]
    source_report = json.loads(
        (REPO_ROOT / evidence["source_report"]).read_text(encoding="utf-8")
    )
    diagnostic = json.loads(
        (REPO_ROOT / evidence["quality_repair_diagnostic"]).read_text(encoding="utf-8")
    )
    control = source_report["control_plane"]
    contract = build_jqdltb_transformation_contract(
        tenant_id=str(manifest["scope"]["tenant"]),
        mode=JqdltbTransformationMode.APPROVAL_REQUIRED,
        source_resource_version_id=UUID(str(control["resource_version_id"])),
        source_resource_urn=str(control["resource_urn"]),
        archive_sha256=str(identities["archive_sha256"]),
        bundle_sha256=str(identities["bundle_sha256"]),
        standard_version_ref=(
            f"{identities['standard_doc_code']}:{identities['standard_version_label']}"
        ),
        standard_fingerprint=str(identities["standard_elements_sha256"]),
        diagnostic_sha256=str(diagnostic["diagnostic_sha256"]),
        created_by="workload:ar0-contract-builder",
        created_at=datetime.fromisoformat(
            f"{manifest['effective_date']}T00:00:00+00:00"
        ),
    )
    return contract.model_dump(mode="json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = args.manifest if args.manifest.is_absolute() else REPO_ROOT / args.manifest
    output = args.output if args.output.is_absolute() else REPO_ROOT / args.output
    payload = build_contract(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "approval_required",
                "contract_sha256": payload["contract_sha256"],
                "output": str(output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
