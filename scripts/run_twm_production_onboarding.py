#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent.territory_world_model.deployment_punch_list import build_deployment_punch_list

DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs/reports/twm_production_onboarding"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the TWM production onboarding smoke flow: data foundation + validation bundle + combined summary."
    )
    parser.add_argument("--raw-production-observed-history", default="", help="Optional raw approval/review export CSV.")
    parser.add_argument("--production-observed-history", default="", help="Optional already-normalized production observed-history CSV.")
    parser.add_argument("--normalized-production-observed-history-output", default="", help="Normalized observed-history CSV output path.")
    parser.add_argument("--production-scale-profile", default="", help="Optional sanitized production scale profile JSON.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for all onboarding outputs.")
    parser.add_argument("--require-production-readiness", action="store_true", help="Pass strict production-readiness gate to the bundle runner.")
    parser.add_argument("--fail-on-blocked", action="store_true", help="Exit 2 when the combined onboarding summary is blocked.")
    args = parser.parse_args()

    raw_history = Path(args.raw_production_observed_history).expanduser() if args.raw_production_observed_history else None
    production_history = Path(args.production_observed_history).expanduser() if args.production_observed_history else None
    if raw_history is None and production_history is None:
        parser.error("provide --raw-production-observed-history or --production-observed-history")
    if raw_history is not None and production_history is not None:
        parser.error("choose exactly one observed-history input: --raw-production-observed-history or --production-observed-history")
    if raw_history is not None and not args.normalized_production_observed_history_output:
        parser.error("--normalized-production-observed-history-output is required with --raw-production-observed-history")

    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized_history = (
        Path(args.normalized_production_observed_history_output).expanduser()
        if args.normalized_production_observed_history_output
        else output_dir / "twm_normalized_production_observed_history.csv"
    )
    production_scale_profile = Path(args.production_scale_profile).expanduser() if args.production_scale_profile else None

    outputs = onboarding_output_paths(output_dir)
    commands = []
    data_foundation_command = build_data_foundation_command(
        outputs,
        raw_history=raw_history,
        production_history=production_history,
        normalized_history=normalized_history,
    )
    commands.append(run_command(data_foundation_command))

    validation_bundle_command = build_validation_bundle_command(
        outputs,
        raw_history=raw_history,
        production_history=production_history,
        normalized_history=normalized_history,
        production_scale_profile=production_scale_profile,
        require_production_readiness=bool(args.require_production_readiness),
    )
    commands.append(run_command(validation_bundle_command, allowed_returncodes={0, 2}))

    data_foundation_report = read_json(outputs["data_foundation_report"])
    validation_bundle_report = read_json(outputs["validation_bundle_report"])
    summary = build_onboarding_summary(
        raw_history=raw_history,
        production_history=production_history,
        normalized_history=normalized_history if raw_history else None,
        production_scale_profile=production_scale_profile,
        outputs=outputs,
        commands=commands,
        data_foundation_report=data_foundation_report,
        validation_bundle_report=validation_bundle_report,
    )
    write_json(outputs["summary_report"], summary)
    write_markdown(outputs["summary_markdown"], render_onboarding_markdown(summary))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"wrote {outputs['summary_report']}")
    print(f"wrote {outputs['summary_markdown']}")

    if args.fail_on_blocked and summary.get("status") == "blocked":
        raise SystemExit(2)


def onboarding_output_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "data_foundation_report": output_dir / "twm_data_foundation_validation.json",
        "data_foundation_markdown": output_dir / "twm_data_foundation_health.md",
        "observed_history_template": output_dir / "twm_production_observed_history_template.csv",
        "structural_observed_history": output_dir / "twm_structural_validation_observed_history.csv",
        "synthetic_experiment_foundation": output_dir / "twm_synthetic_experiment_foundation.csv",
        "validation_bundle_report": output_dir / "twm_validation_bundle.json",
        "validation_bundle_markdown": output_dir / "twm_validation_bundle.md",
        "scale_profile_template": output_dir / "twm_production_scale_profile_template.json",
        "summary_report": output_dir / "twm_production_onboarding_summary.json",
        "summary_markdown": output_dir / "twm_production_onboarding_summary.md",
    }


