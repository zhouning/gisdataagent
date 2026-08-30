from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError

from data_agent.data_architecture_ledger import ProviderObjectState
from data_agent.object_storage_architecture_harvester import (
    ObjectStorageArchitectureError,
    ObjectStorageArchitectureTarget,
    harvest_object_storage_architecture,
)


class _Body:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, amount: int = -1) -> bytes:
        return self._payload if amount < 0 else self._payload[:amount]

    def close(self) -> None:
        return None


class _FakeS3:
    def __init__(self, payload: bytes, *, revision: str = "1") -> None:
        self.payload = payload
        self.revision = revision
        self.present = True
        self.denied = False

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        del Bucket, Key
        if self.denied:
            raise ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "denied"}},
                "HeadObject",
            )
        if not self.present:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
                "HeadObject",
            )
        return {
            "ContentLength": len(self.payload),
            "ETag": f'"etag-{self.revision}"',
            "VersionId": self.revision,
            "ContentType": "application/geo+json",
        }

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        del Bucket, Key
        return {"Body": _Body(self.payload)}


def _target() -> ObjectStorageArchitectureTarget:
    return ObjectStorageArchitectureTarget(
        tenant_id="object-storage-harvest-test",
        resource_version_id=uuid4(),
        provider_ref="local-minio",
        bucket="lakehouse",
        key="roads/v1.json",
        snapshot_ref="product:v1",
        content_checksum="a" * 64,
        schema_format="geojson",
    )


def _geojson(*, include_height: bool = False, height: int = 1) -> bytes:
    features = [
        {
            "type": "Feature",
            "properties": {"road_id": "r-1", **({"height": height} if include_height else {})},
            "geometry": {"type": "Point", "coordinates": [106.5, 29.5]},
        },
        {
            "type": "Feature",
            "properties": {"road_id": "r-2", **({"height": height + 1} if include_height else {})},
            "geometry": {"type": "Point", "coordinates": [106.6, 29.6]},
        },
    ]
    return (json.dumps({"type": "FeatureCollection", "features": features}) + "\n").encode()


def test_object_harvest_is_exact_and_replayable() -> None:
    client = _FakeS3(_geojson())
    target = _target()
    observed_at = datetime(2026, 8, 23, 13, tzinfo=UTC)

    first = harvest_object_storage_architecture(
        client,
        target,
        observed_by="workload:object-harvester",
        observed_at=observed_at,
    )
    replay = harvest_object_storage_architecture(
        client,
        target,
        observed_by="workload:object-harvester",
        observed_at=observed_at,
    )

    assert first.observation.object_state is ProviderObjectState.PRESENT
    assert first.schema_snapshot is not None
    assert first.schema_snapshot.record_count == 2
    assert {field.name for field in first.schema_snapshot.fields} == {
        "geometry.coordinates",
        "geometry.type",
        "properties.road_id",
        "type",
    }
    assert first.observation == replay.observation
    assert first.schema_snapshot == replay.schema_snapshot


def test_object_revision_and_schema_drift_are_separated() -> None:
    client = _FakeS3(_geojson())
    target = _target()
    baseline = harvest_object_storage_architecture(
        client,
        target,
        observed_by="workload:object-harvester",
        observed_at=datetime(2026, 8, 23, 13, tzinfo=UTC),
    )

    client.payload = _geojson(include_height=True)
    client.revision = "2"
    additive = harvest_object_storage_architecture(
        client,
        target,
        observed_by="workload:object-harvester",
        observed_at=datetime(2026, 8, 23, 13, 1, tzinfo=UTC),
    )
    client.payload = _geojson(include_height=True, height=10)
    client.revision = "3"
    same_schema = harvest_object_storage_architecture(
        client,
        target,
        observed_by="workload:object-harvester",
        observed_at=datetime(2026, 8, 23, 13, 2, tzinfo=UTC),
    )

    assert baseline.observation.schema_content_sha256 != additive.observation.schema_content_sha256
    assert baseline.observation.physical_location_sha256 != (
        additive.observation.physical_location_sha256
    )
    assert additive.observation.schema_content_sha256 == (
        same_schema.observation.schema_content_sha256
    )
    assert additive.observation.physical_location_sha256 != (
        same_schema.observation.physical_location_sha256
    )


def test_missing_object_is_tombstone_but_provider_error_is_not() -> None:
    client = _FakeS3(_geojson())
    client.present = False
    tombstone = harvest_object_storage_architecture(
        client,
        _target(),
        observed_by="workload:object-harvester",
        observed_at=datetime(2026, 8, 23, 13, tzinfo=UTC),
    )
    assert tombstone.observation.object_state is ProviderObjectState.TOMBSTONED
    assert tombstone.schema_snapshot is None

    client.present = True
    client.denied = True
    with pytest.raises(ObjectStorageArchitectureError, match="HEAD failed"):
        harvest_object_storage_architecture(
            client,
            _target(),
            observed_by="workload:object-harvester",
            observed_at=datetime(2026, 8, 23, 13, tzinfo=UTC),
        )


def test_oversized_object_fails_closed_instead_of_sampling() -> None:
    client = _FakeS3(_geojson())
    target = _target().model_copy(update={"max_schema_bytes": 4})
    with pytest.raises(ObjectStorageArchitectureError, match="byte limit"):
        harvest_object_storage_architecture(
            client,
            target,
            observed_by="workload:object-harvester",
            observed_at=datetime(2026, 8, 23, 13, tzinfo=UTC),
        )
