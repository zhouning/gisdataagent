import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from data_agent.metadata_fabric_bridge import (
    DEFAULT_GOLDEN_FIXTURE,
    GravitinoClient,
    GravitinoProfile,
    GravitinoTableRef,
    MetadataFabricConfigurationError,
    MetadataFabricNotFoundError,
    MetadataFabricProtocolError,
    OpenMetadataClient,
    OpenMetadataProfile,
    OpenMetadataTableRef,
    ReconciliationStatus,
    build_metadata_fabric_binding,
    build_metadata_fabric_bridge_report,
    parse_gravitino_table_observation,
    parse_openmetadata_table_observation,
    reconcile_metadata_fabric,
)
from data_agent.platform_contracts import Resource, ResourceVersion

NOW = datetime(2026, 7, 27, 9, 0, tzinfo=UTC)


def _payload():
    return json.loads(Path(DEFAULT_GOLDEN_FIXTURE).read_text(encoding="utf-8"))


def _models(payload=None):
    payload = payload or _payload()
    resource = Resource.model_validate(payload["resource"])
    version = ResourceVersion.model_validate(payload["resource_version"])
    openmetadata_ref = OpenMetadataTableRef.model_validate(payload["openmetadata_ref"])
    gravitino_refs = tuple(
        GravitinoTableRef.model_validate(item) for item in payload["gravitino_refs"]
    )
    binding = build_metadata_fabric_binding(
        resource,
        version,
        openmetadata=openmetadata_ref,
        gravitino=gravitino_refs,
    )
    governance = parse_openmetadata_table_observation(
        openmetadata_ref,
        payload["openmetadata_response"],
        observed_at=NOW,
    )
    technical = tuple(
        parse_gravitino_table_observation(ref, response, observed_at=NOW)
        for ref, response in zip(
            gravitino_refs,
            payload["gravitino_responses"],
            strict=True,
        )
    )
    return resource, version, binding, governance, technical


def test_golden_report_is_read_only_and_does_not_claim_live_provider_evidence():
    report = build_metadata_fabric_bridge_report()

    assert report["m1_contract_verified"] is True
    assert report["read_only"] is True
    assert report["writes_performed"] is False
    assert report["production_provider_verified"] is False
    assert report["binding_sha256"] == _payload()["expected"]["binding_sha256"]
    assert (
        report["reconciliation_sha256"]
        == (_payload()["expected"]["reconciliation_sha256"])
    )


def test_golden_replay_is_deterministic():
    assert (
        build_metadata_fabric_bridge_report() == build_metadata_fabric_bridge_report()
    )


def test_binding_requires_resource_to_store_exact_provider_refs():
    payload = _payload()
    payload["resource"]["governance_ref"]["entity_id"] = (
        "10000000-0000-4000-8000-000000000099"
    )
    resource = Resource.model_validate(payload["resource"])
    version = ResourceVersion.model_validate(payload["resource_version"])
    openmetadata_ref = OpenMetadataTableRef.model_validate(payload["openmetadata_ref"])
    gravitino_refs = tuple(
        GravitinoTableRef.model_validate(item) for item in payload["gravitino_refs"]
    )

    with pytest.raises(MetadataFabricConfigurationError, match="governance_ref"):
        build_metadata_fabric_binding(
            resource,
            version,
            openmetadata=openmetadata_ref,
            gravitino=gravitino_refs,
        )


def test_binding_rejects_duplicate_gravitino_identity():
    resource, version, binding, _, _ = _models()
    duplicate_refs = (binding.gravitino[0], binding.gravitino[0])
    resource = resource.model_copy(
        update={
            "technical_refs": tuple(
                item.model_dump(mode="json") for item in duplicate_refs
            )
        }
    )

    with pytest.raises(ValidationError, match="must be unique"):
        build_metadata_fabric_binding(
            resource,
            version,
            openmetadata=binding.openmetadata,
            gravitino=duplicate_refs,
        )


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.update({"deleted": True}),
        lambda value: value.pop("deleted"),
        lambda value: value.pop("extension"),
        lambda value: value["extension"].update({"access_token": "leak"}),
        lambda value: value.update({"owners": []}),
        lambda value: value.update({"tags": ["malformed"]}),
    ),
)
def test_openmetadata_observation_fails_closed_on_untrusted_payload(mutation):
    payload = _payload()
    response = copy.deepcopy(payload["openmetadata_response"])
    mutation(response)
    ref = OpenMetadataTableRef.model_validate(payload["openmetadata_ref"])

    with pytest.raises(MetadataFabricProtocolError):
        parse_openmetadata_table_observation(ref, response, observed_at=NOW)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.update({"code": 1003}),
        lambda value: value["table"].update({"name": "other_table"}),
        lambda value: value["table"]["properties"].pop("gda.content_sha256"),
        lambda value: value["table"]["properties"].update({"secretKey": "leak"}),
        lambda value: value["table"]["properties"].update(
            {"gda.provider_revision": "other-snapshot"}
        ),
    ),
)
def test_gravitino_observation_fails_closed_on_untrusted_payload(mutation):
    payload = _payload()
    response = copy.deepcopy(payload["gravitino_responses"][0])
    mutation(response)
    ref = GravitinoTableRef.model_validate(payload["gravitino_refs"][0])

    with pytest.raises(MetadataFabricProtocolError):
        parse_gravitino_table_observation(ref, response, observed_at=NOW)


