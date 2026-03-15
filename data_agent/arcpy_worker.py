#!/usr/bin/env python
"""
ArcPy Worker Process — runs in the ArcGIS Pro Python environment.

Communicates via JSON-line protocol over stdin/stdout.
Each line is a complete JSON object terminated by newline.

Protocol:
  -> stdin:  {"command": "buffer", "params": {...}}
  <- stdout: {"status": "success", "output_path": "...", ...}

Special commands:
  __ping__    -> {"status": "pong"}
  __shutdown__ -> process exits

DO NOT import anything from the data_agent package.
This script runs in a completely separate Python environment.
"""
import sys
import json
import os
import traceback
import csv


def _send(obj):
    """Write a JSON line to stdout and flush immediately."""
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Handlers — each receives (arcpy_module, params_dict) and returns a dict
# ---------------------------------------------------------------------------

def handle_ping(arcpy, params):
    return {"status": "pong"}


def handle_shutdown(arcpy, params):
    _send({"status": "shutdown_ack"})
    raise SystemExit(0)


def handle_buffer(arcpy, params):
    input_path = params["input_path"]
    output_path = params["output_path"]
    distance = params.get("distance", 500)
    dissolve_type = params.get("dissolve_type", "NONE")

    distance_expr = f"{distance} Meters"

    arcpy.analysis.Buffer(
        in_features=input_path,
        out_feature_class=output_path,
        buffer_distance_or_field=distance_expr,
        dissolve_option=dissolve_type,
    )
    count = int(arcpy.GetCount_management(output_path)[0])
    return {
        "status": "success",
        "output_path": output_path,
        "feature_count": count,
        "message": f"Buffer completed: {count} features",
    }


def handle_clip(arcpy, params):
    input_path = params["input_path"]
    clip_path = params["clip_path"]
    output_path = params["output_path"]

    arcpy.analysis.Clip(
        in_features=input_path,
        clip_features=clip_path,
        out_feature_class=output_path,
    )
    count = int(arcpy.GetCount_management(output_path)[0])
    return {
        "status": "success",
        "output_path": output_path,
        "feature_count": count,
        "message": f"Clip completed: {count} features",
    }


def handle_dissolve(arcpy, params):
    input_path = params["input_path"]
    output_path = params["output_path"]
    dissolve_field = params.get("dissolve_field")
    statistics_fields = params.get("statistics_fields")

    # Parse statistics_fields: "Shape_Area SUM;Slope MEAN" -> [["Shape_Area","SUM"], ...]
    stats = None
    if statistics_fields:
        stats = []
        for pair in statistics_fields.split(";"):
            parts = pair.strip().split()
            if len(parts) == 2:
                stats.append(parts)

    arcpy.management.Dissolve(
        in_features=input_path,
        out_feature_class=output_path,
        dissolve_field=dissolve_field,
        statistics_fields=stats,
    )
    count = int(arcpy.GetCount_management(output_path)[0])
    return {
        "status": "success",
        "output_path": output_path,
        "feature_count": count,
        "message": f"Dissolve completed: {count} features",
    }


def handle_project(arcpy, params):
    input_path = params["input_path"]
    output_path = params["output_path"]
    target_crs = params.get("target_crs", "EPSG:4490")

    # Parse CRS: support "EPSG:XXXX" or bare WKID string
    if target_crs.upper().startswith("EPSG:"):
        wkid = int(target_crs.split(":")[1])
    else:
        wkid = int(target_crs)

    sr = arcpy.SpatialReference(wkid)
    arcpy.management.Project(
        in_dataset=input_path,
        out_dataset=output_path,
        out_coor_system=sr,
    )
    count = int(arcpy.GetCount_management(output_path)[0])
    return {
        "status": "success",
        "output_path": output_path,
        "feature_count": count,
        "message": f"Project completed: {count} features -> WKID {wkid}",
    }


def handle_check_geometry(arcpy, params):
    input_path = params["input_path"]
    output_path = params.get("output_path")

    check_table = "in_memory/geom_check_table"
    arcpy.management.CheckGeometry(
        in_features=input_path,
        out_table=check_table,
    )

    error_counts = {}
    total_errors = 0
    rows = []
    with arcpy.da.SearchCursor(check_table, ["FEATURE_ID", "PROBLEM"]) as cursor:
        for fid, problem in cursor:
            total_errors += 1
            error_counts[problem] = error_counts.get(problem, 0) + 1
            rows.append({"FEATURE_ID": fid, "PROBLEM": problem})

    # Write CSV report if output path given and there are errors
    if output_path and rows:
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["FEATURE_ID", "PROBLEM"])
            writer.writeheader()
            writer.writerows(rows)

    try:
        arcpy.management.Delete(check_table)
    except Exception:
        pass

    return {
        "status": "success",
        "total_errors": total_errors,
        "error_counts": error_counts,
        "output_path": output_path if rows else None,
        "message": f"Found {total_errors} geometry errors" if total_errors else "No geometry errors found",
    }


