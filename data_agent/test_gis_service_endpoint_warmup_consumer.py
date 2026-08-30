import hashlib
import io
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest

from data_agent.gis_provider_runtime import (
    MartinMVTWarmupSample,
    MartinVectorTileProvider,
    MVTProviderReleaseContext,
    martin_mvt_warmup_sample_set_fingerprint,
)
from data_agent.gis_service_control_plane import (
    CacheKeyDimension,
    CachePolicyVersion,
    EndpointProtocol,
    EndpointRevision,
    GISServiceType,
    MVTServingProjectionVersion,
    ServiceDeploymentRevision,
    ServiceDeploymentState,
    ServiceReleaseBinding,
    TileMatrixSetDefinitionVersion,
    cache_policy_version_fingerprint,
    endpoint_revision_fingerprint,
    mvt_serving_projection_fingerprint,
    service_deployment_fingerprint,
    service_release_binding_fingerprint,
    tile_matrix_set_definition_fingerprint,
)
from data_agent.gis_service_endpoint_warmup import (
    GIS_SERVICE_ENDPOINT_WARMUP_COMMAND_SCHEMA,
    GIS_SERVICE_ENDPOINT_WARMUP_PURPOSE,
    GIS_SERVICE_ENDPOINT_WARMUP_WORKLOAD,
    GISServiceEndpointWarmupExecutionPlan,
    GISServiceEndpointWarmupReceipt,
    gis_service_endpoint_warmup_fingerprint,
    gis_service_endpoint_warmup_plan_fingerprint,
)
from data_agent.gis_service_endpoint_warmup_consumer import (
    GISServiceEndpointWarmupConsumer,
    LocalWarmupReceiptStore,
    S3WarmupReceiptStore,
    WarmupReceiptStoreConflict,
    WarmupReceiptStoreUnavailable,
    validate_warmup_s3_location,
)
from data_agent.platform_contracts import (
    OrchestrationClass,
    PlatformCommand,
    PlatformCommandStatus,
    PlatformCommandType,
    PlatformRun,
    ResourceBinding,
    RunStatus,
    SubjectContext,
    SubjectType,
    canonical_json_fingerprint,
)
from data_agent.platform_gateway import PlatformGateway

TENANT = "planning"
NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


