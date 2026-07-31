import inspect
import json
from copy import deepcopy
from datetime import UTC, datetime

import geopandas as gpd
import pytest
from pydantic import SecretStr, ValidationError
from shapely.geometry import Polygon

from data_agent import metadata_fabric_object_store_active_metadata_promotion as m321
from data_agent import metadata_fabric_real_feature_ingestion as ingestion
from data_agent import metadata_fabric_spark_object_store_interoperability as m310
from data_agent.platform_contracts import canonical_json_fingerprint

AT = datetime(2026, 7, 31, 10, 0, tzinfo=UTC)
EXPECTED_EVIDENCE_SHA256 = (
    "42abd82613eaf28cb53c64280258bc75dba6cf841f9a513a4c801a9f798b9899"
)


def _profile():
    return ingestion.load_profile()


def _predecessor():
    profile = _profile()
    return ingestion._load_json_object(
        ingestion._resolve_repo_path(profile.dependencies.m321_evidence_path)
    )


def _source():
    dataset = _predecessor()["dataset_bundle"]
    row_hashes = sorted(
        canonical_json_fingerprint({"bounded_test_row": index}) for index in range(20)
    )
    row_set_sha256 = canonical_json_fingerprint(row_hashes)
    output_content_sha256 = ingestion._output_content_sha256(
        source_content_sha256=dataset["content_sha256"],
        row_set_sha256=row_set_sha256,
    )
    return {
        "inventory": dataset,
        "projection": {
            "schema": ingestion.ROW_SET_SCHEMA,
            "feature_count": 20,
            "unique_identifier_count": 20,
            "valid_geometry_count": 20,
            "non_empty_geometry_count": 20,
            "geometry_z_count": 20,
            "geometry_types": ["Polygon"],
            "srid": 4490,
            "bounds": [106.0, 29.0, 107.0, 30.0],
            "row_set_sha256": row_set_sha256,
            "row_sha256": row_hashes,
            "payload_sha256": "1" * 64,
            "payload_size_bytes": 100,
            "source_payload_recorded": False,
        },
        "payload": {
            "source_content_sha256": dataset["content_sha256"],
            "output_content_sha256": output_content_sha256,
            "row_set_sha256": row_set_sha256,
        },
    }


def _plan():
    return ingestion.build_ingestion_plan(
        _profile(),
        _predecessor(),
        _source(),
        {
            "cluster_uid": "99999999-9999-4999-8999-999999999999",
            "provider_runtime": "bounded-test-runtime",
        },
    )


def _spark(plan, authorization_sha256):
    row_hashes = _source()["projection"]["row_sha256"]
    snapshots = [{"snapshot_id": 71, "parent_id": None, "operation": "append"}]
    data_files = [
        {
            "file_path": (
                "s3://gda-metadata-warehouse/warehouse/cultural_heritage/"
                "cultural_districts/data/00000-test.parquet"
            ),
            "record_count": 20,
        }
    ]
    quality = {
        "feature_count": 20,
        "unique_bsm_count": 20,
        "valid_geometry_count": 20,
        "srid_match_count": 20,
        "positive_area_count": 20,
        "bbox_match_count": 20,
    }
    return {
        "wait_completed": True,
        "terminal_condition": "Complete",
        "job": {"succeeded": 1, "failed": 0},
        "pod": {
            "node_name": "desktop-worker",
            "service_account": "spark-object-store-probe",
            "service_account_automount_disabled": True,
            "persistent_volume_claims": [],
        },
        "result_line_count": 1,
        "failure_diagnostic": [],
        "result": {
            "schema": ingestion.PROBE_RESULT_SCHEMA,
            "plan_sha256": plan.ingestion_plan_sha256,
            "authorization_sha256": authorization_sha256,
            "source_resource_version_id": str(ingestion.SOURCE_RESOURCE_VERSION_ID),
            "source_content_sha256": plan.source_content_sha256,
            "output_resource_version_id": str(ingestion.OUTPUT_RESOURCE_VERSION_ID),
            "output_content_sha256": plan.output_content_sha256,
            "row_set_sha256": plan.row_set_sha256,
            "spark_version": "3.5.0",
            "sedona_version": "1.9.0",
            "iceberg_runtime": "1.6.1",
            "table_columns": list(ingestion.SPARK_COLUMNS),
            "quality": quality,
            "first_execution": {
                "status": "appended",
                "mutation_count": 1,
                "row_sha256": row_hashes,
                "snapshots": snapshots,
                "data_files": data_files,
            },
            "immediate_replay": {
                "status": "no_op",
                "mutation_count": 0,
                "row_sha256": row_hashes,
                "snapshots": snapshots,
                "data_files": data_files,
            },
            "source_payload_recorded": False,
            "material_recorded": False,
        },
    }


