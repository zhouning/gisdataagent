#!/usr/bin/env python3
"""Download small public proxy datasets for UWM data foundation."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

from data_agent.uwm.public_proxy_downloader import build_openmeteo_urls, write_openmeteo_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Download UWM public proxy snapshots.")
    parser.add_argument("--source", choices=["openmeteo"], default="openmeteo")
    parser.add_argument("--latitude", type=float, default=29.563)
    parser.add_argument("--longitude", type=float, default=106.551)
    parser.add_argument("--label", default="Chongqing central")
    parser.add_argument(
        "--output-dir",
        default="data/uwm_public_proxy/chongqing_central/openmeteo_current",
    )
    args = parser.parse_args()

    if args.source != "openmeteo":
        raise ValueError(f"unsupported source: {args.source}")

    urls = build_openmeteo_urls(latitude=args.latitude, longitude=args.longitude)
    weather_payload = _fetch_json(urls["weather"])
    air_quality_payload = _fetch_json(urls["air_quality"])
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    manifest = write_openmeteo_snapshot(
        output_dir=Path(args.output_dir),
        weather_payload=weather_payload,
        air_quality_payload=air_quality_payload,
        requested_location={"latitude": args.latitude, "longitude": args.longitude, "label": args.label},
        fetched_at=fetched_at,
    )
    print(json.dumps({"output_dir": args.output_dir, "manifest": manifest}, ensure_ascii=False, indent=2))
    return 0


def _fetch_json(url: str) -> dict:
    with urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
