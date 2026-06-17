"""Optional S3/MinIO adapter for MMFE STAC item publishing."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import quote


def build_s3_stac_executor(
    *,
    endpoint_url: str | None = None,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
    region_name: str | None = None,
    bucket: str | None = None,
    catalog_uri: str | None = None,
):
    """Build a STAC executor backed by S3/MinIO via boto3.

    boto3 is imported only when the executor runs so MMFE core imports remain
    usable in environments without cloud-storage dependencies.
    """

    def executor(payload: dict[str, Any]) -> dict[str, Any]:
        return publish_stac_payload_to_s3(
            payload,
            endpoint_url=endpoint_url,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            region_name=region_name,
            bucket=bucket,
            catalog_uri=catalog_uri,
        )

    return executor


def build_s3_static_stac_catalog_executor(
    *,
    endpoint_url: str | None = None,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
    region_name: str | None = None,
    bucket: str | None = None,
    catalog_uri: str | None = None,
):
    """Build an executor that writes static STAC catalog/collection indexes."""

    def executor(payload: dict[str, Any]) -> dict[str, Any]:
        return publish_static_stac_catalog_to_s3(
            payload,
            endpoint_url=endpoint_url,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            region_name=region_name,
            bucket=bucket,
            catalog_uri=catalog_uri,
        )

    return executor


def publish_stac_payload_to_s3(
    payload: dict[str, Any],
    *,
    endpoint_url: str | None = None,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
    region_name: str | None = None,
    bucket: str | None = None,
    catalog_uri: str | None = None,
) -> dict[str, Any]:
    """Write one STAC item JSON to an S3-compatible object store."""

    try:
        import boto3
        from botocore.config import Config as BotoConfig
    except Exception as exc:  # pragma: no cover - exercised when optional deps absent.
        raise RuntimeError("S3 STAC publishing requires optional dependency: boto3") from exc

    item = payload.get("item")
    if not isinstance(item, dict):
        raise ValueError("payload.item must be an object")
    collection = str(payload.get("collection") or item.get("collection") or "")
    item_id = str(payload.get("item_id") or item.get("id") or "")
    if not collection:
        raise ValueError("payload.collection is required")
    if not item_id:
        raise ValueError("payload.item_id is required")

    target_catalog_uri = catalog_uri or str(payload.get("catalog_uri") or "")
    target_bucket, key_prefix = _catalog_target(target_catalog_uri, bucket=bucket)
    object_key = "/".join(part.strip("/") for part in [key_prefix, collection, f"{item_id}.json"] if part)

    endpoint = endpoint_url or os.environ.get("AWS_ENDPOINT_URL") or None
    client_kwargs = {
        "aws_access_key_id": access_key_id or os.environ.get("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": secret_access_key or os.environ.get("AWS_SECRET_ACCESS_KEY"),
        "region_name": region_name or os.environ.get("AWS_REGION", "us-east-1"),
    }
    if endpoint:
        client_kwargs["endpoint_url"] = endpoint
        client_kwargs["config"] = BotoConfig(s3={"addressing_style": "path"})

    client = boto3.client("s3", **client_kwargs)
    body = json.dumps(item, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    client.put_object(
        Bucket=target_bucket,
        Key=object_key,
        Body=body,
        ContentType="application/geo+json",
    )

    item_href = f"s3://{target_bucket}/{object_key}"
    return {
        "published": True,
        "published_count": 1,
        "target": "stac",
        "collection": collection,
        "item_id": item_id,
        "bucket": target_bucket,
        "key": object_key,
        "item_href": item_href,
        "endpoint_url": endpoint or "",
        "bytes_written": len(body),
        "console_hint": _console_hint(endpoint, target_bucket, object_key),
    }


def publish_static_stac_catalog_to_s3(
    payload: dict[str, Any],
    *,
    endpoint_url: str | None = None,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
    region_name: str | None = None,
    bucket: str | None = None,
    catalog_uri: str | None = None,
) -> dict[str, Any]:
    """Write static STAC ``catalog.json`` and collection indexes to S3/MinIO."""

    try:
        import boto3
        from botocore.config import Config as BotoConfig
    except Exception as exc:  # pragma: no cover - exercised when optional deps absent.
        raise RuntimeError("S3 static STAC catalog publishing requires optional dependency: boto3") from exc

    target_catalog_uri = catalog_uri or str(payload.get("catalog_uri") or "")
    target_bucket, key_prefix = _catalog_target(target_catalog_uri, bucket=bucket)
    documents = build_static_stac_catalog_documents(
        catalog_uri=f"s3://{target_bucket}/{key_prefix}".rstrip("/"),
        collections=list(payload.get("collections") or []),
        catalog_id=str(payload.get("catalog_id") or "mmfe-static-catalog"),
        description=str(payload.get("description") or "MMFE static STAC catalog"),
        title=str(payload.get("title") or ""),
    )

    endpoint = endpoint_url or os.environ.get("AWS_ENDPOINT_URL") or None
    client_kwargs = {
        "aws_access_key_id": access_key_id or os.environ.get("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": secret_access_key or os.environ.get("AWS_SECRET_ACCESS_KEY"),
        "region_name": region_name or os.environ.get("AWS_REGION", "us-east-1"),
    }
    if endpoint:
        client_kwargs["endpoint_url"] = endpoint
        client_kwargs["config"] = BotoConfig(s3={"addressing_style": "path"})

    client = boto3.client("s3", **client_kwargs)
    catalog_key = "/".join(part.strip("/") for part in [key_prefix, "catalog.json"] if part)
    catalog_body = _json_body(documents["catalog"])
    client.put_object(Bucket=target_bucket, Key=catalog_key, Body=catalog_body, ContentType="application/json")

    collections = []
    bytes_written = len(catalog_body)
    for collection_id, collection_doc in documents["collections"].items():
        collection_key = "/".join(part.strip("/") for part in [key_prefix, collection_id, "collection.json"] if part)
        collection_body = _json_body(collection_doc)
        client.put_object(
            Bucket=target_bucket,
            Key=collection_key,
            Body=collection_body,
            ContentType="application/json",
        )
        bytes_written += len(collection_body)
        collections.append(
            {
                "collection": collection_id,
                "key": collection_key,
                "href": f"s3://{target_bucket}/{collection_key}",
                "item_count": len([link for link in collection_doc.get("links", []) if link.get("rel") == "item"]),
                "bytes_written": len(collection_body),
            }
        )

    return {
        "published": True,
        "published_count": 1 + len(collections),
        "target": "stac_static_catalog",
        "bucket": target_bucket,
        "catalog_key": catalog_key,
        "catalog_href": f"s3://{target_bucket}/{catalog_key}",
        "collections": collections,
        "endpoint_url": endpoint or "",
        "bytes_written": bytes_written,
        "console_hint": _console_hint(endpoint, target_bucket, catalog_key),
    }


def build_static_stac_catalog_documents(
    *,
    catalog_uri: str,
    collections: list[dict[str, Any]],
    catalog_id: str = "mmfe-static-catalog",
    description: str = "MMFE static STAC catalog",
    title: str = "",
) -> dict[str, Any]:
    """Build dependency-free static STAC catalog and collection documents."""

    if not catalog_uri:
        raise ValueError("catalog_uri is required")
    normalized = [_normalize_collection_spec(collection) for collection in collections]
    catalog_href = _join_uri(catalog_uri, "catalog.json")
    catalog_links = [
        {"rel": "self", "href": catalog_href, "type": "application/json"},
        {"rel": "root", "href": catalog_href, "type": "application/json"},
    ]
    collection_docs: dict[str, dict[str, Any]] = {}
    for collection in normalized:
        collection_id = collection["id"]
        collection_href = _join_uri(catalog_uri, collection_id, "collection.json")
        catalog_links.append(
            {
                "rel": "child",
                "href": collection_href,
                "type": "application/json",
                "title": collection.get("title") or collection_id,
            }
        )
        item_links = [
            {
                "rel": "item",
                "href": item["href"],
                "type": "application/geo+json",
                "title": item["id"],
            }
            for item in collection["items"]
        ]
        collection_docs[collection_id] = {
            "type": "Collection",
            "stac_version": "1.0.0",
            "id": collection_id,
            "title": collection.get("title") or collection_id,
            "description": collection.get("description") or f"MMFE STAC collection {collection_id}",
            "license": collection.get("license") or "other",
            "extent": {
                "spatial": {"bbox": [_collection_bbox(collection["items"])]},
                "temporal": {"interval": [_collection_interval(collection["items"])]},
            },
            "links": [
                {"rel": "self", "href": collection_href, "type": "application/json"},
                {"rel": "root", "href": catalog_href, "type": "application/json"},
                {"rel": "parent", "href": catalog_href, "type": "application/json"},
                *item_links,
            ],
        }

    catalog = {
        "type": "Catalog",
        "stac_version": "1.0.0",
        "id": catalog_id,
        "description": description,
        "links": catalog_links,
    }
    if title:
        catalog["title"] = title
    return {"catalog": catalog, "collections": collection_docs}


def _catalog_target(catalog_uri: str, *, bucket: str | None = None) -> tuple[str, str]:
    if catalog_uri.startswith("s3://"):
        rest = catalog_uri[5:]
        parts = rest.split("/", 1)
        parsed_bucket = parts[0]
        prefix = parts[1] if len(parts) > 1 else ""
        if not parsed_bucket:
            raise ValueError("catalog_uri bucket is required")
        return parsed_bucket, prefix
    target_bucket = bucket or os.environ.get("MMFE_LAKEHOUSE_BUCKET") or os.environ.get("AWS_S3_BUCKET")
    if not target_bucket:
        raise ValueError("catalog_uri must be s3://... or bucket/MMFE_LAKEHOUSE_BUCKET must be configured")
    prefix = catalog_uri.strip("/") if catalog_uri else "catalog/stac"
    return target_bucket, prefix


def _normalize_collection_spec(collection: dict[str, Any]) -> dict[str, Any]:
    collection_id = str(collection.get("id") or collection.get("collection") or "")
    if not collection_id:
        raise ValueError("collection id is required")
    items = [_normalize_item_link(item) for item in list(collection.get("items") or [])]
    return {
        "id": collection_id,
        "title": str(collection.get("title") or collection_id),
        "description": str(collection.get("description") or ""),
        "license": str(collection.get("license") or "other"),
        "items": items,
    }


def _normalize_item_link(item: dict[str, Any]) -> dict[str, Any]:
    stac_item = item.get("item") if isinstance(item.get("item"), dict) else item
    item_id = str(item.get("id") or item.get("item_id") or stac_item.get("id") or "")
    href = str(item.get("href") or item.get("item_href") or "")
    if not item_id:
        raise ValueError("STAC item id is required for collection index")
    if not href:
        raise ValueError(f"STAC item href is required for collection index: {item_id}")
    properties = stac_item.get("properties") if isinstance(stac_item.get("properties"), dict) else {}
    return {
        "id": item_id,
        "href": href,
        "bbox": list(item.get("bbox") or stac_item.get("bbox") or []),
        "datetime": item.get("datetime") or properties.get("datetime"),
    }


def _collection_bbox(items: list[dict[str, Any]]) -> list[float]:
    bboxes = [item["bbox"] for item in items if _valid_bbox(item.get("bbox"))]
    if not bboxes:
        return [-180.0, -90.0, 180.0, 90.0]
    return [
        min(float(bbox[0]) for bbox in bboxes),
        min(float(bbox[1]) for bbox in bboxes),
        max(float(bbox[2]) for bbox in bboxes),
        max(float(bbox[3]) for bbox in bboxes),
    ]


def _collection_interval(items: list[dict[str, Any]]) -> list[str | None]:
    values = sorted(str(item.get("datetime")) for item in items if item.get("datetime"))
    if not values:
        return [None, None]
    return [values[0], values[-1]]


def _valid_bbox(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 4:
        return False
    try:
        [float(part) for part in value]
    except (TypeError, ValueError):
        return False
    return True


def _join_uri(base_uri: str, *parts: str) -> str:
    base = base_uri.rstrip("/")
    clean_parts = [str(part).strip("/") for part in parts if str(part).strip("/")]
    if not clean_parts:
        return base
    return "/".join([base, *clean_parts])


def _json_body(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")


def _console_hint(endpoint_url: str | None, bucket: str, key: str) -> str:
    if not endpoint_url:
        return ""
    base = endpoint_url.replace(":9000", ":9001").rstrip("/")
    return f"{base}/browser/{quote(bucket)}/{quote(key)}"
