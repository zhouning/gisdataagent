#!/usr/bin/env python3
"""Build the April 2024 Abu Dhabi/UAE extreme-rainfall event ledger."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from data_agent.uwm.abu_dhabi_flood.event_catalog import (
    build_april_2024_event_catalog,
    verify_april_2024_event_catalog,
)

if __package__:
    from scripts.run_abu_dhabi_flood_public_forcing_comparison import (
        DEFAULT_NASA_HOURLY_FORCING,
        load_nasa_power_hourly,
    )
    from scripts.run_abu_dhabi_flood_public_proxy_candidate import (
        DEFAULT_FORCING,
        REPOSITORY_ROOT,
        load_openmeteo_hourly,
    )
else:
    from run_abu_dhabi_flood_public_forcing_comparison import (
        DEFAULT_NASA_HOURLY_FORCING,
        load_nasa_power_hourly,
    )
    from run_abu_dhabi_flood_public_proxy_candidate import (
        DEFAULT_FORCING,
        REPOSITORY_ROOT,
        load_openmeteo_hourly,
    )


DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "benchmarks/abu_dhabi_stormwater_data_v1/derived/events/"
    / "april_2024_event_catalog.json"
)


def _relative_label(path: Path) -> str:
    try:
        return str(path.relative_to(REPOSITORY_ROOT))
    except ValueError:
        return f"external-input:{path.name}"


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def run(
    openmeteo_path: Path = DEFAULT_FORCING,
    nasa_hourly_path: Path = DEFAULT_NASA_HOURLY_FORCING,
) -> dict[str, object]:
    openmeteo_path = openmeteo_path.resolve()
    nasa_hourly_path = nasa_hourly_path.resolve()
    openmeteo = load_openmeteo_hourly(openmeteo_path)
    nasa = load_nasa_power_hourly(nasa_hourly_path)
    payload = build_april_2024_event_catalog(
        openmeteo={
            "source": "Open-Meteo Historical API archive point product",
            "source_file": _relative_label(openmeteo_path),
            "file_sha256": openmeteo["file_sha256"],
            "time_standard": openmeteo["payload"]["timezone"],
            "latitude": openmeteo["payload"]["latitude"],
            "longitude": openmeteo["payload"]["longitude"],
            "source_elevation_m": openmeteo["payload"]["elevation"],
            "hourly_interval_count": len(openmeteo["precipitation_mm"]),
            "total_precipitation_mm": round(openmeteo["total_precipitation_mm"], 8),
            "maximum_hourly_precipitation_mm": round(
                openmeteo["maximum_hourly_precipitation_mm"], 8
            ),
        },
        nasa_power_merra2={
            "source": "NASA POWER Hourly API MERRA2 point product",
            "source_file": _relative_label(nasa_hourly_path),
            "file_sha256": nasa["file_sha256"],
            "time_standard": nasa["time_standard"],
            "latitude": nasa["payload"]["geometry"]["coordinates"][1],
            "longitude": nasa["payload"]["geometry"]["coordinates"][0],
            "source_elevation_m": nasa["payload"]["geometry"]["coordinates"][2],
            "hourly_interval_count": len(nasa["precipitation_mm"]),
            "total_precipitation_mm": round(nasa["total_precipitation_mm"], 8),
            "maximum_hourly_precipitation_mm": round(
                nasa["maximum_hourly_precipitation_mm"], 8
            ),
        },
    )
    verify_april_2024_event_catalog(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openmeteo", type=Path, default=DEFAULT_FORCING)
    parser.add_argument("--nasa-hourly", type=Path, default=DEFAULT_NASA_HOURLY_FORCING)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    os.chdir(REPOSITORY_ROOT)
    payload = run(args.openmeteo, args.nasa_hourly)
    output = args.output if args.output.is_absolute() else REPOSITORY_ROOT / args.output
    content = (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        + "\n"
    ).encode("ascii")
    _atomic_write(output, content)
    print(json.dumps({"output": str(output), "catalog_sha256": payload["catalog_sha256"]}))


if __name__ == "__main__":
    main()
