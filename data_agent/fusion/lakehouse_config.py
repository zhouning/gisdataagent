"""Local S3/MinIO lakehouse configuration helpers for MMFE."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Mapping
from urllib.parse import urlparse


INFRASTRUCTURE_PREFLIGHT_SCHEMA = "mmfe.infrastructure_preflight.v1"
DEFAULT_LAKEHOUSE_BUCKET = "gis-agent-lakehouse"
DEFAULT_UPLOADS_BUCKET = "gis-agent-uploads"
DEFAULT_ICEBERG_CATALOG = "local"
DEFAULT_ICEBERG_NAMESPACE = "gis.fusion"
DEFAULT_ICEBERG_TABLE = "semantic_products"
LOCAL_DEFAULT_ACCESS_KEY = "minio_admin"
LOCAL_DEFAULT_SECRET_KEY = "local_dev_minio_secret"


def build_lakehouse_object_store_config(env: Mapping[str, str] | None = None) -> dict:
    """Build an MMFE lakehouse object-store config from environment variables."""
    values = env or os.environ
    lakehouse_bucket = _get(values, "MMFE_LAKEHOUSE_BUCKET", DEFAULT_LAKEHOUSE_BUCKET)
    uploads_bucket = _get(values, "AWS_S3_BUCKET", DEFAULT_UPLOADS_BUCKET)
    endpoint_url = _get(values, "AWS_ENDPOINT_URL", "http://minio:9000")
    access_key = _get(values, "AWS_ACCESS_KEY_ID", "minio_admin")
    secret_key = _get(values, "AWS_SECRET_ACCESS_KEY", "local_dev_minio_secret")
    region = _get(values, "AWS_REGION", "us-east-1")
    warehouse_uri = _get(values, "MMFE_LAKEHOUSE_WAREHOUSE_URI", f"s3://{lakehouse_bucket}/warehouse")
    stac_catalog_uri = _get(values, "MMFE_STAC_CATALOG_URI", f"s3://{lakehouse_bucket}/catalog/stac")

    config = {
        "object_store": "s3",
        "provider": _get(values, "CLOUD_STORAGE_PROVIDER", "aws"),
        "endpoint_url": endpoint_url,
        "region": region,
        "uploads_bucket": uploads_bucket,
        "lakehouse_bucket": lakehouse_bucket,
        "warehouse_uri": warehouse_uri,
        "stac_catalog_uri": stac_catalog_uri,
        "path_style_access": True,
        "s3_uri_examples": {
            "warehouse": warehouse_uri,
            "stac_catalog": stac_catalog_uri,
            "curated_prefix": f"s3://{lakehouse_bucket}/curated/mmfe",
            "raw_prefix": f"s3://{lakehouse_bucket}/raw",
        },
        "credentials_configured": bool(access_key and secret_key),
    }
    if access_key:
        config["access_key_id"] = access_key
    if secret_key:
        config["secret_access_key"] = secret_key
    return config


def build_default_iceberg_publish_config(env: Mapping[str, str] | None = None) -> dict:
    """Return default Iceberg publish config for local MMFE lakehouse planning."""
    values = env or os.environ
    object_store = build_lakehouse_object_store_config(values)
    return {
        "catalog": _get(values, "MMFE_ICEBERG_CATALOG", DEFAULT_ICEBERG_CATALOG),
        "namespace": _get(values, "MMFE_ICEBERG_NAMESPACE", DEFAULT_ICEBERG_NAMESPACE),
        "table": _get(values, "MMFE_ICEBERG_TABLE", DEFAULT_ICEBERG_TABLE),
        "warehouse_uri": object_store["warehouse_uri"],
        "object_store": object_store["object_store"],
        "spatial_engine": _get(values, "MMFE_ICEBERG_SPATIAL_ENGINE", "sedona"),
        "partition_by": _parse_csv(_get(values, "MMFE_ICEBERG_PARTITION_BY", "product_id")),
        "metadata": {
            "object_store_endpoint": object_store["endpoint_url"],
            "lakehouse_bucket": object_store["lakehouse_bucket"],
            "path_style_access": object_store["path_style_access"],
        },
    }


def build_default_stac_publish_config(env: Mapping[str, str] | None = None) -> dict:
    """Return default STAC catalog config for local MMFE lakehouse planning."""
    values = env or os.environ
    object_store = build_lakehouse_object_store_config(values)
    return {
        "collection": _get(values, "MMFE_STAC_COLLECTION", "mmfe-fusion-products"),
        "catalog_uri": object_store["stac_catalog_uri"],
        "metadata": {
            "object_store_endpoint": object_store["endpoint_url"],
            "lakehouse_bucket": object_store["lakehouse_bucket"],
        },
    }


def build_sedona_s3a_spark_conf(env: Mapping[str, str] | None = None) -> dict:
    """Build Spark/Sedona S3A settings for MinIO or another S3-compatible store."""
    object_store = build_lakehouse_object_store_config(env)
    conf = {
        "spark.hadoop.fs.s3a.endpoint": object_store["endpoint_url"],
        "spark.hadoop.fs.s3a.path.style.access": "true",
        "spark.hadoop.fs.s3a.connection.ssl.enabled": _ssl_enabled(object_store["endpoint_url"]),
        "spark.hadoop.fs.s3a.impl": "org.apache.hadoop.fs.s3a.S3AFileSystem",
        "spark.hadoop.fs.s3a.aws.credentials.provider": (
            "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider"
        ),
    }
    if object_store.get("access_key_id"):
        conf["spark.hadoop.fs.s3a.access.key"] = object_store["access_key_id"]
    if object_store.get("secret_access_key"):
        conf["spark.hadoop.fs.s3a.secret.key"] = object_store["secret_access_key"]
    return conf


def build_lakehouse_publish_defaults(env: Mapping[str, str] | None = None) -> dict:
    """Return object-store, Iceberg, STAC, and Spark defaults as one payload."""
    values = env or os.environ
    return {
        "object_store": build_lakehouse_object_store_config(values),
        "iceberg": build_default_iceberg_publish_config(values),
        "stac": build_default_stac_publish_config(values),
        "sedona_spark_conf": build_sedona_s3a_spark_conf(values),
    }


def build_lakehouse_infrastructure_preflight(
    config: dict | None = None,
    *,
    environment: str = "development",
    timestamp: str | None = None,
) -> dict:
    """Build a dependency-free infrastructure preflight report for MMFE lakehouse publishing."""
    defaults = dict(config or build_lakehouse_publish_defaults())
    object_store = defaults.get("object_store") if isinstance(defaults.get("object_store"), dict) else {}
    iceberg = defaults.get("iceberg") if isinstance(defaults.get("iceberg"), dict) else {}
    stac = defaults.get("stac") if isinstance(defaults.get("stac"), dict) else {}
    spark_conf = defaults.get("sedona_spark_conf") if isinstance(defaults.get("sedona_spark_conf"), dict) else {}
    env_name = str(environment or "development").strip().lower()
    checks = [
        _preflight_check(
            "object_store_endpoint",
            "pass" if _valid_http_uri(object_store.get("endpoint_url")) else "fail",
            "object-store endpoint must be an http(s) URI",
            {"endpoint_url": object_store.get("endpoint_url", "")},
            severity="critical",
        ),
        _preflight_check(
            "object_store_buckets",
            "pass" if object_store.get("lakehouse_bucket") and object_store.get("uploads_bucket") else "fail",
            "lakehouse and uploads buckets must be configured",
            {
                "lakehouse_bucket": object_store.get("lakehouse_bucket", ""),
                "uploads_bucket": object_store.get("uploads_bucket", ""),
            },
            severity="critical",
        ),
        _preflight_check(
            "object_store_credentials",
            "pass" if object_store.get("credentials_configured") else "fail",
            "object-store credentials must be configured before publishing",
            {
                "credentials_configured": bool(object_store.get("credentials_configured")),
                "access_key_id": _redact_secret(object_store.get("access_key_id", "")),
                "secret_access_key": _redact_secret(object_store.get("secret_access_key", "")),
            },
            severity="critical",
        ),
        _preflight_check(
            "iceberg_warehouse",
            "pass" if _valid_s3_uri(iceberg.get("warehouse_uri")) else "fail",
            "Iceberg warehouse URI must be an s3:// URI",
            {"warehouse_uri": iceberg.get("warehouse_uri", "")},
            severity="critical",
        ),
        _preflight_check(
            "iceberg_identifier",
            "pass" if iceberg.get("catalog") and iceberg.get("namespace") and iceberg.get("table") else "fail",
            "Iceberg catalog, namespace, and table must be configured",
            {
                "catalog": iceberg.get("catalog", ""),
                "namespace": iceberg.get("namespace", ""),
                "table": iceberg.get("table", ""),
            },
            severity="critical",
        ),
        _preflight_check(
            "stac_catalog",
            "pass" if stac.get("collection") and _valid_s3_uri(stac.get("catalog_uri")) else "fail",
            "STAC collection and catalog URI must be configured",
            {
                "collection": stac.get("collection", ""),
                "catalog_uri": stac.get("catalog_uri", ""),
            },
            severity="high",
        ),
        _preflight_check(
            "spark_s3a",
            "pass" if _spark_s3a_core_ready(spark_conf) else "fail",
            "Spark S3A configuration must include endpoint, implementation, and credentials provider",
            {"configured_keys": sorted(spark_conf.keys())},
            severity="high",
        ),
        _preflight_check(
            "spark_s3a_credentials",
            "pass" if _spark_s3a_credentials_ready(spark_conf) else "fail",
            "Spark S3A simple credentials provider must include access and secret keys",
            {
                "credentials_provider": spark_conf.get("spark.hadoop.fs.s3a.aws.credentials.provider", ""),
                "access_key_configured": bool(spark_conf.get("spark.hadoop.fs.s3a.access.key")),
                "secret_key_configured": bool(spark_conf.get("spark.hadoop.fs.s3a.secret.key")),
            },
            severity="high",
        ),
    ]
    checks.extend(_consistency_preflight_checks(object_store, iceberg, stac, spark_conf))
    checks.extend(_environment_preflight_checks(env_name, object_store))
    summary = _preflight_summary(checks)
    return {
        "schema": INFRASTRUCTURE_PREFLIGHT_SCHEMA,
        "created_at": timestamp or datetime.now(timezone.utc).isoformat(),
        "environment": env_name,
        "valid": summary["fail_count"] == 0,
        "summary": summary,
        "checks": checks,
        "sanitized_config": _sanitized_lakehouse_config(defaults),
        "config_fingerprint": _lakehouse_config_fingerprint(defaults),
    }


def validate_lakehouse_infrastructure_preflight(payload: dict) -> dict:
    """Validate the MMFE lakehouse infrastructure preflight contract surface."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be a JSON object"]}
    if payload.get("schema") != INFRASTRUCTURE_PREFLIGHT_SCHEMA:
        errors.append(f"schema must be {INFRASTRUCTURE_PREFLIGHT_SCHEMA}")
    if not isinstance(payload.get("summary"), dict):
        errors.append("summary must be an object")
    if not isinstance(payload.get("checks"), list):
        errors.append("checks must be a list")
    if not isinstance(payload.get("sanitized_config"), dict):
        errors.append("sanitized_config must be an object")
    if not isinstance(payload.get("config_fingerprint"), dict):
        errors.append("config_fingerprint must be an object")
    if not isinstance(payload.get("valid"), bool):
        errors.append("valid must be boolean")
    return {"valid": not errors, "errors": errors}