class _S3Error(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _MemoryS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str, str], bytes] = {}
        self.current_versions: dict[tuple[str, str], str] = {}
        self.metadata: dict[tuple[str, str, str], dict[str, str]] = {}
        self.content_types: dict[tuple[str, str, str], str] = {}
        self.etags: dict[tuple[str, str, str], str] = {}
        self.put_calls: list[dict] = []
        self.head_calls: list[dict] = []
        self.get_calls: list[dict] = []
        self.versioning_status = "Enabled"
        self.object_lock_enabled = "Enabled"
        self.default_retention: dict = {"Mode": "GOVERNANCE", "Days": 1}
        self.next_put_version_id: str | None = "version-1"
        self.next_put_etag = "etag-1"
        self.head_version_override: str | None = None
        self.get_version_override: str | None = None

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        identity = (kwargs["Bucket"], kwargs["Key"])
        if kwargs.get("IfNoneMatch") == "*" and identity in self.current_versions:
            raise _S3Error("PreconditionFailed")
        version_id = self.next_put_version_id
        if version_id is not None:
            versioned = (*identity, version_id)
            self.objects[versioned] = kwargs["Body"]
            self.current_versions[identity] = version_id
            self.metadata[versioned] = kwargs["Metadata"]
            self.content_types[versioned] = kwargs["ContentType"]
            self.etags[versioned] = self.next_put_etag
        return {
            "VersionId": version_id,
            "ETag": f'"{self.next_put_etag}"',
        }

    def seed_current(
        self,
        bucket: str,
        key: str,
        content: bytes,
        *,
        version_id: str = "existing-version",
        metadata: dict[str, str] | None = None,
        content_type: str = "application/json",
    ) -> None:
        identity = (bucket, key)
        versioned = (*identity, version_id)
        self.objects[versioned] = content
        self.current_versions[identity] = version_id
        self.metadata[versioned] = metadata or {
            "sha256": hashlib.sha256(content).hexdigest()
        }
        self.content_types[versioned] = content_type
        self.etags[versioned] = f"etag-{version_id}"

    def head_object(self, **kwargs):
        self.head_calls.append(kwargs)
        identity = (kwargs["Bucket"], kwargs["Key"])
        version_id = kwargs.get("VersionId") or self.current_versions.get(identity)
        versioned = (*identity, version_id)
        try:
            content = self.objects[versioned]
        except KeyError as exc:
            raise _S3Error("NoSuchVersion") from exc
        return {
            "VersionId": self.head_version_override or version_id,
            "ETag": f'"{self.etags[versioned]}"',
            "ContentLength": len(content),
            "ContentType": self.content_types[versioned],
            "Metadata": self.metadata[versioned],
        }

    def get_object(self, **kwargs):
        self.get_calls.append(kwargs)
        identity = (kwargs["Bucket"], kwargs["Key"], kwargs["VersionId"])
        try:
            content = self.objects[identity]
        except KeyError as exc:
            raise _S3Error("NoSuchVersion") from exc
        return {
            "Body": io.BytesIO(content),
            "VersionId": self.get_version_override or kwargs["VersionId"],
        }

    def get_bucket_versioning(self, *, Bucket):
        del Bucket
        return {"Status": self.versioning_status}

    def get_object_lock_configuration(self, *, Bucket):
        del Bucket
        return {
            "ObjectLockConfiguration": {
                "ObjectLockEnabled": self.object_lock_enabled,
                "Rule": {"DefaultRetention": self.default_retention},
            }
        }


def _mock_receipt(payload: dict | None = None):
    payload = payload or {"schema": "test.warmup.receipt.v1"}
    receipt = MagicMock()
    receipt.model_dump.return_value = payload
    receipt.receipt_sha256 = canonical_json_fingerprint(payload)
    receipt.tenant_id = TENANT
    return receipt


