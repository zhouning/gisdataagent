#!/usr/bin/env python3
"""Accept the pinned Gravitino metadata plane and GDA bridge contract."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx

from data_agent.data_architecture_ledger import ProviderObjectState
from data_agent.metadata_fabric import (
    MetadataFabricSystem,
    build_gravitino_architecture_observation,
    build_gravitino_reference,
    gravitino_reference_from_binding,
)
from data_agent.metadata_provider_health import check_metadata_provider
from data_agent.metadata_provider_read import (
    GravitinoMetadataProviderReadClient,
    ProviderReadStatus,
)
from data_agent.metadata_provider_search import GravitinoMetadataProviderSearchClient
from data_agent.platform_contracts import ResourceVersion, canonical_json_fingerprint


class AcceptanceError(RuntimeError):
    """A required Gravitino acceptance assertion failed."""


def _request(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    expected_status: int = 200,
) -> dict[str, Any]:
    response = client.request(method, path, json=payload)
    try:
        document = response.json()
    except ValueError as exc:
        raise AcceptanceError(
            f"Gravitino {method} {path} returned non-JSON HTTP {response.status_code}"
        ) from exc
    if response.status_code != expected_status:
        error = document if isinstance(document, dict) else {}
        raise AcceptanceError(
            f"Gravitino {method} {path} expected HTTP {expected_status}, "
            f"got {response.status_code}: {error.get('type', 'unknown')} "
            f"code={error.get('code', 'unknown')}"
        )
    if not isinstance(document, dict):
        raise AcceptanceError(f"Gravitino {method} {path} returned an invalid document")
    if expected_status < 400 and document.get("code") != 0:
        raise AcceptanceError(
            f"Gravitino {method} {path} returned provider code {document.get('code')}"
        )
    return document


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceError(message)


def _resource_version(*, table_fingerprint: str, created_at: datetime) -> ResourceVersion:
    resource_urn = "gda://tenant-a/dataset/gravitino-parcels"
    return ResourceVersion(
        tenant_id="tenant-a",
        resource_urn=resource_urn,
        resource_version_id=uuid5(NAMESPACE_URL, f"{resource_urn}:{table_fingerprint}"),
        version_key=f"metadata-{table_fingerprint[:12]}",
        content_sha256=table_fingerprint,
        authority_version_ref={"gravitino": f"metadata-sha256:{table_fingerprint}"},
        created_by="workload:gravitino-acceptance",
        created_at=created_at,
    )


def _catalog_properties(
    *,
    backend: str,
    uri: str | None,
    jdbc_driver: str | None,
    jdbc_user: str | None,
    jdbc_password: str | None,
    jdbc_initialize: bool,
    warehouse: str | None,
) -> dict[str, str]:
    if backend == "memory":
        return {
            "catalog-backend": "memory",
            "uri": uri or "file:///tmp/gda-gravitino-warehouse",
        }
    if backend != "jdbc":
        raise AcceptanceError(f"unsupported Gravitino catalog backend: {backend}")
    required = {
        "uri": uri,
        "jdbc-driver": jdbc_driver,
        "jdbc-user": jdbc_user,
        "jdbc-password": jdbc_password,
        "warehouse": warehouse,
    }
    missing = sorted(key for key, value in required.items() if not value)
    if missing:
        raise AcceptanceError(
            "JDBC Gravitino catalog properties are missing: " + ", ".join(missing)
        )
    return {
        "catalog-backend": "jdbc",
        "jdbc-driver": str(jdbc_driver),
        "uri": str(uri),
        "jdbc-user": str(jdbc_user),
        "jdbc-password": str(jdbc_password),
        "jdbc-initialize": "true" if jdbc_initialize else "false",
        "warehouse": str(warehouse),
    }


def _table_contract(table: dict[str, Any]) -> dict[str, Any]:
    properties = table.get("properties")
    if not isinstance(properties, dict):
        raise AcceptanceError("Gravitino table properties must be an object")
    _require(table.get("name") == "parcels", "loaded table name drifted")
    _require(
        properties.get("provider") == "iceberg",
        "loaded table must identify the Iceberg provider",
    )
    _require(
        properties.get("format-version") == "2",
        "loaded table must expose Iceberg format version 2",
    )
    _require(
        isinstance(properties.get("location"), str) and properties["location"],
        "loaded table must expose a physical location",
    )
    stable_table = dict(table)
    # Gravitino reconstructs audit metadata after restart. It is useful
    # evidence, but it is not part of the stable technical-object revision.
    stable_table.pop("audit", None)
    return {
        "table_fingerprint": canonical_json_fingerprint(stable_table),
        "schema_fingerprint": canonical_json_fingerprint(
            {"columns": table.get("columns", [])}
        ),
        "schema_version_fingerprint": canonical_json_fingerprint(
            {
                "columns": table.get("columns", []),
                "format_version": properties.get("format-version"),
            }
        ),
        "location_fingerprint": canonical_json_fingerprint(
            {
                "location": properties.get("location"),
                "format": properties.get("format"),
                "snapshot": properties.get("current-snapshot-id"),
            }
        ),
        "table_properties": {
            "format": properties.get("format"),
            "format-version": properties.get("format-version"),
            "provider": properties.get("provider"),
            "location": properties.get("location"),
            "current-snapshot-id": properties.get("current-snapshot-id"),
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def run_acceptance(
    *,
    gravitino_url: str,
    evidence_file: Path,
    image_ref: str,
    image_id: str,
    phase: str = "single",
    state_file: Path | None = None,
    catalog_backend: str = "memory",
    catalog_uri: str | None = None,
    catalog_jdbc_driver: str | None = None,
    catalog_jdbc_user: str | None = None,
    catalog_jdbc_password: str | None = None,
    catalog_jdbc_initialize: bool = True,
    catalog_warehouse: str | None = None,
    runtime_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if phase not in {"single", "seed", "recover"}:
        raise AcceptanceError(f"unsupported acceptance phase: {phase}")
    if phase in {"seed", "recover"} and state_file is None:
        raise AcceptanceError(f"{phase} phase requires --state-file")
    metalake = "gda_acceptance"
    catalog = "iceberg"
    namespace = "transportation"
    object_name = "parcels"
    base_path = f"/api/metalakes/{metalake}/catalogs/{catalog}/schemas/{namespace}"
    state: dict[str, Any] | None = None
    loaded_table: dict[str, Any]
    table_contract: dict[str, Any]
    observed_at: datetime

    with httpx.Client(base_url=gravitino_url.rstrip("/"), timeout=15.0) as client:
        health = _request(client, "GET", "/health")
        version = _request(client, "GET", "/api/version")
        _require(health.get("status") == "up", "Gravitino health must be up")
        version_data = version.get("version")
        _require(
            isinstance(version_data, dict) and version_data.get("version") == "1.3.0",
            "acceptance requires Gravitino 1.3.0",
        )
        os.environ["GDA_GRAVITINO_URL"] = gravitino_url
        provider_health = check_metadata_provider(MetadataFabricSystem.GRAVITINO)
        _require(
            provider_health["status"] == "ok",
            f"GDA provider health probe failed: {provider_health['status']}",
        )

        if phase in {"single", "seed"}:
            _request(
                client,
                "POST",
                "/api/metalakes",
                payload={
                    "name": metalake,
                    "comment": "GDA Gravitino metadata bridge acceptance",
                    "properties": {},
                },
            )
            _request(
                client,
                "POST",
                f"/api/metalakes/{metalake}/catalogs",
                payload={
                    "name": catalog,
                    "type": "RELATIONAL",
                    "provider": "lakehouse-iceberg",
                    "comment": "GDA Gravitino metadata bridge acceptance",
                    "properties": _catalog_properties(
                        backend=catalog_backend,
                        uri=catalog_uri,
                        jdbc_driver=catalog_jdbc_driver,
                        jdbc_user=catalog_jdbc_user,
                        jdbc_password=catalog_jdbc_password,
                        jdbc_initialize=catalog_jdbc_initialize,
                        warehouse=catalog_warehouse,
                    ),
                },
            )
            _request(
                client,
                "POST",
                f"/api/metalakes/{metalake}/catalogs/{catalog}/schemas",
                payload={
                    "name": namespace,
                    "comment": "GDA Gravitino metadata bridge acceptance",
                    "properties": {},
                },
            )
            created = _request(
                client,
                "POST",
                f"{base_path}/tables",
                payload={
                    "name": object_name,
                    "columns": [
                        {
                            "name": "parcel_id",
                            "type": "integer",
                            "comment": "stable parcel identifier",
                            "nullable": False,
                        },
                        {
                            "name": "geom_wkb",
                            "type": "binary",
                            "comment": "provider geometry payload",
                            "nullable": True,
                        },
                    ],
                    "comment": "GDA Gravitino metadata bridge acceptance table",
                    "properties": {},
                },
            )
            table = created.get("table")
            _require(isinstance(table, dict), "table create response must include a table")
            if phase in {"single", "seed"}:
                loaded = _request(client, "GET", f"{base_path}/tables/{object_name}")
                loaded_table = loaded.get("table")
                _require(
                    isinstance(loaded_table, dict),
                    "table load response must include a table",
                )
                listed = _request(client, "GET", f"{base_path}/tables")
                identifiers = listed.get("identifiers")
                _require(
                    isinstance(identifiers, list)
                    and any(
                        item.get("name") == object_name
                        and item.get("namespace") == [metalake, catalog, namespace]
                        for item in identifiers
                        if isinstance(item, dict)
                    ),
                    "created Gravitino table must be listed with its full namespace",
                )
                table_contract = _table_contract(loaded_table)
                observed_at = datetime.now(UTC).replace(microsecond=0)
                if phase == "seed":
                    state = {
                        "schema_version": "gda.gravitino_metadata_bridge_persistence_state.v1",
                        "metalake": metalake,
                        "catalog": catalog,
                        "namespace": namespace,
                        "object_name": object_name,
                        "catalog_backend": catalog_backend,
                        "table": loaded_table,
                        "table_contract": table_contract,
                        "observed_at": observed_at.isoformat(),
                    }
                    _write_json(state_file, state)
                    return {
                        "schema_version": state["schema_version"],
                        "status": "seeded",
                        "state_file": str(state_file),
                        "table_fingerprint": table_contract["table_fingerprint"],
                    }
        else:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            _require(
                state.get("schema_version")
                == "gda.gravitino_metadata_bridge_persistence_state.v1",
                "persistence state schema is invalid",
            )
            _require(
                [
                    state.get("metalake"),
                    state.get("catalog"),
                    state.get("namespace"),
                    state.get("object_name"),
                ]
                == [metalake, catalog, namespace, object_name],
                "persistence state identity drifted",
            )
            _request(client, "GET", f"/api/metalakes/{metalake}")
            catalog_document = _request(
                client,
                "GET",
                f"/api/metalakes/{metalake}/catalogs/{catalog}",
            )
            catalog_payload = catalog_document.get("catalog")
            _require(
                isinstance(catalog_payload, dict),
                "recovered catalog response must include a catalog",
            )
            catalog_properties = catalog_payload.get("properties")
            _require(
                isinstance(catalog_properties, dict)
                and catalog_properties.get("catalog-backend") == "jdbc",
                "recovered catalog must remain JDBC-backed",
            )
            _request(
                client,
                "GET",
                f"/api/metalakes/{metalake}/catalogs/{catalog}/schemas/{namespace}",
            )
            loaded = _request(client, "GET", f"{base_path}/tables/{object_name}")
            loaded_table = loaded.get("table")
            _require(
                isinstance(loaded_table, dict),
                "recovered table response must include a table",
            )
            table_contract = _table_contract(loaded_table)
            _require(
                table_contract["table_fingerprint"]
                == state["table_contract"]["table_fingerprint"],
                "recovered table fingerprint drifted",
            )
            recovered_stable_table = dict(loaded_table)
            recovered_stable_table.pop("audit", None)
            seeded_stable_table = dict(state["table"])
            seeded_stable_table.pop("audit", None)
            _require(
                recovered_stable_table == seeded_stable_table,
                "recovered stable table payload drifted",
            )
            observed_at = datetime.fromisoformat(state["observed_at"])

        table_fingerprint = table_contract["table_fingerprint"]
        schema_fingerprint = table_contract["schema_fingerprint"]
        schema_version_fingerprint = table_contract["schema_version_fingerprint"]
        location_fingerprint = table_contract["location_fingerprint"]
        resource_version = _resource_version(
            table_fingerprint=table_fingerprint,
            created_at=observed_at,
        )
        reference = build_gravitino_reference(
            resource_version,
            metalake=metalake,
            catalog=catalog,
            namespace=namespace,
            object_name=object_name,
            object_type="table",
            object_version_ref=f"metadata-sha256:{table_fingerprint}",
        )
        binding = reference.to_metadata_binding(
            binding_id=uuid5(resource_version.resource_version_id, "metadata-binding"),
            created_by="workload:gravitino-acceptance",
            created_at=observed_at,
        )
        restored = gravitino_reference_from_binding(
            binding,
            resource_version=resource_version,
        )
        _require(restored == reference, "Gravitino binding must round-trip exactly")
        present_observation = build_gravitino_architecture_observation(
            reference,
            source_revision=f"metadata-sha256:{table_fingerprint}",
            schema_content_sha256=schema_fingerprint,
            schema_version_sha256=schema_version_fingerprint,
            physical_location_sha256=location_fingerprint,
            observed_at=observed_at,
            fresh_until=observed_at + timedelta(minutes=5),
            observed_by="workload:gravitino-acceptance",
            recorded_at=observed_at,
        )
        replay_observation = build_gravitino_architecture_observation(
            reference,
            source_revision=present_observation.source_revision,
            schema_content_sha256=present_observation.schema_content_sha256,
            schema_version_sha256=present_observation.schema_version_sha256,
            physical_location_sha256=present_observation.physical_location_sha256,
            observed_at=present_observation.observed_at,
            fresh_until=present_observation.fresh_until,
            observed_by=present_observation.observed_by,
            recorded_at=present_observation.recorded_at,
        )
        _require(
            replay_observation.observation_id == present_observation.observation_id
            and replay_observation.observation_sha256
            == present_observation.observation_sha256,
            "identical provider facts must replay to one observation",
        )

        with GravitinoMetadataProviderReadClient(gravitino_url) as read_client:
            provider_read = read_client.read(binding)
        _require(
            provider_read.status is ProviderReadStatus.PRESENT,
            "provider-read bridge must observe the created Gravitino table",
        )
        _require(
            provider_read.provider_fingerprint == table_fingerprint,
            "provider-read bridge fingerprint must match the bound table version",
        )
        _require(
            provider_read.evidence.get("name") == object_name,
            "provider-read bridge evidence must identify the table",
        )
        with GravitinoMetadataProviderSearchClient(gravitino_url) as search_client:
            provider_search = search_client.search(
                resource_version.tenant_id,
                provider_namespace=reference.external_namespace,
                object_type="table",
                query=object_name,
                limit=10,
                offset=0,
            )
        _require(
            [item.external_object_id for item in provider_search.items] == [object_name],
            "provider-search bridge must discover the bound Gravitino table",
        )

        dropped = _request(client, "DELETE", f"{base_path}/tables/{object_name}?purge=true")
        _require(dropped.get("dropped") is True, "Gravitino must report the table as dropped")
        missing = _request(
            client,
            "GET",
            f"{base_path}/tables/{object_name}",
            expected_status=404,
        )
        _require(
            missing.get("type") == "NoSuchTableException",
            "post-delete load must fail with NoSuchTableException",
        )
        with GravitinoMetadataProviderReadClient(gravitino_url) as read_client:
            provider_read_missing = read_client.read(binding)
        _require(
            provider_read_missing.status is ProviderReadStatus.NOT_FOUND,
            "provider-read bridge must preserve the post-delete not-found state",
        )
        tombstone_at = datetime.now(UTC).replace(microsecond=0)
        tombstone_observation = build_gravitino_architecture_observation(
            reference,
            source_revision=None,
            schema_content_sha256=None,
            schema_version_sha256=None,
            physical_location_sha256=None,
            observed_at=tombstone_at,
            fresh_until=tombstone_at + timedelta(minutes=5),
            observed_by="workload:gravitino-acceptance",
            recorded_at=tombstone_at,
            object_state=ProviderObjectState.TOMBSTONED,
        )

    persistent = phase == "recover"
    report: dict[str, Any] = {
        "schema_version": "gda.gravitino_metadata_bridge_acceptance.v4",
        "status": "passed",
        "phase": phase,
        "runtime": runtime_metadata or {},
        "gravitino": {
            "image_ref": image_ref,
            "image_id": image_id,
            "version": version_data,
            "health_status": health.get("status"),
            "health_probe": {
                "status": provider_health["status"],
                "endpoint": provider_health["endpoint"],
                "status_code": provider_health["status_code"],
                "retryable": provider_health["retryable"],
                "code": provider_health["code"],
            },
        },
        "provider_facts": {
            "metalake": metalake,
            "catalog": catalog,
            "catalog_provider": "lakehouse-iceberg",
            "namespace": namespace,
            "object_name": object_name,
            "table_fingerprint": table_fingerprint,
            "table_properties": table_contract["table_properties"],
            "post_delete_error_type": missing.get("type"),
        },
        "gda_projection": {
            "resource_version": resource_version.model_dump(mode="json"),
            "reference": reference.model_dump(mode="json"),
            "binding": binding.model_dump(mode="json"),
            "present_observation": present_observation.model_dump(mode="json"),
            "tombstone_observation": tombstone_observation.model_dump(mode="json"),
        },
        "provider_read": {
            "present": provider_read.model_dump(mode="json"),
            "not_found": provider_read_missing.model_dump(mode="json"),
        },
        "provider_search": provider_search.model_dump(mode="json"),
        "checks": {
            "health": True,
            "version_pinned": True,
            "metalake_catalog_namespace_table_create": True,
            "table_read_and_list": True,
            "iceberg_provider_and_format_observed": True,
            "entity_store_persistent": persistent,
            "iceberg_catalog_jdbc_persistent": persistent,
            "metalake_catalog_namespace_table_survived_restart": persistent,
            "resource_reference_binding_round_trip": True,
            "present_observation_replay_idempotent": True,
            "provider_read_present_fingerprint_and_evidence": True,
            "provider_read_not_found_after_delete": True,
            "provider_search_bound_namespace_discovery": True,
            "volatile_audit_field_excluded_from_revision": True,
            "delete_and_tombstone_projection": True,
        },
        "limitations": [
            "This is a local Gravitino metadata-plane acceptance only.",
            "The persistence phase validates durable H2 entity metadata and JDBC "
            "catalog metadata across one container restart.",
            "It does not validate OIDC, backup/restore, MinIO object bytes, or production HA.",
            "It does not validate Spark/Sedona/Flink create/read/write/schema evolution "
            "or lineage conformance.",
        ],
    }
    report["report_sha256"] = canonical_json_fingerprint(report)
    evidence_file.parent.mkdir(parents=True, exist_ok=True)
    evidence_file.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    evidence_file.chmod(0o600)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gravitino-url", required=True)
    parser.add_argument("--evidence-file", type=Path, required=True)
    parser.add_argument("--image-ref", required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--phase", choices=("single", "seed", "recover"), default="single")
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--catalog-backend", choices=("memory", "jdbc"), default="memory")
    parser.add_argument("--catalog-uri")
    parser.add_argument("--catalog-jdbc-driver")
    parser.add_argument("--catalog-jdbc-user")
    parser.add_argument("--catalog-jdbc-password")
    parser.add_argument(
        "--catalog-jdbc-initialize",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--catalog-warehouse")
    parser.add_argument("--runtime-metadata", type=json.loads, default=None)
    args = parser.parse_args()
    report = run_acceptance(
        gravitino_url=args.gravitino_url,
        evidence_file=args.evidence_file,
        image_ref=args.image_ref,
        image_id=args.image_id,
        phase=args.phase,
        state_file=args.state_file,
        catalog_backend=args.catalog_backend,
        catalog_uri=args.catalog_uri,
        catalog_jdbc_driver=args.catalog_jdbc_driver,
        catalog_jdbc_user=args.catalog_jdbc_user,
        catalog_jdbc_password=args.catalog_jdbc_password,
        catalog_jdbc_initialize=args.catalog_jdbc_initialize,
        catalog_warehouse=args.catalog_warehouse,
        runtime_metadata=args.runtime_metadata,
    )
    print(f"Gravitino metadata bridge acceptance: {args.evidence_file}")
    if "report_sha256" in report:
        print(f"Report SHA-256: {report['report_sha256']}")
    else:
        print(f"Acceptance phase: {report.get('status', 'unknown')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
