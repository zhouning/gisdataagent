"""Data Asset Coding System — structured code generation for data assets.

Provides a unified coding scheme: DA-{TYPE}-{SOURCE}-{YEAR}-{SEQ}
for uniquely identifying data assets across the platform lifecycle.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Data modality → 3-char type code
TYPE_CODES = {
    "vector": "VEC",
    "raster": "RAS",
    "tabular": "TAB",
    "point_cloud": "PCD",
    "stream": "STR",
    "fusion": "FUS",
    "cleaned": "CLN",
    "map": "VEC",
    "report": "OTH",
    "script": "OTH",
    "other": "OTH",
}

# File extension → type fallback
_EXT_TO_TYPE = {
    ".geojson": "vector", ".shp": "vector", ".gpkg": "vector",
    ".kml": "vector", ".kmz": "vector",
    ".tif": "raster", ".tiff": "raster", ".img": "raster",
    ".csv": "tabular", ".xlsx": "tabular", ".xls": "tabular",
    ".las": "point_cloud", ".laz": "point_cloud",
}


def generate_asset_code(
    asset_id: int,
    data_type: str = "other",
    owner: str = "UNK",
    year: Optional[int] = None,
) -> str:
    """Generate a structured asset code.

    Format: DA-{TYPE}-{SOURCE}-{YEAR}-{SEQ}

    Args:
        asset_id: Numeric ID from agent_data_assets (SERIAL).
        data_type: Data modality string (vector/raster/tabular/fusion/...).
        owner: Owner username — first 3 chars uppercased as source code.
        year: Data year. Defaults to current year.

    Returns:
        Asset code string, e.g. "DA-VEC-ADM-2024-0A1B".
    """
    type_code = TYPE_CODES.get(data_type.lower(), "OTH")
    source_code = (owner[:3] if owner else "UNK").upper()
    year_str = str(year if year else datetime.now(timezone.utc).year)
    seq = format(asset_id, "04X").upper()
    return f"DA-{type_code}-{source_code}-{year_str}-{seq}"


def infer_data_type_from_path(file_path: str) -> str:
    """Infer data type from file extension.

    Args:
        file_path: Path to the data file.

    Returns:
        Data type string (vector/raster/tabular/point_cloud/other).
    """
    import os
    ext = os.path.splitext(file_path)[1].lower()
    return _EXT_TO_TYPE.get(ext, "other")


def parse_asset_code(code: str) -> Optional[dict]:
    """Parse a structured asset code into its components.

    Args:
        code: Asset code string, e.g. "DA-VEC-ADM-2024-0A1B".

    Returns:
        Dict with {prefix, type_code, source_code, year, sequence} or None.
    """
    if not code:
        return None
    parts = code.split("-")
    if len(parts) != 5 or parts[0] != "DA":
        return None
    return {
        "prefix": parts[0],
        "type_code": parts[1],
        "source_code": parts[2],
        "year": int(parts[3]) if parts[3].isdigit() else None,
        "sequence": parts[4],
    }
