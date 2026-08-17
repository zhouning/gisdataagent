import hashlib
import json
import os
import stat
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from data_agent.public_dataops_run import (
    ATTEMPT_SCHEMA,
    DEFINITION_PUBLISHED_AT,
    PublicDataOpsError,
    PublicDataOpsRequest,
    PublicDataOpsResult,
    _safe_extract_zip,
    main,
    materialize_public_dataops,
    verify_public_dataops_result,
)
from data_agent.public_source_landing import (
    PublicSourceLandingRequest,
    stage_public_source,
)

NOW = datetime(2026, 8, 17, 14, 0, tzinfo=UTC)
FEATURE_COLLECTION = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "id": "capital",
            "properties": {"name": "Example City"},
            "geometry": {"type": "Point", "coordinates": [106.55, 29.56]},
        },
        {
            "type": "Feature",
            "properties": {"name": "Example Area"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[106.0, 29.0], [107.0, 29.0], [107.0, 30.0], [106.0, 29.0]]],
            },
        },
    ],
}


def _request(**updates) -> PublicDataOpsRequest:
    values = {
        "executor": "workload:public-dataops",
        "quality_evaluator": "workload:public-quality",
        "output_dataset_id": "countries-serving",
        "executed_at": NOW,
        "min_feature_count": 1,
    }
    values.update(updates)
    return PublicDataOpsRequest(**values)


def _stage_geojson(
    tmp_path: Path,
    document=FEATURE_COLLECTION,
    *,
    dataset_id: str = "public-features",
    created_at: datetime = NOW,
):
    payload = json.dumps(document, sort_keys=True).encode() + b"\n"
    source = tmp_path / f"{dataset_id}.geojson"
    source.write_bytes(payload)
    return stage_public_source(
        PublicSourceLandingRequest(
            tenant_id="public-demo",
            dataset_id=dataset_id,
            source_uri=f"https://example.org/open/{dataset_id}.geojson",
            license_id="CC0-1.0",
            owner_ref="team:data-platform",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            media_type="application/geo+json",
            created_by="workload:public-source-ingest",
            created_at=created_at,
        ),
        source_path=source,
        landing_root=tmp_path / "landing",
    )


def _materialize(tmp_path: Path, document=FEATURE_COLLECTION):
    return materialize_public_dataops(
        _stage_geojson(tmp_path, document),
        _request(),
        serving_root=tmp_path / "serving",
    )


def test_materializes_deterministic_content_addressed_geojson_and_replays(tmp_path):
    landing = _stage_geojson(tmp_path)
    request = _request()
    first = materialize_public_dataops(landing, request, serving_root=tmp_path / "serving")
    verify_public_dataops_result(first)

    output = json.loads(Path(first.output_path).read_bytes())
    assert output["type"] == "FeatureCollection"
    assert len(output["features"]) == 2
    assert first.output_created is True
    assert first.quality_created is True
    assert f"sha256/{first.output_artifact.content_sha256}/data.geojson" in first.output_path
    assert (
        f"evidence/sha256/{first.quality_evidence_artifact.content_sha256}/quality.json"
        in first.quality_path
    )
    assert first.quality_result.metrics == {
        "bbox_epsg4326": [106.0, 29.0, 107.0, 30.0],
        "crs": "EPSG:4326",
        "empty_geometry_count": 0,
        "feature_count": 2,
        "geometry_types": {"Point": 1, "Polygon": 1},
        "invalid_geometry_count": 0,
        "null_geometry_count": 0,
        "output_sha256": first.output_artifact.content_sha256,
    }

    replay = materialize_public_dataops(landing, request, serving_root=tmp_path / "serving")
    verify_public_dataops_result(replay)
    assert replay.output_created is False
    assert replay.quality_created is False
    assert replay.model_copy(update={"output_created": True, "quality_created": True}) == first


def test_identity_chain_and_portable_definition_are_exact(tmp_path):
    landing = _stage_geojson(tmp_path)
    result = materialize_public_dataops(landing, _request(), serving_root=tmp_path / "serving")
    definition = result.definition_registration

    assert "source_resource_urn" not in definition.definition.definition_document
    assert definition.resource_version.created_at == DEFINITION_PUBLISHED_AT
    assert result.target_resource.governance_ref["source_resource_urn"] == (
        landing.registration.resource.resource_urn
    )
    assert result.run.definition_version_id == definition.definition.definition_version_id
    assert result.run.input_bindings[0].resource_version_id == (
        landing.registration.resource_version.resource_version_id
    )
    assert result.output_artifact.resource_version_id == result.target_version.resource_version_id
    assert result.quality_result.evidence_artifact_id == (
        result.quality_evidence_artifact.artifact_id
    )
    assert result.lineage_event.source_resource_version_id == (
        landing.registration.resource_version.resource_version_id
    )
    assert result.lineage_event.target_resource_version_id == (
        result.target_version.resource_version_id
    )
    assert result.success_evidence.attempt_observation_id == (
        result.attempt_observation.observation_id
    )
    assert result.attempt_observation.evidence["schema"] == ATTEMPT_SCHEMA
    assert result.attempt_observation.evidence["execution_mode"] == "local_inline"

    later_landing = _stage_geojson(
        tmp_path,
        dataset_id="other-public-features",
        created_at=NOW + timedelta(days=1),
    )
    later = materialize_public_dataops(
        later_landing,
        _request(
            executor="workload:alternate-dataops",
            output_dataset_id="other-serving",
            executed_at=NOW + timedelta(days=1),
        ),
        serving_root=tmp_path / "serving",
    )
    assert later.definition_registration == definition