def _get(values: Mapping[str, str], key: str, default: str) -> str:
    value = values.get(key)
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip()


def _parse_csv(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _ssl_enabled(endpoint_url: str) -> str:
    return "true" if str(endpoint_url).lower().startswith("https://") else "false"


def _preflight_check(check_id: str, status: str, message: str, evidence: dict, *, severity: str) -> dict:
    return {
        "check_id": check_id,
        "status": status,
        "severity": severity,
        "message": message,
        "evidence": evidence,
    }


def _environment_preflight_checks(environment: str, object_store: dict) -> list[dict]:
    endpoint = str(object_store.get("endpoint_url") or "")
    local_endpoint = _is_local_endpoint(endpoint)
    default_credentials = (
        object_store.get("access_key_id") == LOCAL_DEFAULT_ACCESS_KEY
        or object_store.get("secret_access_key") == LOCAL_DEFAULT_SECRET_KEY
    )
    if environment == "production":
        return [
            _preflight_check(
                "production_endpoint",
                "fail" if local_endpoint else "pass",
                "production object-store endpoint must not point to localhost or the local minio service",
                {"endpoint_url": endpoint},
                severity="critical",
            ),
            _preflight_check(
                "production_credentials",
                "fail" if default_credentials else "pass",
                "production publishing must not use local default MinIO credentials",
                {
                    "access_key_id": _redact_secret(object_store.get("access_key_id", "")),
                    "uses_local_default_secret": bool(default_credentials),
                },
                severity="critical",
            ),
        ]
    return [
        _preflight_check(
            "development_endpoint",
            "warn" if local_endpoint else "pass",
            "development endpoint is local; this is acceptable for smoke tests but not production",
            {"endpoint_url": endpoint},
            severity="low",
        )
    ]


def _consistency_preflight_checks(
    object_store: dict,
    iceberg: dict,
    stac: dict,
    spark_conf: dict,
) -> list[dict]:
    warehouse_uri = str(iceberg.get("warehouse_uri") or "")
    object_store_warehouse_uri = str(object_store.get("warehouse_uri") or "")
    stac_catalog_uri = str(stac.get("catalog_uri") or "")
    object_store_stac_catalog_uri = str(object_store.get("stac_catalog_uri") or "")
    lakehouse_bucket = str(object_store.get("lakehouse_bucket") or "")
    warehouse_bucket = _s3_bucket(warehouse_uri)
    object_store_endpoint = str(object_store.get("endpoint_url") or "")
    spark_endpoint = str(spark_conf.get("spark.hadoop.fs.s3a.endpoint") or "")
    object_store_access_key = str(object_store.get("access_key_id") or "")
    spark_access_key = str(spark_conf.get("spark.hadoop.fs.s3a.access.key") or "")
    object_store_path_style = _bool_text(object_store.get("path_style_access"))
    spark_path_style = _bool_text(spark_conf.get("spark.hadoop.fs.s3a.path.style.access"))
    expected_ssl_enabled = _ssl_enabled(object_store_endpoint) if object_store_endpoint else ""
    spark_ssl_enabled = _bool_text(spark_conf.get("spark.hadoop.fs.s3a.connection.ssl.enabled"))

    return [
        _preflight_check(
            "iceberg_warehouse_consistency",
            "pass" if _matches_when_present(object_store_warehouse_uri, warehouse_uri) else "fail",
            "object-store warehouse URI and Iceberg warehouse URI must match when both are configured",
            {
                "object_store_warehouse_uri": object_store_warehouse_uri,
                "iceberg_warehouse_uri": warehouse_uri,
            },
            severity="high",
        ),
        _preflight_check(
            "lakehouse_bucket_consistency",
            "pass" if _matches_when_present(lakehouse_bucket, warehouse_bucket) else "fail",
            "Iceberg warehouse bucket must match the configured lakehouse bucket",
            {
                "lakehouse_bucket": lakehouse_bucket,
                "iceberg_warehouse_bucket": warehouse_bucket,
            },
            severity="high",
        ),
        _preflight_check(
            "stac_catalog_consistency",
            "pass" if _matches_when_present(object_store_stac_catalog_uri, stac_catalog_uri) else "fail",
            "object-store STAC catalog URI and STAC publish catalog URI must match when both are configured",
            {
                "object_store_stac_catalog_uri": object_store_stac_catalog_uri,
                "stac_catalog_uri": stac_catalog_uri,
            },
            severity="high",
        ),
        _preflight_check(
            "spark_endpoint_consistency",
            "pass" if _matches_when_present(object_store_endpoint, spark_endpoint) else "fail",
            "Spark S3A endpoint must match the object-store endpoint when both are configured",
            {
                "object_store_endpoint": object_store_endpoint,
                "spark_s3a_endpoint": spark_endpoint,
            },
            severity="high",
        ),
        _preflight_check(
            "spark_credentials_consistency",
            "pass" if _matches_when_present(object_store_access_key, spark_access_key) else "fail",
            "Spark S3A access key must match the object-store access key when both are configured",
            {
                "object_store_access_key": _redact_secret(object_store_access_key),
                "spark_s3a_access_key": _redact_secret(spark_access_key),
            },
            severity="high",
        ),
        _preflight_check(
            "spark_path_style_consistency",
            "pass" if _matches_when_present(object_store_path_style, spark_path_style) else "fail",
            "Spark S3A path-style access setting must match the object-store path-style setting",
            {
                "object_store_path_style_access": object_store_path_style,
                "spark_s3a_path_style_access": spark_path_style,
            },
            severity="medium",
        ),
        _preflight_check(
            "spark_ssl_consistency",
            "pass" if _matches_when_present(expected_ssl_enabled, spark_ssl_enabled) else "fail",
            "Spark S3A SSL setting must match the object-store endpoint scheme",
            {
                "object_store_endpoint": object_store_endpoint,
                "expected_spark_ssl_enabled": expected_ssl_enabled,
                "spark_s3a_ssl_enabled": spark_ssl_enabled,
            },
            severity="medium",
        ),
    ]


def _preflight_summary(checks: list[dict]) -> dict:
    return {
        "check_count": len(checks),
        "pass_count": sum(1 for check in checks if check.get("status") == "pass"),
        "warn_count": sum(1 for check in checks if check.get("status") == "warn"),
        "fail_count": sum(1 for check in checks if check.get("status") == "fail"),
        "critical_fail_count": sum(
            1 for check in checks if check.get("status") == "fail" and check.get("severity") == "critical"
        ),
    }


def _sanitized_lakehouse_config(config: dict) -> dict:
    sanitized = {}
    for key, value in config.items():
        if isinstance(value, dict):
            sanitized[key] = {
                nested_key: _redact_secret(nested_value)
                if _secret_key_name(nested_key)
                else nested_value
                for nested_key, nested_value in value.items()
            }
        else:
            sanitized[key] = value
    return sanitized


def _lakehouse_config_fingerprint(config: dict) -> dict:
    material = _lakehouse_fingerprint_material(config)
    canonical = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "algorithm": "sha256",
        "value": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "material_version": "mmfe.lakehouse_config_fingerprint.v1",
        "material": material,
    }


