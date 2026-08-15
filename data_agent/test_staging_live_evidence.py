import hashlib
import json
from datetime import UTC, datetime, timedelta

from data_agent import (
    staging_candidate_evidence,
    staging_live_evidence,
    staging_release_evidence,
)

NOW = datetime(2026, 7, 26, 6, 0, tzinfo=UTC)
SOURCE_REVISION = "a" * 40
SCHEMA_FINGERPRINT = "b" * 64
CANDIDATE_CONFIG_FINGERPRINT = "c" * 64
LIVE_CONFIG_FINGERPRINT = "6" * 64
ENVIRONMENT_ACCESS_FINGERPRINT = "7" * 64
RUNTIME_FINGERPRINT = "d" * 64
IMAGE_DIGEST = "sha256:" + "e" * 64
IMAGE = "registry.example.com/platform/gis-data-agent@" + IMAGE_DIGEST
CLUSTER_UID = "00000000-0000-4000-8000-000000000101"
NAMESPACE_UID = "00000000-0000-4000-8000-000000000102"
DEPLOYMENT_UID = "00000000-0000-4000-8000-000000000103"
SERVICE_ACCOUNT_UID = "00000000-0000-4000-8000-000000000104"
POD_UID = "00000000-0000-4000-8000-000000000105"
GOLDEN_TENANT_ID = "local-dev"
GOLDEN_CAPABILITY_ID = "transportation.osm_roads.layered_publish"
GOLDEN_DEFINITION_VERSION_ID = "00000000-0000-4000-8000-000000000204"
GOLDEN_INPUT_RESOURCE_VERSION_ID = "00000000-0000-4000-8000-000000000205"
GOLDEN_IDENTITY_KWARGS = {
    "expected_golden_tenant_id": GOLDEN_TENANT_ID,
    "expected_golden_capability_id": GOLDEN_CAPABILITY_ID,
    "expected_golden_definition_version_id": GOLDEN_DEFINITION_VERSION_ID,
    "expected_golden_input_resource_version_id": (
        GOLDEN_INPUT_RESOURCE_VERSION_ID
    ),
}


def _fingerprint(value: object) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


PLATFORM_FINGERPRINT = _fingerprint(
    {
        "config": LIVE_CONFIG_FINGERPRINT,
        "environment_access": ENVIRONMENT_ACCESS_FINGERPRINT,
        "runtime": RUNTIME_FINGERPRINT,
    }
)
CANDIDATE_PLATFORM_FINGERPRINT = _fingerprint(
    {
        "config": CANDIDATE_CONFIG_FINGERPRINT,
        "environment_access": ENVIRONMENT_ACCESS_FINGERPRINT,
        "runtime": RUNTIME_FINGERPRINT,
    }
)


def _candidate() -> dict:
    schema = {
        "status": "in_sync",
        "catalog_count": 97,
        "applied_count": 97,
        "catalog_fingerprint": SCHEMA_FINGERPRINT,
        "database_fingerprint": SCHEMA_FINGERPRINT,
        "pending": [],
        "unknown_applied": [],
        "missing_checksums": [],
        "checksum_mismatches": [],
        "metadata_mismatches": [],
    }
    platform = {
        "schema": "gda.platform_truth.v1",
        "platform_fingerprint": CANDIDATE_PLATFORM_FINGERPRINT,
        "config": {
            "profile": "staging",
            "strict": True,
            "valid": True,
            "startup_allowed": True,
            "config_fingerprint": CANDIDATE_CONFIG_FINGERPRINT,
        },
        "environment_access": {
            "fingerprint": ENVIRONMENT_ACCESS_FINGERPRINT,
            "matches_baseline": True,
            "parse_errors": [],
        },
        "runtime": {
            "status": "valid",
            "errors": [],
            "matches_primitive_baseline": True,
            "inventory_fingerprint": RUNTIME_FINGERPRINT,
        },
    }
    return staging_candidate_evidence.build_candidate_evidence(
        schema,
        platform,
        {"tests": 12, "failures": 0, "errors": 0, "skipped": 1},
        source_revision=SOURCE_REVISION,
        image_id="sha256:" + "f" * 64,
    )


