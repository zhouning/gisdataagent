import tempfile
import logging
from pathlib import Path
from urllib.request import urlretrieve

from fastapi import APIRouter, HTTPException

from app.schemas import ModelValidationRequest, ModelValidationResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/model-validate", response_model=ModelValidationResponse)
async def validate_model(req: ModelValidationRequest):
    """Validate a 3D model for topology and geometry issues."""
    tmp_path = None
    try:
        import trimesh

        with tempfile.NamedTemporaryFile(suffix=".obj", delete=False) as tmp:
            tmp_path = tmp.name
        urlretrieve(req.model_file_url, tmp_path)

        mesh = trimesh.load(tmp_path, force="mesh")
        errors: list[str] = []
        warnings: list[str] = []

        if not mesh.is_watertight:
            errors.append("Mesh is not watertight")
        if not mesh.is_volume:
            errors.append("Mesh does not represent a valid volume")

        # Check degenerate faces (near-zero area)
        face_areas = mesh.area_faces
        degen_count = int((face_areas < 1e-10).sum())
        if degen_count > 0:
            errors.append(f"{degen_count} degenerate faces with near-zero area")

        # Check duplicate vertices
        unique_verts = len(set(map(tuple, mesh.vertices.tolist())))
        dup_count = len(mesh.vertices) - unique_verts
        if dup_count > 0:
            warnings.append(f"{dup_count} duplicate vertices")

        # Face count warning
        if len(mesh.faces) > 500_000:
            warnings.append(f"High face count: {len(mesh.faces)}")

        is_valid = len(errors) == 0
        return ModelValidationResponse(
            is_valid=is_valid, errors=errors, warnings=warnings,
        )
    except Exception as e:
        logger.error("Model validation failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