def build_data_foundation_command(
    outputs: dict[str, Path],
    *,
    raw_history: Path | None,
    production_history: Path | None,
    normalized_history: Path,
) -> list[str]:
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts/validate_twm_data_foundation.py"),
        "--output",
        str(outputs["data_foundation_report"]),
        "--markdown-output",
        str(outputs["data_foundation_markdown"]),
        "--schema-template-output",
        str(outputs["observed_history_template"]),
        "--structural-observed-history-output",
        str(outputs["structural_observed_history"]),
        "--synthetic-experiment-output",
        str(outputs["synthetic_experiment_foundation"]),
    ]
    if production_history is not None:
        command.extend(["--production-observed-history", str(production_history)])
    if raw_history is not None:
        command.extend(
            [
                "--normalize-production-observed-history-source",
                str(raw_history),
                "--normalized-production-observed-history-output",
                str(normalized_history),
            ]
        )
    return command


def build_validation_bundle_command(
    outputs: dict[str, Path],
    *,
    raw_history: Path | None,
    production_history: Path | None,
    normalized_history: Path,
    production_scale_profile: Path | None,
    require_production_readiness: bool,
) -> list[str]:
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts/run_twm_validation_bundle.py"),
        "--output",
        str(outputs["validation_bundle_report"]),
        "--markdown-output",
        str(outputs["validation_bundle_markdown"]),
        "--synthetic-experiment-foundation",
        str(outputs["synthetic_experiment_foundation"]),
        "--scale-profile-template-output",
        str(outputs["scale_profile_template"]),
    ]
    if production_history is not None:
        command.extend(["--production-observed-history", str(production_history)])
    if raw_history is not None:
        command.extend(
            [
                "--normalize-production-observed-history-source",
                str(raw_history),
                "--normalized-production-observed-history-output",
                str(normalized_history),
            ]
        )
    if production_scale_profile is not None:
        command.extend(["--production-scale-profile", str(production_scale_profile)])
    if require_production_readiness:
        command.append("--require-production-readiness")
    return command


def run_command(command: list[str], *, allowed_returncodes: set[int] | None = None) -> dict[str, Any]:
    allowed = allowed_returncodes or {0}
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    result = {
        "command": command,
        "returncode": completed.returncode,
        "stdout_tail": tail_lines(completed.stdout or "", limit=20),
    }
    if completed.returncode not in allowed:
        raise SystemExit(completed.returncode)
    return result


def build_onboarding_summary(
    *,
    raw_history: Path | None,
    production_history: Path | None,
    normalized_history: Path | None,
    production_scale_profile: Path | None,
    outputs: dict[str, Path],
    commands: list[dict[str, Any]],
    data_foundation_report: dict[str, Any],
    validation_bundle_report: dict[str, Any],
) -> dict[str, Any]:
    data_foundation_summary = data_foundation_report.get("summary") or {}
    data_foundation_normalization = data_foundation_report.get("production_observed_history_normalization") or {}
    validation_normalization = validation_bundle_report.get("production_observed_history_normalization") or {}
    validation_preflight = validation_bundle_report.get("production_observed_history_preflight") or {}
    readiness = validation_bundle_report.get("production_readiness_gate") or {}
    scale = validation_bundle_report.get("production_scale_readiness") or {}
    deployment_punch_list = build_deployment_punch_list(
        schema="territory_world_model.production_onboarding_punch_list.v1",
        status=onboarding_status(data_foundation_summary, validation_bundle_report),
        readiness_gate=readiness,
    )
    data_normalized = data_foundation_normalization.get("output_path")
    bundle_normalized = validation_normalization.get("output_path")
    normalized_output = data_normalized or bundle_normalized or (str(normalized_history) if normalized_history else None)
    same_normalized_output = (
        True
        if data_normalized and bundle_normalized and data_normalized == bundle_normalized
        else None if normalized_history is None else False
    )
    summary = {
        "schema": "territory_world_model.production_onboarding_summary.v1",
        "status": onboarding_status(data_foundation_summary, validation_bundle_report),
        "observed_history": {
            "raw_source": str(raw_history) if raw_history else None,
            "production_observed_history": str(production_history) if production_history else None,
            "normalized_output": normalized_output,
            "data_foundation_normalization_status": data_foundation_normalization.get("status"),
            "validation_bundle_normalization_status": validation_normalization.get("status"),
            "same_normalized_output": same_normalized_output,
        },
        "data_foundation": {
            "report": str(outputs["data_foundation_report"]),
            "status": data_foundation_summary.get("status"),
            "production_schema_status": data_foundation_summary.get("production_observed_history_schema_status"),
            "production_candidate_rows": data_foundation_summary.get("production_observed_history_schema_production_candidate_rows", 0),
            "production_policy_alignment_status": data_foundation_summary.get("production_policy_alignment_status"),
            "production_policy_alignment_missing": data_foundation_summary.get("production_policy_alignment_missing", []),
        },
        "validation_bundle": {
            "report": str(outputs["validation_bundle_report"]),
            "status": validation_bundle_report.get("status"),
            "production_preflight_status": validation_preflight.get("status"),
            "production_preflight_history": validation_preflight.get("production_observed_history"),
            "scale_readiness_status": scale.get("status"),
            "readiness_gate_status": readiness.get("status"),
            "readiness_missing": readiness.get("missing", []),
        },
        "production_scale_profile": str(production_scale_profile) if production_scale_profile else None,
        "deployment_punch_list": deployment_punch_list,
        "commands": commands,
        "outputs": {key: str(value) for key, value in outputs.items()},
        "claim_boundary": "onboarding summary checks ingestion and validation wiring only; it does not certify production accuracy or legal approval readiness",
    }
    return summary


