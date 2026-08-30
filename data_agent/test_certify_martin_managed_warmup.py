import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

from scripts import certify_martin_managed_warmup as certification


def test_managed_warmup_certificate_wires_latest_bootstrap_and_wraps_evidence(
    monkeypatch, tmp_path
):
    fixture_calls = []
    proof = {
        "schema": "gda.gis_service_martin_managed_warmup.v1",
        "status": "passed",
    }

    def fake_active_release(database_url, **kwargs):
        fixture_calls.append((database_url, kwargs))
        return {
            "fixture": {
                "ephemeral": True,
                "cleanup": "completed",
                "martin_image": "fixture-martin",
                "source_content_sha256": "a" * 64,
            },
            "active_release": {"service_urn": "gda://planning/gis_service/test"},
            "post_activation": proof,
        }

    monkeypatch.setattr(certification, "certify_active_release", fake_active_release)
    report_path = tmp_path / "managed-warmup-report.json"
    report = certification.certify(
        "postgresql://fixture",
        docker_network="fixture-network",
        docker_database_host="fixture-db",
        docker_database_port=6543,
        martin_image="fixture-martin",
        report_path=report_path,
    )

    assert fixture_calls == [
        (
            "postgresql://fixture",
            {
                "docker_network": "fixture-network",
                "docker_database_host": "fixture-db",
                "docker_database_port": 6543,
                "martin_image": "fixture-martin",
                "after_activation": certification._certify_managed_warmup,
                "fixture_bootstrap": certification._bootstrap_latest,
            },
        )
    ]
    assert report["managed_warmup"] == proof
    assert report["fixture"]["cleanup"] == "completed"
    assert json.loads(report_path.read_text(encoding="utf-8")) == report


def test_managed_warmup_certificate_accepts_injected_receipt_store(monkeypatch):
    run_id = uuid4()
    artifact_id = uuid4()
    command_id = uuid4()
    endpoint_id = uuid4()
    storage_evidence = {
        "schema": "gda.gis_service_endpoint_warmup_storage.v1",
        "backend": "s3",
        "version_id": "version-1",
        "etag": "etag-1",
    }
    artifact = SimpleNamespace(
        storage_uri="s3://evidence/gis-warmup/planning/run/receipt.json",
        content_sha256="a" * 64,
        manifest={"storage_evidence": storage_evidence},
    )
    receipt = SimpleNamespace(
        run_id=run_id,
        evidence_artifact_id=artifact_id,
        endpoint_revision_id=endpoint_id,
        deployment_revision_id=uuid4(),
        service_release_binding_id=uuid4(),
        provider_receipt_sha256="a" * 64,
        warmup_sha256="b" * 64,
        sample_set_sha256="c" * 64,
    )
    gateway = SimpleNamespace(
        get_endpoint_revision=lambda tenant, value: SimpleNamespace(
            endpoint_revision_id=value
        ),
        get_run=lambda tenant, value: SimpleNamespace(
            status=SimpleNamespace(value="succeeded")
        ),
        get_command=lambda tenant, value: SimpleNamespace(
            status=SimpleNamespace(value="done")
        ),
        list_gis_service_endpoint_warmups=lambda *args: (receipt,),
        get_artifact=lambda tenant, value: artifact,
    )
    request = SimpleNamespace(run_id=run_id)
    admission = SimpleNamespace(command=SimpleNamespace(command_id=command_id))
    receipt_document = {
        "provider_origin_uri": "http://martin:3000",
        "requested_sample_count": 3,
        "successful_sample_count": 3,
        "mvt_serving_projection_version_id": "projection-1",
        "samples": [
            {"z": 0, "x": 0, "y": 0, "content_bytes": 122},
            {"z": 1, "x": 1, "y": 0, "content_bytes": 122},
            {"z": 2, "x": 3, "y": 1, "content_bytes": 122},
        ],
    }
    receipt_bytes = json.dumps(
        receipt_document, sort_keys=True, separators=(",", ":")
    ).encode()
    artifact.content_sha256 = receipt.provider_receipt_sha256 = hashlib.sha256(
        receipt_bytes
    ).hexdigest()
    active_release = {
        "tenant": "planning",
        "service_urn": "gda://planning/gis_service/test",
        "endpoint_revision_id": str(endpoint_id),
        "deployment_revision_id": str(receipt.deployment_revision_id),
        "service_release_binding_id": str(receipt.service_release_binding_id),
        "mvt_serving_projection_version_id": "projection-1",
    }
    store = SimpleNamespace()
    consumer = SimpleNamespace(
        run_once=lambda *args, **kwargs: SimpleNamespace(
            claimed=1,
            completed=1,
            succeeded=1,
            retry_pending=0,
            failed=0,
        )
    )
    monkeypatch.setattr(
        certification, "_register_warmup_definition", lambda *args: object()
    )
    monkeypatch.setattr(
        certification,
        "_admit",
        lambda *args, **kwargs: (request, admission),
    )
    monkeypatch.setattr(
        certification,
        "GISServiceEndpointWarmupConsumer",
        lambda *args, **kwargs: consumer,
    )
    monkeypatch.setattr(
        certification, "_evidence_counts", lambda *args: (1, 1, 1, 1, 1)
    )

    report = certification._certify_managed_warmup(
        gateway,
        active_release,
        "http://martin:3000",
        receipt_store=store,
        receipt_reader=lambda value: receipt_bytes,
    )

    assert report["status"] == "passed"
    assert report["artifact_storage_uri"].startswith("s3://")
    assert report["artifact_storage_evidence"] == storage_evidence