def _release(candidate: dict) -> dict:
    stable = {
        "schema": staging_release_evidence.RELEASE_EVIDENCE_SCHEMA,
        "source_revision": candidate["source_revision"],
        "verifier_revision": "9" * 40,
        "candidate_evidence_fingerprint": candidate["evidence_fingerprint"],
        "registry_evidence_fingerprint": "1" * 64,
        "provenance_evidence_fingerprint": "2" * 64,
        "repository": "registry.example.com/platform/gis-data-agent",
        "digest": IMAGE_DIGEST,
        "image": IMAGE,
        "schema_fingerprint": candidate["schema_fingerprint"],
        "platform_fingerprint": candidate["platform_fingerprint"],
        "config_fingerprint": candidate["config_fingerprint"],
        "environment_access_fingerprint": candidate[
            "environment_access_fingerprint"
        ],
        "runtime_fingerprint": candidate["runtime_fingerprint"],
        "staging_apply_allowed": True,
        "errors": [],
    }
    return {
        **stable,
        "status": "staging_release_admitted",
        "staging_deployed": False,
        "live_cluster_verified": False,
        "golden_slice_verified": False,
        "promotion_authority_verified": False,
        "production_promotion_allowed": False,
        "evidence_fingerprint": (
            staging_release_evidence.release_evidence_fingerprint(stable)
        ),
    }


def _schema_report() -> dict:
    return {
        "format_version": 1,
        "generated_at": NOW.isoformat(),
        "status": "in_sync",
        "ledger_present": True,
        "catalog_fingerprint": SCHEMA_FINGERPRINT,
        "database_fingerprint": SCHEMA_FINGERPRINT,
        "catalog_count": 97,
        "applied_count": 97,
        "pending": [],
        "unknown_applied": [],
        "missing_checksums": [],
        "checksum_mismatches": [],
        "metadata_mismatches": [],
    }


def _platform_snapshot() -> dict:
    return {
        "schema": "gda.platform_truth.v1",
        "generated_at": NOW.isoformat(),
        "platform_fingerprint": PLATFORM_FINGERPRINT,
        "config": {
            "schema": "gda.platform_truth.v1",
            "generated_at": NOW.isoformat(),
            "profile": "staging",
            "strict": True,
            "valid": True,
            "startup_allowed": True,
            "config_fingerprint": LIVE_CONFIG_FINGERPRINT,
        },
        "environment_access": {
            "fingerprint": ENVIRONMENT_ACCESS_FINGERPRINT,
            "matches_baseline": True,
            "parse_errors": [],
        },
        "runtime": {
            "schema": "gda.platform_truth.v1",
            "status": "valid",
            "matches_primitive_baseline": True,
            "inventory_fingerprint": RUNTIME_FINGERPRINT,
        },
    }


def _collection(candidate: dict) -> dict:
    release = _release(candidate)
    return {
        "schema": staging_live_evidence.COLLECTION_SCHEMA,
        "observed_at": NOW.isoformat(),
        "kubernetes": {
            "cluster_uid": CLUSTER_UID,
            "namespace": {
                "name": "gis-agent-staging",
                "uid": NAMESPACE_UID,
                "resource_version": "10",
            },
            "deployment": {
                "name": "gis-agent-app",
                "uid": DEPLOYMENT_UID,
                "resource_version": "20",
                "generation": 3,
                "observed_generation": 3,
                "replicas": 1,
                "status_replicas": 1,
                "updated_replicas": 1,
                "ready_replicas": 1,
                "available_replicas": 1,
                "available": True,
                "progressing": True,
                "source_revision": SOURCE_REVISION,
                "candidate_evidence_fingerprint": candidate[
                    "evidence_fingerprint"
                ],
                "environment": "staging",
                "platform_fingerprint": PLATFORM_FINGERPRINT,
                "release_evidence_fingerprint": release[
                    "evidence_fingerprint"
                ],
                "schema_fingerprint": SCHEMA_FINGERPRINT,
                "environment_access_fingerprint": (
                    ENVIRONMENT_ACCESS_FINGERPRINT
                ),
                "runtime_fingerprint": RUNTIME_FINGERPRINT,
                "image": IMAGE,
                "service_account_name": "gis-agent-app",
                "automount_service_account_token": False,
            },
            "service_account": {
                "name": "gis-agent-app",
                "uid": SERVICE_ACCOUNT_UID,
                "resource_version": "21",
            },
            "pods": [
                {
                    "name": "gis-agent-app-abc",
                    "uid": POD_UID,
                    "created_at": (NOW - timedelta(minutes=10)).isoformat(),
                    "phase": "Running",
                    "service_account_name": "gis-agent-app",
                    "image": IMAGE,
                    "image_id": "docker-pullable://" + IMAGE,
                    "ready": True,
                    "restart_count": 0,
                }
            ],
            "ready_endpoint_pod_uids": [POD_UID],
        },
        "schema_report": _schema_report(),
        "platform_snapshot": _platform_snapshot(),
        "health": {
            "liveness": {"status": "ok", "checks": {}},
            "readiness": {
                "status": "ok",
                "checks": {"database": {"status": "ok"}},
            },
        },
    }


