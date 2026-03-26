"""Helper functions that generate arcpy script strings.

Basic engine scripts use arcpy core (topology, spatial join, buffer, export).
DL engine scripts use arcgis.learn + arcpy.ia for deep learning inference.
"""


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


# ---------------------------------------------------------------------------
# Deep Learning engine scripts (require arcgis.learn + PyTorch)
# ---------------------------------------------------------------------------

def detect_objects_script(image_path: str, model_path: str, threshold: float = 0.3) -> str:
    """Generate arcgis.learn object detection script."""
    return f'''
import json, sys, os
try:
    from arcgis.learn import SingleShotDetector
    model = SingleShotDetector.from_model(r"{model_path}")
    results = model.predict(r"{image_path}", threshold={threshold})
    detections = []
    if hasattr(results, 'label') and hasattr(results, 'score'):
        for i in range(len(results.label)):
            detections.append({{
                "label": str(results.label[i]),
                "score": float(results.score[i]),
                "bbox": results.bboxes[i].tolist() if hasattr(results, 'bboxes') else None,
            }})
    sys.stdout.write(json.dumps({{"status": "ok", "detections": detections, "count": len(detections)}}))
    sys.stdout.flush()
    os._exit(0)
except Exception as e:
    sys.stdout.write(json.dumps({{"status": "error", "message": str(e)}}))
    sys.stdout.flush()
    os._exit(1)
'''


def classify_pixels_script(raster_path: str, model_path: str, output_path: str) -> str:
    """Generate arcgis.learn pixel classification script."""
    return f'''
import arcpy, json, sys, os
try:
    from arcgis.learn import UnetClassifier
    model = UnetClassifier.from_model(r"{model_path}")
    result = model.predict(r"{raster_path}")
    result.save(r"{output_path}")
    sys.stdout.write(json.dumps({{"status": "ok", "output": r"{output_path}"}}))
    sys.stdout.flush()
    os._exit(0)
except Exception as e:
    sys.stdout.write(json.dumps({{"status": "error", "message": str(e)}}))
    sys.stdout.flush()
    os._exit(1)
'''


def detect_change_script(raster_before: str, raster_after: str, model_path: str, output_path: str) -> str:
    """Generate arcgis.learn change detection script."""
    return f'''
import arcpy, json, sys, os
try:
    from arcgis.learn import ChangeDetector
    model = ChangeDetector.from_model(r"{model_path}")
    result = model.predict(r"{raster_before}", r"{raster_after}")
    result.save(r"{output_path}")
    import numpy as np
    arr = arcpy.RasterToNumPyArray(r"{output_path}")
    changed = int(np.count_nonzero(arr))
    total = int(arr.size)
    pct = round(changed / total * 100, 2) if total > 0 else 0
    sys.stdout.write(json.dumps({{"status": "ok", "output": r"{output_path}", "changed_pixels": changed, "total_pixels": total, "change_pct": pct}}))
    sys.stdout.flush()
    os._exit(0)
except Exception as e:
    sys.stdout.write(json.dumps({{"status": "error", "message": str(e)}}))
    sys.stdout.flush()
    os._exit(1)
'''


def assess_image_quality_script(raster_path: str) -> str:
    """Generate arcpy.ia image quality assessment script (no model required)."""
    return f'''
import arcpy, json, sys, os
from arcpy import ia

try:
    raster = arcpy.Raster(r"{raster_path}")
    stats = {{
        "mean": float(raster.mean) if raster.mean is not None else None,
        "std": float(raster.standardDeviation) if raster.standardDeviation is not None else None,
        "min": float(raster.minimum) if raster.minimum is not None else None,
        "max": float(raster.maximum) if raster.maximum is not None else None,
        "nodata_value": raster.noDataValue,
        "band_count": raster.bandCount,
        "width": raster.width,
        "height": raster.height,
        "pixel_type": raster.pixelType,
        "spatial_reference": raster.spatialReference.name if raster.spatialReference else None,
        "cell_size_x": raster.meanCellWidth,
        "cell_size_y": raster.meanCellHeight,
    }}

    import numpy as np
    arr = arcpy.RasterToNumPyArray(raster, nodata_to_value=np.nan)
    valid = arr[~np.isnan(arr)]
    nodata_pct = round((1 - len(valid) / arr.size) * 100, 2) if arr.size > 0 else 0
    dynamic_range = float(np.ptp(valid)) if len(valid) > 0 else 0
    snr = round(float(np.mean(valid) / np.std(valid)), 2) if len(valid) > 0 and np.std(valid) > 0 else 0

    quality = {{
        "nodata_pct": nodata_pct,
        "dynamic_range": dynamic_range,
        "signal_to_noise_ratio": snr,
    }}

    grade = "优" if nodata_pct < 1 and snr > 10 else "合格" if nodata_pct < 5 and snr > 3 else "不合格"

    sys.stdout.write(json.dumps({{"status": "ok", "stats": stats, "quality": quality, "grade": grade}}))
    sys.stdout.flush()
    os._exit(0)
except Exception as e:
    sys.stdout.write(json.dumps({{"status": "error", "message": str(e)}}))
    sys.stdout.flush()
    os._exit(1)
'''


def superresolution_script(raster_path: str, model_path: str, output_path: str, scale: int = 2) -> str:
    """Generate arcgis.learn super-resolution script."""
    return f'''
import arcpy, json, sys, os
try:
    from arcgis.learn import SuperResolution
    model = SuperResolution.from_model(r"{model_path}")
    result = model.predict(r"{raster_path}", scale_factor={scale})
    result.save(r"{output_path}")
    out_raster = arcpy.Raster(r"{output_path}")
    sys.stdout.write(json.dumps({{
        "status": "ok",
        "output": r"{output_path}",
        "scale_factor": {scale},
        "output_width": out_raster.width,
        "output_height": out_raster.height,
    }}))
    sys.stdout.flush()
    os._exit(0)
except Exception as e:
    sys.stdout.write(json.dumps({{"status": "error", "message": str(e)}}))
    sys.stdout.flush()
    os._exit(1)
'''
