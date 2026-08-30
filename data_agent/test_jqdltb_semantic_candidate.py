from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from data_agent.jqdltb_semantic_candidate import (
    JqdltbSemanticCandidateConfig,
    build_semantic_candidate,
)
from data_agent.platform_contracts import (
    JqdltbSemanticFieldQuarantineArtifact,
    canonical_json_fingerprint,
)

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/reports/jqdltb_semantic_candidate_audit_2026-08-26.json"
SOURCE_ID = UUID("34441c77-2cf0-5ca2-83bf-81dd6a488d5b")
ARCHIVE_SHA256 = "2043b60c2f4f7f32a31388a634fae4ac28534990e205aa86b8df0e4b64dcbbca"
BUNDLE_SHA256 = "cae2047f6b72127e5eae0651909761c0f06d8c3e0491921dbd806c653ba715c3"
STANDARD_FINGERPRINT = (
    "a9b58ea766e1f7fd0f203b07bb23e3848e1db7dad560ebf04843b83a5b713630"
)


def _source(path: Path, *, include_untrusted_targets: bool = False) -> None:
    rows = []
    for key, area in (("A", 1), ("B", 0), ("C", 2)):
        properties = {
            "TBBH": key,
            "TBMJ": area,
            "TBDLMJ": area,
            "JQDLMC": "耕地",
        }
        if include_untrusted_targets:
            properties.update({"SJNF": "2019", "MSSM": "01"})
        rows.append(
            {
                "type": "Feature",
                "id": key,
                "properties": properties,
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [0, 1], [0, 0]]],
                },
            }
        )
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": "EPSG:4523"}},
                "features": rows,
            }
        ),
        encoding="utf-8",
    )


def _config(tmp_path: Path, *, source: Path) -> JqdltbSemanticCandidateConfig:
    return JqdltbSemanticCandidateConfig(
        source_path=source.resolve(),
        output_root=(tmp_path / "outputs").resolve(),
        tenant_id="local-dev",
        source_resource_version_id=SOURCE_ID,
        source_resource_urn="gda://local-dev/dataset/chongqing-bizhu-jqdltb-source",
        archive_sha256=ARCHIVE_SHA256,
        bundle_sha256=BUNDLE_SHA256,
        standard_version_ref="NR_ONE_MAP_TWM_CORE_2026:2026-06-16-draft",
        standard_fingerprint=STANDARD_FINGERPRINT,
        semantic_candidate_audit_path=AUDIT.resolve(),
        allow_non_shapefile_fixture=True,
    )


def test_candidate_omits_unresolved_semantic_fields_and_writes_typed_quarantine(
    tmp_path: Path,
) -> None:
    source = tmp_path / "JQDLTB.geojson"
    _source(source, include_untrusted_targets=True)

    result = build_semantic_candidate(
        _config(tmp_path, source=source),
        evaluated_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
    )

    assert result.status == "completed_non_promotable_candidate"
    assert result.quality_verdict == "failed"
    assert result.promotable is False
    assert result.authority_state_created is False
    assert result.data_product_version_created is False
    assert result.records_read == 3
    assert result.records_materialized == 3
    assert result.semantic_fields_quarantined == 6

    output = Path(result.output_root)
    raw = json.loads((output / "raw/jqdltb.json").read_text(encoding="utf-8"))
    ads = json.loads((output / "ads/jqdltb.json").read_text(encoding="utf-8"))
    assert raw["features"][0]["properties"]["SJNF"] == "2019"
    assert raw["features"][0]["properties"]["MSSM"] == "01"
    assert "SJNF" not in ads["features"][0]["properties"]
    assert "MSSM" not in ads["features"][0]["properties"]

    quarantine_payload = json.loads(
        (output / "quarantine/semantic-fields.json").read_text(encoding="utf-8")
    )
    quarantine = JqdltbSemanticFieldQuarantineArtifact.model_validate(quarantine_payload)
    assert quarantine_payload["schema"] == "gda.jqdltb_semantic_field_quarantine.v1"
    assert quarantine.records_quarantined == 6
    assert {entry.target_field for entry in quarantine.records} == {"SJNF", "MSSM"}
    assert all(
        entry.reason == "semantic_derivation_unresolved"
        and entry.policy == "quarantine_until_authority_exists"
        for entry in quarantine.records
    )
    assert all("value" not in entry.model_dump() for entry in quarantine.records)

    evidence = json.loads((output / "candidate-evidence.json").read_text(encoding="utf-8"))
    assert evidence["quality"]["verdict"] == "failed"
    assert evidence["quality"]["promotion_ready"] is False
    assert evidence["quarantine"]["relative_path"] == "quarantine/semantic-fields.json"
    assert evidence["quarantine"]["artifact_sha256"] == quarantine.artifact_sha256
    assert evidence["authority_state_created"] is False
    assert evidence["data_product_version_created"] is False


def test_candidate_replays_without_creating_a_second_output(tmp_path: Path) -> None:
    source = tmp_path / "JQDLTB.geojson"
    _source(source)
    config = _config(tmp_path, source=source)

    first = build_semantic_candidate(config)
    replay = build_semantic_candidate(config)

    assert replay.replayed is True
    assert replay.candidate_sha256 == first.candidate_sha256
    assert list((tmp_path / "outputs/local-dev" / str(SOURCE_ID)).iterdir())


def test_candidate_rejects_an_audit_that_has_been_semantically_admitted(
    tmp_path: Path,
) -> None:
    source = tmp_path / "JQDLTB.geojson"
    _source(source)
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    audit["decisions"]["SJNF"] = "accepted"
    audit.pop("report_sha256")
    audit["report_sha256"] = canonical_json_fingerprint(audit)
    audit_path = tmp_path / "accepted-audit.json"
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    config = _config(tmp_path, source=source).model_copy(
        update={"semantic_candidate_audit_path": audit_path.resolve()}
    )

    with pytest.raises(ValueError, match="approved transformation executor"):
        build_semantic_candidate(config)


def test_semantic_quarantine_artifact_fingerprint_is_tamper_evident(
    tmp_path: Path,
) -> None:
    source = tmp_path / "JQDLTB.geojson"
    _source(source)
    result = build_semantic_candidate(_config(tmp_path, source=source))
    path = Path(result.output_root) / "quarantine/semantic-fields.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["records"][0]["record_key"] = "tampered"
    with pytest.raises(ValueError, match="fingerprint"):
        JqdltbSemanticFieldQuarantineArtifact.model_validate(payload)
