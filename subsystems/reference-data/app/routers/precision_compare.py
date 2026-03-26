import math
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.schemas import PrecisionCompareRequest, PrecisionCompareResponse
from app.db import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

_GRADE_THRESHOLDS = {"优": 0.05, "合格": 0.10}  # RMSE in meters


@router.post("/compare/coordinates", response_model=PrecisionCompareResponse)
async def compare_coordinates(
    req: PrecisionCompareRequest,
    db: Session = Depends(get_db),
):
    """Compare measured coordinates against reference points. Returns RMSE and grade."""
    if not req.pairs:
        raise HTTPException(status_code=400, detail="At least one coordinate pair required")

    details = []
    errors = []

    for pair in req.pairs:
        # Try to find a nearby reference point in DB for the target coords
        ref_x, ref_y = pair.target_x, pair.target_y
        try:
            row = db.execute(text("""
                SELECT ST_X(geom), ST_Y(geom)
                FROM control_points
                ORDER BY ST_Distance(geom, ST_SetSRID(ST_MakePoint(:x, :y), 4326))
                LIMIT 1
            """), {"x": ref_x, "y": ref_y}).fetchone()
            if row:
                ref_x, ref_y = row[0], row[1]
        except Exception:
            pass  # fall back to user-provided target

        dx = ref_x - pair.source_x
        dy = ref_y - pair.source_y
        # Convert degree offset to meters (approximate)
        lat_rad = math.radians((pair.source_y + ref_y) / 2)
        mx = dx * 111_320 * math.cos(lat_rad)
        my = dy * 110_540
        error_m = math.sqrt(mx ** 2 + my ** 2)
        errors.append(error_m)
        details.append({
            "source": [pair.source_x, pair.source_y],
            "reference": [ref_x, ref_y],
            "error_m": round(error_m, 4),
        })

    n = len(errors)
    mean_err = sum(errors) / n
    max_err = max(errors)
    rmse = math.sqrt(sum(e ** 2 for e in errors) / n)

    # Determine grade
    grade = "不合格"
    for label, threshold in _GRADE_THRESHOLDS.items():
        if rmse <= threshold:
            grade = label
            break

    return PrecisionCompareResponse(
        pair_count=n,
        mean_error_m=round(mean_err, 4),
        max_error_m=round(max_err, 4),
        rmse_m=round(rmse, 4),
        details=details,
        grade=grade,
    )