def _raw_rollout_resources() -> tuple[dict, dict, dict]:
    deployment = {
        "metadata": {
            "name": "gis-agent-app",
            "uid": DEPLOYMENT_UID,
            "generation": 3,
            "annotations": {"internal.example/token": "must-never-appear"},
        },
        "spec": {
            "replicas": 1,
            "template": {
                "spec": {
                    "containers": [{"name": "app", "image": IMAGE}]
                }
            },
        },
        "status": {
            "observedGeneration": 3,
            "replicas": 1,
            "updatedReplicas": 1,
            "readyReplicas": 1,
            "availableReplicas": 1,
        },
    }
    pods = {
        "items": [
            {
                "metadata": {"name": "gis-agent-app-new", "uid": POD_UID},
                "spec": {
                    "containers": [
                        {
                            "name": "app",
                            "image": IMAGE,
                            "env": [
                                {
                                    "name": "SECRET",
                                    "value": "must-never-appear",
                                }
                            ],
                        }
                    ]
                },
                "status": {
                    "phase": "Running",
                    "containerStatuses": [
                        {
                            "name": "app",
                            "imageID": "docker-pullable://" + IMAGE,
                            "ready": True,
                        }
                    ],
                },
            }
        ]
    }
    endpoint_slices = {
        "items": [
            {
                "endpoints": [
                    {
                        "conditions": {"ready": True},
                        "targetRef": {"kind": "Pod", "uid": POD_UID},
                    }
                ]
            }
        ]
    }
    return deployment, pods, endpoint_slices


def _golden_slice() -> dict:
    golden = {
        "schema": staging_live_evidence.GOLDEN_SLICE_SCHEMA,
        "environment": "staging",
        "status": "passed",
        "source_revision": SOURCE_REVISION,
        "deployment_uid": DEPLOYMENT_UID,
        "image_digest": IMAGE_DIGEST,
        "schema_fingerprint": SCHEMA_FINGERPRINT,
        "config_fingerprint": LIVE_CONFIG_FINGERPRINT,
        "environment_access_fingerprint": ENVIRONMENT_ACCESS_FINGERPRINT,
        "runtime_fingerprint": RUNTIME_FINGERPRINT,
        "tenant_id": GOLDEN_TENANT_ID,
        "capability_id": GOLDEN_CAPABILITY_ID,
        "definition_version_id": GOLDEN_DEFINITION_VERSION_ID,
        "definition_sha256": "5" * 64,
        "input_resource_version_id": GOLDEN_INPUT_RESOURCE_VERSION_ID,
        "output_resource_version_id": "00000000-0000-4000-8000-000000000206",
        "run_id": "00000000-0000-4000-8000-000000000201",
        "output_artifact_sha256": "2" * 64,
        "quality_result_id": "00000000-0000-4000-8000-000000000202",
        "quality_evidence_fingerprint": "3" * 64,
        "lineage_event_id": "00000000-0000-4000-8000-000000000203",
        "run_success_evidence_fingerprint": "4" * 64,
        "observed_at": NOW.isoformat(),
        "evidence_fingerprint": "",
    }
    golden["evidence_fingerprint"] = (
        staging_live_evidence.golden_slice_fingerprint(golden)
    )
    return golden


