"""Bounded DuckDB provider for admitted DataProductBlueprint test runs."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlsplit
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from .duckdb_blueprint_object_store import (
    DuckDBBlueprintObjectStore,
    DuckDBBlueprintObjectStoreConflict,
    DuckDBBlueprintObjectStoreError,
    DuckDBBlueprintObjectStoreUnavailable,
    S3ObjectVersionEvidence,
    parse_blueprint_s3_uri,
)
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
)

DUCKDB_BLUEPRINT_WORKLOAD = "workload:blueprint-duckdb-executor"
DUCKDB_BLUEPRINT_PIPELINE_SCHEMA = "gda.data_product_blueprint.duckdb_pipeline.v1"
DUCKDB_BLUEPRINT_EXECUTION_SPEC_SCHEMA = (
    "gda.data_product_blueprint_duckdb_execution_spec.v1"
)
DUCKDB_BLUEPRINT_PROVIDER_RECEIPT_SCHEMA = (
    "gda.data_product_blueprint_duckdb_provider_receipt.v1"
)
DUCKDB_BLUEPRINT_CONFORMANCE_SCHEMA = (
    "gda.data_product_blueprint_duckdb_conformance.v1"
)
DUCKDB_SPATIAL_EXTENSION_EVIDENCE_SCHEMA = "gda.duckdb_spatial_extension.v1"
DUCKDB_SPATIAL_OUTPUT_EVIDENCE_SCHEMA = "gda.geoparquet_spatial_output.v1"
DUCKDB_SPATIAL_GEOPARQUET_VERSION = "1.1.0"

_SAFE_RELATION = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_FORBIDDEN_SQL = re.compile(
    r"\b(?:ATTACH|CALL|COPY|CREATE|DELETE|DETACH|DROP|EXPORT|IMPORT|INSERT|"
    r"INSTALL|LOAD|MERGE|PRAGMA|REPLACE|TRUNCATE|UPDATE|VACUUM)\b",
    flags=re.IGNORECASE,
)
_FORBIDDEN_FILE_FUNCTION = re.compile(
    r"\b(?:delta_scan|glob|http_get|http_post|iceberg_scan|mysql_scan|"
    r"parquet_scan|postgres_scan|read_blob|read_csv|read_csv_auto|read_json|"
    r"read_json_auto|read_ndjson|read_parquet|read_text|sqlite_scan)\s*\(",
    flags=re.IGNORECASE,
)
_SPATIAL_SQL_FUNCTION = re.compile(r"\bST_[A-Za-z0-9_]+\s*\(", flags=re.IGNORECASE)
_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, Any])


class DuckDBBlueprintProviderError(RuntimeError):
    """Base failure raised by the bounded Blueprint provider."""

    code = "duckdb_blueprint_provider_error"


class DuckDBBlueprintProviderContractError(DuckDBBlueprintProviderError):
    """The admitted plan cannot be executed without violating the contract."""

    code = "duckdb_blueprint_provider_contract"


class DuckDBBlueprintProviderExecutionError(DuckDBBlueprintProviderError):
    """DuckDB failed after the admitted provider contract was validated."""

    code = "duckdb_blueprint_provider_execution"


class DuckDBBlueprintProviderUnavailableError(DuckDBBlueprintProviderError):
    """A remote provider dependency failed without disproving the contract."""

    code = "duckdb_blueprint_provider_unavailable"


class DuckDBBlueprintPipeline(BaseModel):
    """Portable, bounded SQL subset accepted by the lightweight provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_name: Literal[
        "gda.data_product_blueprint.duckdb_pipeline.v1"
    ] = Field(default=DUCKDB_BLUEPRINT_PIPELINE_SCHEMA, alias="schema")
    engine: Literal["duckdb"]
    mode: Literal["batch"] = "batch"
    sql: NonEmptyText
    output_format: Literal["parquet"] = "parquet"
    max_input_bytes: int = Field(default=2_147_483_648, ge=1, le=1_099_511_627_776)
    max_input_rows: int = Field(default=10_000_000, ge=1, le=1_000_000_000)
    max_output_rows: int = Field(default=100_000, ge=1, le=1_000_000)
    max_output_bytes: int = Field(default=536_870_912, ge=1, le=10_737_418_240)
    timeout_seconds: float = Field(default=60.0, ge=0.1, le=600.0)
    require_ordered_output: bool = True
    require_spatial: bool = False
    spatial_output_srid: int | None = Field(default=None, ge=1, le=999_999)

    @model_validator(mode="after")
    def _consistent_spatial_contract(self) -> DuckDBBlueprintPipeline:
        if self.require_spatial != (self.spatial_output_srid is not None):
            raise ValueError(
                "DuckDB spatial pipelines must declare require_spatial and "
                "spatial_output_srid together"
            )
        return self