def handle_repair_geometry(arcpy, params):
    input_path = params["input_path"]
    output_path = params["output_path"]

    # Copy first, then repair in place (original untouched)
    arcpy.management.CopyFeatures(input_path, output_path)
    arcpy.management.RepairGeometry(
        in_features=output_path,
        delete_null="DELETE_NULL",
    )
    count = int(arcpy.GetCount_management(output_path)[0])
    return {
        "status": "success",
        "output_path": output_path,
        "feature_count": count,
        "message": f"Repair completed: {count} features",
    }


def handle_slope(arcpy, params):
    input_path = params["input_path"]
    output_path = params["output_path"]
    output_measurement = params.get("output_measurement", "DEGREE")

    arcpy.CheckOutExtension("Spatial")
    try:
        from arcpy.sa import Slope
        out_slope = Slope(input_path, output_measurement=output_measurement)
        out_slope.save(output_path)
    finally:
        arcpy.CheckInExtension("Spatial")

    return {
        "status": "success",
        "output_path": output_path,
        "message": f"Slope ({output_measurement}) computed",
    }


def handle_zonal_statistics(arcpy, params):
    zone_path = params["zone_path"]
    raster_path = params["raster_path"]
    zone_field = params.get("zone_field", "FID")
    stats_type = params.get("stats_type", "ALL")
    output_path = params["output_path"]

    arcpy.CheckOutExtension("Spatial")
    try:
        from arcpy.sa import ZonalStatisticsAsTable
        mem_table = "in_memory/zonal_stats_table"
        ZonalStatisticsAsTable(
            zone_path, zone_field, raster_path, mem_table,
            statistics_type=stats_type,
        )

        # Export to CSV
        fields = [f.name for f in arcpy.ListFields(mem_table)]
        rows = []
        with arcpy.da.SearchCursor(mem_table, fields) as cursor:
            for row in cursor:
                rows.append(dict(zip(fields, [
                    v if not isinstance(v, (bytes, bytearray)) else str(v) for v in row
                ])))

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

        try:
            arcpy.management.Delete(mem_table)
        except Exception:
            pass
    finally:
        arcpy.CheckInExtension("Spatial")

    return {
        "status": "success",
        "output_path": output_path,
        "row_count": len(rows),
        "message": f"Zonal statistics computed: {len(rows)} zones",
    }


# ---------------------------------------------------------------------------
# Watershed extraction (Spatial Analyst hydrology chain)
# ---------------------------------------------------------------------------

