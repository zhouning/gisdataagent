"""Read-only audit of the delivered AAM L2 pond and its native SWMM results.

Reads GIS/native files and writes a separate evidence directory. Does not change
the prepared inputs, run results, source GIS, or application configuration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
import shapely
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree


def dump(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def native_series(path: Path, component_links, upstream_links, upstream_nodes,
                  pond_node: int, seam_nodes: tuple[int, int]):
    """Read SWMM 5.2 OUT using its stored IDs, properties, and variable codes.

    Layout is checked against src/solver/output.c; no SWMM model is opened or run.
    """
    with path.open("rb") as f:
        magic, version, flow_units, ns, nn, nl, npoll = struct.unpack("<7i", f.read(28))
        f.seek(-24, 2)
        id_pos, input_pos, out_pos, periods, error, end_magic = struct.unpack("<6i", f.read(24))
        assert magic == end_magic == 516114522 and error == 0
        assert version == 52004 and flow_units == 3 and ns == 0 and npoll == 0
        f.seek(id_pos)
        ids = []
        for count in (ns, nn, nl, npoll):
            group = []
            for _ in range(count):
                size = struct.unpack("<i", f.read(4))[0]
                group.append(f.read(size).decode())
            ids.append(group)
        f.seek(input_pos)
        for count in (ns, nn, nl):
            properties = struct.unpack("<i", f.read(4))[0]
            f.seek(4 * properties * (count + 1), 1)
        variable_codes = []
        for _ in range(4):
            count = struct.unpack("<i", f.read(4))[0]
            variable_codes.append(struct.unpack("<" + "i" * count, f.read(4 * count)))
        _, step = struct.unpack("<di", f.read(12))
        assert f.tell() == out_pos
        assert variable_codes[1] == (0, 1, 2, 3, 4, 5)
        assert variable_codes[2] == (0, 1, 2, 3, 4)
        sv, nv, lv, syv = map(len, variable_codes)
        bytes_per_period = 8 + 4 * (ns * sv + nn * nv + nl * lv + syv)
        assert out_pos + periods * bytes_per_period + 24 == path.stat().st_size
        node_index = {name: k for k, name in enumerate(ids[1])}
        link_index = {name: k for k, name in enumerate(ids[2])}
        branch_idx = [link_index[f"C{k:06d}"] for k in component_links.index]
        upstream_idx = [link_index[f"C{k:06d}"] for k in upstream_links.index]
        upstream_node_idx = [node_index[f"N{k:06d}"] for k in upstream_nodes.native_node]
        seam_pipe = upstream_links[upstream_links.start_node.eq(seam_nodes[1]) |
                                   upstream_links.end_node.eq(seam_nodes[1])]
        target_node_names = [f"N{k:06d}" for k in [pond_node, *seam_nodes]]
        rows = []
        for period in range(periods):
            f.seek(out_pos + period * bytes_per_period)
            f.read(8)
            nodes = np.frombuffer(f.read(nn * nv * 4), dtype="<f4").reshape(nn, nv)
            links = np.frombuffer(f.read(nl * lv * 4), dtype="<f4").reshape(nl, lv)
            row = {"time_seconds": (period + 1) * step}
            for name in target_node_names:
                labels = ("depth_m", "head_m", "volume_m3", "lateral_inflow_cms",
                          "total_inflow_cms", "overflow_cms")
                for k, label in enumerate(labels):
                    row[f"{name}_{label}"] = float(nodes[node_index[name], k])
            row["pond_component_max_abs_link_flow_cms"] = float(np.max(np.abs(links[branch_idx, 0])))
            row["upstream_component_lateral_inflow_cms"] = float(nodes[upstream_node_idx, 3].sum())
            row["upstream_component_max_abs_link_flow_cms"] = float(np.max(np.abs(links[upstream_idx, 0])))
            for k in seam_pipe.index:
                row[f"C{k:06d}_flow_cms"] = float(links[link_index[f"C{k:06d}"], 0])
            rows.append(row)
        metadata = {"version": version, "flow_units": "m3/s", "periods": periods,
                    "report_step_seconds": step, "node_count": nn, "link_count": nl,
                    "node_variable_codes": variable_codes[1], "link_variable_codes": variable_codes[2],
                    "file_layout_size_verified": True, "native_error_code": error}
        return pd.DataFrame(rows), metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run, source, out = args.run_root, args.source_root, args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    boundary = pyogrio.read_dataframe(source / "aam_boundary.gpkg").to_crs(32640).geometry.union_all()
    inventory = []
    for gdb in sorted((source / "aa_wr").glob("*.gdb")) + [source / "stormwater.gdb"]:
        for layer, geom in pyogrio.list_layers(gdb):
            keys = ("POND", "RESERVOIR", "TANK", "WET_WELL", "DITCH", "SPILLWAY",
                    "SOAKAWAY", "CATCHBASIN", "WATERSTRUCT", "WATERSTRUCTER")
            if not geom or not any(k in layer.upper() for k in keys):
                continue
            data = pyogrio.read_dataframe(gdb, layer=layer)
            selected = data.to_crs(32640).geometry.intersects(boundary) if len(data) else []
            inventory.append({"gdb": gdb.name, "layer": layer, "total_records": len(data),
                              "aam_intersecting_records": int(sum(selected)), "source_crs": str(data.crs)})
    pd.DataFrame(inventory).to_csv(out / "facility_inventory.csv", index=False)

    nodes = pd.read_csv(run / "prepared/node_mapping.csv")
    links = pd.read_csv(run / "prepared/link_mapping_and_adaptations.csv")
    interfaces = np.load(run / "prepared/L2/interfaces.npz")
    pond = int(interfaces["pond_logical_index"])
    valid = links[links.included]
    graph = coo_matrix((np.ones(len(valid) * 2),
                        (np.r_[valid.start_node, valid.end_node],
                         np.r_[valid.end_node, valid.start_node])),
                       shape=(len(nodes), len(nodes))).tocsr()
    _, labels = connected_components(graph, directed=False)
    pond_nodes = nodes[labels == labels[pond]]
    pond_links = valid[valid.start_node.isin(pond_nodes.native_node)]
    others = nodes[labels != labels[pond]]
    dist, nearest = cKDTree(others[["x_m", "y_m"]]).query(pond_nodes[["x_m", "y_m"]])
    k = int(np.argmin(dist))
    a, b = pond_nodes.iloc[k], others.iloc[nearest[k]]
    seam = (int(a.native_node), int(b.native_node))
    upstream_nodes = nodes[labels == labels[seam[1]]]
    upstream_links = valid[valid.start_node.isin(upstream_nodes.native_node)]
    for name, data in (("pond_component_nodes", pond_nodes), ("pond_component_links", pond_links),
                       ("upstream_component_nodes", upstream_nodes), ("upstream_component_links", upstream_links)):
        data.to_csv(out / f"{name}.csv", index="links" in name, index_label="native_link_index")

    # Keep original record coordinates alongside processed geometry endpoints.
    seam_links = valid[valid.start_node.isin(seam) | valid.end_node.isin(seam)]
    raw = pyogrio.read_dataframe(source / "stormwater.gdb", layer="PIPELINE")
    raw = raw[raw.UNITID.isin(seam_links.source_unitid)]
    cols = ["UNITID", "ASSET_BEFORE", "ASSET_AFTER", "StartCode", "EndCode", "XCOORD_START",
            "YCOORD_START", "XCOORD_END", "YCOORD_END", "INVERT_LEVEL_UPSTREAM",
            "INVERT_LEVEL_DOWNSTREAM", "StartX", "StartY", "EndX", "EndY", "STATUS"]
    raw[cols].to_csv(out / "seam_source_pipe_records.csv", index=False)
    raw_aa = pyogrio.read_dataframe(source / "aa_wr/DMT_IrrigationStormWater_AlAin.gdb", layer="PIPELINE")
    matches = []
    for _, row in raw.iterrows():
        other = raw_aa[raw_aa.UNITID.eq(row.UNITID)]
        matches.append({"unitid": row.UNITID, "aa_wr_matching_records": len(other),
                        "same_geometry_as_processed": bool(len(other) == 1 and row.geometry.equals_exact(other.iloc[0].geometry, 1e-8))})
    dump(out / "seam_original_geometry_crosscheck.json", matches)

    series, binary = native_series(run / "results/L2/AAM_L2_1D.out", pond_links, upstream_links,
                                   upstream_nodes, pond, seam)
    series.to_csv(out / "native_out_timeseries.csv", index=False)
    pond_layer = pyogrio.read_dataframe(source / "aa_wr/DMT_IrrigationStormWater_AlAin.gdb", layer="POND")
    pond_area = float(pond_layer.geometry.area.sum())
    summary = {
        "run_root": str(run), "source_root": str(source), "analysis_does_not_modify_model": True,
        "aam_selection": "spatial intersection with the union of supplied AAM administrative polygons; CRS transformed",
        "pond_logical_node": pond,
        "pond_component": {"nodes": len(pond_nodes), "links": len(pond_links),
                           "length_m": float(pond_links.native_length_m.sum()),
                           "inlet_nodes": int(pond_nodes.inlet_capture.sum()),
                           "opening_area_m2": float(interfaces["opening_area_m2"][pond_nodes.native_node].sum())},
        "closest_other_component_seam": {"pond_side_node": seam[0], "upstream_side_node": seam[1],
                                         "distance_m_using_native_coordinates": float(dist[k]),
                                         "pond_side_xy": [float(a.x_m), float(a.y_m)],
                                         "upstream_side_xy": [float(b.x_m), float(b.y_m)]},
        "upstream_component": {"nodes": len(upstream_nodes), "links": len(upstream_links),
                               "length_m": float(upstream_links.native_length_m.sum()),
                               "inlet_nodes": int(upstream_nodes.inlet_capture.sum()),
                               "outfall_nodes": int(upstream_nodes.physical_outfall_as_surface_exchange.sum())},
        "native_binary": binary,
        "native_reported_series_ranges": {c: {"min": float(series[c].min()), "max": float(series[c].max())}
                                          for c in series.columns if c != "time_seconds"},
        "pond_footprint_m2": pond_area,
        "rainfall_over_footprint_m3_at_60mm": pond_area * .06,
        "rainfall_over_footprint_interpretation": "geometric reference only; not observed or predicted actual inflow",
        "coupling_pond_volume_m3_ranges": {},
    }
    for filename, key in (("water_balance_windows.json", "pond_storage_m3"),
                          ("hydrograph.json", "pond_volume_m3")):
        rows = json.loads((run / "results/L2" / filename).read_text())
        values = [row[key] for row in rows]
        summary["coupling_pond_volume_m3_ranges"][filename] = {
            "count": len(values), "min": min(values), "max": max(values)}
    for filename in ("configuration.json", "pond_dtm_check.json", "source_archives.json"):
        (out / filename).write_bytes((run / "prepared" / filename).read_bytes())
    # RPT summaries retain maxima over routing steps, beyond the five-minute OUT sampling.
    targets = {f"N{pond:06d}", *(f"N{j:06d}" for j in seam),
               *(f"C{j:06d}" for j in pond_links.index),
               *(f"C{j:06d}" for j in seam_links.index)}
    sections = {"Node Depth Summary", "Node Inflow Summary", "Node Flooding Summary",
                "Node Surcharge Summary", "Flow Classification Summary",
                "Storage Volume Summary", "Link Flow Summary", "Conduit Surcharge Summary"}
    excerpts, section = [], ""
    with (run / "results/L2/AAM_L2_1D.rpt").open(errors="replace") as f:
        for lineno, line in enumerate(f, 1):
            if "<<<" in line:
                break
            if line.strip() in sections:
                section = line.strip()
            words = line.split()
            if words and words[0] in targets:
                excerpts.append({"line_number": lineno, "section": section, "text": line.strip()})
    dump(out / "native_report_summary_excerpts.json", excerpts)
    for name in ("prepared/L2/model.inp", "prepared/link_mapping_and_adaptations.csv", "prepared/node_mapping.csv"):
        summary.setdefault("input_sha256", {})[name] = hashlib.sha256((run / name).read_bytes()).hexdigest()
    dump(out / "audit_summary.json", summary)
    print(json.dumps({"output_dir": str(out), "pond_component": summary["pond_component"],
                      "seam": summary["closest_other_component_seam"],
                      "upstream_component": summary["upstream_component"], "native_binary": binary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
