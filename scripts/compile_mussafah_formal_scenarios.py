#!/usr/bin/env python3
"""Compile and run review-only Mussafah L1/L2/L2+ SWMM counterfactuals.

The customer-confirmed production scope is Catchment 20 / Mussafah-01.  The
only runnable SWMM export currently available is the separate Parsons
Mussafah_00 package.  This utility therefore does two things explicitly:

* creates a source-model verification package from Mussafah_00;
* keeps the package marked ``engineering_admitted=false`` and records that it
  is not the formal Catchment-20 result until the Mussafah-01 1-D network is
  supplied.

The L1/L2 counterfactual removes the planned STO-PO3/PMP5 chain.  The Parsons
PO-2 counterfactual retains that chain and uses the report geometry (800 m2
top area, 400 m2 bottom area, 1.5 m depth, 3:1 side slopes) as a SWMM
stage-area curve.  No 2-D coupling is claimed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path



DEFAULT_INP = Path("/private/tmp/hydraulic_model_export_inspect/Hydraulic Model Data Export/SWMM_Export/Mussafah_00.inp")
DEFAULT_EXE = Path("/Users/zhouning/gisdataagent/external_models/swmm-5.2.4/build-local/bin/runswmm")
DEFAULT_OUT = Path("/Users/zhouning/Downloads/阿布扎比/flood/解决方案_20260924/下一阶段推进_20260925/正式场景编译_20260926")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def section_spans(lines: list[str]) -> dict[str, tuple[int, int]]:
    starts: list[tuple[str, int]] = []
    for i, raw in enumerate(lines):
        s = raw.strip().upper()
        if s.startswith("[") and s.endswith("]"):
            starts.append((s, i))
    spans: dict[str, tuple[int, int]] = {}
    for j, (name, start) in enumerate(starts):
        end = starts[j + 1][1] if j + 1 < len(starts) else len(lines)
        spans[name] = (start + 1, end)
    return spans


def replace_section(lines: list[str], name: str, transform) -> list[str]:
    spans = section_spans(lines)
    start, end = spans[name]
    body = lines[start:end]
    return lines[:start] + transform(body) + lines[end:]


def tokens(raw: str) -> list[str]:
    return raw.strip().split()


def remove_named_rows(body: list[str], names: set[str], field: int = 0) -> list[str]:
    out = []
    for raw in body:
        p = tokens(raw)
        if p and not p[0].startswith(";") and p[field] in names:
            continue
        out.append(raw)
    return out


def compile_input(source: Path, destination: Path, *, include_pond: bool) -> dict[str, object]:
    lines = source.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    # The design chain is W-4 -> PMP5 -> PMP5_Junction -> 1235 -> STO-PO3.
    if not include_pond:
        for name in ("[PUMPS]", "[CONDUITS]", "[XSECTIONS]", "[LOSSES]", "[COORDINATES]"):
            if name not in section_spans(lines):
                continue
            if name == "[PUMPS]":
                lines = replace_section(lines, name, lambda b: remove_named_rows(b, {"PMP5"}))
            elif name in {"[CONDUITS]", "[XSECTIONS]", "[LOSSES]"}:
                lines = replace_section(lines, name, lambda b: remove_named_rows(b, {"1235"}))
            elif name == "[COORDINATES]":
                lines = replace_section(lines, name, lambda b: remove_named_rows(b, {"PMP5_Junction"}))
        lines = replace_section(lines, "[STORAGE]", lambda b: remove_named_rows(b, {"STO-PO3"}))
        lines = replace_section(lines, "[CURVES]", lambda b: remove_named_rows(b, {"STO-PO3_Curve"}))
        lines = replace_section(lines, "[CONTROLS]", lambda b: [x for x in b if "STO-PO3" not in x and "PMP5" not in x and x.strip().upper() not in {"PRIORITY 1", "PRIORITY 2"}])
        # STO-PO3 is a planned storage node in the source export.  Preserve
        # the node as a junction only if another source link references it;
        # after removing 1235 it is disconnected, so remove its coordinate.
        lines = replace_section(lines, "[COORDINATES]", lambda b: remove_named_rows(b, {"STO-PO3"}))
    else:
        # Replace the source model's flat 800 m2 curve with the Parsons report
        # geometry.  The middle point linearly interpolates equivalent square
        # side lengths; it does NOT independently enforce the stated 3H:1V.
        def curve(b: list[str]) -> list[str]:
            out = []
            for raw in b:
                p = tokens(raw)
                if p and p[0] == "STO-PO3_Curve":
                    continue
                out.append(raw)
            newline = "\n"
            return out + [f"STO-PO3_Curve Storage 0 400{newline}", f"STO-PO3_Curve 0.75 582.843{newline}", f"STO-PO3_Curve 1.5 800{newline}"]
        lines = replace_section(lines, "[CURVES]", curve)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(lines), encoding="utf-8")
    return {
        "path": str(destination),
        "sha256": sha256(destination),
        "planned_pond_included": include_pond,
        "planned_chain": ["W-4", "PMP5", "PMP5_Junction", "STO-PO3"] if include_pond else [],
        "geometry": {"top_area_m2": 800.0, "bottom_area_m2": 400.0, "depth_m": 1.5,
                     "reported_side_slope_h_over_v": 3.0, "reported_capacity_m3": 900.0,
                     "curve_basis": "equivalent_square_width_interpolation_then_piecewise_linear_area",
                     "implemented_tabular_capacity_m3": 887.13225,
                     "equivalent_square_side_slope_h_over_v": (800.0**0.5-400.0**0.5)/3.0,
                     "geometry_consistency_status": "report_dimensions_and_slope_not_exactly_consistent"} if include_pond else None,
    }


def run_one(executable: Path, inp: Path, outdir: Path) -> dict[str, object]:
    rpt = outdir / (inp.stem + ".rpt")
    out = outdir / (inp.stem + ".out")
    proc = subprocess.run([str(executable), str(inp), str(rpt), str(out)], capture_output=True, text=True, timeout=900)
    receipt: dict[str, object] = {"returncode": proc.returncode, "report": str(rpt), "output": str(out), "stdout_tail": proc.stdout[-1000:], "stderr_tail": proc.stderr[-1000:]}
    if rpt.exists():
        text = rpt.read_text(encoding="utf-8", errors="replace")
        receipt["parsed_report"] = parse_external_inflow_report(text)
    return receipt


def report_section(text: str, title: str) -> str:
    """Return exactly one SWMM starred report section, never later tables."""
    headings = list(re.finditer(r"(?m)^[ \t]*\*{3,}[^\n]*\n[ \t]*([^\n*]+)\n[ \t]*\*{3,}[^\n]*", text))
    for i, match in enumerate(headings):
        if match.group(1).strip().startswith(title):
            return text[match.start():headings[i + 1].start() if i + 1 < len(headings) else len(text)]
    return ""


def parse_external_inflow_report(text: str) -> dict[str, object]:
    """Parse the report mode used by the supplied Mussafah export.

    REPORT INPUT NO hides the input summary, not rainfall/runoff statistics.
    Presence of a runoff continuity section and routing inflow values are
    inspected independently. Node flooding includes ponded water, whereas
    routing Flooding Loss counts water leaving the system; these are not
    interchangeable mass-balance terms when surface ponding is enabled.
    """
    FLOAT = r"[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][-+]?[0-9]+)?"

    def number(pattern: str, default: float | None = None) -> float | None:
        m = re.search(pattern, text, re.I)
        return float(m.group(1)) if m else default

    version = re.search(r"VERSION\s+([0-9.]+)\s+\(Build\s+([0-9.]+)\)", text, re.I)
    flow_units = re.search(r"Flow Units\s+\.+\s+([A-Z0-9/]+)", text, re.I)
    routing = re.search(r"Flow Routing Method\s+\.+\s+([A-Z0-9_-]+)", text, re.I)
    routing_sec = report_section(text, "Flow Routing Continuity")
    cont_match = re.search(rf"Continuity Error\s*\(%\)\s*\.+\s*({FLOAT})", routing_sec)
    continuity = float(cont_match.group(1)) if cont_match else None
    nonconverging = number(rf"% of Steps Not Converging\s*:\s*({FLOAT})")
    # SWMM aligns this table with dot leaders between the label and the two
    # quantities.  Capture the second value (10^6 litres) explicitly; a
    # generic ``number`` regex is easy to misalign because the labels contain
    # several spaces and the first column is also numeric.
    def routing_second_quantity(label: str) -> float | None:
        m = re.search(rf"^[ \t]*{re.escape(label)}[ \t.]+({FLOAT})[ \t]+({FLOAT})[ \t]*$", routing_sec, re.I | re.M)
        return float(m.group(2)) if m else None

    external_inflow = routing_second_quantity("External Inflow")
    external_outflow = routing_second_quantity("External Outflow")
    flooding_loss = routing_second_quantity("Flooding Loss")
    block = report_section(text, "Node Flooding Summary")
    metric_units = bool(re.search(r"10\^6\s+ltr", routing_sec, re.I))
    if routing_sec and not metric_units:
        raise ValueError("unsupported_report_units: expected 10^6 ltr; cannot label US volumes as m3")
    rows: list[dict[str, float | str]] = []
    row_re = re.compile(rf"^\s*(\S+)\s+({FLOAT})\s+({FLOAT})\s+\d+\s+\d+:\d+\s+({FLOAT})\s+({FLOAT})\s*$")
    for line in block.splitlines():
        m = row_re.match(line)
        if not m or m.group(1) in {"Node", "---"}:
            continue
        rows.append({"node_id": m.group(1), "hours_flooded": float(m.group(2)), "max_rate_lps": float(m.group(3)), "flood_volume_m3": float(m.group(4)) * 1000.0, "max_ponded_depth_m": float(m.group(5))})
    table_parsed = bool(rows) or "No nodes were flooded" in block
    total_flood = sum(float(r["flood_volume_m3"]) for r in rows) if table_parsed else None
    routing_flooding_loss_m3 = flooding_loss * 1000.0 if flooding_loss is not None else None
    warning_count = len(re.findall(r"^\s*WARNING\s+\d+", text, re.I | re.M))
    error_count = len(re.findall(r"^\s*ERROR\s+\d+", text, re.I | re.M))
    warnings = re.findall(r"^\s*(WARNING\s+\d+:[^\n]+)", text, re.I | re.M)
    errors = re.findall(r"^\s*(ERROR\s+\d+:[^\n]+)", text, re.I | re.M)
    runoff_present = bool(report_section(text, "Runoff Quantity Continuity"))
    ponding = re.search(r"Ponding Allowed\s*\.+\s*(YES|NO)", text, re.I)
    complete = bool(re.search(r"Analysis ended on:", text)) and error_count == 0 and continuity is not None
    numerical_checks = {
        "report_completed": complete,
        "absolute_continuity_le_1_percent": continuity is not None and abs(continuity) <= 1.0,
        "nonconverging_steps_le_1_percent": nonconverging is not None and nonconverging <= 1.0,
    }
    additional_volumes = {
        key: routing_second_quantity(label)
        for key, label in {
            "dry_weather_inflow_million_litre": "Dry Weather Inflow",
            "wet_weather_inflow_million_litre": "Wet Weather Inflow",
            "groundwater_inflow_million_litre": "Groundwater Inflow",
            "rdii_inflow_million_litre": "RDII Inflow",
            "evaporation_loss_million_litre": "Evaporation Loss",
            "exfiltration_loss_million_litre": "Exfiltration Loss",
            "initial_storage_million_litre": "Initial Stored Volume",
            "final_storage_million_litre": "Final Stored Volume",
        }.items()
    }
    return {
        "solver": {"name": "EPA SWMM", "version_series": version.group(1) if version else None, "version": version.group(2) if version else None},
        "analysis_options": {"flow_units": flow_units.group(1) if flow_units else None, "flow_routing_method": routing.group(1) if routing else None, "rainfall_runoff_reported": runoff_present, "external_inflow_model": external_inflow is not None and external_inflow > 0, "ponding_allowed": ponding.group(1).upper() == "YES" if ponding else None},
        "flow_routing_continuity": {"external_inflow_million_litre": external_inflow, "external_outflow_million_litre": external_outflow, "flooding_loss_million_litre": flooding_loss, "continuity_error_percent": continuity, **additional_volumes},
        "stability": {"all_links_stable": True if "All links are stable" in text else None, "instability_table_present": bool(report_section(text, "Highest Flow Instability Indexes"))},
        "convergence": {"steps_not_converging_percent": nonconverging},
        "node_flooding": {"summary_present": bool(block), "table_parsed": table_parsed, "flooded_node_count": len(rows) if table_parsed else None, "total_flood_volume_m3": total_flood, "maximum_ponded_depth_m": max((float(r["max_ponded_depth_m"]) for r in rows), default=0.0) if table_parsed else None, "rows": rows, "volume_is_sum_of_rounded_report_values": True, "not_a_2d_inundation_measure": True},
        "quality": {
            "warning_count": warning_count,
            "error_count": error_count,
            "routing_flooding_loss_m3": routing_flooding_loss_m3,
            "report_completed_without_errors": complete,
            "warnings": warnings,
            "errors": errors,
            "numerical_screen": {"policy": "project diagnostic screening only; not an EPA or engineering acceptance standard", "checks": numerical_checks, "passed": all(numerical_checks.values())},
            "node_flood_volume_equals_routing_loss_required": False,
            "volume_metric_semantics": "Node flooding includes ponding; routing flooding loss is water lost from the system. Do not equate or sum them.",
        },
        "admission": {"engineering_admitted": False, "rainfall_runoff_statistics_not_available": not runoff_present},
    }


def execution_status(execution: dict) -> str:
    valid = execution.get("returncode") == 0 and execution.get("parsed_report", {}).get("quality", {}).get("report_completed_without_errors")
    return "completed_diagnostic" if valid else "failed_diagnostic"


def reparse_existing(root: Path) -> dict:
    """Refresh receipts from preserved RPTs without rerunning the solver."""
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = []
    for old in manifest["scenarios"]:
        receipt_path = root / old["scenario_id"] / "scenario_receipt.json"
        record = json.loads(receipt_path.read_text(encoding="utf-8"))
        execution = record["execution"]
        execution["parsed_report"] = parse_external_inflow_report(Path(execution["report"]).read_text(encoding="utf-8", errors="replace"))
        record["status"] = execution_status(execution)
        record["parser_version"] = "routing_and_flooding_v2"
        record["engineering_admitted"] = False
        if record["input"].get("geometry"):
            geom = record["input"]["geometry"]
            geom["reported_side_slope_h_over_v"] = geom.pop("side_slope_h_over_v", 3.0)
            geom.update({"curve_basis": "equivalent_square_width_interpolation_then_piecewise_linear_area", "implemented_tabular_capacity_m3": 887.13225, "equivalent_square_side_slope_h_over_v": (800**.5-400**.5)/3, "geometry_consistency_status": "report_dimensions_and_slope_not_exactly_consistent"})
        receipt_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        records.append(record)
    manifest["scenarios"] = records
    manifest["status"] = "diagnostic_source_model_package_complete" if all(r["status"] == "completed_diagnostic" for r in records) else "diagnostic_source_model_package_incomplete"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inp", type=Path, default=DEFAULT_INP)
    ap.add_argument("--executable", type=Path, default=DEFAULT_EXE)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--no-run", action="store_true")
    ap.add_argument("--reparse-only", action="store_true", help="Refresh existing RPT receipts without rerunning SWMM")
    args = ap.parse_args()
    if args.reparse_only:
        manifest = reparse_existing(args.output.resolve())
        print(json.dumps({"output": str(args.output), "status": manifest["status"]}, ensure_ascii=False))
        return 0
    if not args.inp.exists():
        raise SystemExit(f"missing_input:{args.inp}")
    if not args.executable.exists():
        raise SystemExit(f"missing_executable:{args.executable}")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    scenarios = [
        ("MUSSAFAH_SOURCE_MODEL_L1_PROXY", False, "L1 proxy with Parsons planned STO-PO3/PMP5 chain removed"),
        ("MUSSAFAH_SOURCE_MODEL_L2_PROXY", False, "L2 proxy; Catchment-20 database pond count is zero, therefore no incremental pond"),
        ("MUSSAFAH_L2PLUS_A_PARSONS_REPORT_PO2", True, "Parsons report PO-2/STO-PO3 geometry and pump chain"),
    ]
    records = []
    for scenario, pond, note in scenarios:
        d = root / scenario
        d.mkdir(parents=True, exist_ok=True)
        compiled = compile_input(args.inp, d / "Mussafah_00.inp", include_pond=pond)
        record: dict[str, object] = {"scenario_id": scenario, "source_scope": "Mussafah_00 Parsons package", "status": "compiled", "note": note, "input": compiled, "engineering_admitted": False, "formal_catchment20_result": False}
        if not args.no_run:
            record["execution"] = run_one(args.executable, d / "Mussafah_00.inp", d)
            record["status"] = execution_status(record["execution"])
        (d / "scenario_receipt.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        records.append(record)
    manifest = {
        "schema": "gwm.abu_dhabi_flood.mussafah_formal_scenario_compile.v1",
        "status": "diagnostic_source_model_package_complete",
        "engineering_admitted": False,
        "formal_scope": {"catchment_fid": 20, "catchment_name": "Mussafah_01", "area_km2": 7.372614},
        "source_model_scope": {"model": "Mussafah_00", "area_ha": 149.0, "relationship": "separate Parsons report/model package; not interchangeable with Catchment 20"},
        "scenarios": records,
        "quality_boundary": [
            "The L1/L2 proxy removes planned STO-PO3/PMP5 from the Mussafah_00 source model; it is not yet the Catchment-20 as-built L1 model.",
            "The Parsons PO-2 run is a 1-D source-model diagnostic only; no 2-D surface exchange is executed.",
            "Mussafah-01 five-pond GIS topology is separately audited and must receive a matching one-dimensional network before formal runs.",
            "All outputs remain engineering_admitted=false until customer data, boundaries, controls and validation events are approved.",
        ],
        "next_blocker": "Mussafah-01 complete L1 SWMM network/input plus rainfall, tailwater and control/operation data",
    }
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(root), "scenarios": [x["scenario_id"] for x in records]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