def _store():
    prefix = "warehouse/cultural_heritage/cultural_districts/"
    data_key = f"{prefix}data/00000-test.parquet"
    metadata_key = f"{prefix}metadata/00001-test.metadata.json"
    manifest_key = f"{prefix}metadata/test-m0.avro"
    return {
        "bucket": "gda-metadata-warehouse",
        "prefix": prefix,
        "object_count": 3,
        "objects": [
            {"key": data_key, "size": 2048, "etag": "data-etag"},
            {"key": metadata_key, "size": 1024, "etag": "metadata-etag"},
            {"key": manifest_key, "size": 512, "etag": "manifest-etag"},
        ],
        "data_keys": [data_key],
        "metadata_keys": [metadata_key],
        "manifest_keys": [manifest_key],
        "latest_metadata": {
            "key": metadata_key,
            "body_sha256": "2" * 64,
            "size_bytes": 1024,
            "location": _profile().target.table_location,
            "current_snapshot_id": 71,
            "current_schema_id": 0,
            "fields": list(ingestion.ICEBERG_FIELDS),
        },
        "source_feature_payload_recorded": False,
        "material_recorded": False,
    }


def test_profile_binds_checked_real_data_and_runtime_dependencies():
    profile = _profile()
    predecessor, runtime_profile = ingestion._load_dependencies(profile)

    assert predecessor["evidence_sha256"] == ingestion.M321_EVIDENCE_SHA256
    assert predecessor["dataset_bundle"]["content_sha256"] == (
        "fd474fd65c8e4a71da241eb3fd07748ca3b972fbd2d3c32833376dbe71104007"
    )
    assert runtime_profile.catalog.backend == "jdbc"
    assert profile.source.expected_feature_count == 20
    assert profile.source.expected_srid == 4490
    assert profile.target.identity == (
        "gda_chongqing_m3_22/lakehouse/cultural_heritage/cultural_districts"
    )
    assert profile.claims.production_ingestion_verified is False


def test_dependencies_use_full_predecessor_validators(monkeypatch):
    m321_called = False
    m310_called = False
    m321_validator = m321.build_validation_report
    m310_validator = m310.build_validation_report

    def checked_m321(**kwargs):
        nonlocal m321_called
        m321_called = True
        return m321_validator(**kwargs)

    def checked_m310(**kwargs):
        nonlocal m310_called
        m310_called = True
        return m310_validator(**kwargs)

    monkeypatch.setattr(m321, "build_validation_report", checked_m321)
    monkeypatch.setattr(m310, "build_validation_report", checked_m310)

    ingestion._load_dependencies(_profile())

    assert m321_called is True
    assert m310_called is True


