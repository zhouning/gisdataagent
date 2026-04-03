"""Fusion engine constants and configuration."""

# Strategy matrix: data type pair → available strategies
STRATEGY_MATRIX: dict[tuple[str, str], list[str]] = {
    ("vector", "vector"):       ["spatial_join", "overlay", "nearest_join"],
    ("vector", "raster"):       ["zonal_statistics", "point_sampling"],
    ("raster", "vector"):       ["zonal_statistics", "point_sampling"],
    ("raster", "raster"):       ["band_stack"],
    ("vector", "tabular"):      ["attribute_join"],
    ("tabular", "vector"):      ["attribute_join"],
    ("vector", "stream"):       ["time_snapshot"],
    ("stream", "vector"):       ["time_snapshot"],
    ("vector", "point_cloud"):  ["height_assign"],
    ("point_cloud", "vector"):  ["height_assign"],
    ("raster", "tabular"):      ["raster_vectorize"],
}

# Unit conversion factors (source_unit → target_unit → factor)
UNIT_CONVERSIONS = {
    ("m2", "mu"):    1 / 666.67,       # 平方米 → 亩
    ("mu", "m2"):    666.67,
    ("m2", "ha"):    1 / 10000,
    ("ha", "m2"):    10000,
    ("mu", "ha"):    1 / 15,
    ("ha", "mu"):    15,
    ("m", "km"):     1 / 1000,
    ("km", "m"):     1000,
}

# Column name patterns for unit detection
UNIT_PATTERNS = {
    "mu": ["亩", "mu"],
    "m2": ["平方米", "m2", "sqm", "square_m"],
    "ha": ["公顷", "ha", "hectare"],
    "m":  ["米", "meter"],
    "km": ["千米", "公里", "km", "kilometer"],
}

# Table names for DB recording
T_FUSION_OPS = "agent_fusion_operations"
T_FUSION_ONTOLOGY_CACHE = "agent_fusion_ontology_cache"

# Large dataset thresholds
LARGE_ROW_THRESHOLD = 500_000
LARGE_FILE_MB = 500
