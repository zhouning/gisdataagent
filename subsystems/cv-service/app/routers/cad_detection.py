import tempfile
import logging
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException

from app.schemas import CadLayerDetectionResponse
from app.engines.yolo_engine import YoloEngine
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

_engine = YoloEngine(model_path=settings.YOLO_MODEL, device=settings.DEVICE)
_engine.load_model()


@router.post("/cad-layers", response_model=CadLayerDetectionResponse)
async def detect_cad_layers(file: UploadFile = File(...)):
    """Detect layers and elements in a CAD drawing image."""
    try:
        suffix = Path(file.filename or "img.png").suffix
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        result = _engine.detect_cad_layers(tmp_path)
        layers = result.get("layers", [])
        total = result.get("total_detections", 0)
        avg_conf = 0.0
        if total > 0:
            detections = _engine.detect(tmp_path)
            avg_conf = sum(d["confidence"] for d in detections) / len(detections)

        return CadLayerDetectionResponse(
            layers=layers,
            topology_issues=[],
            confidence=round(avg_conf, 3),
        )
    except Exception as e:
        logger.error("CAD layer detection failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@router.post("/cad-topology")
async def detect_cad_topology(file: UploadFile = File(...)):
    """Check topology issues in a CAD drawing image."""
    try:
        suffix = Path(file.filename or "img.png").suffix
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        detections = _engine.detect(tmp_path, conf=0.15)
        total = len(detections)
        issues = []
        for d in detections:
            if d["confidence"] < 0.3:
                issues.append({
                    "type": "low_confidence",
                    "location": {"x": d["x1"], "y": d["y1"]},
                    "severity": "warning",
                })
        pass_rate = 1.0 - (len(issues) / max(total, 1))
        return {
            "total_elements": total,
            "issues": issues,
            "pass_rate": round(pass_rate, 3),
        }
    except Exception as e:
        logger.error("CAD topology detection failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        Path(tmp_path).unlink(missing_ok=True)
