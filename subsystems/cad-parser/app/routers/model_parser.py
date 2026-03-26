import tempfile
import logging
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException

from app.schemas import MeshParseResponse
from app.engines.mesh_engine import MeshEngine

logger = logging.getLogger(__name__)
router = APIRouter()
_mesh = MeshEngine()


@router.post("/obj", response_model=MeshParseResponse)
async def parse_obj(file: UploadFile = File(...)):
    """Parse an OBJ 3D model file."""
    tmp_path = None
    try:
        suffix = Path(file.filename or "model.obj").suffix or ".obj"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        result = _mesh.parse(tmp_path)
        return MeshParseResponse(
            filename=file.filename or "unknown.obj",
            vertex_count=result["vertex_count"],
            face_count=result["face_count"],
            bounding_box=result["bounding_box"],
            is_watertight=result["is_watertight"],
            volume=result.get("volume"),
        )
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("OBJ parse failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


@router.post("/fbx")
async def parse_fbx(file: UploadFile = File(...)):
    """Parse an FBX 3D model file (via trimesh)."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".fbx", delete=False) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        result = _mesh.parse(tmp_path)
        return {
            "filename": file.filename or "unknown.fbx",
            "vertex_count": result["vertex_count"],
            "face_count": result["face_count"],
            "bounding_box": result["bounding_box"],
            "is_watertight": result["is_watertight"],
        }
    except Exception as e:
        logger.error("FBX parse failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
