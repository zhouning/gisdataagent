"""GeoCausal: open geospatial causal inference tools derived from Paper6."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _configure_conda_proj_data() -> None:
    if os.environ.get("PROJ_DATA") or os.environ.get("PROJ_LIB"):
        return
    for prefix in (sys.prefix, sys.base_prefix):
        candidate = Path(prefix) / "share" / "proj"
        if (candidate / "proj.db").exists():
            os.environ["PROJ_DATA"] = str(candidate)
            return


_configure_conda_proj_data()

__version__ = "0.1.0"

from .spatial_outputs import (  # noqa: E402
    COUNTY_ANALYSIS_COLUMNS,
    COUNTY_SHAPEFILE_FIELD_MAP,
    build_spatial_analysis_outputs,
    prepare_county_analysis_table_from_shapefile,
)

__all__ = [
    "__version__",
    "COUNTY_ANALYSIS_COLUMNS",
    "COUNTY_SHAPEFILE_FIELD_MAP",
    "build_spatial_analysis_outputs",
    "prepare_county_analysis_table_from_shapefile",
]
