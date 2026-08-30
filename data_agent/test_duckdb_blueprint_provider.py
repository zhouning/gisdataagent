import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from pydantic import ValidationError
from shapely import from_wkb
from shapely.geometry import box

from data_agent.duckdb_blueprint_provider import (
    DuckDBBlueprintExecutionSpec,
    DuckDBBlueprintInput,
    DuckDBBlueprintPipeline,
    DuckDBBlueprintProvider,
    DuckDBBlueprintProviderContractError,
    DuckDBBlueprintProviderExecutionError,
)


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _spec(
    tmp_path,
    *,
    sql=None,
    max_input_bytes=2_147_483_648,
    max_output_rows=100,
    require_spatial=False,
    spatial_output_srid=None,
) -> DuckDBBlueprintExecutionSpec:
    source = tmp_path / "districts.parquet"
    pq.write_table(
        pa.table(
            {
                "district": ["a", "a", "b"],
                "area": [10.5, 4.5, 7.0],
                "min_x": [1.0, 1.5, 5.0],
                "min_y": [2.0, 2.5, 6.0],
                "geometry_wkb": [
                    box(106.50, 29.50, 106.51, 29.51).wkb,
                    box(106.51, 29.51, 106.52, 29.52).wkb,
                    box(106.55, 29.55, 106.56, 29.56).wkb,
                ],
                "srid": [4326, 4326, 4326],
                "bbox": [
                    [106.50, 29.50, 106.51, 29.51],
                    [106.51, 29.51, 106.52, 29.52],
                    [106.55, 29.55, 106.56, 29.56],
                ],
            }
        ),
        source,
    )
    content_sha256 = _sha256(source)
    return DuckDBBlueprintExecutionSpec(
        tenant_id="planning",
        run_id=UUID("00000000-0000-4000-8000-000000000801"),
        execution_plan_artifact_id=UUID(
            "00000000-0000-4000-8000-000000000802"
        ),
        execution_plan_sha256="1" * 64,
        definition_version_id=UUID("00000000-0000-4000-8000-000000000803"),
        definition_sha256="2" * 64,
        pipeline=DuckDBBlueprintPipeline(
            engine="duckdb",
            sql=sql
            or (
                "SELECT district, sum(area) AS area "
                "FROM source GROUP BY district ORDER BY district"
            ),
            max_input_bytes=max_input_bytes,
            max_output_rows=max_output_rows,
            require_spatial=require_spatial,
            spatial_output_srid=spatial_output_srid,
        ),
        inputs=(
            DuckDBBlueprintInput(
                binding_name="source",
                resource_version_id=UUID(
                    "00000000-0000-4000-8000-000000000804"
                ),
                resource_urn="gda://planning/dataset/district-source",
                content_sha256=content_sha256,
                physical_location_id=UUID(
                    "00000000-0000-4000-8000-000000000805"
                ),
                location_sha256="3" * 64,
                provider_system="duckdb",
                provider_locator=source.as_uri(),
                content_checksum=content_sha256,
            ),
        ),
        output_uri=(tmp_path / "output.parquet").as_uri(),
        admitted_at=datetime(2026, 8, 20, tzinfo=UTC),
    )


def test_duckdb_blueprint_provider_executes_bound_parquet_and_certifies_replay(
    tmp_path,
):
    spec = _spec(tmp_path)
    provider = DuckDBBlueprintProvider()

    receipt = provider.execute(spec)
    report = provider.certify(spec)
    output = pq.read_table(tmp_path / "output.parquet").to_pylist()

    assert output == [
        {"district": "a", "area": 15.0},
        {"district": "b", "area": 7.0},
    ]
    assert receipt.output_rows == 2
    assert receipt.input_rows == 3
    assert receipt.external_access == "disabled"
    assert receipt.checkpoint_mode == "atomic_output"
    assert receipt.output_content_sha256 == _sha256(tmp_path / "output.parquet")
    assert report.verdict == "passed"
    assert report.output_content_sha256 == receipt.output_content_sha256
    assert report.checks["deterministic_replay"] == "passed"
    assert report.checks["cancel_reconcile"] == "not_applicable"


def test_duckdb_blueprint_provider_probe_disables_external_access():
    report = DuckDBBlueprintProvider().probe()

    assert report["duckdb_version"]
    assert report["pyarrow_version"]
    assert report["external_access"] == "disabled"
    assert report["spatial_extension"]


def test_duckdb_blueprint_provider_rejects_changed_input(tmp_path):
    spec = _spec(tmp_path)
    source = tmp_path / "districts.parquet"
    source.write_bytes(source.read_bytes() + b"tampered")

    with pytest.raises(
        DuckDBBlueprintProviderContractError,
        match="checksum changed",
    ):
        DuckDBBlueprintProvider().execute(spec)


@pytest.mark.parametrize(
    "sql",
    (
        "SELECT * FROM read_parquet('/tmp/unbound.parquet') ORDER BY 1",
        "SELECT * FROM unbound ORDER BY 1",
        "DELETE FROM source",
        "SELECT * FROM source",
    ),
)
def test_duckdb_blueprint_provider_rejects_unsafe_or_nondeterministic_sql(
    tmp_path,
    sql,
):
    spec = _spec(tmp_path, sql=sql)

    with pytest.raises(DuckDBBlueprintProviderContractError):
        DuckDBBlueprintProvider().execute(spec)


