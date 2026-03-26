from fastapi import APIRouter, HTTPException
from app.schemas import DatumInfo

router = APIRouter()

_DATUMS = {
    "CGCS2000": DatumInfo(
        datum_id="CGCS2000", name="China Geodetic Coordinate System 2000",
        ellipsoid="CGCS2000", semi_major_axis=6378137.0, flattening=1 / 298.257222101,
        epsg_code=4490, description="中国2000国家大地坐标系",
    ),
    "WGS84": DatumInfo(
        datum_id="WGS84", name="World Geodetic System 1984",
        ellipsoid="WGS84", semi_major_axis=6378137.0, flattening=1 / 298.257223563,
        epsg_code=4326, description="GPS全球定位系统使用的坐标系",
    ),
    "Beijing54": DatumInfo(
        datum_id="Beijing54", name="Beijing 1954",
        ellipsoid="Krassowsky", semi_major_axis=6378245.0, flattening=1 / 298.3,
        epsg_code=4214, description="北京54坐标系（已废弃）",
    ),
    "Xian80": DatumInfo(
        datum_id="Xian80", name="Xi'an 1980",
        ellipsoid="IAG 1975", semi_major_axis=6378140.0, flattening=1 / 298.257,
        epsg_code=4610, description="1980西安坐标系",
    ),
}


@router.get("/datums", response_model=list[DatumInfo])
async def list_datums():
    """List all supported datum/CRS definitions."""
    return list(_DATUMS.values())


@router.get("/datum/{datum_id}", response_model=DatumInfo)
async def get_datum_info(datum_id: str):
    """Get datum/CRS information by ID."""
    datum = _DATUMS.get(datum_id)
    if not datum:
        raise HTTPException(status_code=404, detail=f"Unknown datum: {datum_id}")
    return datum