def _bundle():
    service_definition_id = uuid4()
    layer_id = uuid4()
    source_output_id = uuid4()
    tms_values = {
        "tenant_id": TENANT,
        "tile_matrix_set_definition_version_id": uuid4(),
        "service_definition_version_id": service_definition_id,
        "layer_definition_version_id": layer_id,
        "tile_matrix_set_key": "webmercatorquad",
        "version_key": "v1.0.0",
        "crs_uri": "http://www.opengis.net/def/crs/EPSG/0/3857",
        "tile_width": 256,
        "tile_height": 256,
        "min_zoom": 0,
        "max_zoom": 2,
        "scale_denominators": (559082264.029, 279541132.015, 139770566.007),
        "spatial_extent": (-20037508.0, -20037508.0, 20037508.0, 20037508.0),
        "created_by": "workload:service-controller",
        "created_at": NOW,
    }
    tms = TileMatrixSetDefinitionVersion(
        **tms_values,
        definition_sha256=tile_matrix_set_definition_fingerprint(tms_values),
    )
    projection_values = {
        "tenant_id": TENANT,
        "mvt_serving_projection_version_id": uuid4(),
        "service_definition_version_id": service_definition_id,
        "layer_definition_version_id": layer_id,
        "projection_key": "district-features-serving",
        "version_key": "v1.0.0",
        "source_output_resource_version_id": source_output_id,
        "source_schema": "serving",
        "source_table": "district_features_v1",
        "geometry_column": "geom",
        "geometry_srid": 4326,
        "feature_id_column": "district_id",
        "property_allowlist": ("name",),
        "allowed_spatial_extent": (-180.0, -90.0, 180.0, 90.0),
        "max_features_per_tile": 10_000,
        "source_content_sha256": "a" * 64,
        "created_by": "workload:service-controller",
        "created_at": NOW,
    }
    projection = MVTServingProjectionVersion(
        **projection_values,
        projection_sha256=mvt_serving_projection_fingerprint(projection_values),
    )
    cache_values = {
        "tenant_id": TENANT,
        "cache_policy_version_id": uuid4(),
        "service_definition_version_id": service_definition_id,
        "cache_policy_key": "district-features-private",
        "version_key": "v1.0.0",
        "cache_namespace": "district-features-v1",
        "cache_max_age_seconds": 120,
        "cache_key_dimensions": tuple(CacheKeyDimension),
        "created_by": "workload:service-controller",
        "created_at": NOW,
    }
    cache = CachePolicyVersion(
        **cache_values,
        policy_sha256=cache_policy_version_fingerprint(cache_values),
    )
    release_values = {
        "tenant_id": TENANT,
        "service_release_binding_id": uuid4(),
        "service_definition_version_id": service_definition_id,
        "layer_definition_version_id": layer_id,
        "style_definition_version_id": uuid4(),
        "tile_matrix_set_definition_version_id": (
            tms.tile_matrix_set_definition_version_id
        ),
        "cache_policy_version_id": cache.cache_policy_version_id,
        "mvt_serving_projection_version_id": (
            projection.mvt_serving_projection_version_id
        ),
        "release_key": "v1.0.0",
        "created_by": "workload:service-controller",
        "created_at": NOW,
    }
    release = ServiceReleaseBinding(
        **release_values,
        binding_sha256=service_release_binding_fingerprint(release_values),
    )
    context = MVTProviderReleaseContext.from_release(
        release,
        tms,
        projection,
        service_type=GISServiceType.VECTOR_TILE,
        provider_layer_ref="gda_mvt_serving_projection",
        provider_query={
            "serving_projection_version_id": str(
                projection.mvt_serving_projection_version_id
            )
        },
    )
    deployment_values = {
        "tenant_id": TENANT,
        "deployment_revision_id": uuid4(),
        "service_definition_version_id": service_definition_id,
        "service_release_binding_id": release.service_release_binding_id,
        "run_id": uuid4(),
        "revision_key": "r1",
        "provider_system": "martin",
        "provider_namespace": "planning-prod",
        "provider_deployment_id": "district-features-r1",
        "provider_revision_ref": "deployment:17",
        "config_sha256": "b" * 64,
        "created_by": "workload:service-controller",
        "created_at": NOW,
        "updated_at": NOW,
    }
    planned = ServiceDeploymentRevision(
        **deployment_values,
        deployment_sha256=service_deployment_fingerprint(deployment_values),
    )
    deployment = planned.model_copy(
        update={
            "state": ServiceDeploymentState.READY,
            "state_version": 2,
            "terminal_observation_id": uuid4(),
            "terminal_at": NOW,
        }
    )
    endpoint_values = {
        "tenant_id": TENANT,
        "endpoint_revision_id": uuid4(),
        "service_urn": "gda://planning/gis_service/district-features",
        "deployment_revision_id": deployment.deployment_revision_id,
        "endpoint_protocol": EndpointProtocol.MVT,
        "endpoint_uri": "https://tiles.example.test/district-features/v1.0.0",
        "endpoint_contract": {
            "schema": "gda.mvt_endpoint.v1",
            "provider_layer_ref": "gda_mvt_serving_projection",
            "provider_query": dict(context.provider_query),
        },
        "created_by": "workload:service-controller",
        "created_at": NOW,
    }
    endpoint = EndpointRevision(
        **endpoint_values,
        endpoint_sha256=endpoint_revision_fingerprint(endpoint_values),
    )
    return context, release, tms, projection, cache, deployment, endpoint


