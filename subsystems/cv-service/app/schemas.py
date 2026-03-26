from pydantic import BaseModel, Field
from typing import List, Optional

class BoundingBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float
    class_name: str

class DetectionResult(BaseModel):
    image_id: str
    detections: List[BoundingBox]
    processing_time_ms: float

class CadLayerDetectionRequest(BaseModel):
    image_base64: Optional[str] = None
    file_url: Optional[str] = None

class CadLayerDetectionResponse(BaseModel):
    layers: List[dict] = Field(default_factory=list)
    topology_issues: List[str] = Field(default_factory=list)
    confidence: float

class RasterQualityRequest(BaseModel):
    image_base64: Optional[str] = None
    file_url: Optional[str] = None

class RasterQualityResponse(BaseModel):
    quality_score: float
    issues: List[dict]
    metrics: dict

class ModelValidationRequest(BaseModel):
    model_file_url: str
    validation_type: str = "topology"

class ModelValidationResponse(BaseModel):
    is_valid: bool
    errors: List[str]
    warnings: List[str]
