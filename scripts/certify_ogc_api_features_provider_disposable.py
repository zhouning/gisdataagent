#!/usr/bin/env python3
"""Run a deterministic disposable OGC API Features provider certification.

This is explicitly synthetic evidence for adapter/control-contract behavior;
it is not a pygeoapi production certification. A real provider origin can be
passed to ``certify_ogc_api_features_provider.py`` once an environment owner
supplies the endpoint and release projection.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from data_agent.gis_provider_runtime import OGCAPIFeaturesProvider, OGCAPIFeaturesReleaseContext


class _Handler(BaseHTTPRequestHandler):
    server_version = "gda-ogc-fixture/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        if parsed.path == "/":
            self._send(200, {"title": "synthetic pygeoapi"})
        elif parsed.path == "/conformance":
            self._send(
                200,
                {"conformsTo": ["http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core"]},
            )
        elif parsed.path == "/collections":
            self._send(200, {"collections": [{"id": "districts", "title": "Districts"}]})
        elif parsed.path == "/collections/districts/items":
            query = parse_qs(parsed.query)
            limit = int(query.get("limit", ["100"])[0])
            self._send(
                200,
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "id": "d-1",
                            "geometry": {"type": "Point", "coordinates": [121.1, 31.2]},
                            "properties": {"name": "district"},
                        }
                    ][:limit],
                },
            )
        else:
            self._send(404, {"error": "not found"})

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/geo+json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


def run() -> dict[str, object]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        import asyncio

        from data_agent.test_gis_service_control_plane import (
            _definition,
            _release_bundle,
        )

        definition = _definition()
        layer, _style, _tms, release = _release_bundle(definition)
        context = OGCAPIFeaturesReleaseContext.from_release(
            release, definition, layer, collection_id="districts"
        )
        provider = OGCAPIFeaturesProvider(
            f"http://127.0.0.1:{server.server_port}",
        )
        receipt = asyncio.run(provider.conform_features_read(context, limit=10))
        return {
            "schema": "gda.gis_ogc_api_features_provider_disposable_certification.v1",
            "status": "passed",
            "evidence_class": "synthetic_disposable",
            "provider_origin": provider.endpoint_uri,
            "collection_id": context.collection_id,
            "feature_count": receipt.feature_count,
            "receipt_sha256": receipt.receipt_sha256,
            "manifest_sha256": provider.manifest.manifest_sha256,
            "checks": [
                "health",
                "ogc_api_features_conformance",
                "collections_advertisement",
                "non_empty_geojson_items",
                "release_product_layer_identity",
            ],
        }
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
