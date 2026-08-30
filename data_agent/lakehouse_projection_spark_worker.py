"""Fixed Spark worker used by the plan-bound Iceberg projection provider."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from .lakehouse_projection_executor import (
    lakehouse_projection_drop_evidence_sha256,
    lakehouse_projection_receipt_fingerprint,
    lakehouse_projection_stable_commit_ref,
)
from .platform_contracts import canonical_json_fingerprint

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{1,62}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RECEIPT_SCHEMA = "gda.iceberg-provider-receipt.v1"
_RECEIPT_SUMMARY_KEYS = {
    "provider_receipt_schema": "gda.receipt.schema",
    "provider_receipt_action": "gda.receipt.action",
    "provider_receipt_plan_sha256": "gda.receipt.plan_sha256",
    "provider_receipt_idempotency_key": "gda.receipt.idempotency_key",
    "provider_receipt_sha256": "gda.receipt.sha256",
}


def _validated_target(payload: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    target = payload.get("target")
    if not isinstance(target, dict):
        raise ValueError("target must be an object")
    catalog = str(target.get("catalog") or "")
    namespace = str(target.get("namespace") or "")
    table = str(target.get("table") or "")
    if any(not _IDENTIFIER.fullmatch(value) for value in (catalog, namespace, table)):
        raise ValueError("unsafe Iceberg table identifier")
    warehouse_uri = str(target.get("warehouse_uri") or "")
    endpoint_url = str(target.get("endpoint_url") or "")
    region_name = str(target.get("region_name") or "")
    if not warehouse_uri.startswith("s3://") or not endpoint_url.startswith(
        ("http://", "https://")
    ):
        raise ValueError("invalid Iceberg storage configuration")
    return catalog, namespace, table, warehouse_uri, endpoint_url, region_name


def _spark_session(payload: dict[str, Any]):
    from pyspark.sql import SparkSession

    catalog, _, _, warehouse_uri, endpoint_url, _ = _validated_target(payload)
    warehouse = "s3a://" + warehouse_uri.removeprefix("s3://")
    return (
        SparkSession.builder.master("local[2]")
        .appName("gda-chongqing-lakehouse-projection")
        .config(
            "spark.sql.extensions",
            "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        )
        .config(f"spark.sql.catalog.{catalog}", "org.apache.iceberg.spark.SparkCatalog")
        .config(f"spark.sql.catalog.{catalog}.type", "hadoop")
        .config(f"spark.sql.catalog.{catalog}.warehouse", warehouse)
        .config("spark.hadoop.fs.s3a.endpoint", endpoint_url)
        .config("spark.hadoop.fs.s3a.path.style.access", "true")
        .config("spark.hadoop.fs.s3a.connection.ssl.enabled", str(endpoint_url.startswith("https")))
        .config("spark.hadoop.fs.s3a.access.key", os.environ["AWS_ACCESS_KEY_ID"])
        .config("spark.hadoop.fs.s3a.secret.key", os.environ["AWS_SECRET_ACCESS_KEY"])
        .config(
            "spark.hadoop.fs.s3a.aws.credentials.provider",
            "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider",
        )
        .getOrCreate()
    )


def _table_exists(spark, table_identifier: str) -> bool:
    try:
        spark.sql(f"DESCRIBE TABLE {table_identifier}").limit(1).collect()
        return True
    except Exception:
        return False


def _current_snapshot(spark, table_identifier: str) -> tuple[int, dict[str, str]]:
    row = spark.sql(
        f"SELECT snapshot_id, summary FROM {table_identifier}.snapshots "
        "ORDER BY committed_at DESC, snapshot_id DESC LIMIT 1"
    ).first()
    if row is None:
        raise RuntimeError("Iceberg table has no current snapshot")
    raw_summary = row["summary"] or {}
    try:
        summary = {str(key): str(value) for key, value in dict(raw_summary).items()}
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Iceberg snapshot summary is invalid") from exc
    return int(row["snapshot_id"]), summary


def _summary_receipt(summary: dict[str, str]) -> dict[str, str | None]:
    return {
        field: summary.get(summary_key)
        for field, summary_key in _RECEIPT_SUMMARY_KEYS.items()
    }


def _missing_receipt() -> dict[str, None]:
    return {field: None for field in _RECEIPT_SUMMARY_KEYS}


def _receipt_sha256(
    payload: dict[str, Any],
    *,
    action: str,
    deleted_snapshot_id: int | None = None,
    drop_evidence_sha256: str | None = None,
) -> str:
    target = payload.get("target") or {}
    plan_sha256 = str(payload.get("plan_sha256") or "")
    idempotency_key = str(payload.get("idempotency_key") or "")
    if not _SHA256.fullmatch(plan_sha256) or not _SHA256.fullmatch(idempotency_key):
        raise ValueError("Iceberg provider mutation requires sealed plan identifiers")
    commit_ref = lakehouse_projection_stable_commit_ref(
        tenant_id=str(target.get("tenant_id") or ""),
        projection_id=str(target.get("projection_id") or ""),
        target_ref=str(target.get("target_ref") or ""),
        table_identifier=(
            f"{target.get('catalog')}.{target.get('namespace')}.{target.get('table')}"
        ),
        warehouse_uri=str(target.get("warehouse_uri") or ""),
        artifact_sha256=str(target.get("artifact_sha256") or ""),
        action=action,
        plan_sha256=plan_sha256,
        idempotency_key=idempotency_key,
        deleted_snapshot_id=deleted_snapshot_id,
        drop_evidence_sha256=drop_evidence_sha256,
    )
    expected = lakehouse_projection_receipt_fingerprint(
        tenant_id=str(target.get("tenant_id") or ""),
        projection_id=str(target.get("projection_id") or ""),
        target_ref=str(target.get("target_ref") or ""),
        action=action,
        plan_sha256=plan_sha256,
        idempotency_key=idempotency_key,
        provider_commit_ref=commit_ref,
        target_exists=action == "rebuild",
        target_content_sha256=(
            str(target.get("expected_table_content_sha256") or "")
            if action == "rebuild"
            else None
        ),
        target_row_count=(int(target.get("expected_row_count") or 0) if action == "rebuild" else 0),
    )
    supplied = payload.get("receipt_sha256")
    if supplied is not None and str(supplied) != expected:
        raise ValueError("Iceberg provider receipt fingerprint differs from the sealed plan")
    return expected


def _tombstone_uri(payload: dict[str, Any]) -> str:
    _, namespace, table, warehouse_uri, _, _ = _validated_target(payload)
    warehouse = "s3a://" + warehouse_uri.removeprefix("s3://").rstrip("/")
    return f"{warehouse}/_gda_projection_tombstones/{namespace}/{table}.json"


def _write_tombstone(spark, payload: dict[str, Any], document: dict[str, Any]) -> None:
    path = spark._jvm.org.apache.hadoop.fs.Path(_tombstone_uri(payload))  # noqa: SLF001
    filesystem = path.getFileSystem(spark._jsc.hadoopConfiguration())  # noqa: SLF001
    filesystem.mkdirs(path.getParent())
    stream = filesystem.create(path, True)
    try:
        encoded = json.dumps(
            document, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        stream.write(bytearray(encoded))
        stream.hflush()
    finally:
        stream.close()


def _read_tombstone(spark, payload: dict[str, Any]) -> dict[str, Any] | None:
    path = spark._jvm.org.apache.hadoop.fs.Path(_tombstone_uri(payload))  # noqa: SLF001
    filesystem = path.getFileSystem(spark._jsc.hadoopConfiguration())  # noqa: SLF001
    if not filesystem.exists(path):
        return None
    stream = filesystem.open(path)
    try:
        content = bytearray()
        while True:
            value = stream.read()
            if value < 0:
                break
            content.append(value)
    finally:
        stream.close()
    document = json.loads(content.decode("utf-8"))
    if not isinstance(document, dict):
        raise RuntimeError("Iceberg projection tombstone must be an object")
    return document


def _observe(spark, payload: dict[str, Any], table_identifier: str) -> dict[str, Any]:
    if not _table_exists(spark, table_identifier):
        tombstone = _read_tombstone(spark, payload)
        receipt = (
            {
                field: tombstone.get(field)
                for field in _RECEIPT_SUMMARY_KEYS
            }
            if tombstone
            else _missing_receipt()
        )
        return {
            "target_exists": False,
            "content_sha256": None,
            "row_count": 0,
            "snapshot_id": None,
            "deleted_snapshot_id": (int(tombstone["deleted_snapshot_id"]) if tombstone else None),
            "drop_evidence_sha256": (str(tombstone["drop_evidence_sha256"]) if tombstone else None),
            "tombstone_plan_sha256": (str(tombstone["plan_sha256"]) if tombstone else None),
            "tombstone_idempotency_key": (str(tombstone["idempotency_key"]) if tombstone else None),
            **receipt,
        }
    rows = [
        row.asDict(recursive=True)
        for row in spark.table(table_identifier).orderBy("feature_index").collect()
    ]
    if not rows:
        raise RuntimeError("registered Iceberg table exists without customer rows")
    snapshot_id, summary = _current_snapshot(spark, table_identifier)
    return {
        "target_exists": True,
        "content_sha256": canonical_json_fingerprint(rows),
        "row_count": len(rows),
        "snapshot_id": snapshot_id,
        "deleted_snapshot_id": None,
        "drop_evidence_sha256": None,
        "tombstone_plan_sha256": None,
        "tombstone_idempotency_key": None,
        **_summary_receipt(summary),
    }


def _rebuild(spark, payload: dict[str, Any], table_identifier: str) -> dict[str, Any]:
    from pyspark.sql.types import LongType, StringType, StructField, StructType

    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("rebuild requires non-empty normalized customer rows")
    schema = StructType(
        [
            StructField("feature_index", LongType(), False),
            StructField("feature_id", StringType(), False),
            StructField("parcel_id", StringType(), False),
            StructField("geometry_json", StringType(), False),
            StructField("properties_json", StringType(), False),
            StructField("feature_sha256", StringType(), False),
        ]
    )
    catalog, namespace, _, _, _, _ = _validated_target(payload)
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {catalog}.{namespace}")
    frame = spark.createDataFrame(records, schema=schema).orderBy("feature_index")
    receipt_sha256 = _receipt_sha256(payload, action="rebuild")
    receipt_properties = {
        _RECEIPT_SUMMARY_KEYS["provider_receipt_schema"]: _RECEIPT_SCHEMA,
        _RECEIPT_SUMMARY_KEYS["provider_receipt_action"]: "rebuild",
        _RECEIPT_SUMMARY_KEYS["provider_receipt_plan_sha256"]: str(payload["plan_sha256"]),
        _RECEIPT_SUMMARY_KEYS["provider_receipt_idempotency_key"]: str(
            payload["idempotency_key"]
        ),
        _RECEIPT_SUMMARY_KEYS["provider_receipt_sha256"]: receipt_sha256,
    }
    writer = (
        frame.writeTo(table_identifier)
        .using("iceberg")
        .tableProperty("format-version", "2")
        .tableProperty("gda.plan_sha256", str(payload.get("plan_sha256") or ""))
        .tableProperty("gda.idempotency_key", str(payload.get("idempotency_key") or ""))
        .tableProperty(
            "gda.artifact_sha256",
            str((payload.get("target") or {}).get("artifact_sha256") or ""),
        )
    )
    for key, value in receipt_properties.items():
        writer = writer.option(f"snapshot-property.{key}", value)
    if _table_exists(spark, table_identifier):
        writer.createOrReplace()
    else:
        writer.create()
    return _observe(spark, payload, table_identifier)


def _drop(spark, payload: dict[str, Any], table_identifier: str) -> dict[str, Any]:
    before = _observe(spark, payload, table_identifier)
    if not before["target_exists"]:
        return before
    deleted_snapshot_id = int(before["snapshot_id"])
    drop_evidence_sha256 = lakehouse_projection_drop_evidence_sha256(
        table_identifier=table_identifier,
        deleted_snapshot_id=deleted_snapshot_id,
        plan_sha256=str(payload.get("plan_sha256") or ""),
        idempotency_key=str(payload.get("idempotency_key") or ""),
    )
    receipt_sha256 = _receipt_sha256(
        payload,
        action="delete",
        deleted_snapshot_id=deleted_snapshot_id,
        drop_evidence_sha256=drop_evidence_sha256,
    )
    tombstone = {
        "schema": "gda.lakehouse-projection-tombstone.v1",
        "table_identifier": table_identifier,
        "deleted_snapshot_id": deleted_snapshot_id,
        "drop_evidence_sha256": drop_evidence_sha256,
        "plan_sha256": payload.get("plan_sha256"),
        "idempotency_key": payload.get("idempotency_key"),
        "provider_receipt_schema": _RECEIPT_SCHEMA,
        "provider_receipt_action": "delete",
        "provider_receipt_plan_sha256": payload.get("plan_sha256"),
        "provider_receipt_idempotency_key": payload.get("idempotency_key"),
        "provider_receipt_sha256": receipt_sha256,
    }
    _write_tombstone(spark, payload, tombstone)
    spark.sql(f"DROP TABLE {table_identifier} PURGE")
    after = _observe(spark, payload, table_identifier)
    if after["target_exists"]:
        raise RuntimeError("Iceberg table still exists after DROP TABLE PURGE")
    return after


def run(payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action") or "")
    if action not in {"observe", "rebuild", "delete"}:
        raise ValueError("unsupported lakehouse projection action")
    catalog, namespace, table, _, _, _ = _validated_target(payload)
    table_identifier = f"{catalog}.{namespace}.{table}"
    spark = _spark_session(payload)
    try:
        spark.sparkContext.setLogLevel("WARN")
        if action == "observe":
            return _observe(spark, payload, table_identifier)
        if action == "rebuild":
            return _rebuild(spark, payload, table_identifier)
        return _drop(spark, payload, table_identifier)
    finally:
        spark.stop()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.request.read_text(encoding="utf-8"))
    result = run(payload)
    args.result.write_text(
        json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
