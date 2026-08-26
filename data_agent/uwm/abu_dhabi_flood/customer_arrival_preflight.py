"""Orchestrate the private Abu Dhabi customer-data arrival preflight.

This module deliberately separates evidence checks from model execution.  It
can be run when a customer delivery arrives, but it never admits SWMM,
calibration, GWM training, a hybrid planner, or city-scale claims.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .customer_event_validation import (
    EventValidationPolicy,
    validate_customer_event_csv,
)
from .customer_gdb_network import (
    _require_private_output_root,
    compile_customer_gdb_network,
)
from .customer_receipt_acceptance import accept_customer_receipt

SCHEMA = "gwm.abu_dhabi_flood.customer_arrival_preflight.v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path_status(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"provided": False, "exists": False}
    resolved = path.expanduser().resolve()
    return {
        "provided": True,
        "path": str(resolved),
        "exists": resolved.exists(),
        "is_file": resolved.is_file(),
        "is_directory": resolved.is_dir(),
    }


def _stage(status: str, *, reasons: Sequence[str] = (), **details: Any) -> dict[str, Any]:
    return {"status": status, "reasons": list(reasons), **details}


def _run_receipt_stage(
    workbook: Path | None,
    register: Path | None,
    data_roots: Sequence[Path],
) -> dict[str, Any]:
    if workbook is None and register is None:
        return _stage("not_requested", action="provide_customer_receipt_and_issue_register")
    if workbook is None or register is None:
        return _stage(
            "input_incomplete",
            reasons=["receipt_workbook_and_issue_register_are_a_pair"],
            action="provide_both_receipt_workbook_and_issue_register",
            workbook=_path_status(workbook),
            register=_path_status(register),
        )
    try:
        payload = accept_customer_receipt(workbook, register, list(data_roots) or None)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return _stage(
            "failed",
            reasons=[str(error)],
            action="correct_receipt_and_register_before_model_work",
            workbook=_path_status(workbook),
            register=_path_status(register),
        )
    summary = payload["summary"]
    return _stage(
        "accepted" if payload["status"] == "customer_receipt_accepted" else "requires_action",
        action=(
            "continue_to_spatial_and_temporal_prechecks"
            if payload["status"] == "customer_receipt_accepted"
            else "return_receipt_for_customer_completion"
        ),
        acceptance_status=payload["status"],
        summary=summary,
        admission=payload["admission"],
    )


def _run_event_stage(
    *,
    csv_path: Path | None,
    metadata_path: Path | None,
    event_kind: str | None,
    output_root: Path,
    timestamp_column: str,
    value_column: str,
    cadence_minutes: int | None,
    event_id: str | None,
    validate: bool,
) -> dict[str, Any]:
    provided = (csv_path is not None, metadata_path is not None, event_kind is not None)
    if not any(provided):
        return _stage("not_requested", action="provide_authoritative_event_csv_and_metadata")
    if not all(provided):
        return _stage(
            "input_incomplete",
            reasons=["event_csv_metadata_and_event_kind_are_a_triplet"],
            action="provide_event_csv_metadata_and_event_kind",
            csv=_path_status(csv_path),
            metadata=_path_status(metadata_path),
            event_kind=event_kind,
        )
    assert csv_path is not None and metadata_path is not None and event_kind is not None
    if not csv_path.expanduser().is_file() or not metadata_path.expanduser().is_file():
        return _stage(
            "input_incomplete",
            reasons=["event_csv_or_metadata_not_found"],
            action="place_event_csv_and_metadata_in_private_delivery_root",
            csv=_path_status(csv_path),
            metadata=_path_status(metadata_path),
            event_kind=event_kind,
        )
    if not validate:
        return _stage(
            "ready_to_validate",
            action="rerun_with_validate_event",
            csv=_path_status(csv_path),
            metadata=_path_status(metadata_path),
            event_kind=event_kind,
        )
    try:
        payload = validate_customer_event_csv(
            csv_path=csv_path,
            metadata_path=metadata_path,
            output_root=output_root / "event_validation",
            policy=EventValidationPolicy(
                event_kind=event_kind,
                timestamp_column=timestamp_column,
                value_column=value_column,
                cadence_minutes=cadence_minutes,
                event_id=event_id,
            ),
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return _stage(
            "failed",
            reasons=[str(error)],
            action="correct_event_file_or_metadata_before_SWMM_binding",
            csv=_path_status(csv_path),
            metadata=_path_status(metadata_path),
            event_kind=event_kind,
        )
    return _stage(
        "accepted" if payload["accepted"] else "requires_action",
        action=(
            "continue_to_SWMM_forcing_binding"
            if payload["accepted"]
            else "return_event_delivery_for_correction"
        ),
        accepted=payload["accepted"],
        event_status=payload["status"],
        source=payload["source"],
        quality=payload["quality"],
        reasons=payload["reasons"],
        admission=payload["admission"],
    )


def _run_network_stage(
    *,
    gdb_path: Path | None,
    output_root: Path,
    source_archive_path: Path | None,
    compile_network: bool,
) -> dict[str, Any]:
    if gdb_path is None:
        return _stage("not_requested", action="provide_customer_gdb_for_network_compile")
    if not gdb_path.expanduser().exists():
        return _stage(
            "input_incomplete",
            reasons=["customer_gdb_not_found"],
            action="place_customer_gdb_in_private_delivery_root",
            gdb=_path_status(gdb_path),
            source_archive=_path_status(source_archive_path),
        )
    if not compile_network:
        return _stage(
            "ready_to_compile",
            action="rerun_with_compile_network",
            gdb=_path_status(gdb_path),
            source_archive=_path_status(source_archive_path),
        )
    try:
        manifest = compile_customer_gdb_network(
            gdb_path,
            output_root=output_root / "network_compile",
            source_archive_path=source_archive_path,
        )
    except (OSError, ValueError, RuntimeError) as error:
        return _stage(
            "failed",
            reasons=[str(error)],
            action="correct_GDB_layers_or_engineering_metadata_before_SWMM_compile",
            gdb=_path_status(gdb_path),
            source_archive=_path_status(source_archive_path),
        )
    return _stage(
        "compiled",
        action="run_network_audit_then_compile_SWMM",
        manifest_schema=manifest.get("schema"),
        diagnostic_only=manifest.get("diagnostic_only"),
        admitted=manifest.get("admitted"),
        outputs=manifest.get("outputs"),
        topology_audit=manifest.get("topology_audit"),
    )


def _next_gate(stages: dict[str, dict[str, Any]]) -> str:
    receipt = stages["receipt"]["status"]
    if receipt in {"requires_action", "failed", "input_incomplete"}:
        return "customer_receipt_completion"
    event = stages["event"]["status"]
    if event in {"requires_action", "failed", "input_incomplete"}:
        return "customer_event_correction"
    network = stages["network"]["status"]
    if network in {"failed", "input_incomplete"}:
        return "customer_gdb_correction"
    if network in {"not_requested", "ready_to_compile"}:
        return "customer_network_compile"
    if event in {"not_requested", "ready_to_validate"}:
        return "authoritative_event_validation"
    return "engineering_network_audit_and_SWMM_binding"


def run_customer_arrival_preflight(
    *,
    output_root: Path,
    receipt_workbook: Path | None = None,
    issue_register: Path | None = None,
    data_roots: Sequence[Path] = (),
    gdb_path: Path | None = None,
    source_archive_path: Path | None = None,
    compile_network: bool = False,
    event_csv: Path | None = None,
    event_metadata: Path | None = None,
    event_kind: str | None = None,
    validate_event: bool = False,
    timestamp_column: str = "timestamp",
    value_column: str = "value",
    cadence_minutes: int | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Run available private arrival checks and write a hashable receipt."""

    root = _require_private_output_root(output_root)
    root.mkdir(parents=True, exist_ok=True)
    stages = {
        "receipt": _run_receipt_stage(receipt_workbook, issue_register, data_roots),
        "event": _run_event_stage(
            csv_path=event_csv,
            metadata_path=event_metadata,
            event_kind=event_kind,
            output_root=root,
            timestamp_column=timestamp_column,
            value_column=value_column,
            cadence_minutes=cadence_minutes,
            event_id=event_id,
            validate=validate_event,
        ),
        "network": _run_network_stage(
            gdb_path=gdb_path,
            output_root=root,
            source_archive_path=source_archive_path,
            compile_network=compile_network,
        ),
    }
    next_gate = _next_gate(stages)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "version": "2026-08-24",
        "status": "preflight_complete",
        "output_root": str(root),
        "stages": stages,
        "next_gate": next_gate,
        "model_gate_summary": {
            "traditional_model_admitted": False,
            "engineering_calibration_admitted": False,
            "gwm_training_admitted": False,
            "hybrid_planner_admitted": False,
            "city_scale_prediction_claim_allowed": False,
        },
        "claim_boundary": [
            "public_proxy_or_customer_receipt_checks_do_not_replace_engineering_review",
            "network_compile_is_diagnostic_only_until_units_elevations_boundaries_and_flow_direction_are_accepted",
            "event_temporal_QC_does_not_establish_hydraulic_calibration",
            "customer_rows_and_credentials_must_remain_outside_the_public_repository",
        ],
    }
    json_path = root / "abu_dhabi_customer_arrival_preflight.json"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    payload["report"] = {
        "json": str(json_path),
        "payload_without_report_sha256": _sha256(json_path),
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def render_customer_arrival_preflight_markdown(payload: dict[str, Any]) -> str:
    """Render a concise operator/customer handoff summary."""

    lines = [
        "# 阿布扎比城市暴雨内涝世界模型",
        "## 客户数据到达预检",
        "",
        f"下一准入：**{payload['next_gate']}**。本报告只记录数据验收和编译状态，不打开任何模型准入开关。",
        "",
        "| 阶段 | 状态 | 下一动作 |",
        "|---|---|---|",
    ]
    for name in ("receipt", "event", "network"):
        stage = payload["stages"][name]
        lines.append(f"| {name} | {stage['status']} | {stage.get('action', '')} |")
    lines.extend(
        [
            "",
            "## 准入边界",
            "",
            "- 传统模型正式准入：关闭",
            "- 工程校准：关闭",
            "- GWM训练：关闭",
            "- 混合规划器：关闭",
            "- 城市级预测声明：关闭",
            "",
            "后续客户数据应按“回执验收 -> 网络编译/拓扑审计 -> 事件时序校验 -> "
            "SWMM绑定与运行 -> 空间结果提取 -> 二维模型校准 -> GWM训练”的顺序推进。",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "SCHEMA",
    "run_customer_arrival_preflight",
    "render_customer_arrival_preflight_markdown",
]
