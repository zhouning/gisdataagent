import tempfile
import logging
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Query, HTTPException

from app.schemas import ConvertResponse
from app.engines.dxf_engine import DxfEngine
from app.engines.export_engine import ExportEngine

logger = logging.getLogger(__name__)
router = APIRouter()
_dxf = DxfEngine()
_export = ExportEngine()


@router.post("/to-geojson", response_model=ConvertResponse)
async def convert_to_geojson(
    file: UploadFile = File(...),
    target_crs: str = Query("EPSG:4326", description="Target CRS"),
):
    """Convert a CAD file to GeoJSON format."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        entities = _dxf.get_entities(tmp_path)
        geojson = _export.to_geojson(entities, crs=target_crs)

        out_name = Path(file.filename or "output").stem + ".geojson"
        out_path = str(Path(tempfile.gettempdir()) / out_name)
        _export.save_geojson(geojson, out_path)

        geom_types = geojson.get("geometry_types", [])
        return ConvertResponse(
            output_path=out_path,
            feature_count=len(geojson["features"]),
            crs=target_crs,
            geometry_types=geom_types,
        )
    except Exception as e:
        logger.error("GeoJSON conversion failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


@router.post("/to-shapefile", response_model=ConvertResponse)
async def convert_to_shapefile(
    file: UploadFile = File(...),
    target_crs: str = Query("EPSG:4326", description="Target CRS"),
):
    """Convert a CAD file to Shapefile format."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        entities = _dxf.get_entities(tmp_path)
        out_dir = tempfile.mkdtemp(prefix="shp_")
        shp_path = _export.to_shapefile(entities, out_dir, crs=target_crs)

        geojson = _export.to_geojson(entities, crs=target_crs)
        geom_types = geojson.get("geometry_types", [])
        return ConvertResponse(
            output_path=shp_path,
            feature_count=len(geojson["features"]),
            crs=target_crs,
            geometry_types=geom_types,
        )
    except Exception as e:
        logger.error("Shapefile conversion failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