def test_complete_live_staging_observation_still_cannot_authorize_production():
    candidate = _candidate()
    report = staging_live_evidence.build_live_staging_evidence(
        candidate,
        _release(candidate),
        _collection(candidate),
        _golden_slice(),
        expected_cluster_uid=CLUSTER_UID,
        expected_namespace_uid=NAMESPACE_UID,
        **GOLDEN_IDENTITY_KWARGS,
        now=NOW,
    )

    assert report["status"] == "live_staging_verified"
    assert report["live_staging_verified"] is True
    assert report["staging_deployed"] is True
    assert report["registry_digest_verified"] is True
    assert report["golden_slice_verified"] is True
    assert report["candidate_config_fingerprint"] == CANDIDATE_CONFIG_FINGERPRINT
    assert report["config_fingerprint"] == LIVE_CONFIG_FINGERPRINT
    assert (
        report["environment_access_fingerprint"]
        == ENVIRONMENT_ACCESS_FINGERPRINT
    )
    assert set(report["checks"].values()) == {"passed"}
    assert report["promotion_authority_verified"] is False
    assert report["production_promotion_allowed"] is False
    assert len(report["required_promotion_provenance"]) == 3


def test_golden_identity_drift_blocks_after_recomputed_content_fingerprint():
    candidate = _candidate()
    golden = _golden_slice()
    golden["capability_id"] = "transportation.other"
    golden["evidence_fingerprint"] = (
        staging_live_evidence.golden_slice_fingerprint(golden)
    )

    report = staging_live_evidence.build_live_staging_evidence(
        candidate,
        _release(candidate),
        _collection(candidate),
        golden,
        expected_cluster_uid=CLUSTER_UID,
        expected_namespace_uid=NAMESPACE_UID,
        **GOLDEN_IDENTITY_KWARGS,
        now=NOW,
    )

    assert report["checks"]["golden_slice"] == "blocked"
    assert report["golden_slice_verified"] is False
    assert any(
        "capability_id does not match the protected identity" in error
        for error in report["errors"]
    )
    assert report["production_promotion_allowed"] is False


def test_live_gate_reports_revision_digest_identity_and_evidence_drift():
    candidate = _candidate()
    candidate["source_revision"] = "9" * 40
    collection = _collection(_candidate())
    kubernetes = collection["kubernetes"]
    kubernetes["cluster_uid"] = "00000000-0000-4000-8000-000000000999"
    deployment = kubernetes["deployment"]
    deployment["replicas"] = 2
    deployment["image"] = "gis-data-agent:latest"
    deployment["ready_replicas"] = 0
    deployment["automount_service_account_token"] = True
    kubernetes["ready_endpoint_pod_uids"] = [{}]
    collection["schema_report"]["pending"] = ["098_missing"]
    collection["platform_snapshot"]["config"]["profile"] = "development"
    collection["health"]["readiness"]["status"] = "error"
    golden = _golden_slice()
    golden["output_artifact_sha256"] = "5" * 64

    report = staging_live_evidence.build_live_staging_evidence(
        candidate,
        _release(candidate),
        collection,
        golden,
        expected_cluster_uid=CLUSTER_UID,
        expected_namespace_uid=NAMESPACE_UID,
        **GOLDEN_IDENTITY_KWARGS,
        now=NOW,
    )

    assert report["status"] == "blocked"
    assert report["live_staging_verified"] is False
    assert report["production_promotion_allowed"] is False
    assert report["checks"] == {
        "candidate": "blocked",
        "release": "passed",
        "collection": "passed",
        "kubernetes": "blocked",
        "schema": "blocked",
        "platform": "blocked",
        "health": "blocked",
        "golden_slice": "blocked",
    }
    rendered = "\n".join(report["errors"])
    assert "candidate evidence fingerprint does not match" in rendered
    assert "cluster UID does not match" in rendered
    assert "exactly one staging replica" in rendered
    assert "immutable registry digest" in rendered
    assert "service account token mounting" in rendered
    assert "EndpointSlice Pod UIDs" in rendered
    assert "live schema report contains pending" in rendered
    assert "strict staging" in rendered
    assert "readiness endpoint is not healthy" in rendered
    assert "golden-slice evidence fingerprint does not match" in rendered


