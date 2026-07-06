"""Download a small GEE ERA5/CAMS point proxy snapshot for UWM.

This script requires local Google Earth Engine authentication. It writes raw
sampled FeatureCollections, a normalized UWM proxy, and an MMFE state input.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ee

from data_agent.uwm.gee_environment import (
    build_mmfe_state_input_from_gee_environmental_proxy,
    write_gee_environmental_snapshot,
)


ERA5_BANDS = [
    "temperature_2m",
    "surface_pressure",
    "u_component_of_wind_10m",
    "v_component_of_wind_10m",
    "total_precipitation",
]

CAMS_BANDS = [
    "particulate_matter_d_less_than_25_um_surface",
    "total_aerosol_optical_depth_at_550nm_surface",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--latitude", type=float, default=29.563)
    parser.add_argument("--longitude", type=float, default=106.551)
    parser.add_argument("--label", default="Chongqing central")
    parser.add_argument("--start-date", default="2024-07-01")
    parser.add_argument("--end-date-exclusive", default="2024-07-08")
    parser.add_argument(
        "--output-dir",
        default="data/uwm_public_proxy/chongqing_central/gee_era5_cams_2024_07_01_07",
    )
    args = parser.parse_args()

    ee.Initialize()
    point = ee.Geometry.Point([args.longitude, args.latitude])
    era5 = _sample_collection(
        asset_id="ECMWF/ERA5/HOURLY",
        bands=ERA5_BANDS,
        point=point,
        start_date=args.start_date,
        end_date=args.end_date_exclusive,
        scale=30000,
    )
    cams = _sample_collection(
        asset_id="ECMWF/CAMS/NRT",
        bands=CAMS_BANDS,
        point=point,
        start_date=args.start_date,
        end_date=args.end_date_exclusive,
        scale=40000,
    )
    fetched_at = datetime.now(timezone.utc).isoformat()
    output_dir = Path(args.output_dir)
    manifest = write_gee_environmental_snapshot(
        output_dir=output_dir,
        era5_payload=era5,
        cams_payload=cams,
        requested_location={"latitude": args.latitude, "longitude": args.longitude, "label": args.label},
        time_range={
            "start_date": args.start_date,
            "end_date": _inclusive_end_date(args.end_date_exclusive),
        },
        fetched_at=fetched_at,
    )
    proxy = json.loads((output_dir / "gee_era5_cams_environmental_proxy.json").read_text(encoding="utf-8"))
    state_input = build_mmfe_state_input_from_gee_environmental_proxy(proxy, timestamp=fetched_at)
    _write_json(output_dir / "mmfe_uwm_state_input_gee_era5_cams.json", state_input)
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "manifest": "snapshot_manifest.json",
                "record_counts": manifest["record_counts"],
                "claim_boundary": manifest["claim_boundary"],
            },
            ensure_ascii=False,
        )
    )


def _sample_collection(
    *,
    asset_id: str,
    bands: list[str],
    point: Any,
    start_date: str,
    end_date: str,
    scale: int,
) -> dict[str, Any]:
    collection = ee.ImageCollection(asset_id).filterDate(start_date, end_date).select(bands)

    def sample_image(image: Any) -> Any:
        image = ee.Image(image)
        values = image.reduceRegion(
            reducer=ee.Reducer.first(),
            geometry=point,
            scale=scale,
            bestEffort=True,
        )
        values = values.combine(
            ee.Dictionary(
                {
                    "system:index": image.get("system:index"),
                    "system:time_start": image.get("system:time_start"),
                }
            )
        )
        return ee.Feature(None, values)

    payload = ee.FeatureCollection(collection.map(sample_image)).getInfo()
    payload["source_asset"] = asset_id
    payload["selected_bands"] = bands
    return payload


def _inclusive_end_date(end_date_exclusive: str) -> str:
    date = datetime.fromisoformat(end_date_exclusive)
    previous = date.fromordinal(date.toordinal() - 1)
    return previous.date().isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
