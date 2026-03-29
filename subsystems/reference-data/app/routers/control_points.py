import logging
from typing import Annotated

from fastapi import APIRouter, Query, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.schemas import ControlPoint
from app.db import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/points/nearby", response_model=list[ControlPoint])
async def get_nearby_points(
    longitude: float = Query(..., ge=-180, le=180),
    latitude: float = Query(..., ge=-90, le=90),
    radius_km: float = Query(10.0, gt=0, le=100),
    limit: int = Query(20, gt=0, le=100),
    db: Session = Depends(get_db),
):
    """Find control points near a given coordinate using PostGIS ST_DWithin."""
    try:
        radius_m = radius_km * 1000
        query = text("""
            SELECT point_id, name, ST_X(geom) AS longitude, ST_Y(geom) AS latitude,
                   elevation, datum, accuracy_class, source
            FROM control_points
            WHERE ST_DWithin(
                geom::geography,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                :radius
            )
            ORDER BY ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)
            LIMIT :limit
        """)
        result = db.execute(query, {"lon": longitude, "lat": latitude, "radius": radius_m, "limit": limit})
        rows = result.fetchall()
        return [
            ControlPoint(
                point_id=r[0], name=r[1], longitude=r[2], latitude=r[3],
                elevation=r[4], datum=r[5] or "CGCS2000",
                accuracy_class=r[6] or "C", source=r[7] or "国家测绘基准",
            )
            for r in rows
        ]
    except Exception as e:
        logger.error("Nearby points query failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/points/{point_id}", response_model=ControlPoint)
async def get_point_by_id(point_id: str, db: Session = Depends(get_db)):
    """Get a specific control point by ID."""
    try:
        query = text("""
            SELECT point_id, name, ST_X(geom) AS longitude, ST_Y(geom) AS latitude,
                   elevation, datum, accuracy_class, source
            FROM control_points
            WHERE point_id = :pid
        """)
        result = db.execute(query, {"pid": point_id})
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Point {point_id} not found")
        return ControlPoint(
            point_id=row[0], name=row[1], longitude=row[2], latitude=row[3],
            elevation=row[4], datum=row[5] or "CGCS2000",
            accuracy_class=row[6] or "C", source=row[7] or "国家测绘基准",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Point lookup failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
