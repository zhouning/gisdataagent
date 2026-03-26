"""Helper functions that generate arcpy script strings."""


def topology_check_script(gdb_path: str, dataset: str, rule: str) -> str:
    """Generate arcpy script for topology validation."""
    return f'''
import arcpy
import json

arcpy.env.workspace = r"{gdb_path}"
topology = r"{gdb_path}/{dataset}_Topology"

try:
    arcpy.ValidateTopology_management(topology)
    errors = []
    with arcpy.da.SearchCursor(topology + "_errors_point", ["SHAPE@", "RuleDescription"]) as cur:
        for row in cur:
            errors.append({{"type": "point", "rule": row[1], "x": row[0].centroid.X, "y": row[0].centroid.Y}})
    print(json.dumps({{"status": "ok", "errors": errors, "error_count": len(errors)}}))
except Exception as e:
    print(json.dumps({{"status": "error", "message": str(e)}}))
'''


def spatial_join_script(target: str, join_features: str, output: str, join_type: str = "JOIN_ONE_TO_ONE") -> str:
    """Generate arcpy script for spatial join."""
    return f'''
import arcpy
import json

try:
    result = arcpy.analysis.SpatialJoin(
        r"{target}", r"{join_features}", r"{output}",
        join_operation="{join_type}"
    )
    count = int(arcpy.management.GetCount(r"{output}")[0])
    print(json.dumps({{"status": "ok", "output": r"{output}", "feature_count": count}}))
except Exception as e:
    print(json.dumps({{"status": "error", "message": str(e)}}))
'''


def buffer_analysis_script(input_fc: str, output: str, distance: str) -> str:
    """Generate arcpy script for buffer analysis."""
    return f'''
import arcpy
import json

try:
    arcpy.analysis.Buffer(r"{input_fc}", r"{output}", "{distance}")
    count = int(arcpy.management.GetCount(r"{output}")[0])
    print(json.dumps({{"status": "ok", "output": r"{output}", "feature_count": count}}))
except Exception as e:
    print(json.dumps({{"status": "error", "message": str(e)}}))
'''


def export_map_script(aprx_path: str, layout_name: str, output_path: str, dpi: int = 300) -> str:
    """Generate arcpy script for map export."""
    return f'''
import arcpy
import json

try:
    aprx = arcpy.mp.ArcGISProject(r"{aprx_path}")
    layout = aprx.listLayouts("{layout_name}")[0]
    layout.exportToPDF(r"{output_path}", resolution={dpi})
    print(json.dumps({{"status": "ok", "output": r"{output_path}", "dpi": {dpi}}}))
except Exception as e:
    print(json.dumps({{"status": "error", "message": str(e)}}))
'''