def test_stale_collection_and_missing_golden_slice_fail_closed():
    candidate = _candidate()
    collection = _collection(candidate)
    collection["observed_at"] = (NOW - timedelta(seconds=901)).isoformat()
    collection["unexpected"] = "must-never-appear"

    report = staging_live_evidence.build_live_staging_evidence(
        candidate,
        _release(candidate),
        collection,
        None,
        expected_cluster_uid=CLUSTER_UID,
        expected_namespace_uid=NAMESPACE_UID,
        **GOLDEN_IDENTITY_KWARGS,
        now=NOW,
    )

    assert report["checks"]["collection"] == "blocked"
    assert report["checks"]["golden_slice"] == "blocked"
    assert "collection: live collection is stale" in report["errors"]
    assert any("v1 allowlist" in error for error in report["errors"])
    assert "golden_slice: live golden-slice evidence is missing" in report["errors"]
    assert report["staging_deployed"] is False
    assert report["registry_digest_verified"] is False
    assert report["golden_slice_verified"] is False
    assert report["production_promotion_allowed"] is False
    assert "must-never-appear" not in json.dumps(report)


def test_candidate_payload_is_revalidated_after_fingerprint_recomputation():
    candidate = _candidate()
    candidate["image_id"] = "gis-data-agent:latest"
    candidate["tests"]["failures"] = 1
    candidate["evidence_fingerprint"] = _fingerprint(
        {
            field: candidate.get(field)
            for field in staging_live_evidence.CANDIDATE_STABLE_FIELDS
        }
    )
    collection = _collection(candidate)

    report = staging_live_evidence.build_live_staging_evidence(
        candidate,
        _release(candidate),
        collection,
        _golden_slice(),
        expected_cluster_uid=CLUSTER_UID,
        expected_namespace_uid=NAMESPACE_UID,
        **GOLDEN_IDENTITY_KWARGS,
        now=NOW,
    )

    assert report["checks"]["candidate"] == "blocked"
    assert any("immutable local sha256" in error for error in report["errors"])
    assert any("failures must be zero" in error for error in report["errors"])
    assert report["staging_deployed"] is False
    assert report["golden_slice_verified"] is False
    assert report["production_promotion_allowed"] is False


def test_live_environment_access_drift_fails_closed():
    candidate = _candidate()
    collection = _collection(candidate)
    environment_access = collection["platform_snapshot"]["environment_access"]
    environment_access["fingerprint"] = "8" * 64
    environment_access["matches_baseline"] = False
    environment_access["parse_errors"] = ["data_agent/example.py: invalid syntax"]
    collection["platform_snapshot"]["platform_fingerprint"] = _fingerprint(
        {
            "config": LIVE_CONFIG_FINGERPRINT,
            "environment_access": "8" * 64,
            "runtime": RUNTIME_FINGERPRINT,
        }
    )

    report = staging_live_evidence.build_live_staging_evidence(
        candidate,
        _release(candidate),
        collection,
        _golden_slice(),
        expected_cluster_uid=CLUSTER_UID,
        expected_namespace_uid=NAMESPACE_UID,
        now=NOW,
    )

    assert report["checks"]["platform"] == "blocked"
    assert report["checks"]["golden_slice"] == "blocked"
    assert report["live_staging_verified"] is False
    assert report["production_promotion_allowed"] is False
    rendered = "\n".join(report["errors"])
    assert "environment accesses drifted" in rendered
    assert "environment access scan contains parse errors" in rendered
    assert "environment access fingerprint does not match" in rendered


def test_live_image_must_match_the_attested_release_digest():
    candidate = _candidate()
    collection = _collection(candidate)
    other_digest = "sha256:" + "8" * 64
    other_image = (
        "registry.example.com/platform/gis-data-agent@" + other_digest
    )
    deployment = collection["kubernetes"]["deployment"]
    deployment["image"] = other_image
    pod = collection["kubernetes"]["pods"][0]
    pod["image"] = other_image
    pod["image_id"] = "docker-pullable://" + other_image

    report = staging_live_evidence.build_live_staging_evidence(
        candidate,
        _release(candidate),
        collection,
        None,
        expected_cluster_uid=CLUSTER_UID,
        expected_namespace_uid=NAMESPACE_UID,
        now=NOW,
    )

    assert report["checks"]["release"] == "passed"
    assert report["checks"]["kubernetes"] == "blocked"
    assert report["registry_digest_verified"] is False
    assert any(
        "image does not match the attested release" in error
        for error in report["errors"]
    )
    assert report["production_promotion_allowed"] is False


