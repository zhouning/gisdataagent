#!/usr/bin/env python3
"""Create reusable local evidence for DuckDB Blueprint Spatial conformance."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pyarrow as pa
import pyarrow.parquet as pq
from shapely.geometry import box

from data_agent.duckdb_blueprint_provider import (
    DuckDBBlueprintExecutionSpec,
    DuckDBBlueprintInput,
    DuckDBBlueprintPipeline,
    DuckDBBlueprintProvider,
)
from data_agent.platform_contracts import canonical_json_fingerprint


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _spec(root: Path) -> DuckDBBlueprintExecutionSpec:
    source = root / "source.parquet"
    pq.write_table(
        pa.table(
            {
                "feature_id": ["a", "b"],
                "geometry_wkb": [
                    box(106.50, 29.50, 106.51, 29.51).wkb,
                    box(106.51, 29.51, 106.52, 29.52).wkb,
                ],
                "srid": [4326, 4326],
            }
        ),
        source,
    )
    content_sha256 = _sha256(source)
    return DuckDBBlueprintExecutionSpec(
        tenant_id="planning",
        run_id=UUID("00000000-0000-4000-8000-000000000a01"),
        execution_plan_artifact_id=UUID("00000000-0000-4000-8000-000000000a02"),
        execution_plan_sha256="a" * 64,
        definition_version_id=UUID("00000000-0000-4000-8000-000000000a03"),
        definition_sha256="b" * 64,
        pipeline=DuckDBBlueprintPipeline(
            engine="duckdb",
            require_spatial=True,
            spatial_output_srid=3857,
            sql=(
                "WITH projected AS ("
                "SELECT feature_id, ST_Transform(ST_GeomFromWKB(geometry_wkb), "
                "'EPSG:4326', 'EPSG:3857', always_xy := true) AS geom "
                "FROM source WHERE srid = 4326"
                ") SELECT feature_id, ST_AsWKB(geom) AS geometry_wkb, "
                "3857::INTEGER AS srid, "
                "[ST_XMin(geom), ST_YMin(geom), ST_XMax(geom), ST_YMax(geom)]"
                "::DOUBLE[] AS bbox, ST_Area(geom) AS area_m2 "
                "FROM projected ORDER BY feature_id"
            ),
        ),
        inputs=(
            DuckDBBlueprintInput(
                binding_name="source",
                resource_version_id=UUID("00000000-0000-4000-8000-000000000a04"),
                resource_urn="gda://planning/dataset/spatial-source",
                content_sha256=content_sha256,
                physical_location_id=UUID("00000000-0000-4000-8000-000000000a05"),
                location_sha256="c" * 64,
                provider_system="duckdb",
                provider_locator=source.as_uri(),
                content_checksum=content_sha256,
            ),
        ),
        output_uri=(root / "output.parquet").as_uri(),
        admitted_at=datetime(2026, 8, 20, tzinfo=UTC),
    )


def certify(output_dir: Path) -> dict[str, object]:
    workspace = output_dir / "workspace"
    workspace.mkdir(parents=True)
    spec = _spec(workspace)
    provider = DuckDBBlueprintProvider()
    receipt = provider.execute(spec)
    conformance = provider.certify(spec)
    output = pq.read_table(workspace / "output.parquet")
    geo = json.loads(output.schema.metadata[b"geo"])
    checks = {
        "spatial_extension_loaded": receipt.spatial_extension_loaded,
        "preinstalled_extension_only": (
            receipt.spatial_extension_evidence is not None
            and receipt.spatial_extension_evidence.autoinstall_enabled is False
            and receipt.spatial_extension_evidence.autoload_enabled is False
        ),
        "portable_wkb_srid_bbox": (
            receipt.spatial_output_evidence is not None
            and receipt.spatial_output_evidence.srid == 3857
            and receipt.spatial_output_evidence.invalid_geometry_rows == 0
        ),
        "geoparquet_1_1": (
            geo["version"] == "1.1.0"
            and geo["primary_column"] == "geometry_wkb"
            and geo["columns"]["geometry_wkb"]["encoding"] == "WKB"
        ),
        "deterministic_replay": (
            conformance.checks["deterministic_replay"] == "passed"
        ),
        "external_access_disabled": receipt.external_access == "disabled",
    }
    if not all(checks.values()):
        raise RuntimeError("DuckDB Spatial conformance checks did not all pass")
    payload: dict[str, object] = {
        "schema": "gda.duckdb_blueprint_spatial_certification.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "duckdb_version": receipt.provider_version,
        "spatial_extension": receipt.spatial_extension_evidence.model_dump(
            mode="json", by_alias=True
        ),
        "spatial_output": receipt.spatial_output_evidence.model_dump(
            mode="json", by_alias=True
        ),
        "output_content_sha256": receipt.output_content_sha256,
        "output_rows": receipt.output_rows,
        "conformance_report_sha256": conformance.report_sha256,
        "checks": checks,
        "verdict": "passed",
    }
    payload["report_sha256"] = canonical_json_fingerprint(payload)
    shutil.rmtree(workspace)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".tmp/duckdb-blueprint-spatial"),
    )
    args = parser.parse_args(argv)
    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        if any(output_dir.iterdir()):
            parser.error("--output-dir must not already contain files")
    else:
        output_dir.mkdir(parents=True)
    try:
        report = certify(output_dir)
    except Exception as exc:
        print(f"certification failed: {exc}", file=sys.stderr)
        return 1
    report_path = output_dir / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
