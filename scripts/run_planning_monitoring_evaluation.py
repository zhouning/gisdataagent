#!/usr/bin/env python3
"""Run the offline planning-monitoring model on governed materialized data.

Example (the Chongqing sample acceptance run)::

    uv run python scripts/run_planning_monitoring_evaluation.py \
      --materialization /private/tmp/gda-script-check-lake/materialized/<run>/materialization.json \
      --output /private/tmp/gda-script-check-lake/model/planning-monitoring

The command has no ArcPy, MCP, database, container or network requirement.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.planning_monitoring import MonitoringConfig, run_monitoring_evaluation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--materialization", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cell-size-m", type=int, default=5000)
    parser.add_argument("--analysis-crs")
    parser.add_argument("--dem-resolution-m", type=int, default=250)
    parser.add_argument("--sample-scope", default="chongqing_demo")
    parser.add_argument(
        "--authority-mode",
        choices=("rehearsal", "production"),
        default="rehearsal",
        help="rehearsal permits explicit alias fallback; production requires ontology bindings",
    )
    parser.add_argument(
        "--ontology-binding",
        type=Path,
        help="binding.json emitted by offline ingest ontology binding",
    )
    parser.add_argument(
        "--semantic-mapping",
        type=Path,
        help="optional replacement for the bundled semantic input mapping contract",
    )
    parser.add_argument(
        "--ontology-package",
        type=Path,
        help="immutable ontology package directory; defaults to the active bundled package",
    )
    parser.add_argument(
        "--skip-ontology-validation",
        action="store_true",
        help="rehearsal-only escape hatch for diagnostics when the package is not installed",
    )
    args = parser.parse_args()
    if not args.materialization.is_file():
        parser.error(f"materialization file does not exist: {args.materialization}")
    if args.cell_size_m < 100:
        parser.error("--cell-size-m must be at least 100")
    result = run_monitoring_evaluation(
        args.materialization,
        args.output,
        config=MonitoringConfig(
            cell_size_m=args.cell_size_m,
            analysis_crs=args.analysis_crs,
            dem_resolution_m=args.dem_resolution_m,
            sample_scope=args.sample_scope,
            authority_mode=args.authority_mode,
            ontology_binding_path=str(args.ontology_binding) if args.ontology_binding else None,
            semantic_mapping_path=str(args.semantic_mapping) if args.semantic_mapping else None,
            ontology_package_dir=str(args.ontology_package) if args.ontology_package else None,
            validate_ontology=not args.skip_ontology_validation,
        ),
    )
    print(json.dumps({
        "report": str(args.output.resolve() / "monitoring_evaluation_report.json"),
        "status": result["status"],
        "units": result["unit_count"],
        "diagnostic_counts": result.get("diagnostic_counts", {}),
        "production_eligible": result["production_eligible"],
        "semantic_gate": (result.get("semantic_gate") or {}).get("status"),
    }, ensure_ascii=False))
    return 2 if result["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