def test_rollout_convergence_waits_for_old_pod_and_endpoint_removal():
    deployment, pods, endpoint_slices = _raw_rollout_resources()
    old_pod_uid = "00000000-0000-4000-8000-000000000106"
    pods["items"].append(
        {
            "metadata": {
                "name": "gis-agent-app-old",
                "uid": old_pod_uid,
                "deletionTimestamp": NOW.isoformat(),
            },
            "spec": {
                "containers": [
                    {
                        "name": "app",
                        "image": (
                            "registry.example.com/platform/"
                            "gis-data-agent@sha256:" + "8" * 64
                        ),
                    }
                ]
            },
            "status": {
                "phase": "Running",
                "containerStatuses": [
                    {
                        "name": "app",
                        "imageID": "docker-pullable://sha256:" + "8" * 64,
                        "ready": False,
                    }
                ],
            },
        }
    )

    report = staging_live_evidence.build_rollout_convergence_observation(
        deployment,
        pods,
        endpoint_slices,
        expected_image=IMAGE,
        now=NOW,
    )

    assert report["status"] == "waiting"
    rendered = "\n".join(report["errors"])
    assert "Pod count has not converged" in rendered
    assert "still terminating" in rendered
    assert "runtime image ID has not converged" in rendered

    pods["items"] = pods["items"][:1]
    endpoint_slices["items"][0]["endpoints"][0]["targetRef"]["uid"] = (
        old_pod_uid
    )
    report = staging_live_evidence.build_rollout_convergence_observation(
        deployment,
        pods,
        endpoint_slices,
        expected_image=IMAGE,
        now=NOW,
    )
    assert report["status"] == "waiting"
    assert "ready EndpointSlice Pod UIDs have not converged" in report[
        "errors"
    ]

    endpoint_slices["items"][0]["endpoints"][0]["targetRef"]["uid"] = POD_UID
    report = staging_live_evidence.build_rollout_convergence_observation(
        deployment,
        pods,
        endpoint_slices,
        expected_image=IMAGE,
        now=NOW,
    )
    assert report["status"] == "converged"
    assert report["errors"] == []


def test_rollout_convergence_collector_projects_only_allowlisted_fields():
    responses = list(_raw_rollout_resources())
    commands: list[list[str]] = []

    def run(arguments: list[str]) -> str:
        commands.append(arguments)
        return json.dumps(responses.pop(0))

    report = staging_live_evidence.collect_rollout_convergence(
        expected_image=IMAGE,
        now=NOW,
        run=run,
    )

    assert report["schema"] == (
        staging_live_evidence.ROLLOUT_CONVERGENCE_SCHEMA
    )
    assert report["status"] == "converged"
    assert responses == []
    assert len(commands) == 3
    assert any("endpointslices" in command for command in commands)
    assert "must-never-appear" not in json.dumps(report)