def _plan_and_command(bundle):
    context, release, tms, projection, cache, deployment, endpoint = bundle
    run_id = uuid4()
    definition_id = uuid4()
    plan_artifact_id = uuid4()
    samples = (
        MartinMVTWarmupSample(z=0, x=0, y=0),
        MartinMVTWarmupSample(z=1, x=1, y=0),
    )
    plan_values = {
        "schema": "gda.gis_service_endpoint_warmup_execution_plan.v1",
        "tenant_id": TENANT,
        "run_id": run_id,
        "definition_version_id": definition_id,
        "definition_sha256": "c" * 64,
        "service_urn": endpoint.service_urn,
        "service_definition_version_id": context.service_definition_version_id,
        "endpoint_revision_id": endpoint.endpoint_revision_id,
        "endpoint_sha256": endpoint.endpoint_sha256,
        "consumer_endpoint_uri": endpoint.endpoint_uri,
        "deployment_revision_id": deployment.deployment_revision_id,
        "deployment_sha256": deployment.deployment_sha256,
        "service_release_binding_id": release.service_release_binding_id,
        "release_binding_sha256": release.binding_sha256,
        "cache_policy_version_id": cache.cache_policy_version_id,
        "cache_policy_sha256": cache.policy_sha256,
        "cache_namespace": cache.cache_namespace,
        "cache_max_age_seconds": cache.cache_max_age_seconds,
        "tile_matrix_set_definition_version_id": (
            tms.tile_matrix_set_definition_version_id
        ),
        "tile_matrix_set_sha256": tms.definition_sha256,
        "mvt_serving_projection_version_id": (
            projection.mvt_serving_projection_version_id
        ),
        "serving_projection_sha256": projection.projection_sha256,
        "source_output_resource_version_id": (
            projection.source_output_resource_version_id
        ),
        "provider_system": "martin",
        "provider_layer_ref": "gda_mvt_serving_projection",
        "samples": samples,
        "sample_set_sha256": martin_mvt_warmup_sample_set_fingerprint(samples),
    }
    plan = GISServiceEndpointWarmupExecutionPlan(
        **plan_values,
        plan_sha256=gis_service_endpoint_warmup_plan_fingerprint(plan_values),
    )
    command = PlatformCommand(
        tenant_id=TENANT,
        command_id=uuid4(),
        run_id=run_id,
        command_type=PlatformCommandType.GIS_SERVICE_ENDPOINT_WARMUP,
        execution_plan_artifact_id=plan_artifact_id,
        dedupe_key=f"gis_service.endpoint_warmup:{run_id}",
        actor_subject=GIS_SERVICE_ENDPOINT_WARMUP_WORKLOAD,
        payload={
            "schema": GIS_SERVICE_ENDPOINT_WARMUP_COMMAND_SCHEMA,
            "run_id": str(run_id),
            "execution_plan_artifact_id": str(plan_artifact_id),
            "execution_plan_sha256": plan.plan_sha256,
            "sample_set_sha256": plan.sample_set_sha256,
            "endpoint_revision_id": str(plan.endpoint_revision_id),
            "service_release_binding_id": str(
                plan.service_release_binding_id
            ),
            "provider_system": "martin",
        },
        status=PlatformCommandStatus.IN_FLIGHT,
        attempt_count=1,
        max_attempts=5,
        available_at=NOW,
        claimed_by="worker:warmup-1",
        claimed_until=datetime.now(UTC) + timedelta(minutes=10),
        created_at=NOW,
    )
    subject = SubjectContext(
        tenant_id=TENANT,
        subject_id="gis-warmup-controller",
        subject_type=SubjectType.WORKLOAD,
        purpose=GIS_SERVICE_ENDPOINT_WARMUP_PURPOSE,
    )
    run = PlatformRun(
        tenant_id=TENANT,
        run_id=run_id,
        definition_version_id=definition_id,
        orchestration_class=OrchestrationClass.DATAOPS,
        subject_context=subject,
        input_bindings=(
            ResourceBinding(
                binding_name="source_product_output",
                resource_version_id=plan.source_output_resource_version_id,
                semantic_type="gda.gis_service.warmup_source",
            ),
        ),
        idempotency_key=f"warmup-{run_id}",
        config_fingerprint=plan.plan_sha256,
        submitted_at=NOW,
    )
    return plan, command, run


