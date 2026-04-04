"""
Artifact Handler — detects and processes output files from tool responses.

Extracted from app.py to reduce its complexity. Handles:
- File path extraction from tool response strings/dicts
- Map layer construction from HTML mapconfig and GeoJSON files
- Adaptive delivery: GeoJSON (<5K) / FlatGeobuf (5K-50K) / MVT tiles (>50K)
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

    Uses adaptive delivery based on feature count:
    - <= FGB_FEATURE_THRESHOLD (5K): GeoJSON file (original behavior)
    - <= MVT_FEATURE_THRESHOLD (50K): FlatGeobuf with viewport streaming
    - > MVT_FEATURE_THRESHOLD: PostGIS MVT vector tiles

    Returns map_update dict or None on failure.
    """
    try:
        import geopandas as gpd
        gdf = gpd.read_file(geojson_path)
        if gdf.empty:
            return existing_update

        feature_count = len(gdf)
        basename = os.path.basename(geojson_path)
        label = basename.replace(".geojson", "").replace("_", " ").title()

        # Compute center in WGS84
        gdf_4326 = gdf.to_crs(epsg=4326) if gdf.crs and gdf.crs.to_epsg() != 4326 else gdf
        center = [float(gdf_4326.geometry.centroid.y.mean()),
                  float(gdf_4326.geometry.centroid.x.mean())]

        # Detect geometry type
        geom_types = set(gdf.geom_type.dropna().unique())
        if geom_types & {"Point", "MultiPoint"}:
            ltype = "point"
        elif geom_types & {"LineString", "MultiLineString"}:
            ltype = "line"
        else:
            ltype = "polygon"

        from .tile_server import MVT_FEATURE_THRESHOLD, FGB_FEATURE_THRESHOLD

        # --- Tier 3: MVT vector tiles (>50K features) ---
        if feature_count > MVT_FEATURE_THRESHOLD:
            new_layer = _build_mvt_layer(geojson_path, label)
            if new_layer:
                logger.info("[ArtifactGeoJSON] MVT mode: %d features -> tile layer %s",
                            feature_count, new_layer.get("layer_id"))
                return _merge_layer(new_layer, existing_update, center)

        # --- Tier 2: FlatGeobuf streaming (5K-50K features) ---
        if feature_count > FGB_FEATURE_THRESHOLD:
            new_layer = _build_fgb_layer(geojson_path, gdf, label, ltype)
            if new_layer:
                logger.info("[ArtifactGeoJSON] FGB mode: %d features -> %s",
                            feature_count, new_layer.get("fgb"))
                return _merge_layer(new_layer, existing_update, center)

        # --- Tier 1: GeoJSON file (<=5K features, original behavior) ---
        new_layer = {"name": label, "type": ltype, "geojson": basename}
        return _merge_layer(new_layer, existing_update, center)

    except Exception as e:
        logger.debug("[ArtifactGeoJSON] Failed to load %s: %s",
                     os.path.basename(geojson_path), e)
        return existing_update


def _build_mvt_layer(geojson_path: str, label: str) -> Optional[dict]:
    """Create a PostGIS-backed MVT tile layer for large datasets."""
    try:
        from .tile_server import create_tile_layer
        from .user_context import current_user_id
        user_id = current_user_id.get("")
        meta = create_tile_layer(geojson_path, user_id, label)
        return {
            "name": label,
            "type": "mvt",
            "tile_url": f"/api/tiles/{meta['layer_id']}/{{z}}/{{x}}/{{y}}.pbf",
            "metadata_url": f"/api/tiles/{meta['layer_id']}/metadata.json",
            "layer_id": meta["layer_id"],
            "source_layer": meta["layer_name"] or "default",
            "style": {"fillColor": "#4682B4", "fillOpacity": 0.6,
                      "color": "#333333", "weight": 1},
            "visible": True,
        }
    except Exception as e:
        logger.warning("[ArtifactGeoJSON] MVT creation failed, falling back: %s", e)
        return None


def _build_fgb_layer(geojson_path: str, gdf, label: str,
                     ltype: str) -> Optional[dict]:
    """Convert GeoJSON to FlatGeobuf for viewport-based streaming."""
    try:
        fgb_path = geojson_path.rsplit(".", 1)[0] + ".fgb"
        gdf.to_file(fgb_path, driver="FlatGeobuf")
        fgb_basename = os.path.basename(fgb_path)
        logger.info("[ArtifactGeoJSON] Wrote FlatGeobuf: %s", fgb_basename)
        return {
            "name": label,
            "type": "fgb",
            "fgb": fgb_basename,
            "geom_type": ltype,
            "style": {"fillColor": "#4682B4", "fillOpacity": 0.6,
                      "color": "#333333", "weight": 1},
            "visible": True,
        }
    except Exception as e:
        logger.warning("[ArtifactGeoJSON] FGB conversion failed, falling back: %s", e)
        return None


def _merge_layer(new_layer: dict, existing_update: Optional[dict],
                 center: list) -> dict:
    """Merge a new layer into an existing map_update or create a new one."""
    if existing_update and "layers" in existing_update:
        existing_update["layers"].append(new_layer)
        return existing_update
    return {"layers": [new_layer], "center": center, "zoom": 13}


def check_layer_control(resp_val) -> Optional[dict]:
    """Check if a tool response contains a layer_control command.

    Returns the layer_control dict or None.
    """
    if isinstance(resp_val, dict) and "layer_control" in resp_val:
        return resp_val["layer_control"]
    return None