@pytest.mark.parametrize(
    "geometry",
    [
        None,
        {"type": "GeometryCollection", "geometries": []},
        {
            "type": "Polygon",
            "coordinates": [[[0.0, 0.0], [1.0, 1.0], [1.0, 0.0], [0.0, 1.0], [0.0, 0.0]]],
        },
    ],
)
def test_quality_gate_rejects_null_empty_or_invalid_geometry_before_publish(tmp_path, geometry):
    document = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {}, "geometry": geometry}],
    }
    with pytest.raises(PublicDataOpsError, match="quality gate failed"):
        _materialize(tmp_path, document)
    assert not tuple((tmp_path / "serving").glob("**/data.geojson"))


def test_zip_with_directory_and_geojson_is_supported(tmp_path):
    archive = tmp_path / "features.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("dataset/", b"")
        handle.writestr("dataset/features.geojson", json.dumps(FEATURE_COLLECTION))
    landing = stage_public_source(
        PublicSourceLandingRequest(
            tenant_id="public-demo",
            dataset_id="zipped-features",
            source_uri="https://example.org/open/zipped-features.zip",
            license_id="CC0-1.0",
            owner_ref="team:data-platform",
            expected_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            media_type="application/zip",
            created_by="workload:public-source-ingest",
            created_at=NOW,
        ),
        source_path=archive,
        landing_root=tmp_path / "landing",
    )
    result = materialize_public_dataops(landing, _request(), serving_root=tmp_path / "serving")
    assert result.quality_result.metrics["feature_count"] == 2


def _mark_zip_encrypted(path: Path) -> None:
    payload = bytearray(path.read_bytes())
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        position = payload.find(signature)
        assert position >= 0
        payload[position + flag_offset] |= 1
    path.write_bytes(payload)


@pytest.mark.parametrize("unsafe_kind", ["traversal", "symlink", "encrypted"])
def test_zip_rejects_unsafe_entries(tmp_path, unsafe_kind):
    archive = tmp_path / f"{unsafe_kind}.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        if unsafe_kind == "traversal":
            handle.writestr("../outside.geojson", json.dumps(FEATURE_COLLECTION))
        elif unsafe_kind == "symlink":
            info = zipfile.ZipInfo("features.geojson")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            handle.writestr(info, "target.geojson")
        else:
            handle.writestr("features.geojson", json.dumps(FEATURE_COLLECTION))
    if unsafe_kind == "encrypted":
        _mark_zip_encrypted(archive)
    with pytest.raises(PublicDataOpsError, match="unsafe entry|symbolic link"):
        _safe_extract_zip(archive, tmp_path / "extract")
    assert not (tmp_path / "outside.geojson").exists()


def test_request_requires_independent_quality_evaluator():
    with pytest.raises(ValidationError, match="quality evaluator must be independent"):
        _request(quality_evaluator="workload:public-dataops")


@pytest.mark.parametrize("target", ["output", "quality"])
def test_verification_detects_output_and_quality_tampering(tmp_path, target):
    result = _materialize(tmp_path)
    path = Path(result.output_path if target == "output" else result.quality_path)
    os.chmod(path, 0o640)
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(PublicDataOpsError, match="does not match"):
        verify_public_dataops_result(result)


def test_cli_runs_and_verifies_bundle(tmp_path, capsys):
    landing = _stage_geojson(tmp_path)
    landing_result = tmp_path / "landing-result.json"
    landing_result.write_text(landing.model_dump_json(indent=2) + "\n", encoding="utf-8")
    output = tmp_path / "dataops-result.json"
    assert (
        main(
            [
                "run",
                "--landing-result",
                str(landing_result),
                "--serving-root",
                str(tmp_path / "serving"),
                "--output-dataset-id",
                "countries-serving",
                "--executed-at",
                "2026-08-17T14:00:00Z",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    capsys.readouterr()
    result = PublicDataOpsResult.model_validate_json(output.read_text(encoding="utf-8"))
    assert result.ledger_completed is None
    assert main(["verify", "--input", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
