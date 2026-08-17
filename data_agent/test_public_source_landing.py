import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from data_agent.api import platform_gateway_routes as routes
from data_agent.platform_gateway import GatewayWriteResult, LandingRegistration
from data_agent.public_source_landing import (
    PublicSourceLandingError,
    PublicSourceLandingRequest,
    main,
    stage_public_source,
    verify_public_source_landing,
)

NOW = datetime(2026, 8, 17, 14, 0, tzinfo=UTC)
PAYLOAD = b'{"type":"FeatureCollection","features":[]}\n'
PAYLOAD_SHA256 = hashlib.sha256(PAYLOAD).hexdigest()


def _request() -> PublicSourceLandingRequest:
    return PublicSourceLandingRequest(
        tenant_id="public-demo",
        dataset_id="natural-earth-countries",
        source_uri=(
            "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
            "v5.1.2/geojson/ne_110m_admin_0_countries.geojson"
        ),
        license_id="public-domain",
        owner_ref="team:data-platform",
        expected_sha256=PAYLOAD_SHA256,
        media_type="application/geo+json",
        created_by="workload:public-source-ingest",
        created_at=NOW,
    )


def _stage(tmp_path: Path):
    source = tmp_path / "countries.geojson"
    source.write_bytes(PAYLOAD)
    return stage_public_source(
        _request(),
        source_path=source,
        landing_root=tmp_path / "landing",
    )


def _api_request(body):
    request = MagicMock()

    async def read_json():
        return body

    request.json.side_effect = read_json
    request.path_params = {}
    request.headers = {"x-request-id": "landing-request"}
    return request


def _user(*, tenant_id="public-demo", identifier="public-source-ingest"):
    return SimpleNamespace(
        identifier=identifier,
        metadata={
            "role": "platform_operator",
            "tenant_id": tenant_id,
            "subject_type": "workload",
        },
    )


def test_stage_public_source_creates_and_replays_immutable_landing(tmp_path):
    result = _stage(tmp_path)
    verify_public_source_landing(result)

    payload = Path(result.payload_path)
    manifest = Path(result.manifest_path)
    assert payload.read_bytes() == PAYLOAD
    assert payload.stat().st_mode & 0o777 == 0o440
    assert manifest.stat().st_mode & 0o777 == 0o440
    assert f"sha256/{PAYLOAD_SHA256}/payload.geojson" in result.payload_path
    assert result.payload_created is True
    assert result.manifest_created is True
    assert result.ledger_created is None

    registration = result.registration
    assert registration.resource.authority_system == "gda_landing"
    assert registration.resource_version.content_sha256 == PAYLOAD_SHA256
    assert registration.artifact.content_sha256 == PAYLOAD_SHA256
    assert registration.artifact.run_id is None
    assert registration.artifact.manifest["content_admission_authorized"] is True
    assert registration.artifact.manifest["production_ready"] is False

    replay = _stage(tmp_path)
    verify_public_source_landing(replay)
    assert replay.registration == registration
    assert replay.payload_created is False
    assert replay.manifest_created is False


def test_stage_rejects_unapproved_or_symlinked_bytes(tmp_path):
    source = tmp_path / "countries.geojson"
    source.write_bytes(PAYLOAD)
    bad_request = _request().model_copy(update={"expected_sha256": "0" * 64})
    with pytest.raises(PublicSourceLandingError, match="does not match"):
        stage_public_source(
            bad_request,
            source_path=source,
            landing_root=tmp_path / "landing",
        )
    assert not tuple((tmp_path / "landing").glob("public-demo/**/payload*"))

    link = tmp_path / "linked.geojson"
    link.symlink_to(source)
    with pytest.raises(PublicSourceLandingError, match="symbolic link"):
        stage_public_source(
            _request(),
            source_path=link,
            landing_root=tmp_path / "other-landing",
        )


def test_verify_detects_payload_and_manifest_tampering(tmp_path):
    result = _stage(tmp_path)
    payload = Path(result.payload_path)
    os.chmod(payload, 0o640)
    payload.write_bytes(b"tampered")
    with pytest.raises(PublicSourceLandingError, match="does not match its key"):
        verify_public_source_landing(result)

    other = tmp_path / "other"
    source = other / "countries.geojson"
    source.parent.mkdir()
    source.write_bytes(PAYLOAD)
    result = stage_public_source(
        _request(), source_path=source, landing_root=other / "landing"
    )
    manifest = Path(result.manifest_path)
    os.chmod(manifest, 0o640)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["manifest"]["license_id"] = "unknown"
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(PublicSourceLandingError, match="does not bind"):
        verify_public_source_landing(result)


def test_public_request_and_registration_fail_closed(tmp_path):
    request_document = _request().model_dump(mode="python")
    request_document["source_uri"] = "file:///private/source.geojson"
    with pytest.raises(ValidationError, match="must use HTTPS"):
        PublicSourceLandingRequest.model_validate(request_document)
    request_document = _request().model_dump(mode="python")
    request_document["created_by"] = "agent:planner"
    with pytest.raises(ValidationError, match="human or workload"):
        PublicSourceLandingRequest.model_validate(request_document)

    result = _stage(tmp_path)
    with pytest.raises(ValidationError, match="public_open admission"):
        LandingRegistration(
            resource=result.registration.resource,
            resource_version=result.registration.resource_version,
            artifact=result.registration.artifact.model_copy(
                update={
                    "manifest": {
                        **result.registration.artifact.manifest,
                        "admission_class": "protected",
                    }
                }
            ),
        )


def test_landing_api_registers_atomically_and_enforces_actor(tmp_path):
    result = _stage(tmp_path)
    registration = result.registration
    gateway = MagicMock()
    gateway.register_landing.return_value = GatewayWriteResult(registration, True)
    request = _api_request(registration.model_dump(mode="json"))
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_gateway", return_value=gateway),
    ):
        response = asyncio.run(routes.create_landing(request))
    assert response.status_code == 201
    assert json.loads(response.body)["created"] is True
    gateway.register_landing.assert_called_once_with(registration)

    request = _api_request(registration.model_dump(mode="json"))
    with patch.object(
        routes,
        "_get_user_from_request",
        return_value=_user(identifier="different-workload"),
    ):
        response = asyncio.run(routes.create_landing(request))
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "actor_mismatch"


def test_cli_stages_and_verifies_landing(tmp_path, capsys):
    source = tmp_path / "countries.geojson"
    source.write_bytes(PAYLOAD)
    output = tmp_path / "landing-result.json"
    exit_code = main(
        [
            "stage",
            "--source-file",
            str(source),
            "--landing-root",
            str(tmp_path / "landing"),
            "--tenant-id",
            "public-demo",
            "--dataset-id",
            "natural-earth-countries",
            "--source-uri",
            _request().source_uri,
            "--license-id",
            "public-domain",
            "--owner-ref",
            "team:data-platform",
            "--expected-sha256",
            PAYLOAD_SHA256,
            "--media-type",
            "application/geo+json",
            "--created-by",
            "workload:public-source-ingest",
            "--created-at",
            "2026-08-17T14:00:00Z",
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    assert output.is_file()
    capsys.readouterr()
    assert main(["verify", "--input", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