def handle_extract_watershed(arcpy, params):
    """Full hydrological analysis: Fill → FlowDirection → FlowAccumulation → Watershed."""
    dem_path = params["dem_path"]
    threshold = int(params.get("threshold", 1000))
    pour_point_x = params.get("pour_point_x")
    pour_point_y = params.get("pour_point_y")
    output_dir = params.get("output_dir", os.path.dirname(dem_path))

    arcpy.CheckOutExtension("Spatial")
    try:
        from arcpy.sa import Fill, FlowDirection, FlowAccumulation, Con, Watershed, SnapPourPoint, StreamOrder

        # 1. Fill sinks
        filled = Fill(dem_path)

        # 2. Flow Direction (D8)
        fdir = FlowDirection(filled)

        # 3. Flow Accumulation
        acc = FlowAccumulation(fdir)

        # 4. Stream Network (Con: acc > threshold → 1)
        streams = Con(acc > threshold, 1)

        # 5. Stream Order (Strahler)
        try:
            stream_order = StreamOrder(streams, fdir, "STRAHLER")
            stream_order_path = os.path.join(output_dir, "stream_order_arcpy.tif")
            stream_order.save(stream_order_path)
        except Exception:
            stream_order_path = None

        # 6. Determine pour point
        acc_path = os.path.join(output_dir, "flow_acc_arcpy.tif")
        acc.save(acc_path)

        if pour_point_x and pour_point_y:
            # Create pour point from coordinates
            px, py = float(pour_point_x), float(pour_point_y)
            sr = arcpy.Describe(dem_path).spatialReference
            pp_fc = os.path.join(output_dir, "pour_point_arcpy.shp")
            if arcpy.Exists(pp_fc):
                arcpy.management.Delete(pp_fc)
            arcpy.management.CreateFeatureclass(output_dir, "pour_point_arcpy.shp", "POINT", spatial_reference=sr)
            with arcpy.da.InsertCursor(pp_fc, ["SHAPE@XY"]) as cursor:
                cursor.insertRow([(px, py)])
            # Snap to high-accumulation cell
            snap_pp = SnapPourPoint(pp_fc, acc, 500)  # 500m snap distance
        else:
            # Auto-detect: create pour point at maximum accumulation cell
            sr = arcpy.Describe(dem_path).spatialReference
            desc = arcpy.Describe(dem_path)
            # Read accumulation as numpy array to find max cell
            import numpy as _np
            acc_arr = arcpy.RasterToNumPyArray(acc, nodata_to_value=0)
            max_idx = _np.unravel_index(_np.argmax(acc_arr), acc_arr.shape)
            # Convert pixel to map coordinates
            px = desc.extent.XMin + (max_idx[1] + 0.5) * desc.meanCellWidth
            py = desc.extent.YMax - (max_idx[0] + 0.5) * desc.meanCellHeight
            pp_fc = os.path.join(output_dir, "pour_point_arcpy.shp")
            if arcpy.Exists(pp_fc):
                arcpy.management.Delete(pp_fc)
            arcpy.management.CreateFeatureclass(output_dir, "pour_point_arcpy.shp", "POINT", spatial_reference=sr)
            with arcpy.da.InsertCursor(pp_fc, ["SHAPE@XY"]) as cursor:
                cursor.insertRow([(px, py)])
            snap_pp = SnapPourPoint(pp_fc, acc, 500)

        # 7. Watershed delineation
        ws = Watershed(fdir, snap_pp)
        ws_raster_path = os.path.join(output_dir, "watershed_arcpy.tif")
        ws.save(ws_raster_path)

        # 8. Convert watershed raster to polygon
        ws_polygon_path = os.path.join(output_dir, "watershed_boundary_arcpy.shp")
        arcpy.conversion.RasterToPolygon(ws_raster_path, ws_polygon_path, "SIMPLIFY")

        # 9. Convert stream raster to polyline
        stream_line_path = os.path.join(output_dir, "stream_network_arcpy.shp")
        try:
            arcpy.conversion.RasterToPolyline(streams, stream_line_path, "ZERO", 0, "SIMPLIFY")
        except Exception:
            stream_line_path = None

        # 10. Compute statistics
        desc = arcpy.Describe(ws_polygon_path)
        extent = desc.extent

        # Elevation stats within watershed
        elev_stats = {}
        try:
            from arcpy.sa import ZonalStatisticsAsTable
            stats_table = os.path.join(output_dir, "ws_elev_stats")
            ZonalStatisticsAsTable(ws_raster_path, "Value", dem_path, stats_table, "DATA", "ALL")
            with arcpy.da.SearchCursor(stats_table, ["MIN", "MAX", "MEAN", "RANGE", "AREA"]) as cursor:
                for row in cursor:
                    elev_stats = {"min": round(row[0], 1), "max": round(row[1], 1),
                                  "mean": round(row[2], 1), "range": round(row[3], 1),
                                  "area_m2": round(row[4], 2)}
                    break
        except Exception:
            pass

        # 11. Export to GeoJSON for frontend compatibility
        ws_geojson = os.path.join(output_dir, "watershed_boundary_arcpy.geojson")
        try:
            arcpy.conversion.FeaturesToJSON(ws_polygon_path, ws_geojson, geoJSON="GEOJSON")
        except Exception:
            ws_geojson = ws_polygon_path  # fallback to shapefile

        stream_geojson = None
        if stream_line_path:
            stream_geojson = os.path.join(output_dir, "stream_network_arcpy.geojson")
            try:
                arcpy.conversion.FeaturesToJSON(stream_line_path, stream_geojson, geoJSON="GEOJSON")
            except Exception:
                stream_geojson = stream_line_path

    finally:
        arcpy.CheckInExtension("Spatial")

    return {
        "status": "success",
        "watershed_boundary": ws_geojson,
        "stream_network": stream_geojson,
        "flow_accumulation": acc_path,
        "stream_order": stream_order_path,
        "elevation": elev_stats,
        "extent": {"xmin": extent.XMin, "ymin": extent.YMin,
                   "xmax": extent.XMax, "ymax": extent.YMax},
        "message": f"ArcPy watershed extraction complete. Threshold={threshold}",
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    # Cold import of arcpy (takes ~3-5 seconds)
    try:
        import arcpy
        arcpy.env.overwriteOutput = True
        info = arcpy.GetInstallInfo()
        _send({
            "status": "ready",
            "arcpy_version": info.get("Version", "unknown"),
            "license_level": info.get("LicenseLevel", "unknown"),
        })
    except ImportError as e:
        _send({"status": "error", "message": f"Failed to import arcpy: {e}"})
        sys.exit(1)

    handlers = {
        "__ping__": handle_ping,
        "__shutdown__": handle_shutdown,
        "buffer": handle_buffer,
        "clip": handle_clip,
        "dissolve": handle_dissolve,
        "project": handle_project,
        "check_geometry": handle_check_geometry,
        "repair_geometry": handle_repair_geometry,
        "slope": handle_slope,
        "zonal_statistics": handle_zonal_statistics,
        "extract_watershed": handle_extract_watershed,
    }

    # Main loop: read JSON lines from stdin
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError as e:
            _send({"status": "error", "message": f"Invalid JSON: {e}"})
            continue

        command = request.get("command", "")
        params = request.get("params", {})

        handler = handlers.get(command)
        if handler is None:
            _send({"status": "error", "message": f"Unknown command: {command}"})
            continue

        try:
            result = handler(arcpy, params)
            _send(result)
        except SystemExit:
            break
        except Exception as e:
            _send({
                "status": "error",
                "message": str(e),
                "traceback": traceback.format_exc(),
            })


if __name__ == "__main__":
    main()