def test_source_input_is_deterministic_and_path_free(monkeypatch):
    predecessor = _predecessor()
    inventory = predecessor["dataset_bundle"]
    geometries = [
        Polygon(
            [
                (106 + index / 100, 29, 10),
                (106.005 + index / 100, 29, 10),
                (106.005 + index / 100, 29.005, 10),
                (106 + index / 100, 29, 10),
            ]
        )
        for index in range(20)
    ]
    frame = gpd.GeoDataFrame(
        {"Bsm": [f"bounded-{index:02d}" for index in range(20)]},
        geometry=geometries,
        crs="EPSG:4490",
    )
    monkeypatch.setattr(
        ingestion,
        "build_shapefile_bundle_inventory",
        lambda *args, **kwargs: inventory,
    )
    monkeypatch.setattr(ingestion.gpd, "read_file", lambda path: frame)

    source = ingestion.build_source_input(
        _profile(),
        predecessor,
        shapefile_path=ingestion.Path("/private/source/real.shp"),
        ogrinfo_path=ingestion.Path("/private/tool/ogrinfo"),
        proj_data_path=None,
    )

    assert source["inventory"] == inventory
    assert source["projection"]["feature_count"] == 20
    assert source["projection"]["geometry_z_count"] == 20
    assert len(set(source["projection"]["row_sha256"])) == 20
    assert source["payload"]["output_content_sha256"] == (
        ingestion._output_content_sha256(
            source_content_sha256=inventory["content_sha256"],
            row_set_sha256=source["projection"]["row_set_sha256"],
        )
    )
    assert "/private/" not in json.dumps(source, sort_keys=True)
    assert "geometry_wkb_hex" not in json.dumps(source["projection"], sort_keys=True)


def test_source_input_rejects_duplicate_identifiers(monkeypatch):
    predecessor = _predecessor()
    polygon = Polygon([(106, 29, 10), (107, 29, 10), (107, 30, 10), (106, 29, 10)])
    frame = gpd.GeoDataFrame(
        {"Bsm": ["duplicate"] * 20}, geometry=[polygon] * 20, crs="EPSG:4490"
    )
    monkeypatch.setattr(
        ingestion,
        "build_shapefile_bundle_inventory",
        lambda *args, **kwargs: predecessor["dataset_bundle"],
    )
    monkeypatch.setattr(ingestion.gpd, "read_file", lambda path: frame)

    with pytest.raises(ingestion.RealFeatureIngestionError):
        ingestion.build_source_input(
            _profile(),
            predecessor,
            shapefile_path=ingestion.Path("source.shp"),
            ogrinfo_path=ingestion.Path("ogrinfo"),
            proj_data_path=None,
        )


def test_plan_binds_source_rows_target_and_runtime():
    plan = _plan()

    assert plan.source_resource_version_id == ingestion.SOURCE_RESOURCE_VERSION_ID
    assert plan.output_resource_version_id == ingestion.OUTPUT_RESOURCE_VERSION_ID
    assert plan.predecessor_promotion_candidate_sha256 == (
        _predecessor()["promotion_candidate_sha256"]
    )
    assert plan.runtime_binding_sha256 == canonical_json_fingerprint(plan.runtime_binding)
    assert plan.table_columns == ingestion.GRAVITINO_COLUMNS
    assert plan.writes_to_gda_control is False

    tampered = plan.model_dump(mode="json", by_alias=True)
    tampered["row_set_sha256"] = "0" * 64
    with pytest.raises(ValidationError):
        ingestion.RealFeatureIngestionPlan.model_validate(tampered)


def test_authorization_binds_the_exact_ingestion_plan():
    plan = _plan()
    authorization = ingestion.build_ingestion_authorization(
        plan, _profile(), authorized_at=AT
    )

    ingestion.validate_ingestion_authorization(plan, authorization, at=AT)
    changed = list(authorization)
    changed[-1] = "0" * 64
    with pytest.raises(ingestion.RealFeatureIngestionError):
        ingestion.validate_ingestion_authorization(plan, tuple(changed), at=AT)


class _BoundedTableClient:
    def __init__(self):
        self.table = None

    def request(self, method, path, *, json_body=None, label):
        if method == "POST":
            self.table = deepcopy(json_body)
            return 200, {"table": self.table}
        assert method == "GET"
        return 200, {"table": self.table}


class _TableRehearsal:
    def __init__(self):
        self.bounded = _BoundedTableClient()

    def _schema_path(self, target):
        return "metalakes/test/catalogs/test/schemas/test"

    def _table_path(self, target):
        return "metalakes/test/catalogs/test/schemas/test/tables/test"


def test_table_create_reads_source_binding_from_table_properties():
    rehearsal = _TableRehearsal()

    result = ingestion.create_target_table(rehearsal, _profile(), _plan())

    assert result["source_binding_verified"] is True
    assert result["mutation_count"] == 1
    properties = rehearsal.bounded.table["properties"]
    assert properties["gda.source_resource_urn"] == _plan().source_resource_urn
    assert properties["gda.row_set_sha256"] == _plan().row_set_sha256


