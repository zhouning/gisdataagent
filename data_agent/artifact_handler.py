"""
Artifact Handler — detects and processes output files from tool responses.

Extracted from app.py to reduce its complexity. Handles:
- File path extraction from tool response strings/dicts
- Map layer construction from HTML mapconfig and GeoJSON files
- Layer control metadata forwarding
- CSV/PNG/GeoJSON artifact classification
"""
import json
import os
from typing import Optional

try:
    from .pipeline_runner import extract_file_paths
except ImportError:
    from data_agent.pipeline_runner import extract_file_paths

try:
    from .observability import get_logger
    logger = get_logger("artifact_handler")
except Exception:
    import logging
    logger = logging.getLogger("artifact_handler")


def extract_response_string(resp_val) -> str:
    """Convert a tool response value (str, dict, or other) to a searchable string.

    Tries common dict keys first, then falls back to full JSON serialization.
    """
    if isinstance(resp_val, str):
        return resp_val
    if isinstance(resp_val, dict):
        # Try common keys that contain file paths
        parts = [
            str(resp_val.get("output_path", "")),
            str(resp_val.get("message", "")),
            str(resp_val.get("result", "")),
        ]
        # Also check 'files' list
        files = resp_val.get("files")
        if isinstance(files, list):
            parts.extend(str(f) for f in files)
        candidate = " ".join(parts)
        if extract_file_paths(candidate):
            return candidate
        # Fall back to full dict serialization
        return json.dumps(resp_val, default=str)
    return str(resp_val)[:500]


def detect_artifacts(resp_val) -> list[dict]:
    """Detect file artifacts from a tool response.

    Returns list of {"path": str, "type": str} dicts.
    """
    resp_str = extract_response_string(resp_val)
    artifacts = extract_file_paths(resp_str)
    logger.info("[ArtifactDetect] resp_type=%s, str_len=%d, artifacts=%d",
                type(resp_val).__name__, len(resp_str), len(artifacts))
    return artifacts


def build_map_update_from_html(html_path: str) -> Optional[dict]:
    """Read mapconfig.json associated with an HTML map file.

    Returns map_update dict or None.
    """
    cfg_path = html_path.replace('.html', '.mapconfig.json')
    if not os.path.exists(cfg_path):
        return None
    try:
        with open(cfg_path, 'r', encoding='utf-8') as f:
            mc_data = json.load(f)
        logger.info("[ArtifactHTML] Loaded mapconfig: layers=%d",
                    len(mc_data.get("layers", [])))
        return mc_data
    except Exception:
        return None


def build_map_update_from_geojson(geojson_path: str,
                                  existing_update: dict = None) -> Optional[dict]:
    """Build a map layer update from a GeoJSON file.

    Detects geometry type, computes center, and merges into existing map_update
    or creates a new one.

    Returns map_update dict or None on failure.
    """
    try:
        import geopandas as gpd
        gdf = gpd.read_file(geojson_path)
        if gdf.empty:
            return existing_update

        # Detect layer type
        geom_types = set(gdf.geom_type.dropna().unique())
        if geom_types & {"Point", "MultiPoint"}:
            ltype = "point"
        elif geom_types & {"LineString", "MultiLineString"}:
            ltype = "line"
        else:
            ltype = "polygon"

        # Human-readable name
        basename = os.path.basename(geojson_path)
        label = basename.replace(".geojson", "").replace("_", " ").title()

        new_layer = {"name": label, "type": ltype, "geojson": basename}

        # Compute center
        gdf_4326 = gdf.to_crs(epsg=4326) if gdf.crs and gdf.crs.to_epsg() != 4326 else gdf
        center = [float(gdf_4326.geometry.centroid.y.mean()),
                  float(gdf_4326.geometry.centroid.x.mean())]

        # Merge or create
        if existing_update and "layers" in existing_update:
            existing_update["layers"].append(new_layer)
            return existing_update
        else:
            return {"layers": [new_layer], "center": center, "zoom": 13}

    except Exception as e:
        logger.debug("[ArtifactGeoJSON] Failed to load %s: %s",
                     os.path.basename(geojson_path), e)
        return existing_update


def check_layer_control(resp_val) -> Optional[dict]:
    """Check if a tool response contains a layer_control command.

    Returns the layer_control dict or None.
    """
    if isinstance(resp_val, dict) and "layer_control" in resp_val:
        return resp_val["layer_control"]
    return None
