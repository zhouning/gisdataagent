"""Build the audited Chongqing OpenAQ station/admin crosswalk artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel.station_admin_crosswalk import (
    build_station_admin_crosswalk,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
DEFAULT_LOCATIONS = DATA_ROOT / "openaq_station_observations/openaq_locations_raw.json"
DEFAULT_ADMIN_UNITS = DATA_ROOT / "admin_units/chongqing_township_admin_units.geojson"
DEFAULT_OUTPUT = (
    DATA_ROOT
    / "geospatial_station_admin_crosswalk_2026_08_04"
    / "uwm_geospatial_station_admin_crosswalk.json"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--locations", type=Path, default=DEFAULT_LOCATIONS)
    parser.add_argument("--admin-units", type=Path, default=DEFAULT_ADMIN_UNITS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    artifact = build_station_admin_crosswalk(
        crosswalk_id="chongqing-openaq-station-township-crosswalk-2026-08-04",
        created_at=args.created_at,
        locations_payload=_read_json(args.locations),
        admin_feature_collection=_read_json(args.admin_units),
        source_refs=[_relative(args.locations), _relative(args.admin_units)],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "crosswalk_complete": artifact["crosswalk_complete"],
                "assignment_status_counts": artifact["audit"]["assignment_status_counts"],
                "remaining_gates": artifact["remaining_gates"],
                "crosswalk_sha256": artifact["crosswalk_sha256"],
            },
            ensure_ascii=False,
        )
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


if __name__ == "__main__":
    main()
