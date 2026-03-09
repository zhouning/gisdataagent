"""Strategy registry — maps strategy names to implementation functions."""
from .spatial_join import _strategy_spatial_join, _fuse_large_datasets_spatial, _extract_geodataframe
from .overlay import _strategy_overlay
from .nearest_join import _strategy_nearest_join
from .attribute_join import _strategy_attribute_join, _auto_detect_join_column
from .zonal_stats import _strategy_zonal_statistics
from .point_sampling import _strategy_point_sampling
from .band_stack import _strategy_band_stack
from .time_snapshot import _strategy_time_snapshot
from .height_assign import _strategy_height_assign
from .raster_vectorize import _strategy_raster_vectorize

_STRATEGY_REGISTRY = {
    "spatial_join":     _strategy_spatial_join,
    "overlay":          _strategy_overlay,
    "nearest_join":     _strategy_nearest_join,
    "attribute_join":   _strategy_attribute_join,
    "zonal_statistics": _strategy_zonal_statistics,
    "point_sampling":   _strategy_point_sampling,
    "band_stack":       _strategy_band_stack,
    "time_snapshot":    _strategy_time_snapshot,
    "height_assign":    _strategy_height_assign,
    "raster_vectorize": _strategy_raster_vectorize,
}
