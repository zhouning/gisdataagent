"""Build UWM Track 2 readiness report artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.track2_submission import build_uwm_default_track2_readiness_matrix


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs/reports/uwm_track2_readiness_2026_07_06"


def build_track2_readiness_report(
    *,
    repo_root: str | Path,
    output_dir: str | Path,
    current_date: str,
) -> dict[str, str]:
    root = Path(repo_root)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    matrix = build_uwm_default_track2_readiness_matrix(root, current_date=current_date)
    json_path = out / "uwm_track2_readiness_matrix.json"
    markdown_path = out / "uwm_track2_readiness_summary.md"
    _write_json(json_path, matrix)
    markdown_path.write_text(_render_markdown(matrix), encoding="utf-8")
    return {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build UWM Track 2 readiness report artifacts.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--current-date", default="2026-07-06")
    args = parser.parse_args()

    result = build_track2_readiness_report(
        repo_root=args.repo_root,
        output_dir=args.output_dir,
        current_date=args.current_date,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _render_markdown(matrix: dict[str, Any]) -> str:
    readiness = matrix.get("world_model_evidence_readiness") or {}
    observed = matrix.get("observed_validation_readiness") or {}
    lines = [
        "# UWM Track 2 Readiness Summary",
        "",
        f"- Current date: `{matrix.get('days_to_initial_review_deadline')}` days to initial review deadline",
        f"- Ready for initial submission: `{matrix.get('ready_for_initial_submission')}`",
        f"- System-level superiority summary: `{readiness.get('system_level_superiority_summary')}`",
        f"- Overall claim ceiling: `{readiness.get('overall_claim_ceiling')}`",
        f"- Traditional method comparison ready: `{readiness.get('traditional_method_comparison_ready')}`",
        f"- Policy outcome superiority ready: `{readiness.get('policy_outcome_superiority_ready')}`",
        f"- Empirical superiority claim: `{readiness.get('empirical_superiority_claim')}`",
        "",
        "## Observed Validation",
        "",
        f"- Temporal state suite ready: `{observed.get('temporal_state_prediction_suite_ready')}`",
        f"- Temporal negative control passed: `{observed.get('temporal_order_negative_control_passed')}`",
        f"- Policy outcome superiority ready: `{observed.get('policy_outcome_superiority_ready')}`",
        "",
        "## Claim Ladder",
        "",
    ]
    for claim in readiness.get("claim_ladder") or []:
        lines.append(
            "- "
            f"`{claim.get('claim')}` | scope `{claim.get('scope')}` | "
            f"level `{claim.get('claim_level')}` | allowed `{claim.get('allowed_in_report')}`"
        )
    lines.extend(
        [
            "",
            "## Forbidden Claims",
            "",
        ]
    )
    for claim in readiness.get("forbidden_claims") or []:
        lines.append(f"- `{claim}`")
    lines.extend(
        [
            "",
            "## Remaining Gates",
            "",
        ]
    )
    for gate in readiness.get("remaining_gates") or []:
        lines.append(f"- `{gate}`")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
