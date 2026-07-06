"""Build NOAA ISD observed weather proxy for the UWM 2024-07 scene."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from data_agent.uwm.noaa_isd_weather_proxy import write_noaa_isd_weather_proxy_snapshot


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "data/uwm_public_proxy/chongqing_central/noaa_isd_weather_2024_07_01_07"
NOAA_ISD_GZ = OUTPUT_DIR / "575160-99999-2024.gz"


def main() -> None:
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    manifest = write_noaa_isd_weather_proxy_snapshot(
        gz_path=NOAA_ISD_GZ,
        output_dir=OUTPUT_DIR,
        start_date="2024-07-01",
        end_date="2024-07-07",
        fetched_at=fetched_at,
    )
    print(
        json.dumps(
            {
                "output_dir": str(OUTPUT_DIR.relative_to(REPO_ROOT)),
                "quality_status": manifest["quality_status"],
                "record_counts": manifest["record_counts"],
                "station_summary": manifest["station_summary"],
                "report_type_counts": manifest["report_type_counts"],
                "summary": manifest["summary"],
                "claim_boundary": manifest["claim_boundary"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