class DuckDBSpatialExtensionEvidence(BaseModel):
    """Identity of the preinstalled extension used by one provider attempt."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    schema_name: Literal["gda.duckdb_spatial_extension.v1"] = Field(
        default=DUCKDB_SPATIAL_EXTENSION_EVIDENCE_SCHEMA,
        alias="schema",
    )
    extension_name: Literal["spatial"] = "spatial"
    extension_version: NonEmptyText
    binary_sha256: Sha256
    install_mode: NonEmptyText
    installed_from: str
    autoinstall_enabled: Literal[False] = False
    autoload_enabled: Literal[False] = False


class DuckDBSpatialOutputEvidence(BaseModel):
    """Portable WKB/SRID/bbox and GeoParquet evidence for a spatial output."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    schema_name: Literal["gda.geoparquet_spatial_output.v1"] = Field(
        default=DUCKDB_SPATIAL_OUTPUT_EVIDENCE_SCHEMA,
        alias="schema",
    )
    geometry_column: Literal["geometry_wkb"] = "geometry_wkb"
    srid_column: Literal["srid"] = "srid"
    bbox_column: Literal["bbox"] = "bbox"
    srid: int = Field(ge=1, le=999_999)
    geometry_rows: int = Field(ge=0)
    invalid_geometry_rows: Literal[0] = 0
    geometry_types: tuple[str, ...]
    bbox: tuple[float, float, float, float] | None = None
    geoparquet_version: Literal["1.1.0"] = DUCKDB_SPATIAL_GEOPARQUET_VERSION
    crs_sha256: Sha256
    geo_metadata_sha256: Sha256

    @field_validator("bbox")
    @classmethod
    def _valid_bbox(
        cls,
        value: tuple[float, float, float, float] | None,
    ) -> tuple[float, float, float, float] | None:
        if value is None:
            return None
        if not all(math.isfinite(item) for item in value):
            raise ValueError("DuckDB spatial output bbox must be finite")
        if value[0] > value[2] or value[1] > value[3]:
            raise ValueError("DuckDB spatial output bbox bounds are inverted")
        return value


class DuckDBBlueprintExecutionRequest(BaseModel):
    """Request to execute an admitted Run with the DuckDB provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    reason: NonEmptyText = "execute admitted Blueprint with DuckDB provider"


class DuckDBBlueprintInput(BaseModel):
    """One content- and location-bound Parquet input exposed as a relation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    binding_name: NonEmptyText
    resource_version_id: UUID
    resource_urn: NonEmptyText
    content_sha256: Sha256
    physical_location_id: UUID
    location_sha256: Sha256
    provider_system: Literal["duckdb", "s3"]
    provider_locator: NonEmptyText
    content_checksum: Sha256
    checksum_algorithm: Literal["sha256"] = "sha256"
    object_version_id: NonEmptyText | None = None

    @field_validator("binding_name")
    @classmethod
    def _safe_binding_name(cls, value: str) -> str:
        if _SAFE_RELATION.fullmatch(value) is None:
            raise ValueError("DuckDB input binding_name must be a safe SQL relation")
        return value

    @model_validator(mode="after")
    def _consistent_checksum(self) -> DuckDBBlueprintInput:
        if self.content_checksum != self.content_sha256:
            raise ValueError(
                "DuckDB physical input checksum must match the ResourceVersion content"
            )
        if self.provider_system == "duckdb":
            _local_file(self.provider_locator)
            if self.object_version_id is not None:
                raise ValueError("local DuckDB input cannot carry an S3 object version")
        else:
            parse_blueprint_s3_uri(self.provider_locator)
            if self.object_version_id is None:
                raise ValueError("S3 DuckDB input requires an immutable object version")
            S3ObjectVersionEvidence(
                version_id=self.object_version_id,
                etag="admitted",
            )
        return self


