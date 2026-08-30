#!/usr/bin/env python3
"""Certify the bounded HTTP GIS MVT cache purge adapter over loopback HTTP."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlunsplit

from data_agent.gis_mvt_http_purge_provider import (
    HTTP_MVT_CACHE_PURGE_SCHEMA,
    HTTPGISMVTCachePurgeProvider,
    HTTPGISMVTCachePurgeProviderError,
)

GENERATION = "a" * 64


class _PurgeHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, object]] = []
    responses: list[tuple[int, object]] = []

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
        except ValueError:
            body = None
        self.__class__.requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("authorization"),
                "body": body,
            }
        )
        status, payload = self.__class__.responses.pop(0)
        encoded = (
            payload
            if isinstance(payload, bytes)
            else json.dumps(payload, ensure_ascii=True).encode("utf-8")
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *_args) -> None:
        return None


def _receipt(generation: str = GENERATION) -> dict[str, object]:
    return {
        "schema": HTTP_MVT_CACHE_PURGE_SCHEMA,
        "status": "succeeded",
        "generation_token": generation,
        "matched_keys": 4,
        "deleted_keys": 4,
        "remaining_keys": 0,
    }


async def _exercise(endpoint: str, token_file: Path) -> dict[str, object]:
    provider = HTTPGISMVTCachePurgeProvider(
        endpoint,
        bearer_token_file=token_file,
        timeout_seconds=2,
    )
    first_retryable = False
    mismatch_rejected = False
    try:
        try:
            await provider.purge_generation(GENERATION, max_keys=10, scan_count=2)
        except HTTPGISMVTCachePurgeProviderError:
            first_retryable = True
        result = await provider.purge_generation(GENERATION, max_keys=10, scan_count=2)
        try:
            await provider.purge_generation(GENERATION, max_keys=10, scan_count=2)
        except HTTPGISMVTCachePurgeProviderError:
            mismatch_rejected = True
    finally:
        await provider.aclose()
    return {
        "first_5xx_rejected_for_outbox_retry": first_retryable,
        "success": result.__dict__,
        "mismatched_generation_rejected": mismatch_rejected,
    }


def certify(report_path: Path | None = None) -> dict[str, object]:
    _PurgeHandler.requests = []
    _PurgeHandler.responses = [
        (503, {"error": "cache unavailable"}),
        (200, _receipt()),
        (200, _receipt("b" * 64)),
    ]
    server = ThreadingHTTPServer(("127.0.0.1", 0), _PurgeHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    with tempfile.TemporaryDirectory(prefix="gda-http-purge-") as directory:
        token_file = Path(directory) / "bearer-token"
        token_file.write_text("loopback-purge-token\n", encoding="utf-8")
        os.chmod(token_file, 0o600)
        endpoint = urlunsplit(("http", f"127.0.0.1:{port}", "/v1/cache/purge", "", ""))
        exercise = asyncio.run(_exercise(endpoint, token_file))
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    requests = _PurgeHandler.requests
    checks = {
        "three_http_requests": len(requests) == 3,
        "fixed_endpoint_path": all(item["path"] == "/v1/cache/purge" for item in requests),
        "bearer_never_in_body": all(
            "loopback-purge-token" not in json.dumps(item["body"], sort_keys=True)
            for item in requests
        ),
        "bearer_header_present": all(
            item["authorization"] == "Bearer loopback-purge-token" for item in requests
        ),
        "request_schema_and_bounds": all(
            item["body"] == {
                "generation_token": GENERATION,
                "max_keys": 10,
                "scan_count": 2,
                "schema": HTTP_MVT_CACHE_PURGE_SCHEMA,
            }
            for item in requests
        ),
        **{
            key: value
            for key, value in exercise.items()
            if key != "success"
        },
        "zero_residue_receipt": exercise["success"] == {
            "enabled": True,
            "namespace": GENERATION,
            "matched_keys": 4,
            "deleted_keys": 4,
            "remaining_keys": 0,
        },
        "loopback_server_cleaned": not thread.is_alive(),
    }
    report: dict[str, object] = {
        "schema": "gda.gis_mvt_http_cache_purge_provider_certification.v1",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "request_count": len(requests),
        "loopback_only": True,
        "production_provider_certified": False,
    }
    if report_path is not None:
        payload = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(payload, encoding="utf-8")
        report["report_sha256"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = certify(args.report)
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