def _gateway(bundle, plan, command, run):
    _, release, tms, projection, cache, deployment, endpoint = bundle
    gateway = MagicMock(spec=PlatformGateway)
    gateway.claim_commands.return_value = [command]
    gateway.get_gis_service_endpoint_warmup_execution_plan.return_value = plan
    gateway.get_run.side_effect = [run, run, run]
    gateway.transition_run.side_effect = [
        run.model_copy(update={"status": RunStatus.DISPATCHING, "state_version": 1}),
        run.model_copy(update={"status": RunStatus.RUNNING, "state_version": 2}),
    ]
    gateway.get_gis_service_definition_version.return_value = SimpleNamespace(
        service_type=GISServiceType.VECTOR_TILE
    )
    gateway.get_service_release_binding.return_value = release
    gateway.get_tile_matrix_set_definition_version.return_value = tms
    gateway.get_mvt_serving_projection_version.return_value = projection
    gateway.get_cache_policy_version.return_value = cache
    gateway.get_service_deployment_revision.return_value = deployment
    gateway.get_endpoint_revision.return_value = endpoint
    return gateway


def test_consumer_executes_real_mock_http_and_builds_atomic_settlement(tmp_path):
    bundle = _bundle()
    plan, command, run = _plan_and_command(bundle)
    gateway = _gateway(bundle, plan, command, run)
    requested_paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/health":
            return httpx.Response(200, text="OK")
        if request.url.path == "/catalog":
            return httpx.Response(
                200,
                json={"tiles": {"gda_mvt_serving_projection": {}}},
            )
        return httpx.Response(
            200,
            content=b"non-empty-mvt",
            headers={"content-type": "application/x-protobuf"},
        )

    consumer = GISServiceEndpointWarmupConsumer(
        gateway,
        MartinVectorTileProvider(
            "http://martin:3000", transport=httpx.MockTransport(handler)
        ),
        LocalWarmupReceiptStore(tmp_path / "receipts"),
    )
    result = consumer.run_once(
        TENANT, worker_id="worker:warmup-1", lease_seconds=600
    )

    assert result.claimed == 1
    assert result.completed == 1
    assert result.succeeded == 1
    assert requested_paths == [
        "/health",
        "/catalog",
        "/gda_mvt_serving_projection/0/0/0",
        "/gda_mvt_serving_projection/1/1/0",
    ]
    settlement = (
        gateway.settle_gis_service_endpoint_warmup_success.call_args.args[0]
    )
    assert settlement.execution_plan == plan
    assert settlement.provider_receipt.requested_sample_count == 2
    assert settlement.evidence_artifact.content_sha256 == (
        settlement.provider_receipt.receipt_sha256
    )
    receipt_path = tmp_path / "receipts" / TENANT / str(run.run_id)
    assert (receipt_path / "martin-origin-warmup-receipt.json").is_file()
    gateway.complete_command.assert_called_once_with(
        TENANT, command.command_id, worker_id="worker:warmup-1"
    )


def test_consumer_retries_provider_unavailability(tmp_path):
    bundle = _bundle()
    plan, command, run = _plan_and_command(bundle)
    gateway = _gateway(bundle, plan, command, run)
    gateway.fail_command.return_value = command.model_copy(
        update={
            "status": PlatformCommandStatus.PENDING,
            "claimed_by": None,
            "claimed_until": None,
        }
    )

    def unavailable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unavailable", request=request)

    consumer = GISServiceEndpointWarmupConsumer(
        gateway,
        MartinVectorTileProvider(
            "http://martin:3000", transport=httpx.MockTransport(unavailable)
        ),
        LocalWarmupReceiptStore(tmp_path / "receipts"),
        retry_delay_seconds=17,
    )
    result = consumer.run_once(TENANT, worker_id="worker:warmup-1")

    assert result.retry_pending == 1
    assert result.failed == 0
    gateway.fail_command.assert_called_once()
    assert gateway.fail_command.call_args.kwargs["retry_delay_seconds"] == 17
    gateway.settle_gis_service_endpoint_warmup_success.assert_not_called()