class DuckDBBlueprintExecutionSpec(BaseModel):
    """Immutable package handed from the control gateway to the provider."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    contract_schema: Literal[
        "gda.data_product_blueprint_duckdb_execution_spec.v1"
    ] = Field(default=DUCKDB_BLUEPRINT_EXECUTION_SPEC_SCHEMA, alias="schema")
    tenant_id: TenantId
    run_id: UUID
    execution_plan_artifact_id: UUID
    execution_plan_sha256: Sha256
    definition_version_id: UUID
    definition_sha256: Sha256
    attempt_no: int = Field(default=1, ge=1, le=100)
    pipeline: DuckDBBlueprintPipeline
    inputs: tuple[DuckDBBlueprintInput, ...] = Field(min_length=1)
    output_uri: NonEmptyText
    admitted_at: datetime

    @field_validator("admitted_at")
    @classmethod
    def _utc_admitted_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("admitted_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _consistent_spec(self) -> DuckDBBlueprintExecutionSpec:
        names = [item.binding_name for item in self.inputs]
        if len(names) != len(set(names)):
            raise ValueError("DuckDB execution inputs must have unique binding names")
        if urlsplit(self.output_uri).scheme == "file":
            _local_file(self.output_uri)
        else:
            parse_blueprint_s3_uri(self.output_uri)
        return self


class DuckDBBlueprintProviderReceipt(BaseModel):
    """Content-bound result produced by one real DuckDB execution attempt."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    contract_schema: Literal[
        "gda.data_product_blueprint_duckdb_provider_receipt.v1"
    ] = Field(default=DUCKDB_BLUEPRINT_PROVIDER_RECEIPT_SCHEMA, alias="schema")
    tenant_id: TenantId
    run_id: UUID
    execution_plan_artifact_id: UUID
    execution_plan_sha256: Sha256
    definition_version_id: UUID
    definition_sha256: Sha256
    attempt_no: int = Field(ge=1, le=100)
    provider_version: NonEmptyText
    output_uri: NonEmptyText
    output_content_sha256: Sha256
    output_size_bytes: int = Field(ge=0)
    output_rows: int = Field(ge=0)
    output_columns: tuple[dict[str, str], ...]
    input_rows: int = Field(ge=0)
    input_bytes: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    spatial_extension_loaded: bool
    spatial_extension_evidence: DuckDBSpatialExtensionEvidence | None = None
    spatial_output_evidence: DuckDBSpatialOutputEvidence | None = None
    checkpoint_mode: Literal["atomic_output"] = "atomic_output"
    external_access: Literal["disabled"] = "disabled"
    output_storage_evidence: S3ObjectVersionEvidence | None = None
    observed_at: datetime
    receipt_sha256: Sha256

    @field_validator("observed_at")
    @classmethod
    def _utc_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _consistent_receipt(self) -> DuckDBBlueprintProviderReceipt:
        if urlsplit(self.output_uri).scheme == "file":
            _local_file(self.output_uri)
            if self.output_storage_evidence is not None:
                raise ValueError("local DuckDB output cannot carry S3 storage evidence")
        else:
            parse_blueprint_s3_uri(self.output_uri)
            if self.output_storage_evidence is None:
                raise ValueError("S3 DuckDB output requires immutable storage evidence")
        if self.spatial_extension_loaded != (
            self.spatial_extension_evidence is not None
        ):
            raise ValueError(
                "DuckDB spatial receipt extension evidence must match loaded state"
            )
        if self.spatial_output_evidence is not None and not self.spatial_extension_loaded:
            raise ValueError("DuckDB spatial output evidence requires the Spatial extension")
        if self.receipt_sha256 != duckdb_blueprint_receipt_fingerprint(self):
            raise ValueError("DuckDB provider receipt fingerprint does not match")
        return self


