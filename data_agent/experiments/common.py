"""Shared utilities for SCI paper experiments: style, paths, data loading."""

import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# SCI Figure Style (Times New Roman, 300 DPI)
# ---------------------------------------------------------------------------

SCI_STYLE = {
    "font.family": "serif",
    "font.serif": ["Times New Roman", "DejaVu Serif"],
    "font.size": 10,
    "axes.labelsize": 11,
    "axes.titlesize": 12,
    "axes.linewidth": 0.8,
    "legend.fontsize": 9,
    "legend.frameon": True,
    "legend.edgecolor": "0.8",
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "xtick.direction": "in",
    "ytick.direction": "in",
    "xtick.major.size": 3,
    "ytick.major.size": 3,
    "figure.dpi": 300,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.05,
    "lines.linewidth": 1.2,
    "lines.markersize": 4,
    "grid.alpha": 0.3,
    "grid.linewidth": 0.5,
}

# Standard widths for journal figures (inches)
FULL_WIDTH = 7.0    # double-column
HALF_WIDTH = 3.4    # single-column
ASPECT_RATIO = 0.75  # height = width * ratio


def apply_sci_style():
    """Apply SCI publication style to all subsequent plots."""
    plt.rcParams.update(SCI_STYLE)


# ---------------------------------------------------------------------------
# Output Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # D:\adk
EXPERIMENT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = EXPERIMENT_DIR / "output"
DATA_DIR = PROJECT_ROOT / "01数据样例"

# Ensure output dir exists
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def output_path(name: str, ext: str = "png") -> Path:
    """Generate output file path, also save PDF copy for LaTeX."""
    return OUTPUT_DIR / f"{name}.{ext}"


def save_fig(fig, name: str, close: bool = True):
    """Save figure as both PNG (300 DPI) and PDF for LaTeX inclusion."""
    png_path = output_path(name, "png")
    pdf_path = output_path(name, "pdf")
    fig.savefig(png_path, dpi=300, bbox_inches="tight", pad_inches=0.05)
    fig.savefig(pdf_path, bbox_inches="tight", pad_inches=0.05)
    if close:
        plt.close(fig)
    print(f"  Saved: {png_path.name} + {pdf_path.name}")
    return png_path


# ---------------------------------------------------------------------------
# Color Palettes
# ---------------------------------------------------------------------------

# Colorblind-safe palette (Wong 2011)
COLORS = {
    "blue": "#0072B2",
    "orange": "#E69F00",
    "green": "#009E73",
    "red": "#D55E00",
    "purple": "#CC79A7",
    "cyan": "#56B4E9",
    "yellow": "#F0E442",
    "black": "#000000",
    "gray": "#999999",
}

# For grouped bar charts
BAR_COLORS = [COLORS["blue"], COLORS["orange"], COLORS["green"], COLORS["red"]]

# LULC color map (ESRI 9-class)
LULC_COLORS = {
    1: ("#4169E1", "Water"),
    2: ("#228B22", "Trees"),
    4: ("#90EE90", "Grassland"),
    5: ("#DEB887", "Shrubs"),
    7: ("#FFD700", "Cropland"),
    8: ("#DC143C", "Built-up"),
    9: ("#D2B48C", "Barren"),
    10: ("#FFFFFF", "Snow/Ice"),
    11: ("#20B2AA", "Wetland"),
}


# ---------------------------------------------------------------------------
# Data Loading Helpers
# ---------------------------------------------------------------------------

def load_shapefile(name: str):
    """Load a shapefile from the data directory by dataset name."""
    import geopandas as gpd
    paths = {
        "buildings": DATA_DIR / "04重庆市中心城区建筑物轮廓数据2021年" / "中心城区建筑数据带层高.shp",
        "roads": DATA_DIR / "02重庆市OSM道路数据2021年" / "OSM_roads.shp",
        "historic": DATA_DIR / "05重庆市中心城区历史文化街区数据" / "中心城区历史文化街区数据.shp",
    }
    path = paths.get(name)
    if path is None or not path.exists():
        raise FileNotFoundError(f"Dataset '{name}' not found at {path}")
    return gpd.read_file(path)


def load_raster(name: str):
    """Load a raster file, return (array, transform, crs)."""
    import rasterio
    paths = {
        "dem": DATA_DIR / "01重庆市DEM数据2020年" / "Chongqing_aster_gdem_80m.tif",
        "clcd": DATA_DIR / "03重庆市遥感影像解译数据2020年" / "CLCD_v01_2020_chongqing.tif",
    }
    path = paths.get(name)
    if path is None or not path.exists():
        raise FileNotFoundError(f"Raster '{name}' not found at {path}")
    with rasterio.open(path) as src:
        data = src.read(1)
        return data, src.transform, src.crs


def load_population():
    """Load Chongqing population statistics."""
    import pandas as pd
    path = DATA_DIR / "08重庆市各区县人口规模表格数据" / "重庆市各区县人口规模数据.xlsx"
    if not path.exists():
        raise FileNotFoundError(f"Population data not found at {path}")
    return pd.read_excel(path)


def load_commute():
    """Load mobile signal commute data."""
    import pandas as pd
    path = DATA_DIR / "11中国联通手机信令数据" / "现状职住通勤数据_202305.csv"
    if not path.exists():
        raise FileNotFoundError(f"Commute data not found at {path}")
    return pd.read_csv(path)


# ---------------------------------------------------------------------------
# GEE Helpers
# ---------------------------------------------------------------------------

_GEE_READY = False


def init_gee():
    """Initialize Google Earth Engine (cached)."""
    global _GEE_READY
    if _GEE_READY:
        return True
    try:
        import ee
        ee.Initialize()
        _GEE_READY = True
        print("  GEE initialized successfully")
        return True
    except Exception as e:
        print(f"  GEE init failed: {e}")
        return False


def fetch_modis_lst(bbox: list, year: int = 2021, scale: int = 1000):
    """Fetch annual mean MODIS Land Surface Temperature for a bounding box.

    Returns numpy array [H, W] of LST in Celsius.
    """
    import ee
    if not init_gee():
        return None

    roi = ee.Geometry.Rectangle(bbox)
    collection = (
        ee.ImageCollection("MODIS/061/MOD11A2")
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filterBounds(roi)
        .select("LST_Day_1km")
    )
    mean_img = collection.mean().multiply(0.02).subtract(273.15)  # Scale + K→C
    arr = mean_img.sampleRectangle(roi, defaultValue=0).getInfo()
    return np.array(arr["properties"]["LST_Day_1km"])


def fetch_ndvi(bbox: list, year: int = 2021, scale: int = 250):
    """Fetch annual mean MODIS NDVI for a bounding box."""
    import ee
    if not init_gee():
        return None

    roi = ee.Geometry.Rectangle(bbox)
    collection = (
        ee.ImageCollection("MODIS/061/MOD13Q1")
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filterBounds(roi)
        .select("NDVI")
    )
    mean_img = collection.mean().multiply(0.0001)  # Scale factor
    arr = mean_img.sampleRectangle(roi, defaultValue=0).getInfo()
    return np.array(arr["properties"]["NDVI"])


# Chongqing central urban area bounding box (approx)
CHONGQING_BBOX = [106.3, 29.3, 106.8, 29.7]
CHONGQING_FULL_BBOX = [105.29, 28.16, 110.19, 32.20]
