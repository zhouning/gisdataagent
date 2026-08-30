#!/usr/bin/env python3
"""Register a validated JQDLTB business-correction ResourceVersion.

The command is intentionally separate from packet submission.  Registering a
real correction artifact makes its bytes addressable; it does not approve the
transformation or create a DataProductVersion.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from data_agent.platform_contracts import Resource, ResourceVersion
from data_agent.platform_gateway import PlatformGateway
from scripts.build_chongqing_jqdltb_business_correction_template import (
    DEFAULT_BASELINE,
    DEFAULT_DIAGNOSTIC,
    DEFAULT_SOURCE,
    validate_artifact,
)

RESOURCE_URN = "gda://local-dev/dataset/chongqing-bizhu-jqdltb-business-correction"
WORKLOAD_SUBJECT = "workload:jqdltb-correction-resource-register"


def register_correction_resource_version(
    *,
    artifact_path: Path,
    source_path: Path = DEFAULT_SOURCE,
    baseline_path: Path = DEFAULT_BASELINE,
    diagnostic_path: Path = DEFAULT_DIAGNOSTIC,
    gateway: Any | None = None,
    owner_ref: str = "team:freedo",
    created_by: str = WORKLOAD_SUBJECT,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Validate and register one exact correction file through the gateway."""

    artifact_path = artifact_path.resolve(strict=True)
    report = validate_artifact(
        artifact_path=artifact_path,
        source_path=source_path,
        baseline_path=baseline_path,
        diagnostic_path=diagnostic_path,
    )
    if report.get("status") != "ready_for_resource_version_registration":
        raise ValueError("correction artifact is not ready for ResourceVersion registration")
    if not owner_ref.startswith(("human:", "team:")):
        raise ValueError("correction ResourceVersion owner must use a typed human or team identity")
    if not created_by.startswith(("human:", "workload:")):
        raise ValueError("correction ResourceVersion creator must use a typed identity")

    artifact_sha256 = str(report["artifact_sha256"])
    source_identity = report["source_identity"]
    resource_version_id = uuid5(
        NAMESPACE_URL,
        f"{RESOURCE_URN}:{artifact_sha256}",
    )
    created_at = created_at or datetime.now(UTC)
    resource = Resource(
        tenant_id="local-dev",
        resource_urn=RESOURCE_URN,
        resource_kind="dataset",
        authority_system="gda-control",
        authority_locator=artifact_path.as_uri(),
        owner_ref=owner_ref,
        governance_ref={
            "logical_stage": "correction_input",
            "approval_state": "unapproved",
            "source_resource_version_id": source_identity["source_resource_version_id"],
        },
        technical_refs=(
            {
                "artifact_sha256": artifact_sha256,
                "artifact_path": artifact_path.as_uri(),
                "validation_schema": report["schema"],
            },
        ),
    )
    version = ResourceVersion(
        tenant_id="local-dev",
        resource_urn=RESOURCE_URN,
        resource_version_id=resource_version_id,
        version_key=f"sha256-{artifact_sha256[:16]}",
        content_sha256=artifact_sha256,
        authority_version_ref={
            "schema": "gda.jqdltb_business_correction_resource_version.v1",
            "artifact_sha256": artifact_sha256,
            "artifact_uri": artifact_path.as_uri(),
            "source_resource_version_id": source_identity["source_resource_version_id"],
            "source_archive_sha256": source_identity["archive_sha256"],
            "source_bundle_sha256": source_identity["bundle_sha256"],
            "diagnostic_sha256": source_identity["diagnostic_sha256"],
            "records": report["records"],
        },
        created_by=created_by,
        created_at=created_at,
    )
    gateway = gateway or PlatformGateway()
    resource_result = gateway.register_resource(resource)
    version_result = gateway.register_resource_version(version)
    return {
        "schema": "gda.jqdltb_business_correction_resource_registration.v1",
        "status": "resource_version_registered",
        "resource_urn": RESOURCE_URN,
        "resource_version_id": str(version.resource_version_id),
        "artifact_sha256": artifact_sha256,
        "records": report["records"],
        "resource_created": bool(getattr(resource_result, "created", True)),
        "resource_version_created": bool(getattr(version_result, "created", True)),
        "approval_case_created": False,
        "strategy_created": False,
        "data_product_version_created": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--diagnostic", type=Path, default=DEFAULT_DIAGNOSTIC)
    parser.add_argument("--owner-ref", default="team:freedo")
    parser.add_argument("--created-by", default=WORKLOAD_SUBJECT)
    args = parser.parse_args(argv)
    result = register_correction_resource_version(
        artifact_path=args.artifact,
        source_path=args.source,
        baseline_path=args.baseline,
        diagnostic_path=args.diagnostic,
        owner_ref=args.owner_ref,
        created_by=args.created_by,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