def test_consumer_recovers_lost_ack_from_atomic_receipt(tmp_path):
    bundle = _bundle()
    plan, command, run = _plan_and_command(bundle)
    succeeded = run.model_copy(
        update={"status": RunStatus.SUCCEEDED, "state_version": 3}
    )
    receipt_values = {
        "tenant_id": TENANT,
        "warmup_id": uuid4(),
        "service_urn": plan.service_urn,
        "endpoint_revision_id": plan.endpoint_revision_id,
        "deployment_revision_id": plan.deployment_revision_id,
        "service_definition_version_id": plan.service_definition_version_id,
        "service_release_binding_id": plan.service_release_binding_id,
        "cache_policy_version_id": plan.cache_policy_version_id,
        "cache_namespace": plan.cache_namespace,
        "run_id": command.run_id,
        "evidence_artifact_id": uuid4(),
        "requested_sample_count": 2,
        "successful_sample_count": 2,
        "sample_set_sha256": plan.sample_set_sha256,
        "provider_receipt_sha256": "d" * 64,
        "started_at": NOW,
        "completed_at": NOW,
        "valid_until": NOW + timedelta(seconds=120),
        "recorded_by": GIS_SERVICE_ENDPOINT_WARMUP_WORKLOAD,
        "recorded_at": NOW + timedelta(seconds=1),
    }
    receipt = GISServiceEndpointWarmupReceipt(
        **receipt_values,
        warmup_sha256=gis_service_endpoint_warmup_fingerprint(receipt_values),
    )
    gateway = MagicMock(spec=PlatformGateway)
    gateway.claim_commands.return_value = [command]
    gateway.get_gis_service_endpoint_warmup_execution_plan.return_value = plan
    gateway.get_run.return_value = succeeded
    gateway.list_gis_service_endpoint_warmups.return_value = (receipt,)
    consumer = GISServiceEndpointWarmupConsumer(
        gateway,
        MartinVectorTileProvider("http://martin:3000"),
        LocalWarmupReceiptStore(tmp_path / "receipts"),
    )

    result = consumer.run_once(TENANT, worker_id="worker:warmup-1")

    assert result.completed == 1
    assert result.succeeded == 0
    gateway.complete_command.assert_called_once()
    gateway.settle_gis_service_endpoint_warmup_success.assert_not_called()


def test_consumer_fails_contract_drift_without_retry(tmp_path):
    bundle = _bundle()
    plan, command, _run = _plan_and_command(bundle)
    command = command.model_copy(
        update={
            "payload": {
                **command.payload,
                "endpoint_revision_id": str(uuid4()),
            }
        }
    )
    gateway = MagicMock(spec=PlatformGateway)
    gateway.claim_commands.return_value = [command]
    gateway.get_gis_service_endpoint_warmup_execution_plan.return_value = plan
    gateway.fail_gis_service_endpoint_warmup_command_terminal.return_value = (
        command.model_copy(
            update={
                "status": PlatformCommandStatus.FAILED,
                "claimed_by": None,
                "claimed_until": None,
                "completed_at": NOW,
            }
        )
    )
    consumer = GISServiceEndpointWarmupConsumer(
        gateway,
        MartinVectorTileProvider("http://martin:3000"),
        LocalWarmupReceiptStore(tmp_path / "receipts"),
    )

    result = consumer.run_once(TENANT, worker_id="worker:warmup-1")

    assert result.failed == 1
    gateway.fail_gis_service_endpoint_warmup_command_terminal.assert_called_once()
    gateway.fail_command.assert_not_called()


