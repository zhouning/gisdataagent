"""Close the unusable frozen 2024 P1 protocol without acquiring its target."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel.state_prior_p1_protocol_closure import (
    build_state_prior_p1_protocol_closure,
    validate_state_prior_p1_protocol_closure,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
DEFAULT_PROTOCOL = (
    DATA_ROOT
    / "geospatial_state_prior_next_p1_protocol_2024_07_02_07"
    / "uwm_geospatial_state_prior_p1_prospective_protocol.json"
)
DEFAULT_PREFLIGHT = (
    DATA_ROOT
    / "geospatial_state_prior_2024_predictor_preflight"
    / "uwm_geospatial_state_prior_predictor_preflight.json"
)
DEFAULT_PLAN = (
    DATA_ROOT
    / "openaq_multi_station_acquisition_plan_2024_07_02_07"
    / "uwm_openaq_multi_station_acquisition_plan.json"
)
DEFAULT_PRIOR_ATTEMPT = (
    DATA_ROOT / "openaq_station_observations_2024_07_attempt/snapshot_manifest.json"
)
DEFAULT_GEOFABRIK_PROBE = (
    ROOT / "docs/reports/uwm_ai_urban_scientist_skill_audit_2026_07_18/live_route_probe.json"
)
DEFAULT_OUTPUT = (
    DATA_ROOT
    / "geospatial_state_prior_2024_protocol_closure"
    / "uwm_geospatial_state_prior_p1_protocol_closure.json"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--predictor-preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--acquisition-plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--prior-attempt-manifest", type=Path, default=DEFAULT_PRIOR_ATTEMPT)
    parser.add_argument("--geofabrik-probe-report", type=Path, default=DEFAULT_GEOFABRIK_PROBE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    evidence_paths = [
        args.protocol,
        args.predictor_preflight,
        args.acquisition_plan,
        args.prior_attempt_manifest,
        args.geofabrik_probe_report,
    ]
    closure = build_state_prior_p1_protocol_closure(
        closure_id="chongqing-observed-station-p1-2024-admin-provenance-closure",
        created_at=args.created_at,
        protocol=_read_json(args.protocol),
        predictor_preflight=_read_json(args.predictor_preflight),
        acquisition_plan=_read_json(args.acquisition_plan),
        prior_attempt_manifest=_read_json(args.prior_attempt_manifest),
        geofabrik_probe_report=_read_json(args.geofabrik_probe_report),
        evidence_refs=[_relative_or_absolute(path) for path in evidence_paths],
    )
    validation = validate_state_prior_p1_protocol_closure(closure)
    if not validation["valid"]:
        raise ValueError(
            "invalid_state_prior_p1_protocol_closure:" + ";".join(validation["errors"])
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(closure, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "closure_sha256": closure["closure_sha256"],
                "status": closure["closure_decision"]["status"],
                "target_unconsumed_under_available_evidence": closure["target_access_audit"][
                    "target_unconsumed_under_available_evidence"
                ],
                "target_acquisition_permitted": closure["closure_decision"][
                    "target_acquisition_permitted"
                ],
                "replacement_protocol_required": closure["closure_decision"][
                    "replacement_protocol_required"
                ],
            },
            ensure_ascii=False,
        )
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative_or_absolute(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


if __name__ == "__main__":
    main()
