from pydantic import BaseModel, Field
from typing import List, Optional


class ControlPoint(BaseModel):
    point_id: str
    name: str
    longitude: float
    latitude: float
    elevation: Optional[float] = None
    datum: str = "CGCS2000"
    accuracy_class: str = "C"
    source: str = "国家测绘基准"


class NearbyPointsRequest(BaseModel):
    longitude: float
    latitude: float
    radius_km: float = 10.0
    datum: str = "CGCS2000"
    limit: int = 20


class DatumInfo(BaseModel):
    datum_id: str
    name: str
    ellipsoid: str
    semi_major_axis: float
    flattening: float
    epsg_code: int
    description: str


class CoordinatePair(BaseModel):
    source_x: float
    source_y: float
    source_z: Optional[float] = None
    target_x: float
    target_y: float
    target_z: Optional[float] = None


class PrecisionCompareRequest(BaseModel):
    pairs: List[CoordinatePair]
    source_datum: str = "WGS84"
    target_datum: str = "CGCS2000"


class PrecisionCompareResponse(BaseModel):
    pair_count: int
    mean_error_m: float
    max_error_m: float
    rmse_m: float
    details: List[dict]
    grade: str = "合格"
