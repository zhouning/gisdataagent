#!/usr/bin/env python3
"""Build UWM district-population artifacts from the local Chongqing Excel sample."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from data_agent.uwm.chongqing_district_population import (
    build_chongqing_district_population_mmfe_state_input,
    write_chongqing_district_population_snapshot,
)
from data_agent.uwm.manifest import audit_uwm_manifest
from data_agent.uwm.renderer import build_canonical_observation_from_state_input


DEFAULT_INPUT = (
    ".tmp/twm_standard_1128/自然资源一张图数据库标准1128/"
    "规划院提供数据样例及Demo系统功能演示建议/01数据样例/"
    "08重庆市各区县人口规模表格数据/重庆市各区县人口规模数据.xlsx"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build UWM Chongqing district population artifacts.")
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", default="data/uwm_public_proxy/chongqing_central/chongqing_district_population_2021")
    parser.add_argument("--manifest-path", default="docs/reports/uwm_data_foundation_manifest.csv")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    df = pd.read_excel(input_path)
    records = json.loads(df.to_json(orient="records", force_ascii=False))
    _write_json(output_dir / "chongqing_district_population_raw_rows.json", {"source_ref": str(input_path), "records": records})
    snapshot_manifest = write_chongqing_district_population_snapshot(
        output_dir=output_dir,
        records=records,
        source_ref=str(input_path),
        created_at=created_at,
    )
    proxy = _read_json(output_dir / "chongqing_district_population_proxy.json")
    state_input = build_chongqing_district_population_mmfe_state_input(proxy, timestamp=created_at)
    _write_json(output_dir / "mmfe_uwm_state_input_chongqing_district_population.json", state_input)
    observation = build_canonical_observation_from_state_input(
        state_input,
        manifest_audit=audit_uwm_manifest(args.manifest_path),
        observation_id="uwm-observation-chongqing-district-population-2021",
        timestamp=created_at,
    )
    _write_json(output_dir / "uwm_canonical_observation_chongqing_district_population.json", observation)
    print(json.dumps({"output_dir": str(output_dir), "snapshot_manifest": snapshot_manifest}, ensure_ascii=False, indent=2))
    return 0


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
