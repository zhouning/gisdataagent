"""Tests for the real-data layered OSM publication contract."""

from __future__ import annotations

import hashlib
import mimetypes
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiLineString

from data_agent.data_products.layered_osm_roads import build_layered_publication
from data_agent.platform_gateway import GatewayNotFoundError


class FakeGateway:
    def __init__(self) -> None:
        self.resources = []
        self.versions = {}
        self.artifacts = []
        self.lineage = []

    def register_resource(self, value):
        self.resources.append(value)
        return SimpleNamespace(value=value, created=True)

    def get_resource(self, tenant_id, resource_urn):
        for resource in self.resources:
            if resource.resource_urn == resource_urn:
                return resource
        raise GatewayNotFoundError("missing")

    def register_resource_version(self, value):
        self.versions[value.resource_version_id] = value
        return SimpleNamespace(value=value, created=True)

    def get_resource_version(self, tenant_id, version_id):
        try:
            return self.versions[version_id]
        except KeyError as exc:
            raise GatewayNotFoundError("missing") from exc

    def record_artifact(self, value):
        self.artifacts.append(value)
        return SimpleNamespace(value=value, created=True)

    def record_lineage(self, value):
        self.lineage.append(value)
        return SimpleNamespace(value=value, created=True)


def test_layered_publication_builds_verified_raw_to_ads_chain(tmp_path: Path) -> None:
    source = tmp_path / "OSM_roads.shp"
    source.write_bytes(b"real-source-member")
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    source_identity = {
        "bundle_sha256": "a" * 64,
        "size_bytes": source.stat().st_size,
        "members": [
            {
                "name": source.name,
                "size_bytes": source.stat().st_size,
                "sha256": source_sha256,
            }
        ],
    }
    raw = gpd.GeoDataFrame(
        {
            "osm_id": ["1", "2"],
            "code": [5111, 5112],
            "fclass": ["primary", "secondary"],
            "name": ["A", "B"],
            "ref": ["G1", "G2"],
            "oneway": ["B", "F"],
            "maxspeed": [80, 60],
            "layer": [0, 0],
            "bridge": ["F", "T"],
            "tunnel": ["F", "F"],
        },
        geometry=[
            MultiLineString([[(106.0, 29.0), (106.1, 29.1)]]),
            MultiLineString([[(106.1, 29.1), (106.2, 29.2)]]),
        ],
        crs="EPSG:4326",
    )
    standardized = gpd.GeoDataFrame(
        {
            "road_id": ["1", "2"],
            "road_class_code": [5111, 5112],
            "road_class": ["primary", "secondary"],
            "road_name": ["A", "B"],
            "route_ref": ["G1", "G2"],
            "travel_direction": ["both", "forward"],
            "max_speed_kph": pd.array([80, 60], dtype="Int64"),
            "layer_level": [0, 0],
            "is_bridge": [False, True],
            "is_tunnel": [False, False],
            "source_vintage": [2021, 2021],
        },
        geometry=raw.geometry,
        crs="EPSG:4326",
    )
    output_path = tmp_path / "ads.geojson"
    output_path.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    stored = {}
    materializer_calls = []

    def materializer(payload):
        materializer_calls.append(payload)
        path = Path(payload["source_path"])
        body = path.read_bytes()
        stored[payload["target_uri"]] = body
        content_type = payload.get("content_type") or mimetypes.guess_type(path.name)[0]
        return {
            "materialized": True,
            "created": True,
            "verified": True,
            "target_uri": payload["target_uri"],
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes_written": len(body),
            "content_type": content_type or "application/octet-stream",
        }

    gateway = FakeGateway()
    run_id = uuid4()
    definition_version_id = uuid4()
    result = build_layered_publication(
        source_path=source,
        target_dir=tmp_path / "product" / "v1.1.0",
        raw_frame=raw,
        standardized_frame=standardized,
        source_identity=source_identity,
        source_version_id=uuid4(),
        output_resource_urn="gda://local-dev/dataset/test-ads",
        output_version_id=uuid4(),
        product_version_id=uuid4(),
        version_key="v1.1.0",
        semantic_sha256="b" * 64,
        output_path=output_path,
        timestamp=datetime(2026, 8, 1, tzinfo=UTC),
        gateway=gateway,
        materializer=materializer,
        run_id=run_id,
        definition_version_id=definition_version_id,
    )

    manifest = result["manifest"]
    assert manifest["profile"] == "lightweight_layered"
    assert [layer["stage"] for layer in manifest["chain"]] == [
        "raw",
        "ods",
        "silver",
        "gold",
        "ads",
    ]
    assert all(layer["read_back_verified"] for layer in manifest["chain"])
    assert all(check["status"] == "passed" for check in manifest["checks"])
    assert len(gateway.resources) == 3
    assert len(gateway.versions) == 3
    assert len(gateway.artifacts) == 6
    assert len(gateway.lineage) == 4
    assert all(artifact.run_id == run_id for artifact in gateway.artifacts)
    assert all(event.run_id == run_id for event in gateway.lineage)
    assert all(
        event.definition_version_id == definition_version_id
        for event in gateway.lineage
    )
    assert len(materializer_calls) == 9
    assert all(call["immutable"] for call in materializer_calls)
    stac_item = next(
        body
        for uri, body in stored.items()
        if uri.endswith("/items/v1.1.0.json")
    )
    assert b'"collection": "chongqing-osm-roads"' in stac_item
    assert str(run_id).encode() in stac_item