def test_ephemeral_large_input_uses_create_without_apply_annotation():
    source = inspect.getsource(ingestion._run_spark_ingestion)

    assert '["create", "-f", "-"]' in source
    assert 'input_resource, ensure_ascii=True' in source


def test_spark_validation_requires_exact_authorization_and_no_op_replay():
    plan = _plan()
    authorization_sha256 = "3" * 64
    spark = _spark(plan, authorization_sha256)

    assert ingestion._spark_errors(
        spark,
        plan,
        _source(),
        expected_authorization_sha256=authorization_sha256,
    ) == []

    tampered = deepcopy(spark)
    tampered["result"]["authorization_sha256"] = "4" * 64
    errors = ingestion._spark_errors(
        tampered,
        plan,
        _source(),
        expected_authorization_sha256=authorization_sha256,
    )
    assert "real feature Spark result is not authorization-bound" in errors


class _Body:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return self.payload


class _S3Client:
    def __init__(self, metadata):
        self.metadata = json.dumps(metadata).encode()
        self.closed = False

    def list_objects_v2(self, **request):
        assert request == {
            "Bucket": "gda-metadata-warehouse",
            "Prefix": "warehouse/cultural_heritage/cultural_districts/",
        }
        prefix = request["Prefix"]
        return {
            "IsTruncated": False,
            "Contents": [
                {"Key": f"{prefix}data/00000-test.parquet", "Size": 2048},
                {
                    "Key": f"{prefix}metadata/00001-test.metadata.json",
                    "Size": len(self.metadata),
                },
                {"Key": f"{prefix}metadata/test-m0.avro", "Size": 512},
            ],
        }

    def get_object(self, **request):
        assert request["Bucket"] == "gda-metadata-warehouse"
        return {"Body": _Body(self.metadata)}

    def close(self):
        self.closed = True


class _Runtime:
    def __init__(self, client):
        self.client = client

    def _s3_client(self, **kwargs):
        assert kwargs["endpoint_url"] == "http://127.0.0.1:9000"
        return self.client


def test_direct_s3_observation_requires_exact_ingested_table_metadata():
    metadata = {
        "location": _profile().target.table_location,
        "current-schema-id": 0,
        "current-snapshot-id": 71,
        "schemas": [
            {
                "schema-id": 0,
                "fields": [
                    {"name": field["name"], "required": True, "type": field["type"]}
                    for field in ingestion.ICEBERG_FIELDS
                ],
            }
        ],
    }
    client = _S3Client(metadata)

    observed = ingestion.observe_ingested_table(
        _Runtime(client),
        _profile(),
        endpoint_url="http://127.0.0.1:9000",
        object_store_user=SecretStr("user"),
        object_store_material=SecretStr("material"),
    )

    assert len(observed["data_keys"]) == 1
    assert observed["latest_metadata"]["current_snapshot_id"] == 71
    assert observed["latest_metadata"]["fields"] == list(ingestion.ICEBERG_FIELDS)
    assert client.closed is True


def test_object_store_validation_handles_missing_snapshot_without_crashing():
    spark = _spark(_plan(), "3" * 64)
    spark["result"]["first_execution"]["snapshots"] = []

    assert ingestion._object_store_errors(_store(), spark, _profile()) == [
        "direct S3 Iceberg data projection does not match Spark readback"
    ]


def test_output_contracts_separate_quality_evaluator_and_lineage():
    plan = _plan()
    contracts = ingestion.build_output_contracts(
        plan, _spark(plan, "3" * 64), _store(), created_at=AT
    )

    assert contracts["output_resource_version"]["resource_version_id"] == str(
        ingestion.OUTPUT_RESOURCE_VERSION_ID
    )
    assert contracts["quality_result"]["evaluated_by"] == ingestion.QUALITY_EVALUATOR
    assert contracts["quality_result"]["evaluated_by"] != ingestion.WORKLOAD
    assert contracts["lineage_event"]["source_resource_version_id"] == str(
        ingestion.SOURCE_RESOURCE_VERSION_ID
    )
    assert contracts["lineage_event"]["target_resource_version_id"] == str(
        ingestion.OUTPUT_RESOURCE_VERSION_ID
    )
    assert contracts["persisted_to_gda_control"] is False