def test_local_receipt_store_rejects_existing_different_content(tmp_path):
    bundle = _bundle()
    plan, command, _run = _plan_and_command(bundle)
    gateway = _gateway(bundle, plan, command, _run)
    consumer = GISServiceEndpointWarmupConsumer(
        gateway,
        MartinVectorTileProvider("http://martin:3000"),
        LocalWarmupReceiptStore(tmp_path / "receipts"),
    )
    store = consumer.receipt_store
    target = (
        tmp_path
        / "receipts"
        / TENANT
        / str(command.run_id)
        / "martin-origin-warmup-receipt.json"
    )
    target.parent.mkdir(parents=True)
    target.write_bytes(b"different")
    receipt = MagicMock()
    receipt.model_dump.return_value = {"schema": "test"}
    receipt.receipt_sha256 = canonical_json_fingerprint({"schema": "test"})
    receipt.tenant_id = TENANT
    with pytest.raises(WarmupReceiptStoreConflict):
        store.publish(receipt, run_id=command.run_id)


def test_s3_receipt_store_conditionally_creates_and_replays_exact_version():
    client = _MemoryS3()
    store = S3WarmupReceiptStore(
        client,
        bucket="gis-agent-evidence",
        prefix="gis-warmup-receipts/v1",
    )
    run_id = uuid4()
    receipt = _mock_receipt()

    first = store.publish(receipt, run_id=run_id)
    replay = store.publish(receipt, run_id=run_id)

    key = (
        f"gis-warmup-receipts/v1/{TENANT}/{run_id}/"
        "martin-origin-warmup-receipt.json"
    )
    assert first == replay
    assert first.storage_uri == f"s3://gis-agent-evidence/{key}"
    assert first.storage_evidence is not None
    assert first.storage_evidence.version_id == "version-1"
    assert first.storage_evidence.etag == "etag-1"
    assert len(client.put_calls) == 2
    assert client.put_calls[0]["IfNoneMatch"] == "*"
    assert client.head_calls[0]["VersionId"] == "version-1"
    assert client.get_calls[0]["VersionId"] == "version-1"


def test_s3_receipt_store_rejects_different_byte_replay_without_overwrite():
    client = _MemoryS3()
    store = S3WarmupReceiptStore(
        client,
        bucket="gis-agent-evidence",
        prefix="gis-warmup-receipts/v1",
    )
    run_id = uuid4()
    first = _mock_receipt()
    store.publish(first, run_id=run_id)
    key = (
        f"gis-warmup-receipts/v1/{TENANT}/{run_id}/"
        "martin-origin-warmup-receipt.json"
    )
    original = client.objects[("gis-agent-evidence", key, "version-1")]

    with pytest.raises(WarmupReceiptStoreConflict, match="metadata differs"):
        store.publish(
            _mock_receipt({"schema": "test.warmup.receipt.v2"}),
            run_id=run_id,
        )

    assert client.objects[("gis-agent-evidence", key, "version-1")] == original


@pytest.mark.parametrize("version_id", [None, "", "null", "bad version"])
def test_s3_receipt_store_requires_immutable_version_id(version_id):
    client = _MemoryS3()
    client.next_put_version_id = version_id
    store = S3WarmupReceiptStore(
        client,
        bucket="gis-agent-evidence",
        prefix="gis-warmup-receipts/v1",
    )

    with pytest.raises(WarmupReceiptStoreUnavailable, match="VersionId"):
        store.publish(_mock_receipt(), run_id=uuid4())


