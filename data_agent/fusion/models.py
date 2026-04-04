"""Fusion engine data structures."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FusionSource:
    """Profile of a single data source for fusion."""
    file_path: str
    data_type: str              # vector | raster | tabular | point_cloud | stream
    crs: Optional[str] = None
    bounds: Optional[tuple] = None   # (minx, miny, maxx, maxy)
    row_count: int = 0
    columns: list = field(default_factory=list)   # [{name, dtype, null_pct}]
    geometry_type: Optional[str] = None
    temporal_range: Optional[tuple] = None
    semantic_domain: Optional[str] = None
    stats: dict = field(default_factory=dict)      # {col: {min, max, mean, unique}}
    band_count: int = 0
    resolution: Optional[tuple] = None  # (x_res, y_res) for raster
    # PostGIS push-down (v7.1)
    postgis_table: Optional[str] = None
    postgis_srid: Optional[int] = None


@dataclass
class CompatibilityReport:
    """Result of compatibility assessment between data sources."""
    crs_compatible: bool = True
    spatial_overlap_iou: float = 0.0
    temporal_aligned: Optional[bool] = None
    field_matches: list = field(default_factory=list)   # [{left, right, confidence}]
    overall_score: float = 0.0
    recommended_strategies: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


@dataclass
class FusionResult:
    """Result of a fusion operation."""
    output_path: str = ""
    strategy_used: str = ""
    row_count: int = 0
    column_count: int = 0
    quality_score: float = 0.0
    quality_warnings: list = field(default_factory=list)
    alignment_log: list = field(default_factory=list)
    duration_s: float = 0.0
    provenance: dict = field(default_factory=dict)
    # v2 explainability fields
    explainability_path: str = ""
    conflict_summary: dict = field(default_factory=dict)
    temporal_log: list = field(default_factory=list)
    # v17.1 asset coding
    output_asset_code: str = ""