def _lakehouse_fingerprint_material(config: dict) -> dict:
    object_store = config.get("object_store") if isinstance(config.get("object_store"), dict) else {}
    iceberg = config.get("iceberg") if isinstance(config.get("iceberg"), dict) else {}
    stac = config.get("stac") if isinstance(config.get("stac"), dict) else {}
    spark_conf = config.get("sedona_spark_conf") if isinstance(config.get("sedona_spark_conf"), dict) else {}
    return {
        "object_store": {
            "provider": str(object_store.get("provider") or ""),
            "object_store": str(object_store.get("object_store") or ""),
            "endpoint_url": str(object_store.get("endpoint_url") or ""),
            "region": str(object_store.get("region") or ""),
            "uploads_bucket": str(object_store.get("uploads_bucket") or ""),
            "lakehouse_bucket": str(object_store.get("lakehouse_bucket") or ""),
            "warehouse_uri": str(object_store.get("warehouse_uri") or ""),
            "stac_catalog_uri": str(object_store.get("stac_catalog_uri") or ""),
            "path_style_access": _bool_text(object_store.get("path_style_access")),
            "credentials_configured": bool(object_store.get("credentials_configured")),
        },
        "iceberg": {
            "catalog": str(iceberg.get("catalog") or ""),
            "namespace": str(iceberg.get("namespace") or ""),
            "table": str(iceberg.get("table") or ""),
            "warehouse_uri": str(iceberg.get("warehouse_uri") or ""),
            "object_store": str(iceberg.get("object_store") or ""),
            "spatial_engine": str(iceberg.get("spatial_engine") or ""),
            "partition_by": list(iceberg.get("partition_by") or []),
        },
        "stac": {
            "collection": str(stac.get("collection") or ""),
            "catalog_uri": str(stac.get("catalog_uri") or ""),
        },
        "sedona_spark_conf": {
            "spark.hadoop.fs.s3a.endpoint": str(spark_conf.get("spark.hadoop.fs.s3a.endpoint") or ""),
            "spark.hadoop.fs.s3a.path.style.access": _bool_text(
                spark_conf.get("spark.hadoop.fs.s3a.path.style.access")
            ),
            "spark.hadoop.fs.s3a.connection.ssl.enabled": _bool_text(
                spark_conf.get("spark.hadoop.fs.s3a.connection.ssl.enabled")
            ),
            "spark.hadoop.fs.s3a.impl": str(spark_conf.get("spark.hadoop.fs.s3a.impl") or ""),
            "spark.hadoop.fs.s3a.aws.credentials.provider": str(
                spark_conf.get("spark.hadoop.fs.s3a.aws.credentials.provider") or ""
            ),
        },
    }