@pytest.mark.parametrize("drift", ["metadata", "size", "readback", "version"])
def test_s3_receipt_store_rejects_readback_drift(drift: str):
    client = _MemoryS3()
    store = S3WarmupReceiptStore(
        client,
        bucket="gis-agent-evidence",
        prefix="gis-warmup-receipts/v1",
    )
    run_id = uuid4()
    receipt = _mock_receipt()
    key = (
        f"gis-warmup-receipts/v1/{TENANT}/{run_id}/"
        "martin-origin-warmup-receipt.json"
    )
    payload = b'{"schema":"test.warmup.receipt.v1"}'
    if drift in {"metadata", "size", "readback"}:
        seeded = payload if drift != "size" else payload + b"x"
        client.seed_current(
            "gis-agent-evidence",
            key,
            seeded,
            metadata={
                "sha256": "0" * 64
                if drift == "metadata"
                else receipt.receipt_sha256
            },
        )
        if drift == "readback":
            client.objects[("gis-agent-evidence", key, "existing-version")] = (
                b"different-same-size-payload-padding"[: len(payload)]
            )
    else:
        client.head_version_override = "other-version"

    error = (
        WarmupReceiptStoreUnavailable
        if drift == "version"
        else WarmupReceiptStoreConflict
    )
    with pytest.raises(error):
        store.publish(receipt, run_id=run_id)


@pytest.mark.parametrize("missing", ["versioning", "object_lock", "retention"])
def test_s3_receipt_store_probe_requires_versioning_and_retention(missing: str):
    client = _MemoryS3()
    if missing == "versioning":
        client.versioning_status = "Suspended"
    elif missing == "object_lock":
        client.object_lock_enabled = "Disabled"
    else:
        client.default_retention = {}
    store = S3WarmupReceiptStore(
        client,
        bucket="gis-agent-evidence",
        prefix="gis-warmup-receipts/v1",
    )

    with pytest.raises(WarmupReceiptStoreUnavailable, match="object-lock"):
        store.probe()


@pytest.mark.parametrize(
    ("bucket", "prefix"),
    [
        ("UPPERCASE", "gis-warmup-receipts/v1"),
        ("ab", "gis-warmup-receipts/v1"),
        ("gis-agent-evidence", "../escape"),
        ("gis-agent-evidence", "/"),
        ("gis-agent-evidence", "gis warmup receipts"),
    ],
)
def test_s3_receipt_location_rejects_unsafe_values(bucket: str, prefix: str):
    with pytest.raises(ValueError, match="warmup S3"):
        validate_warmup_s3_location(bucket, prefix)


def test_consumer_binds_s3_object_version_to_atomic_settlement():
    bundle = _bundle()
    plan, command, run = _plan_and_command(bundle)
    gateway = _gateway(bundle, plan, command, run)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, text="OK")
        if request.url.path == "/catalog":
            return httpx.Response(
                200,
                json={"tiles": {"gda_mvt_serving_projection": {}}},
            )
        return httpx.Response(
            200,
            content=b"non-empty-mvt",
            headers={"content-type": "application/x-protobuf"},
        )

    client = _MemoryS3()
    consumer = GISServiceEndpointWarmupConsumer(
        gateway,
        MartinVectorTileProvider(
            "http://martin:3000", transport=httpx.MockTransport(handler)
        ),
        S3WarmupReceiptStore(
            client,
            bucket="gis-agent-evidence",
            prefix="gis-warmup-receipts/v1",
        ),
    )

    result = consumer.run_once(
        TENANT, worker_id="worker:warmup-1", lease_seconds=600
    )

    assert result.succeeded == 1
    settlement = (
        gateway.settle_gis_service_endpoint_warmup_success.call_args.args[0]
    )
    assert settlement.storage_evidence is not None
    assert settlement.storage_evidence.version_id == "version-1"
    assert settlement.evidence_artifact.storage_uri.startswith(
        "s3://gis-agent-evidence/gis-warmup-receipts/v1/"
    )
    assert settlement.evidence_artifact.manifest["storage_evidence"] == {
        "schema": "gda.gis_service_endpoint_warmup_storage.v1",
        "backend": "s3",
        "version_id": "version-1",
        "etag": "etag-1",
    }