def test_reconciliation_blocks_openmetadata_owner_drift():
    resource, version, binding, governance, technical = _models()
    drifted = governance.model_copy(update={"owner_refs": ("team:other",)})

    report = reconcile_metadata_fabric(resource, version, binding, drifted, technical)

    assert report.status == ReconciliationStatus.BLOCKED
    assert report.blockers == ("openmetadata_owner_drift",)
    assert report.writes_performed is False


def test_reconciliation_blocks_provider_attempt_to_change_gda_identity():
    resource, version, binding, governance, technical = _models()
    drifted = technical[0].model_copy(update={"content_sha256": "f" * 64})

    report = reconcile_metadata_fabric(
        resource, version, binding, governance, (drifted,)
    )

    assert report.status == ReconciliationStatus.BLOCKED
    assert report.blockers == (
        "gravitino_gda_identity_drift:gda_lakehouse/iceberg/land_use/land_use_parcels",
    )


def test_reconciliation_records_missing_gravitino_observation_as_blocked():
    resource, version, binding, governance, _ = _models()

    report = reconcile_metadata_fabric(resource, version, binding, governance, ())

    assert report.status == ReconciliationStatus.BLOCKED
    assert report.blockers == ("gravitino_ref_set_mismatch",)
    assert report.gravitino_snapshot_sha256s == ()


def test_reconciliation_rechecks_refs_stored_on_resource():
    resource, version, binding, governance, technical = _models()
    drifted = resource.model_copy(update={"technical_refs": ()})

    report = reconcile_metadata_fabric(drifted, version, binding, governance, technical)

    assert report.status == ReconciliationStatus.BLOCKED
    assert report.blockers == ("resource_technical_refs_drift",)


def test_openmetadata_client_only_uses_pinned_read_route():
    payload = _payload()
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=payload["openmetadata_response"])

    profile = OpenMetadataProfile(
        base_url="https://metadata.example.test/api",
        access_token=SecretStr("test-token"),
    )
    ref = OpenMetadataTableRef.model_validate(payload["openmetadata_ref"])
    with OpenMetadataClient(profile, transport=httpx.MockTransport(handler)) as client:
        assert client.get_table(ref)["id"] == str(ref.entity_id)

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert request.url.path == f"/api/v1/tables/{ref.entity_id}"
    assert request.url.params["include"] == "non-deleted"
    assert "owners" in request.url.params["fields"]
    assert request.headers["authorization"] == "Bearer test-token"


def test_gravitino_client_checks_live_version_then_uses_pinned_read_route():
    payload = _payload()
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "1.3.1"})
        return httpx.Response(200, json=payload["gravitino_responses"][0])

    profile = GravitinoProfile(
        base_url="https://gravitino.example.test/api",
        access_token=SecretStr("test-token"),
        server_version="1.3.1",
    )
    ref = GravitinoTableRef.model_validate(payload["gravitino_refs"][0])
    with GravitinoClient(profile, transport=httpx.MockTransport(handler)) as client:
        assert client.get_version() == "1.3.1"
        assert client.get_table(ref)["code"] == 0

    assert [request.method for request in requests] == ["GET", "GET"]
    assert requests[0].url.path == "/api/version"
    assert requests[1].url.path == (
        "/api/metalakes/gda_lakehouse/catalogs/iceberg/schemas/land_use/"
        "tables/land_use_parcels"
    )
    assert requests[1].headers["accept"] == "application/vnd.gravitino.v1+json"


def test_provider_profiles_require_https_api_root_and_pinned_versions():
    with pytest.raises(ValidationError, match="HTTPS"):
        OpenMetadataProfile(
            base_url="http://metadata.example.test/api",
            access_token=SecretStr("test-token"),
        )
    with pytest.raises(ValidationError, match="/api root"):
        OpenMetadataProfile(
            base_url="https://metadata.example.test",
            access_token=SecretStr("test-token"),
        )
    with pytest.raises(ValidationError, match="exact 1.3.x patch"):
        GravitinoProfile(
            base_url="https://gravitino.example.test/api",
            access_token=SecretStr("test-token"),
            server_version="latest",
        )


def test_provider_not_found_is_distinct_and_does_not_expose_token():
    payload = _payload()

    def handler(_request):
        return httpx.Response(404, json={"message": "missing"})

    profile = OpenMetadataProfile(
        base_url="https://metadata.example.test/api",
        access_token=SecretStr("do-not-report-this-token"),
    )
    ref = OpenMetadataTableRef.model_validate(payload["openmetadata_ref"])
    with (
        OpenMetadataClient(profile, transport=httpx.MockTransport(handler)) as client,
        pytest.raises(MetadataFabricNotFoundError) as exc_info,
    ):
        client.get_table(ref)

    assert "do-not-report-this-token" not in str(exc_info.value)


def test_binding_rejects_cross_tenant_resource_version():
    resource, version, binding, _, _ = _models()
    other_version = version.model_copy(
        update={
            "tenant_id": "tenant-b",
            "resource_urn": "gda://tenant-b/dataset/land-use-parcels-published",
            "resource_version_id": UUID("00000000-0000-4000-8000-000000000099"),
        }
    )

    with pytest.raises(MetadataFabricConfigurationError, match="tenant differ"):
        build_metadata_fabric_binding(
            resource,
            other_version,
            openmetadata=binding.openmetadata,
            gravitino=binding.gravitino,
        )