def _secret_key_name(key: str) -> bool:
    text = str(key).lower()
    return "secret" in text or "access_key" in text or "password" in text or "token" in text


def _redact_secret(value: object) -> object:
    if value is None:
        return ""
    text = str(value)
    if not text:
        return ""
    if len(text) <= 4:
        return "***"
    return f"{text[:2]}***{text[-2:]}"


def _valid_http_uri(value: object) -> bool:
    parsed = urlparse(str(value or ""))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _valid_s3_uri(value: object) -> bool:
    parsed = urlparse(str(value or ""))
    return parsed.scheme == "s3" and bool(parsed.netloc)


def _s3_bucket(value: object) -> str:
    parsed = urlparse(str(value or ""))
    if parsed.scheme != "s3":
        return ""
    return parsed.netloc


def _matches_when_present(left: object, right: object) -> bool:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    return not left_text or not right_text or left_text == right_text


def _spark_s3a_core_ready(conf: dict) -> bool:
    required = (
        "spark.hadoop.fs.s3a.endpoint",
        "spark.hadoop.fs.s3a.impl",
        "spark.hadoop.fs.s3a.aws.credentials.provider",
    )
    return all(conf.get(key) for key in required)


def _spark_s3a_credentials_ready(conf: dict) -> bool:
    provider = str(conf.get("spark.hadoop.fs.s3a.aws.credentials.provider") or "")
    if provider.endswith("SimpleAWSCredentialsProvider"):
        return bool(conf.get("spark.hadoop.fs.s3a.access.key") and conf.get("spark.hadoop.fs.s3a.secret.key"))
    return bool(provider)


def _bool_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return "true"
    if text in {"0", "false", "no", "n", "off"}:
        return "false"
    return text


def _is_local_endpoint(endpoint_url: str) -> bool:
    host = urlparse(str(endpoint_url or "")).hostname or ""
    return host in {"localhost", "127.0.0.1", "0.0.0.0", "minio"}