def onboarding_status(data_foundation_summary: dict[str, Any], validation_bundle_report: dict[str, Any]) -> str:
    data_status = str(data_foundation_summary.get("status") or "review")
    bundle_status = str(validation_bundle_report.get("status") or "review")
    if data_status == "blocked" or bundle_status == "blocked":
        return "blocked"
    if data_status == "pass" and bundle_status == "pass":
        return "pass"
    return "review"


def render_onboarding_markdown(summary: dict[str, Any]) -> str:
    observed = summary.get("observed_history") or {}
    data_foundation = summary.get("data_foundation") or {}
    bundle = summary.get("validation_bundle") or {}
    punch_list = summary.get("deployment_punch_list") or {}
    outputs = summary.get("outputs") or {}
    lines = [
        "# TWM Production Onboarding Summary",
        "",
        "Generated by `scripts/run_twm_production_onboarding.py`.",
        "",
        "## Status",
        "",
        f"- Overall status: `{summary.get('status')}`",
        f"- Claim boundary: {summary.get('claim_boundary')}",
        "",
        "## Observed History",
        "",
        f"- Raw source: `{observed.get('raw_source')}`",
        f"- Production observed history: `{observed.get('production_observed_history')}`",
        f"- Normalized output: `{observed.get('normalized_output')}`",
        f"- Data-foundation normalization: `{observed.get('data_foundation_normalization_status')}`",
        f"- Bundle normalization: `{observed.get('validation_bundle_normalization_status')}`",
        f"- Same normalized output: `{observed.get('same_normalized_output')}`",
        "",
        "## Data Foundation",
        "",
        f"- Status: `{data_foundation.get('status')}`",
        f"- Production schema: `{data_foundation.get('production_schema_status')}`",
        f"- Production candidate rows: `{data_foundation.get('production_candidate_rows', 0)}`",
        f"- Policy alignment: `{data_foundation.get('production_policy_alignment_status')}`",
        f"- Policy alignment missing: `{data_foundation.get('production_policy_alignment_missing', [])}`",
        "",
        "## Validation Bundle",
        "",
        f"- Status: `{bundle.get('status')}`",
        f"- Production preflight: `{bundle.get('production_preflight_status')}`",
        f"- Scale readiness: `{bundle.get('scale_readiness_status')}`",
        f"- Readiness gate: `{bundle.get('readiness_gate_status')}`",
        f"- Readiness missing: `{bundle.get('readiness_missing', [])}`",
        "",
        "## Deployment Punch List",
        "",
        f"- Status: `{punch_list.get('status')}`",
        f"- Required: `{punch_list.get('required')}`",
        f"- Open actions: `{punch_list.get('open_action_count', 0)}`",
        f"- Blocking actions: `{punch_list.get('blocking_action_count', 0)}`",
        "",
        "| Gate | Phase | Status | Resolution |",
        "|---|---|---|---|",
    ]
    for action in punch_list.get("actions") or []:
        resolution = str(action.get("resolution") or "").replace("|", "\\|")
        lines.append(
            f"| `{action.get('gate')}` | `{action.get('phase')}` | `{action.get('status')}` | {resolution} |"
        )
    lines.extend(
        [
            "",
            "## Outputs",
            "",
        ]
    )
    for key, value in outputs.items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    return "\n".join(lines)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown(path: Path, markdown: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")


def tail_lines(text: str, *, limit: int) -> list[str]:
    lines = text.splitlines()
    return lines[-limit:]


if __name__ == "__main__":
    main()
