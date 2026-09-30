"""Create a compact RGB height map for the Mussafah_00 5 m DTM.

The output is a presentation asset for deck.gl TerrainLayer.  It does not
change the ANUGA/SWMM terrain input or any hydraulic result.
"""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import numpy as np
from pyproj import Transformer


ROOT = Path("/Users/zhouning")
GRID = ROOT / ".tmp/mussafah00_coupled/prepared/L2B6/grid.npz"
OUT_DIR = ROOT / ".tmp/mussafah00_coupled/real_runs"
PNG = OUT_DIR / "mussafah00_5m_terrain_rgb.png"
MANIFEST = OUT_DIR / "mussafah00_5m_terrain.json"
TO_WGS84 = Transformer.from_crs(32640, 4326, always_xy=True)


def png_rgb(rows: np.ndarray) -> bytes:
    height, width, channels = rows.shape
    assert channels == 3

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(row) for row in rows.reshape(height, width * 3))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def main() -> None:
    grid = np.load(GRID)
    x = np.asarray(grid["x"], dtype=float)
    y = np.asarray(grid["y"], dtype=float)
    values = np.asarray(grid["values"], dtype=float)
    finite = np.isfinite(values)
    if not finite.all():
        values = np.where(finite, values, np.nanmedian(values[finite]))

    # The grid stores rows from south to north (y is ascending), while an
    # image's first row is the north edge when it is mapped to TerrainLayer's
    # [west, south, east, north] bounds.  Flip only the raster row order so
    # the surface is not vertically mirrored in the web map.  x already runs
    # west to east and therefore keeps its order.
    values = values[::-1, :]

    # Encode elevations at centimetre precision into 24-bit RGB.
    offset = float(values.min())
    scale = 0.01
    encoded = np.rint((values - offset) / scale).clip(0, 16_777_215).astype(np.uint32)
    rgb = np.stack([
        (encoded >> 16) & 255,
        (encoded >> 8) & 255,
        encoded & 255,
    ], axis=-1).astype(np.uint8)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PNG.write_bytes(png_rgb(rgb))
    corners = [TO_WGS84.transform(float(x[0]), float(y[0])), TO_WGS84.transform(float(x[-1]), float(y[-1]))]
    bounds = [
        min(corners[0][0], corners[1][0]),
        min(corners[0][1], corners[1][1]),
        max(corners[0][0], corners[1][0]),
        max(corners[0][1], corners[1][1]),
    ]
    MANIFEST.write_text(json.dumps({
        "schema": "gwm.abu_dhabi_flood.mussafah00.terrain_rgb.v1",
        "source_grid": str(GRID),
        "crs": "EPSG:4326",
        "bounds": bounds,
        "width": int(values.shape[1]),
        "height": int(values.shape[0]),
        "resolution_m": 5,
        "elevation_min_m": offset,
        "elevation_max_m": float(values.max()),
        "elevation_decoder": {
            "rScaler": 655.36,
            "gScaler": 2.56,
            "bScaler": 0.01,
            "offset": offset,
        },
        "engineering_admitted": False,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(PNG, PNG.stat().st_size)
    print(MANIFEST)


if __name__ == "__main__":
    main()
