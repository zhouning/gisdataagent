import tempfile
import logging
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException

from app.schemas import CadParseResponse, CadEntity
from app.engines.dxf_engine import DxfEngine

logger = logging.getLogger(__name__)
router = APIRouter()
_dxf = DxfEngine()


@router.post("/dxf", response_model=CadParseResponse)
async def parse_dxf(file: UploadFile = File(...)):
    """Parse a DXF file and extract layers, entities, and geometry."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        parsed = _dxf.parse(tmp_path)
        raw_entities = _dxf.get_entities(tmp_path)

        entities = []
        for ent in raw_entities[:200]:  # cap to avoid huge payloads
            coords = (
                ent.get("points")
                or ([ent["start"], ent["end"]] if "start" in ent else [])
                or ([ent.get("center", ent.get("location", ent.get("insert", [0, 0])))])
            )
            attrs = {k: v for k, v in ent.items() if k not in ("type", "layer", "points", "start", "end")}
            entities.append(CadEntity(
                entity_type=ent["type"], layer=ent["layer"],
                coordinates=coords, attributes=attrs,
            ))

        return CadParseResponse(
            filename=file.filename or "unknown.dxf",
            layers=parsed["layers"],
            entity_count=parsed["total_entities"],
            entities=entities,
            bounding_box=parsed.get("bounding_box", {}),
        )
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("DXF parse failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


@router.post("/dwg")
async def parse_dwg(file: UploadFile = File(...)):
    """Parse a DWG file. Requires ODA converter for DWG->DXF first."""
    return {
        "filename": file.filename or "unknown.dwg",
        "status": "not_supported",
        "note": "DWG parsing requires ODA File Converter. Convert to DXF axf endpoint.",
    }