def test_collector_projects_allowlisted_fields_and_never_reads_secrets():
    candidate = _candidate()
    collection = _collection(candidate)
    raw_deployment = {
        "metadata": {
            "name": "gis-agent-app",
            "uid": DEPLOYMENT_UID,
            "resourceVersion": "20",
            "generation": 3,
            "annotations": {
                "kubectl.kubernetes.io/last-applied-configuration": (
                    "must-never-appear"
                )
            },
        },
        "spec": {
            "replicas": 1,
            "template": {
                "metadata": {
                    "annotations": {
                        staging_live_evidence.SOURCE_REVISION_ANNOTATION: (
                            SOURCE_REVISION
                        ),
                        staging_live_evidence.CANDIDATE_FINGERPRINT_ANNOTATION: (
                            candidate["evidence_fingerprint"]
                        ),
                        staging_live_evidence.ENVIRONMENT_ANNOTATION: "staging",
                        staging_live_evidence.PLATFORM_FINGERPRINT_ANNOTATION: (
                            PLATFORM_FINGERPRINT
                        ),
                        staging_live_evidence.RELEASE_FINGERPRINT_ANNOTATION: (
                            _release(candidate)["evidence_fingerprint"]
                        ),
                        staging_live_evidence.SCHEMA_FINGERPRINT_ANNOTATION: (
                            SCHEMA_FINGERPRINT
                        ),
                        staging_live_evidence.ENVIRONMENT_ACCESS_FINGERPRINT_ANNOTATION: (
                            ENVIRONMENT_ACCESS_FINGERPRINT
                        ),
                        staging_live_evidence.RUNTIME_FINGERPRINT_ANNOTATION: (
                            RUNTIME_FINGERPRINT
                        ),
                    }
                },
                "spec": {
                    "serviceAccountName": "gis-agent-app",
                    "automountServiceAccountToken": False,
                    "containers": [{"name": "app", "image": IMAGE}],
                },
            },
        },
        "status": {
            "observedGeneration": 3,
            "replicas": 1,
            "updatedReplicas": 1,
            "readyReplicas": 1,
            "availableReplicas": 1,
            "conditions": [
                {"type": "Available", "status": "True"},
                {"type": "Progressing", "status": "True"},
            ],
        },
    }
    raw_pods = {
        "items": [
            {
                    "metadata": {
                        "name": "gis-agent-app-abc",
                        "uid": POD_UID,
                        "creationTimestamp": (
                            NOW - timedelta(minutes=10)
                        ).isoformat(),
                    },
                "spec": {
                    "serviceAccountName": "gis-agent-app",
                    "containers": [{"name": "app", "image": IMAGE}],
                },
                "status": {
                    "phase": "Running",
                    "containerStatuses": [
                        {
                            "name": "app",
                            "imageID": "docker-pullable://" + IMAGE,
                            "ready": True,
                            "restartCount": 0,
                        }
                    ],
                },
            }
        ]
    }
    raw_endpoints = {
        "items": [
            {
                "endpoints": [
                    {
                        "conditions": {"ready": True},
                        "targetRef": {"kind": "Pod", "uid": POD_UID},
                    }
                ]
            }
        ]
    }
    raw_platform = _platform_snapshot()
    raw_platform["config"]["entries"] = {
        "DATABASE_URL": {"value": "must-never-appear", "secret": True}
    }
    responses = [
        {"metadata": {"uid": CLUSTER_UID}},
        {
            "metadata": {
                "name": "gis-agent-staging",
                "uid": NAMESPACE_UID,
                "resourceVersion": "10",
            }
        },
        raw_deployment,
        raw_pods,
        {
            "metadata": {
                "name": "gis-agent-app",
                "uid": SERVICE_ACCOUNT_UID,
                "resourceVersion": "21",
            },
            "secrets": [{"name": "must-never-appear"}],
        },
        raw_endpoints,
        _schema_report(),
        raw_platform,
        {
            "status": "ok",
            "uptime_seconds": 100,
            "detail": "must-never-appear",
        },
        {
            "status": "ok",
            "checks": {
                "database": {
                    "status": "ok",
                    "latency_ms": 1,
                    "detail": "must-never-appear",
                }
            },
        },
    ]
    commands: list[list[str]] = []

    def run(arguments: list[str]) -> str:
        commands.append(arguments)
        return json.dumps(responses.pop(0))

    report = staging_live_evidence.collect_live_staging(now=NOW, run=run)

    assert report["schema"] == staging_live_evidence.COLLECTION_SCHEMA
    assert report["kubernetes"] == collection["kubernetes"]
    assert report["schema_report"] == collection["schema_report"]
    assert report["platform_snapshot"] == collection["platform_snapshot"]
    assert report["health"] == collection["health"]
    assert responses == []
    assert all("secret" not in command for command in commands)
    assert "must-never-appear" not in json.dumps(report)
    assert any("endpointslices" in command for command in commands)
    assert any("data_agent.migration_runner" in command for command in commands)
    assert any("data_agent.platform_truth" in command for command in commands)


def test_validate_cli_writes_machine_readable_blocked_report_without_golden(
    tmp_path, capsys
):
    candidate = _candidate()
    collection = _collection(candidate)
    candidate_path = tmp_path / "candidate.json"
    release_path = tmp_path / "release.json"
    collection_path = tmp_path / "collection.json"
    output = tmp_path / "live.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    release_path.write_text(json.dumps(_release(candidate)), encoding="utf-8")
    collection_path.write_text(json.dumps(collection), encoding="utf-8")

    assert (
        staging_live_evidence.main(
            [
                "validate",
                "--candidate-evidence",
                str(candidate_path),
                "--release-evidence",
                str(release_path),
                "--live-collection",
                str(collection_path),
                "--expected-cluster-uid",
                CLUSTER_UID,
                "--expected-namespace-uid",
                NAMESPACE_UID,
                "--output",
                str(output),
            ]
        )
        == 1
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "blocked"
    assert report["production_promotion_allowed"] is False
    assert json.loads(capsys.readouterr().out) == report