def test_duckdb_blueprint_provider_enforces_output_row_limit(tmp_path):
    spec = _spec(
        tmp_path,
        sql="SELECT * FROM source ORDER BY district, area",
        max_output_rows=2,
    )

    with pytest.raises(
        DuckDBBlueprintProviderContractError,
        match="exceeds max_output_rows",
    ):
        DuckDBBlueprintProvider().execute(spec)


def test_duckdb_blueprint_provider_enforces_input_byte_limit(tmp_path):
    spec = _spec(tmp_path, max_input_bytes=1)

    with pytest.raises(
        DuckDBBlueprintProviderContractError,
        match="exceed max_input_bytes",
    ):
        DuckDBBlueprintProvider().execute(spec)


def test_duckdb_blueprint_spatial_provider_certifies_crs_wkb_bbox_and_geoparquet(
    tmp_path,
):
    spec = _spec(
        tmp_path,
        sql=(
            "WITH projected AS ("
            "SELECT district, ST_Transform(ST_GeomFromWKB(geometry_wkb), "
            "'EPSG:4326', 'EPSG:3857', always_xy := true) AS geom "
            "FROM source WHERE srid = 4326"
            ") SELECT district, ST_AsWKB(geom) AS geometry_wkb, "
            "3857::INTEGER AS srid, "
            "[ST_XMin(geom), ST_YMin(geom), ST_XMax(geom), ST_YMax(geom)]"
            "::DOUBLE[] AS bbox, ST_Area(geom) AS area_m2 "
            "FROM projected ORDER BY district, area_m2"
        ),
        require_spatial=True,
        spatial_output_srid=3857,
    )
    provider = DuckDBBlueprintProvider()

    receipt = provider.execute(spec)
    report = provider.certify(spec)
    output = pq.read_table(tmp_path / "output.parquet")
    geo = json.loads(output.schema.metadata[b"geo"])

    assert receipt.spatial_extension_loaded is True
    assert receipt.spatial_extension_evidence is not None
    assert len(receipt.spatial_extension_evidence.binary_sha256) == 64
    assert receipt.spatial_extension_evidence.autoinstall_enabled is False
    assert receipt.spatial_output_evidence is not None
    assert receipt.spatial_output_evidence.srid == 3857
    assert receipt.spatial_output_evidence.geometry_types == ("Polygon",)
    assert receipt.spatial_output_evidence.invalid_geometry_rows == 0
    assert receipt.spatial_output_evidence.bbox is not None
    assert geo["version"] == "1.1.0"
    assert geo["primary_column"] == "geometry_wkb"
    assert geo["columns"]["geometry_wkb"]["encoding"] == "WKB"
    assert geo["columns"]["geometry_wkb"]["crs"]["id"] == {
        "authority": "EPSG",
        "code": 3857,
    }
    assert all(from_wkb(item).is_valid for item in output["geometry_wkb"].to_pylist())
    assert set(output["srid"].to_pylist()) == {3857}
    assert report.checks["spatial_extension_identity"] == "passed"
    assert report.checks["portable_spatial_encoding"] == "passed"
    assert report.checks["geoparquet_metadata"] == "passed"


def test_duckdb_blueprint_spatial_contract_is_explicit_and_fail_closed(tmp_path):
    with pytest.raises(ValidationError, match="spatial_output_srid together"):
        DuckDBBlueprintPipeline(
            engine="duckdb",
            sql="SELECT * FROM source ORDER BY district",
            require_spatial=True,
        )

    implicit = _spec(
        tmp_path,
        sql=(
            "SELECT ST_AsWKB(ST_GeomFromWKB(geometry_wkb)) AS geometry_wkb "
            "FROM source ORDER BY district"
        ),
    )
    with pytest.raises(DuckDBBlueprintProviderContractError, match="explicit spatial"):
        DuckDBBlueprintProvider().execute(implicit)


def test_duckdb_blueprint_spatial_rejects_unbound_srid_or_bbox(tmp_path):
    spec = _spec(
        tmp_path,
        sql=(
            "SELECT ST_AsWKB(ST_GeomFromWKB(geometry_wkb)) AS geometry_wkb, "
            "4326::INTEGER AS srid, [0.0, 0.0, 1.0, 1.0]::DOUBLE[] AS bbox "
            "FROM source ORDER BY district"
        ),
        require_spatial=True,
        spatial_output_srid=3857,
    )

    with pytest.raises(
        DuckDBBlueprintProviderContractError,
        match="WKB/SRID/bbox contract",
    ):
        DuckDBBlueprintProvider().execute(spec)


def test_duckdb_blueprint_spatial_never_installs_extension_at_runtime(
    tmp_path,
    monkeypatch,
):
    missing = tmp_path / "missing-spatial.duckdb_extension"
    monkeypatch.setenv(
        "GDA_BLUEPRINT_DUCKDB_SPATIAL_EXTENSION_PATH",
        str(missing),
    )
    spec = _spec(
        tmp_path,
        sql=(
            "SELECT ST_AsWKB(ST_GeomFromWKB(geometry_wkb)) AS geometry_wkb, "
            "4326::INTEGER AS srid, bbox FROM source ORDER BY district"
        ),
        require_spatial=True,
        spatial_output_srid=4326,
    )

    with pytest.raises(DuckDBBlueprintProviderContractError, match="not a regular file"):
        DuckDBBlueprintProvider().execute(spec)

    with pytest.raises(DuckDBBlueprintProviderExecutionError, match="readiness probe failed"):
        DuckDBBlueprintProvider().probe()
