"""Evidence-based admission for Abu Dhabi hydraulic result bundles.

Directory names, a ``completed`` status, or successful execution inside a
container do not prove that a result was produced by a coupled 1D/2D model.
This module classifies a bundle from its native SWMM artifacts and coupling
receipt so surface-only ANUGA results cannot be presented as SWMM--ANUGA runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_SURFACE_ONLY_MODES = {
    "direct_2d_rainfall",
    "direct_2d_uniform_rainfall",
    "surface_rainfall_only",
}
_ONE_WAY_MODES = {
    "one_way_swmm_to_anuga",
    "swmm_to_anuga",
}
_TWO_WAY_MODES = {
    "two_way_swmm_anuga",
    "synchronous_two_way_swmm_anuga_surface_exchange",
}


def _json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _declared_mode(
    summary: dict[str, Any], runtime: dict[str, Any], receipt: dict[str, Any]
) -> str:
    coupling = _dict(summary.get("coupling"))
    coupling_summary = _dict(summary.get("coupling_summary"))
    model_configuration = _dict(summary.get("model_configuration"))
    candidates = (
        runtime.get("mode"),
        coupling_summary.get("coupling_mode"),
        model_configuration.get("coupling_mode"),
        coupling.get("mode"),
        receipt.get("coupling_mode"),
    )
    for candidate in candidates:
        normalized = str(candidate or "").strip().lower()
        if normalized:
            return normalized
    return "unreported"


def _referenced_path(root: Path, value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return candidate.resolve()
    except OSError:
        return candidate


def _first_existing(paths: list[Path | None]) -> Path | None:
    for path in paths:
        if path is not None and path.is_file():
            return path
    return None


def _first_glob(root: Path, patterns: tuple[str, ...]) -> Path | None:
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if path.is_file():
                return path
    return None


def _artifact_paths(
    root: Path, summary: dict[str, Any]
) -> tuple[Path | None, Path | None, Path | None, Path | None]:
    coupling = _dict(summary.get("coupling"))
    outputs = _dict(summary.get("outputs"))
    swmm_input = _first_existing(
        [
            _referenced_path(root, coupling.get("source_inp")),
            _referenced_path(root, outputs.get("swmm_input")),
            _first_glob(root, ("*.inp", "**/*.inp")),
        ]
    )
    swmm_output = _first_existing(
        [
            _referenced_path(root, coupling.get("source_out")),
            _referenced_path(root, outputs.get("swmm_output")),
            _first_glob(root, ("*.out", "**/*.out")),
        ]
    )
    companion_report = swmm_output.with_suffix(".rpt") if swmm_output else None
    swmm_report = _first_existing(
        [
            _referenced_path(root, coupling.get("source_rpt")),
            _referenced_path(root, outputs.get("swmm_report")),
            companion_report,
            _first_glob(root, ("*.rpt", "**/*.rpt")),
        ]
    )
    receipt_path = _first_existing(
        [
            _referenced_path(root, outputs.get("coupling_receipt")),
            root / "bidirectional_coupling_receipt.json",
            root / "coupling_receipt.json",
        ]
    )
    return swmm_input, swmm_output, swmm_report, receipt_path


def _positive_int(*values: Any) -> int:
    for value in values:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return 0


def assess_hydraulic_result(
    root: Path, summary: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Classify one result bundle using native, independently checkable evidence."""

    result_root = Path(root).expanduser().resolve()
    delivery = summary if isinstance(summary, dict) else _json_object(
        result_root / "delivery_summary.json"
    )
    runtime = _json_object(result_root / "coupling_runtime.json")
    initial_receipt = _json_object(
        result_root / "bidirectional_coupling_receipt.json"
    )
    mode = _declared_mode(delivery, runtime, initial_receipt)

    if mode in _SURFACE_ONLY_MODES or (
        mode == "unreported"
        and "swmm" not in str(delivery.get("solver") or "").lower()
    ):
        return {
            "schema": "gisdataagent.abu_dhabi.hydraulic_result_admission.v1",
            "result_class": "surface_only_diagnostic",
            "declared_coupling_mode": mode,
            "is_1d_2d_coupled": False,
            "strict_coupling_evidence_passed": False,
            "engineering_admitted": False,
            "missing_evidence": [
                "native_swmm_input",
                "native_swmm_output",
                "native_swmm_report",
                "coupling_receipt",
                "coupling_window_ledger",
                "interface_bindings",
            ],
            "claim_boundary": (
                "Surface-only ANUGA diagnostic. It is not a coupled 1D/2D "
                "SWMM--ANUGA result and must not be labelled as one."
            ),
        }

    normalized_mode = (
        "one_way_swmm_to_anuga"
        if mode in _ONE_WAY_MODES
        else "two_way_swmm_anuga"
        if mode in _TWO_WAY_MODES
        else "unverified_coupling_claim"
    )
    swmm_input, swmm_output, swmm_report, receipt_path = _artifact_paths(
        result_root, delivery
    )
    receipt = _json_object(receipt_path) if receipt_path else initial_receipt
    coupling = _dict(delivery.get("coupling"))
    coupling_summary = _dict(delivery.get("coupling_summary"))
    windows = receipt.get("windows")
    interfaces = receipt.get("interface_bindings")
    window_count = _positive_int(
        coupling.get("window_count"),
        coupling_summary.get("window_count"),
        len(windows) if isinstance(windows, list) else 0,
    )
    interface_count = _positive_int(
        coupling.get("interface_count"),
        coupling_summary.get("interface_count"),
        len(interfaces) if isinstance(interfaces, list) else 0,
    )

    missing: list[str] = []
    if normalized_mode == "unverified_coupling_claim":
        missing.append("supported_coupling_mode")
    if swmm_input is None:
        missing.append("native_swmm_input")
    if swmm_output is None:
        missing.append("native_swmm_output")
    if swmm_report is None:
        missing.append("native_swmm_report")
    if receipt_path is None:
        missing.append("coupling_receipt")
    if window_count <= 0:
        missing.append("coupling_window_ledger")
    if interface_count <= 0:
        missing.append("interface_bindings")

    evidence_passed = not missing
    result_class = normalized_mode if evidence_passed else "coupled_evidence_incomplete"
    return {
        "schema": "gisdataagent.abu_dhabi.hydraulic_result_admission.v1",
        "result_class": result_class,
        "declared_coupling_mode": mode,
        "normalized_coupling_mode": normalized_mode,
        "is_1d_2d_coupled": evidence_passed,
        "strict_coupling_evidence_passed": evidence_passed,
        "engineering_admitted": False,
        "window_count": window_count,
        "interface_count": interface_count,
        "missing_evidence": missing,
        "evidence": {
            "native_swmm_input": str(swmm_input) if swmm_input else None,
            "native_swmm_output": str(swmm_output) if swmm_output else None,
            "native_swmm_report": str(swmm_report) if swmm_report else None,
            "coupling_receipt": str(receipt_path) if receipt_path else None,
        },
        "claim_boundary": (
            "Coupled execution evidence is complete; calibration and engineering "
            "admission are separate gates."
            if evidence_passed
            else "The bundle claims SWMM--ANUGA coupling, but its native evidence "
            "chain is incomplete and it must not be presented as a strictly "
            "admitted coupled 1D/2D result."
        ),
    }