class DuckDBBlueprintConformanceReport(BaseModel):
    """Provider-local conformance result; control-plane evidence is separate."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    contract_schema: Literal[
        "gda.data_product_blueprint_duckdb_conformance.v1"
    ] = Field(default=DUCKDB_BLUEPRINT_CONFORMANCE_SCHEMA, alias="schema")
    tenant_id: TenantId
    run_id: UUID
    execution_plan_sha256: Sha256
    provider_version: NonEmptyText
    output_content_sha256: Sha256
    checks: dict[str, Literal["passed", "not_applicable"]]
    verdict: Literal["passed"] = "passed"
    report_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_report(self) -> DuckDBBlueprintConformanceReport:
        if self.report_sha256 != duckdb_blueprint_conformance_fingerprint(self):
            raise ValueError("DuckDB conformance report fingerprint does not match")
        return self


def duckdb_blueprint_receipt_fingerprint(value: Any) -> str:
    """Fingerprint a provider receipt while excluding its self-hash."""

    if isinstance(value, BaseModel):
        payload = value.model_dump(
            mode="json",
            by_alias=True,
            exclude={"receipt_sha256"},
            exclude_none=True,
        )
    else:
        payload = {key: item for key, item in dict(value).items() if item is not None}
        payload.pop("receipt_sha256", None)
        if "contract_schema" in payload and "schema" not in payload:
            payload["schema"] = payload.pop("contract_schema")
        payload.setdefault("schema", DUCKDB_BLUEPRINT_PROVIDER_RECEIPT_SCHEMA)
        payload = _JSON_OBJECT_ADAPTER.dump_python(payload, mode="json")
    return canonical_json_fingerprint(payload)


def duckdb_blueprint_conformance_fingerprint(value: Any) -> str:
    """Fingerprint a conformance report while excluding its self-hash."""

    if isinstance(value, BaseModel):
        payload = value.model_dump(
            mode="json",
            by_alias=True,
            exclude={"report_sha256"},
        )
    else:
        payload = dict(value)
        payload.pop("report_sha256", None)
        if "contract_schema" in payload and "schema" not in payload:
            payload["schema"] = payload.pop("contract_schema")
        payload.setdefault("schema", DUCKDB_BLUEPRINT_CONFORMANCE_SCHEMA)
        payload = _JSON_OBJECT_ADAPTER.dump_python(payload, mode="json")
    return canonical_json_fingerprint(payload)


def verify_duckdb_blueprint_output(
    receipt: DuckDBBlueprintProviderReceipt,
    *,
    object_store: DuckDBBlueprintObjectStore | None = None,
) -> Path | None:
    """Re-read provider output before the control plane accepts its receipt."""

    if urlsplit(receipt.output_uri).scheme == "s3":
        if object_store is None or receipt.output_storage_evidence is None:
            raise DuckDBBlueprintProviderContractError(
                "DuckDB Blueprint output verifier is unavailable"
            )
        try:
            object_store.verify_output(
                receipt.tenant_id,
                receipt.run_id,
                receipt.output_uri,
                evidence=receipt.output_storage_evidence,
                expected_sha256=receipt.output_content_sha256,
                expected_size_bytes=receipt.output_size_bytes,
            )
        except DuckDBBlueprintObjectStoreError as exc:
            raise DuckDBBlueprintProviderContractError(
                "DuckDB Blueprint object output verification failed"
            ) from exc
        return None

    path = _local_file(receipt.output_uri)
    if not path.is_file():
        raise DuckDBBlueprintProviderContractError(
            "DuckDB Blueprint provider output was not found"
        )
    if path.stat().st_size != receipt.output_size_bytes:
        raise DuckDBBlueprintProviderContractError(
            "DuckDB Blueprint provider output size changed"
        )
    if _file_sha256(path) != receipt.output_content_sha256:
        raise DuckDBBlueprintProviderContractError(
            "DuckDB Blueprint provider output checksum changed"
        )
    return path


class DuckDBBlueprintProvider:
    """Execute a pre-bound SQL plan without arbitrary DuckDB external access."""

    workload_subject = DUCKDB_BLUEPRINT_WORKLOAD
    engine_name = "duckdb"

    def __init__(
        self,
        *,
        object_store: DuckDBBlueprintObjectStore | None = None,
        workspace_root: Path | None = None,
    ):
        self.object_store = object_store
        self.workspace_root = (
            None if workspace_root is None else workspace_root.expanduser().resolve()
        )

    def probe(self) -> dict[str, str]:
        """Verify the local runtime without opening files or network access."""

        try:
            import duckdb
            import pyarrow

            connection = duckdb.connect(":memory:")
            try:
                configured_spatial_path = _configured_spatial_extension_path()
                connection.execute("SET autoinstall_known_extensions = false")
                connection.execute("SET autoload_known_extensions = false")
                version = str(connection.execute("SELECT version()").fetchone()[0])
                try:
                    spatial = _load_spatial_extension(connection)
                    spatial_status = spatial.extension_version
                except DuckDBBlueprintProviderError:
                    if configured_spatial_path is not None:
                        raise
                    spatial_status = "unavailable"
                connection.execute("SET enable_external_access = false")
            finally:
                connection.close()
            if self.object_store is not None:
                self.object_store.probe()
                storage = "immutable_s3"
            else:
                storage = "local"
        except Exception as exc:
            raise DuckDBBlueprintProviderExecutionError(
                "DuckDB Blueprint provider readiness probe failed"
            ) from exc
        return {
            "duckdb_version": version,
            "pyarrow_version": pyarrow.__version__,
            "external_access": "disabled",
            "spatial_extension": spatial_status,
            "storage": storage,
        }

    def certify(
        self,
        spec: DuckDBBlueprintExecutionSpec,
    ) -> DuckDBBlueprintConformanceReport:
        """Execute twice and prove deterministic provider-local behavior."""

        first = self.execute(spec)
        replay = self.execute(spec)
        if (
            first.output_content_sha256 != replay.output_content_sha256
            or first.output_rows != replay.output_rows
            or first.output_columns != replay.output_columns
        ):
            raise DuckDBBlueprintProviderExecutionError(
                "DuckDB Blueprint provider replay was not deterministic"
            )
        checks: dict[str, Literal["passed", "not_applicable"]] = {
            "execution_plan_binding": "passed",
            "input_content_binding": "passed",
            "deterministic_replay": "passed",
            "atomic_output_checkpoint": "passed",
            "bounded_input": "passed",
            "bounded_output": "passed",
            "external_access_disabled": "passed",
            "provider_metrics": "passed",
            "spatial_extension_identity": (
                "passed" if spec.pipeline.require_spatial else "not_applicable"
            ),
            "portable_spatial_encoding": (
                "passed" if spec.pipeline.require_spatial else "not_applicable"
            ),
            "geoparquet_metadata": (
                "passed" if spec.pipeline.require_spatial else "not_applicable"
            ),
            "cancel_reconcile": "not_applicable",
        }
        values = {
            "tenant_id": spec.tenant_id,
            "run_id": spec.run_id,
            "execution_plan_sha256": spec.execution_plan_sha256,
            "provider_version": replay.provider_version,
            "output_content_sha256": replay.output_content_sha256,
            "checks": checks,
            "verdict": "passed",
        }
        return DuckDBBlueprintConformanceReport(
            **values,
            report_sha256=duckdb_blueprint_conformance_fingerprint(values),
        )

    def execute(
        self,
        spec: DuckDBBlueprintExecutionSpec,
    ) -> DuckDBBlueprintProviderReceipt:
        started = time.perf_counter()
        output_is_s3 = urlsplit(spec.output_uri).scheme == "s3"
        if output_is_s3:
            parse_blueprint_s3_uri(spec.output_uri)
            if self.object_store is None or self.workspace_root is None:
                raise DuckDBBlueprintProviderContractError(
                    "S3 DuckDB output requires object storage and a local workspace"
                )
            workspace_parent = self.workspace_root
        else:
            output_path = _local_file(spec.output_uri)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            workspace_parent = output_path.parent
        workspace_parent.mkdir(parents=True, exist_ok=True)
        workspace = Path(
            tempfile.mkdtemp(
                prefix=f".gda-duckdb-{spec.run_id}.",
                dir=workspace_parent,
            )
        )
        temporary_output = workspace / "output.parquet"
        input_rows = 0
        input_bytes = 0
        timer: threading.Timer | None = None

        try:
            import duckdb
            import pyarrow.parquet as parquet

            expression = _validate_sql(
                spec.pipeline.sql,
                {item.binding_name for item in spec.inputs},
                require_order=spec.pipeline.require_ordered_output,
                require_spatial=spec.pipeline.require_spatial,
            )
            del expression
            connection = duckdb.connect(":memory:")
            spatial_loaded = False
            spatial_extension_evidence = None
            spatial_output_evidence = None
            try:
                if spec.pipeline.require_spatial:
                    spatial_extension_evidence = _load_spatial_extension(connection)
                    spatial_loaded = True
                else:
                    connection.execute("SET enable_external_access = false")

                for item in spec.inputs:
                    if item.provider_system == "s3":
                        if self.object_store is None or item.object_version_id is None:
                            raise DuckDBBlueprintProviderContractError(
                                "S3 DuckDB input requires configured object storage"
                            )
                        source_path = workspace / f"input-{item.binding_name}.parquet"
                        try:
                            source_size = self.object_store.download_input(
                                item.provider_locator,
                                version_id=item.object_version_id,
                                destination=source_path,
                                expected_sha256=item.content_sha256,
                                max_bytes=spec.pipeline.max_input_bytes - input_bytes,
                            )
                        except DuckDBBlueprintObjectStoreConflict as exc:
                            raise DuckDBBlueprintProviderContractError(
                                f"admitted DuckDB input changed: {item.binding_name}"
                            ) from exc
                        except DuckDBBlueprintObjectStoreUnavailable as exc:
                            raise DuckDBBlueprintProviderUnavailableError(
                                "DuckDB Blueprint input storage is unavailable"
                            ) from exc
                    else:
                        source_path = _local_file(item.provider_locator)
                        if not source_path.is_file():
                            raise DuckDBBlueprintProviderContractError(
                                f"admitted DuckDB input is not a file: {item.binding_name}"
                            )
                        source_size = source_path.stat().st_size
                    if not source_path.is_file():
                        raise DuckDBBlueprintProviderContractError(
                            f"admitted DuckDB input is not a file: {item.binding_name}"
                        )
                    actual_sha256 = _file_sha256(source_path)
                    if actual_sha256 != item.content_sha256:
                        raise DuckDBBlueprintProviderContractError(
                            f"admitted DuckDB input checksum changed: {item.binding_name}"
                        )
                    if input_bytes + source_size > spec.pipeline.max_input_bytes:
                        raise DuckDBBlueprintProviderContractError(
                            "DuckDB Blueprint inputs exceed max_input_bytes"
                        )
                    table = parquet.read_table(source_path)
                    input_rows += table.num_rows
                    input_bytes += source_size
                    if input_rows > spec.pipeline.max_input_rows:
                        raise DuckDBBlueprintProviderContractError(
                            "DuckDB Blueprint inputs exceed max_input_rows"
                        )
                    connection.register(item.binding_name, table)

                connection.execute("SET enable_external_access = false")
                bounded_sql = (
                    "SELECT * FROM ("
                    + spec.pipeline.sql
                    + ") AS _gda_blueprint_result LIMIT "
                    + str(spec.pipeline.max_output_rows + 1)
                )
                timer = threading.Timer(
                    spec.pipeline.timeout_seconds,
                    connection.interrupt,
                )
                timer.daemon = True
                timer.start()
                output_table = connection.execute(bounded_sql).to_arrow_table()
                if output_table.num_rows > spec.pipeline.max_output_rows:
                    raise DuckDBBlueprintProviderContractError(
                        "DuckDB Blueprint output exceeds max_output_rows"
                    )
                if spec.pipeline.require_spatial:
                    output_table, spatial_output_evidence = _validate_spatial_output(
                        connection,
                        output_table,
                        expected_srid=spec.pipeline.spatial_output_srid,
                    )
                parquet.write_table(
                    output_table,
                    temporary_output,
                    compression="zstd",
                    version="2.6",
                    write_statistics=True,
                )
            finally:
                if timer is not None:
                    timer.cancel()
                connection.close()

            output_content_sha256 = _file_sha256(temporary_output)
            output_size_bytes = temporary_output.stat().st_size
            if output_size_bytes > spec.pipeline.max_output_bytes:
                raise DuckDBBlueprintProviderContractError(
                    "DuckDB Blueprint output exceeds max_output_bytes"
                )
            storage_evidence = None
            if output_is_s3:
                assert self.object_store is not None
                try:
                    storage_evidence = self.object_store.publish_output(
                        spec.tenant_id,
                        spec.run_id,
                        spec.output_uri,
                        source=temporary_output,
                        expected_sha256=output_content_sha256,
                    )
                except DuckDBBlueprintObjectStoreConflict as exc:
                    raise DuckDBBlueprintProviderContractError(
                        "immutable DuckDB Blueprint output conflicts with existing bytes"
                    ) from exc
                except DuckDBBlueprintObjectStoreUnavailable as exc:
                    raise DuckDBBlueprintProviderUnavailableError(
                        "DuckDB Blueprint output storage is unavailable"
                    ) from exc
            else:
                os.replace(temporary_output, output_path)
            observed_at = datetime.now(UTC)
            values = {
                "tenant_id": spec.tenant_id,
                "run_id": spec.run_id,
                "execution_plan_artifact_id": spec.execution_plan_artifact_id,
                "execution_plan_sha256": spec.execution_plan_sha256,
                "definition_version_id": spec.definition_version_id,
                "definition_sha256": spec.definition_sha256,
                "attempt_no": spec.attempt_no,
                "provider_version": duckdb.__version__,
                "output_uri": spec.output_uri,
                "output_content_sha256": output_content_sha256,
                "output_size_bytes": output_size_bytes,
                "output_rows": output_table.num_rows,
                "output_columns": tuple(
                    {"name": field.name, "type": str(field.type)}
                    for field in output_table.schema
                ),
                "input_rows": input_rows,
                "input_bytes": input_bytes,
                "duration_ms": max(
                    0,
                    int(round((time.perf_counter() - started) * 1000)),
                ),
                "spatial_extension_loaded": spatial_loaded,
                "spatial_extension_evidence": spatial_extension_evidence,
                "spatial_output_evidence": spatial_output_evidence,
                "checkpoint_mode": "atomic_output",
                "external_access": "disabled",
                "output_storage_evidence": storage_evidence,
                "observed_at": observed_at,
            }
            return DuckDBBlueprintProviderReceipt(
                **values,
                receipt_sha256=duckdb_blueprint_receipt_fingerprint(values),
            )
        except DuckDBBlueprintProviderError:
            raise
        except Exception as exc:
            raise DuckDBBlueprintProviderExecutionError(
                "DuckDB Blueprint execution failed"
            ) from exc
        finally:
            for child in workspace.iterdir():
                child.unlink(missing_ok=True)
            workspace.rmdir()


def _local_file(uri: str) -> Path:
    parts = urlsplit(uri)
    if (
        parts.scheme != "file"
        or parts.netloc
        or not parts.path.startswith("/")
        or parts.query
        or parts.fragment
    ):
        raise ValueError("DuckDB provider locations must be absolute file URIs")
    return Path(unquote(parts.path)).resolve()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _configured_spatial_extension_path() -> Path | None:
    value = os.getenv("GDA_BLUEPRINT_DUCKDB_SPATIAL_EXTENSION_PATH", "").strip()
    if not value:
        return None
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise DuckDBBlueprintProviderContractError(
            "configured DuckDB Spatial extension is not a regular file"
        )
    return path


def _load_spatial_extension(connection: Any) -> DuckDBSpatialExtensionEvidence:
    """Load an already-installed extension, with all implicit downloads disabled."""

    configured_path = _configured_spatial_extension_path()
    try:
        connection.execute("SET autoinstall_known_extensions = false")
        connection.execute("SET autoload_known_extensions = false")
        if configured_path is None:
            connection.execute("LOAD spatial")
        else:
            escaped_path = str(configured_path).replace("'", "''")
            connection.execute(f"LOAD '{escaped_path}'")
        row = connection.execute(
            """
            SELECT extension_version, install_mode, installed_from, install_path,
                   installed, loaded
            FROM duckdb_extensions()
            WHERE extension_name = 'spatial'
            """
        ).fetchone()
    except Exception as exc:
        raise DuckDBBlueprintProviderContractError(
            "DuckDB Spatial extension must be preinstalled and loadable"
        ) from exc
    if row is None:
        raise DuckDBBlueprintProviderContractError(
            "DuckDB Spatial extension is absent from the runtime inventory"
        )
    extension_version, install_mode, installed_from, install_path, installed, loaded = row
    inventory_file = Path(str(install_path or "")).expanduser().resolve()
    extension_file = configured_path or inventory_file
    if (
        not loaded
        or not str(extension_version or "").strip()
        or not extension_file.is_file()
        or (configured_path is None and not installed)
    ):
        raise DuckDBBlueprintProviderContractError(
            "DuckDB Spatial extension inventory is incomplete"
        )
    return DuckDBSpatialExtensionEvidence(
        extension_version=str(extension_version),
        binary_sha256=_file_sha256(extension_file),
        install_mode=("EXPLICIT_PATH" if configured_path is not None else str(install_mode)),
        installed_from=str(installed_from or ""),
    )


def _validate_spatial_output(
    connection: Any,
    output_table: Any,
    *,
    expected_srid: int | None,
) -> tuple[Any, DuckDBSpatialOutputEvidence]:
    """Require portable WKB/SRID/bbox output and materialize GeoParquet metadata."""

    if expected_srid is None:
        raise DuckDBBlueprintProviderContractError(
            "DuckDB spatial pipeline does not declare an output SRID"
        )
    try:
        import pyarrow as pa
        from pyproj import CRS
    except Exception as exc:
        raise DuckDBBlueprintProviderContractError(
            "DuckDB Spatial output requires PyArrow and PROJ CRS support"
        ) from exc

    fields = {field.name: field for field in output_table.schema}
    required_names = {"geometry_wkb", "srid", "bbox"}
    if not required_names.issubset(fields):
        raise DuckDBBlueprintProviderContractError(
            "DuckDB spatial output must include geometry_wkb, srid and bbox columns"
        )
    if not (
        pa.types.is_binary(fields["geometry_wkb"].type)
        or pa.types.is_large_binary(fields["geometry_wkb"].type)
    ):
        raise DuckDBBlueprintProviderContractError(
            "DuckDB spatial output geometry_wkb must be binary WKB"
        )
    if not pa.types.is_integer(fields["srid"].type):
        raise DuckDBBlueprintProviderContractError(
            "DuckDB spatial output srid must be an integer"
        )
    if not (
        pa.types.is_list(fields["bbox"].type)
        or pa.types.is_large_list(fields["bbox"].type)
    ) or not pa.types.is_floating(fields["bbox"].type.value_type):
        raise DuckDBBlueprintProviderContractError(
            "DuckDB spatial output bbox must be a floating-point list"
        )

    relation_name = "_gda_spatial_output"
    connection.register(relation_name, output_table)
    try:
        invalid = connection.execute(
            f"""
            SELECT
                count(*) FILTER (
                    WHERE geometry_wkb IS NULL
                       OR srid IS NULL
                       OR srid <> {expected_srid}
                       OR bbox IS NULL
                       OR len(bbox) <> 4
                       OR bbox[1] IS NULL OR bbox[2] IS NULL
                       OR bbox[3] IS NULL OR bbox[4] IS NULL
                       OR NOT isfinite(bbox[1]) OR NOT isfinite(bbox[2])
                       OR NOT isfinite(bbox[3]) OR NOT isfinite(bbox[4])
                       OR bbox[1] > bbox[3] OR bbox[2] > bbox[4]
                ) AS invalid_encoding_rows,
                count(*) FILTER (
                    WHERE geometry_wkb IS NOT NULL
                      AND NOT ST_IsValid(ST_GeomFromWKB(geometry_wkb))
                ) AS invalid_geometry_rows,
                count(*) FILTER (
                    WHERE geometry_wkb IS NOT NULL
                      AND (
                          abs(bbox[1] - ST_XMin(ST_GeomFromWKB(geometry_wkb))) > 1e-9
                       OR abs(bbox[2] - ST_YMin(ST_GeomFromWKB(geometry_wkb))) > 1e-9
                       OR abs(bbox[3] - ST_XMax(ST_GeomFromWKB(geometry_wkb))) > 1e-9
                       OR abs(bbox[4] - ST_YMax(ST_GeomFromWKB(geometry_wkb))) > 1e-9
                      )
                ) AS mismatched_bbox_rows,
                min(ST_XMin(ST_GeomFromWKB(geometry_wkb))) AS min_x,
                min(ST_YMin(ST_GeomFromWKB(geometry_wkb))) AS min_y,
                max(ST_XMax(ST_GeomFromWKB(geometry_wkb))) AS max_x,
                max(ST_YMax(ST_GeomFromWKB(geometry_wkb))) AS max_y
            FROM {relation_name}
            """
        ).fetchone()
    except Exception as exc:
        connection.unregister(relation_name)
        raise DuckDBBlueprintProviderContractError(
            "DuckDB spatial output cannot be decoded as valid WKB geometry"
        ) from exc
    if invalid[0] or invalid[1] or invalid[2]:
        connection.unregister(relation_name)
        raise DuckDBBlueprintProviderContractError(
            "DuckDB spatial output violates its WKB/SRID/bbox contract"
        )
    try:
        type_rows = connection.execute(
            f"""
            SELECT DISTINCT CAST(
                ST_GeometryType(ST_GeomFromWKB(geometry_wkb)) AS VARCHAR
            )
            FROM {relation_name}
            WHERE geometry_wkb IS NOT NULL
            ORDER BY 1
            """
        ).fetchall()
    except Exception as exc:
        raise DuckDBBlueprintProviderContractError(
            "DuckDB spatial output geometry type cannot be certified"
        ) from exc
    finally:
        connection.unregister(relation_name)
    bbox = None
    if invalid[3] is not None:
        bbox = tuple(float(item) for item in invalid[3:7])
    geometry_types = tuple(
        _geoparquet_geometry_type(str(row[0])) for row in type_rows
    )
    try:
        crs = CRS.from_epsg(expected_srid).to_json_dict()
    except Exception as exc:
        raise DuckDBBlueprintProviderContractError(
            "DuckDB spatial output SRID is not a valid PROJ CRS"
        ) from exc
    geo_metadata = {
        "version": DUCKDB_SPATIAL_GEOPARQUET_VERSION,
        "primary_column": "geometry_wkb",
        "columns": {
            "geometry_wkb": {
                "encoding": "WKB",
                "geometry_types": list(geometry_types),
                "crs": crs,
                **({"bbox": list(bbox)} if bbox is not None else {}),
            }
        },
    }
    metadata = dict(output_table.schema.metadata or {})
    metadata[b"geo"] = json.dumps(
        geo_metadata,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    output_table = output_table.replace_schema_metadata(metadata)
    return output_table, DuckDBSpatialOutputEvidence(
        srid=expected_srid,
        geometry_rows=output_table.num_rows,
        geometry_types=geometry_types,
        bbox=bbox,
        crs_sha256=canonical_json_fingerprint(crs),
        geo_metadata_sha256=canonical_json_fingerprint(geo_metadata),
    )


def _geoparquet_geometry_type(value: str) -> str:
    names = {
        "POINT": "Point",
        "LINESTRING": "LineString",
        "POLYGON": "Polygon",
        "MULTIPOINT": "MultiPoint",
        "MULTILINESTRING": "MultiLineString",
        "MULTIPOLYGON": "MultiPolygon",
        "GEOMETRYCOLLECTION": "GeometryCollection",
    }
    try:
        return names[value.upper()]
    except KeyError as exc:
        raise DuckDBBlueprintProviderContractError(
            "DuckDB returned an unsupported GeoParquet geometry type"
        ) from exc


def _validate_sql(
    sql: str,
    relations: set[str],
    *,
    require_order: bool,
    require_spatial: bool,
) -> Any:
    if _FORBIDDEN_SQL.search(sql) or _FORBIDDEN_FILE_FUNCTION.search(sql):
        raise DuckDBBlueprintProviderContractError(
            "DuckDB Blueprint SQL contains a forbidden operation"
        )
    try:
        from sqlglot import exp, parse

        statements = [item for item in parse(sql, read="duckdb") if item is not None]
    except Exception as exc:
        raise DuckDBBlueprintProviderContractError(
            "DuckDB Blueprint SQL is not valid DuckDB SQL"
        ) from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        raise DuckDBBlueprintProviderContractError(
            "DuckDB Blueprint SQL must contain exactly one read-only query"
        )
    expression = statements[0]
    cte_names = {item.alias_or_name.lower() for item in expression.find_all(exp.CTE)}
    for table in expression.find_all(exp.Table):
        if table.catalog or table.db:
            raise DuckDBBlueprintProviderContractError(
                "DuckDB Blueprint SQL cannot address catalogs or schemas"
            )
        relation = table.name.lower()
        if relation not in relations and relation not in cte_names:
            raise DuckDBBlueprintProviderContractError(
                f"DuckDB Blueprint SQL references unbound relation {relation!r}"
            )
    if require_order and expression.find(exp.Order) is None:
        raise DuckDBBlueprintProviderContractError(
            "deterministic DuckDB Blueprint output requires ORDER BY"
        )
    if _SPATIAL_SQL_FUNCTION.search(sql) and not require_spatial:
        raise DuckDBBlueprintProviderContractError(
            "DuckDB Blueprint spatial SQL requires the explicit spatial pipeline contract"
        )
    return expression
