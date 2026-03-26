import tempfile
import logging
from pathlib import Path

import numpy as np
from PIL import Image
from fastapi import APIRouter, UploadFile, File, HTTPException

from app.schemas import RasterQualityResponse

logger = logging.getLogger(__name__)
router = APIRouter()


def _analyze_image(img_path: str) -> dict:
    """Compute quality metrics for a raster image."""
    img = Image.open(img_path)
    arr = np.array(img)

    width, height = img.size
    bands = 1 if arr.ndim == 2 else arr.shape[2]
    bit_depth = arr.dtype.itemsize * 8

    # Blur detection via Laplacian variance (grayscale)
    gray = np.mean(arr, axis=2) if arr.ndim == 3 else arr.astype(float)
    laplacian_kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=float)
    from scipy.signal import convolve2d
    lap = convolve2d(gray, laplacian_kernel, mode="valid")
    blur_var = float(np.var(lap))

    # Nodata / near-black percentage
    if arr.ndim == 3:
        pixel_sum = np.sum(arr, axis=2)
    else:
        pixel_sum = arr.astype(float)
    nodata_pct = float(np.mean(pixel_sum < 1) * 100)

    # Histogram uniformity (normalized entropy proxy)
    hist, _ = np.histogram(gray.ravel(), bins=256, range=(0, 256))
    hist_norm = hist / hist.sum()
    nonzero = hist_norm[hist_norm > 0]
    entropy = -np.sum(nonzero * np.log2(nonzero))
    uniformity = round(entropy / 8.0, 3)  # 8 bits max entropy

    return {
        "width": width, "height": height, "bands": bands,
        "bit_depth": bit_depth, "blur_variance": round(blur_var, 2),
        "nodata_percentage": round(nodata_pct, 2),
        "histogram_uniformity": uniformity,
    }


@router.post("/raster-quality", response_model=RasterQualityResponse)
async def detect_raster_quality(file: UploadFile = File(...)):
    """Assess quality of a raster image (blur, noise, nodata)."""
    tmp_path = None
    try:
        suffix = Path(file.filename or "img.tif").suffix
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        m = _analyze_image(tmp_path)
        issues = []
        score = 1.0

        if m["blur_variance"] < 100:
            severity = "high" if m["blur_variance"] < 30 else "low"
            issues.append({"type": "blur", "severity": severity,
                           "blur_variance": m["blur_variance"]})
            score -= 0.3 if severity == "high" else 0.1

        if m["nodata_percentage"] > 5:
            issues.append({"type": "nodata", "percentage": m["nodata_percentage"]})
            score -= min(m["nodata_percentage"] / 100, 0.3)

        metrics = {
            "width": m["width"], "height": m["height"],
            "bit_depth": m["bit_depth"], "bands": m["bands"],
            "nodata_percentage": m["nodata_percentage"],
            "histogram_uniformity": m["histogram_uniformity"],
            "blur_variance": m["blur_variance"],
        }
        return RasterQualityResponse(
            quality_score=round(max(score, 0.0), 3),
            issues=issues, metrics=metrics,
        )
    except Exception as e:
        logger.error("Raster quality analysis failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