def _observation():
    plan = _plan()
    authorization = ingestion.build_ingestion_authorization(
        plan, _profile(), authorized_at=AT
    )
    authorization_sha256 = authorization[-1]
    spark = _spark(plan, authorization_sha256)
    return {
        "schema": ingestion.OBSERVATION_SCHEMA,
        "observed_at": AT.isoformat(),
        "contract": {
            "contract_sha256": ingestion.build_contract_report()["contract_sha256"]
        },
        "dataset_bundle": _source()["inventory"],
        "source_projection": _source()["projection"],
        "plan": plan.model_dump(mode="json", by_alias=True),
        "authorization": {
            "action": ingestion.ACTION,
            "provider_apply_authorized": True,
            "authorization_sha256": authorization_sha256,
        },
        "table_create": {
            "status": "created",
            "mutation_count": 1,
            "mutations": ["gravitino.table.create"],
            "source_binding_verified": True,
        },
        "spark": spark,
        "object_store": _store(),
        "output_contracts": ingestion.build_output_contracts(
            plan, spark, _store(), created_at=AT
        ),
        "runtime_checks": {
            "all_runtime_port_forwards_stopped": True,
            "namespace_delete_completed": True,
            "namespace_absent": True,
            "persistent_volumes_absent": True,
            "provider_objects_retained": False,
            "object_store_objects_retained": False,
            "material_recorded": False,
        },
    }


def test_evidence_is_path_free_content_bound_and_fail_closed_for_production():
    evidence = ingestion.build_evidence(_observation(), profile=_profile())

    assert evidence["errors"] == []
    assert ingestion.verify_evidence_integrity(evidence) == []
    assert evidence["local_real_feature_ingestion_verified"] is True
    assert evidence["production_ingestion_verified"] is False
    assert evidence["production_ready"] is False
    serialized = json.dumps(evidence, sort_keys=True)
    assert "/Users/" not in serialized
    assert "geometry_wkb_hex" not in serialized

    tampered = _observation()
    tampered["spark"]["result"]["authorization_sha256"] = "0" * 64
    rebuilt = ingestion.build_evidence(tampered, profile=_profile())
    assert "real feature Spark result is not authorization-bound" in rebuilt["errors"]
    assert rebuilt["local_real_feature_ingestion_verified"] is False


def test_contract_is_valid_and_manifest_is_secret_free():
    report = ingestion.build_contract_report()

    assert report["status"] == "valid"
    assert report["expected_feature_count"] == 20
    assert report["production_ingestion_verified"] is False
    assert report["production_ready"] is False
    assert ingestion._manifest_errors() == []


def test_checked_evidence_is_valid_and_content_bound():
    evidence = ingestion._load_json_object(ingestion.DEFAULT_EVIDENCE_PATH)
    report = ingestion.build_validation_report()

    assert evidence["evidence_sha256"] == EXPECTED_EVIDENCE_SHA256
    assert report["status"] == "valid"
    assert report["errors"] == []
    assert report["local_real_feature_ingestion_verified"] is True

    tampered = deepcopy(evidence["observation"])
    tampered["object_store"]["latest_metadata"]["current_snapshot_id"] = -1
    rebuilt = ingestion.build_evidence(tampered, profile=_profile())
    assert "direct S3 Iceberg data projection does not match Spark readback" in rebuilt[
        "errors"
    ]


def test_evidence_integrity_rejects_sensitive_material_and_overclaim():
    evidence = {
        "schema": ingestion.EVIDENCE_SCHEMA,
        "errors": [],
        "local_real_feature_ingestion_verified": True,
        "production_ingestion_verified": True,
        "credential": "must-not-appear",
    }
    evidence["evidence_sha256"] = canonical_json_fingerprint(evidence)

    errors = ingestion.verify_evidence_integrity(evidence)

    assert "real feature evidence contains sensitive material" in errors
    assert any("production_ingestion_verified" in error for error in errors)
