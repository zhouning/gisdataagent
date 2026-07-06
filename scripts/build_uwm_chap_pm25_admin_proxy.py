"""Build CHAP PM2.5 admin proxy for UWM livability candidate units."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from data_agent.uwm.chap_pm25_proxy import write_chap_pm25_admin_proxy_snapshot


REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN_GEOJSON = REPO_ROOT / "data/uwm_public_proxy/chongqing_central/admin_units/chongqing_township_admin_units.geojson"
LIVABILITY_PANEL = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/admin_livability_target_2024_07_2026_07_05/uwm_admin_livability_target_panel.json"
)
OUTPUT_DIR = REPO_ROOT / "data/uwm_public_proxy/chongqing_central/chap_pm25_2024_07"
CHAP_NC = OUTPUT_DIR / "CHAP_PM2.5_M1K_202407_V4.nc"


def main() -> None:
    admin_geojson = _load_json(ADMIN_GEOJSON)
    selected_admin_ids = _selected_admin_ids(_load_json(LIVABILITY_PANEL))
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    manifest = write_chap_pm25_admin_proxy_snapshot(
        nc_path=CHAP_NC,
        admin_geojson=admin_geojson,
        selected_admin_ids=selected_admin_ids,
        output_dir=OUTPUT_DIR,
        fetched_at=fetched_at,
    )
    print(
        json.dumps(
            {
                "output_dir": str(OUTPUT_DIR.relative_to(REPO_ROOT)),
                "record_counts": manifest["record_counts"],
                "coverage": manifest["coverage"],
                "summary": manifest["summary"],
                "claim_boundary": manifest["claim_boundary"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _selected_admin_ids(panel: dict) -> set[str]:
    return {
        str(row.get("admin_unit_id"))
        for row in panel.get("admin_livability_target_rows") or []
        if row.get("admin_unit_id")
    }


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


if __name__ == "__main__":
    main()
