#!/usr/bin/env python3
"""Compile the two missing real Mussafah_00 five-state SWMM inputs.

The customer five-state comparison contains two underground-box states that
were previously described but had not been written into an executable model:

* L2+B: six boxes without the Parsons objects;
* L2+A+B: the Parsons model plus the same six boxes.

The boxes are represented as one-dimensional SWMM Storage nodes.  They do not
modify the DTM and they do not receive a second two-dimensional basin volume;
surface water reaches them through the existing SWMM node exchange and the
declared inlet conduits.  The spatial locations and invert levels come from
the supplied five-state HTML.  The hydraulic outlet target is selected from
the nearest lower-invert model node so the outlet is hydraulically active in
the declared 2 m box depth.  This is a reproducible model compilation, not a
construction approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree


ROOT = Path("/Users/zhouning")
FORMAL = ROOT / "Downloads/阿布扎比/flood/解决方案_20260924/下一阶段推进_20260925/正式场景编译_20260926"
OUT = FORMAL / "five_state"
BASE_L2 = FORMAL / "MUSSAFAH_SOURCE_MODEL_L2_PROXY/Mussafah_00.inp"
BASE_PARSONS = FORMAL / "MUSSAFAH_L2PLUS_A_PARSONS_REPORT_PO2/Mussafah_00.inp"

# Pixel-to-UTM transform calibrated to the three Parsons points in the model
# package: STO-PO3, W-4 and W-6.  The original HTML does not store UTM values.
CALIBRATION = [
    ((1081.0, 4458.0), (248709.867545518, 2695090.98163926)),
    ((1091.0, 4588.0), (248717.751526995, 2694960.58336574)),
    ((1007.0, 393.0), (248708.650765565, 2699165.55407604)),
]


def _affine() -> tuple[np.ndarray, np.ndarray]:
    a = np.array([[1.0, p[0], p[1]] for p, _ in CALIBRATION])
    bx = np.array([xy[0] for _, xy in CALIBRATION])
    by = np.array([xy[1] for _, xy in CALIBRATION])
    return np.linalg.solve(a, bx), np.linalg.solve(a, by)


AX, AY = _affine()


# The two point sets are the report's relocated locations.  Capacities and
# bottom/top levels are transcribed from the HTML.  L2+B has a different
# sizing run but no separate level table; it uses the same 2 m construction
# level standard and its own usable capacities.
POINTS = {
    "L2+B": [(1, 1250, 4350), (2, 1247, 3896), (3, 1527, 5897), (4, 1411, 3334), (5, 1089, 4592), (6, 1356, 2167)],
    "L2+A+B": [(1, 1243, 4156), (2, 1523, 5888), (3, 1246, 3797), (4, 1126, 4593), (5, 1407, 3285), (6, 1358, 2228)],
}
CAPACITY_M3 = {
    "L2+B": {1: 5799.0, 2: 4161.0, 3: 3300.0, 4: 1803.0, 5: 1753.0, 6: 1217.0},
    "L2+A+B": {1: 5309.0, 2: 3298.0, 3: 2947.0, 4: 2000.0, 5: 1581.0, 6: 1136.0},
}
BOTTOM_M = {1: 0.15, 2: -0.06, 3: 0.27, 4: 0.08, 5: -0.28, 6: -0.37}
TOP_M = {1: 2.15, 2: 1.94, 3: 2.27, 4: 2.08, 5: 1.72, 6: 1.63}
INLET_DIAM_M = {1: 0.40, 2: 0.30, 3: 0.30, 4: 0.30, 5: 0.30, 6: 0.30}
INLET_LENGTH_M = {1: 61.0, 2: 87.0, 3: 20.0, 4: 257.0, 5: 69.0, 6: 56.0}


def parse_sections(path: Path) -> tuple[list[str], dict[str, tuple[int, int]]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    starts: list[tuple[str, int]] = []
    for i, raw in enumerate(lines):
        s = raw.strip().upper()
        if s.startswith("[") and s.endswith("]"):
            starts.append((s, i))
    spans: dict[str, tuple[int, int]] = {}
    for j, (name, start) in enumerate(starts):
        spans[name] = (start + 1, starts[j + 1][1] if j + 1 < len(starts) else len(lines))
    return lines, spans


def tokens(line: str) -> list[str]:
    return line.split(";")[0].strip().split()


def section_rows(lines: list[str], spans: dict[str, tuple[int, int]], name: str) -> list[str]:
    start, end = spans[name]
    return lines[start:end]


def section_insert(lines: list[str], spans: dict[str, tuple[int, int]], name: str, rows: list[str]) -> list[str]:
    start, end = spans[name]
    return lines[:end] + rows + lines[end:]


def section_inventory(path: Path) -> tuple[dict[str, tuple[float, float]], dict[str, float], list[tuple[str, str, str, float]]]:
    lines, spans = parse_sections(path)
    coords: dict[str, tuple[float, float]] = {}
    inv: dict[str, float] = {}
    links: list[tuple[str, str, str, float]] = []
    for raw in section_rows(lines, spans, "[COORDINATES]"):
        p = tokens(raw)
        if len(p) >= 3:
            coords[p[0]] = (float(p[1]), float(p[2]))
    for raw in section_rows(lines, spans, "[JUNCTIONS]") + section_rows(lines, spans, "[STORAGE]") + section_rows(lines, spans, "[OUTFALLS]"):
        p = tokens(raw)
        if len(p) >= 2:
            inv[p[0]] = float(p[1])
    for raw in section_rows(lines, spans, "[CONDUITS]"):
        p = tokens(raw)
        if len(p) >= 4:
            links.append((p[0], p[1], p[2], float(p[3])))
    return coords, inv, links


def choose_network_nodes(coords: dict[str, tuple[float, float]], inv: dict[str, float], links: list[tuple[str, str, str, float]], scenario: str) -> list[dict]:
    point_xy = []
    for i, px, py in POINTS[scenario]:
        q = np.array([1.0, px, py])
        point_xy.append((i, float(q @ AX), float(q @ AY)))
    candidate_nodes = [name for name in coords if name in inv and not name.startswith("PMP") and name not in {"STO-PO3", "W-4", "W-6"}]
    tree = cKDTree(np.array([coords[n] for n in candidate_nodes]))
    selected = []
    for i, x, y in point_xy:
        bottom, top = BOTTOM_M[i], TOP_M[i]
        d, idx = tree.query((x, y), k=min(30, len(candidate_nodes)))
        inlet = None
        for dd, jj in zip(np.atleast_1d(d), np.atleast_1d(idx)):
            node = candidate_nodes[int(jj)]
            # `selected` contains metadata dictionaries; keep inlets unique so
            # two boxes do not accidentally share the same source node.
            if node not in {r["inlet_node"] for r in selected}:
                inlet = node
                break
        if inlet is None:
            inlet = candidate_nodes[int(np.atleast_1d(idx)[0])]

        # Select the nearest lower-invert node for an active gravity outlet.
        lower = [(name, math_distance(coords[name], (x, y))) for name in candidate_nodes if inv[name] < top - 0.05 and name != inlet]
        lower.sort(key=lambda row: row[1])
        outlet = lower[0][0]
        selected.append({
            "id": i,
            "x": x,
            "y": y,
            "inlet_node": inlet,
            "outlet_node": outlet,
            "inlet_distance_m": math_distance(coords[inlet], (x, y)),
            "outlet_distance_m": math_distance(coords[outlet], (x, y)),
            "inlet_invert_m": inv[inlet],
            "outlet_invert_m": inv[outlet],
            "bottom_m": bottom,
            "top_m": top,
            "capacity_m3": CAPACITY_M3[scenario][i],
            "inlet_diameter_m": INLET_DIAM_M[i],
            "inlet_length_m": INLET_LENGTH_M[i],
        })
    return selected


def math_distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5)


def compile_state(base: Path, scenario: str, destination: Path) -> dict:
    lines, spans = parse_sections(base)
    coords, inv, links = section_inventory(base)
    selected = choose_network_nodes(coords, inv, links, scenario)
    existing = set(coords)
    storage_rows: list[str] = []
    curve_rows: list[str] = []
    coord_rows: list[str] = []
    conduit_rows: list[str] = []
    xsection_rows: list[str] = []

    for item in selected:
        i = item["id"]
        sid = f"BX-NP{i}"
        inlet_id = f"BX-NP{i}-IN"
        outlet_id = f"BX-NP{i}-OUT"
        curve_id = f"BX-NP{i}-CURVE"
        if sid in existing or inlet_id in existing or outlet_id in existing:
            raise RuntimeError(f"duplicate_box_id:{sid}")
        existing.update({sid, inlet_id, outlet_id})
        depth = item["top_m"] - item["bottom_m"]
        storage_rows.append(f"{sid} {item['bottom_m']:.3f} {depth:.3f} 0 TABULAR {curve_id} 0 0 0 0 0")
        curve_rows.extend([
            f"{curve_id} STORAGE 0 0",
            f"{curve_id} {depth:.3f} {item['capacity_m3']:.3f}",
        ])
        coord_rows.append(f"{sid} {item['x']:.3f} {item['y']:.3f}")
        inlet_d = item["inlet_diameter_m"]
        outlet_d = 0.30
        conduit_rows.extend([
            f"{inlet_id} {item['inlet_node']} {sid} {item['inlet_length_m']:.3f} 0.013 0 0 0 0",
            f"{outlet_id} {sid} {item['outlet_node']} {item['outlet_distance_m']:.3f} 0.013 0 0 0 0",
        ])
        xsection_rows.extend([
            f"{inlet_id} CIRCULAR {inlet_d:.3f} 0 0 0 1 0",
            f"{outlet_id} CIRCULAR {outlet_d:.3f} 0 0 0 1 0",
        ])

    # Insert rows in reverse section order so previously calculated spans stay valid.
    for name, rows in (("[XSECTIONS]", xsection_rows), ("[CONDUITS]", conduit_rows), ("[CURVES]", curve_rows), ("[STORAGE]", storage_rows), ("[COORDINATES]", coord_rows)):
        lines = section_insert(lines, spans, name, ["; Five-state underground box culvert additions"] + rows)
        lines, spans = parse_sections_from_lines(lines)

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    metadata = {
        "schema": "gwm.abu_dhabi_flood.mussafah00.five_state_box_compilation.v1",
        "scenario": scenario,
        "source_model": str(base),
        "source_sha256": hashlib.sha256(base.read_bytes()).hexdigest(),
        "output_model": str(destination),
        "dtm_modified": False,
        "hydraulic_representation": "SWMM Storage + two gravity conduits per box; boxes remain 1D assets",
        "surface_exchange": "existing SWMM junction exchange; no duplicate 2D basin storage",
        "candidate_basis": "Mussafah 五态缺口.html relocated NP1-NP6 points, capacity and levels",
        "engineering_admitted": False,
        "items": selected,
    }
    destination.with_suffix(".metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return metadata


def parse_sections_from_lines(lines: list[str]) -> tuple[list[str], dict[str, tuple[int, int]]]:
    starts: list[tuple[str, int]] = []
    for i, raw in enumerate(lines):
        s = raw.strip().upper()
        if s.startswith("[") and s.endswith("]"):
            starts.append((s, i))
    spans: dict[str, tuple[int, int]] = {}
    for j, (name, start) in enumerate(starts):
        spans[name] = (start + 1, starts[j + 1][1] if j + 1 < len(starts) else len(lines))
    return lines, spans


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for scenario, base in (("L2+B", BASE_L2), ("L2+A+B", BASE_PARSONS)):
        target = args.out / scenario.replace("+", "plus") / "Mussafah_00.inp"
        metadata = compile_state(base, scenario, target)
        rows.append({"scenario": scenario, "path": str(target), "box_count": len(metadata["items"]), "capacity_m3": sum(item["capacity_m3"] for item in metadata["items"])})
    (args.out / "manifest.json").write_text(json.dumps({"schema": "gwm.abu_dhabi_flood.mussafah00.five_state_compile_manifest.v1", "states": rows, "engineering_admitted": False}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False))


if __name__ == "__main__":
    main()
