from pydantic import BaseModel, Field
from typing import List, Optional


class CadEntity(BaseModel):
    entity_type: str
    layer: str
    coordinates: list
    attributes: dict = Field(default_factory=dict)


class CadParseResponse(BaseModel):
    filename: str
    layers: List[str]
    entity_count: int
    entities: List[CadEntity]
    bounding_box: dict


class MeshFace(BaseModel):
    vertices: List[List[float]]
    normal: List[float]


class MeshParseResponse(BaseModel):
    filename: str
    vertex_count: int
    face_count: int
    bounding_box: dict
    is_watertight: bool
    volume: Optional[float] = None


class ConvertRequest(BaseModel):
    source_format: str
    target_crs: str = "EPSG:4326"


class ConvertResponse(BaseModel):
    output_path: str
    feature_count: int
    crs: str
    geometry_types: List[str]
