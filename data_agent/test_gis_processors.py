import unittest
import os
import sys
import shutil
import geopandas as gpd
from shapely.geometry import Point, Polygon, box
import numpy as np
import rasterio
from rasterio.transform import from_origin
import pandas as pd

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_agent.gis_processors import (
    generate_tessellation, 
    raster_to_polygon, 
    pairwise_clip, 
    tabulate_intersection, 
    surface_parameters, 
    zonal_statistics_as_table
)

class TestGISProcessors(unittest.TestCase):
    def setUp(self):
        """Create temporary test data."""
        self.test_dir = os.path.join(os.path.dirname(__file__), "test_gis_data")
        os.makedirs(self.test_dir, exist_ok=True)
        # Ensure data_agent/uploads exists for tool output
        os.makedirs(os.path.join(os.path.dirname(__file__), "uploads"), exist_ok=True)
        
        # 1. Create a simple extent polygon (Square 0,0 to 1000,1000)
        self.extent_shp = os.path.join(self.test_dir, "extent.shp")
        gpd.GeoDataFrame(
            {'id': [1]}, 
            geometry=[Polygon([(0,0), (1000,0), (1000,1000), (0,1000)])],
            crs="EPSG:3857"
        ).to_file(self.extent_shp)
        
        # 2. Create a dummy raster (10x10 pixels, covering 0,0 to 100,100)
        self.raster_path = os.path.join(self.test_dir, "test_raster.tif")
        # Create an elevation-like gradient for slope test
        x = np.linspace(0, 10, 10)
        y = np.linspace(0, 10, 10)
        X, Y = np.meshgrid(x, y)
        self.dem_arr = (X + Y).astype(np.float32) 
        
        transform = from_origin(0, 100, 10, 10) # West, North, xres, yres
        
        with rasterio.open(
            self.raster_path, 'w',
            driver='GTiff', height=10, width=10, count=1, 
            dtype=rasterio.float32, crs='EPSG:3857', transform=transform
        ) as dst:
            dst.write(self.dem_arr, 1)

    def tearDown(self):
        """Cleanup."""
        try:
            shutil.rmtree(self.test_dir)
        except:
            pass

    def test_generate_tessellation(self):
        print("\nTesting generate_tessellation...")
        out = generate_tessellation(self.extent_shp, size=100.0)
        self.assertTrue(os.path.exists(out))
        gdf = gpd.read_file(out)
        self.assertGreater(len(gdf), 0)
        print(f"  Generated {len(gdf)} grid cells.")

    def test_raster_to_polygon(self):
        print("\nTesting raster_to_polygon...")
        out = raster_to_polygon(self.raster_path)
        self.assertTrue(os.path.exists(out))
        gdf = gpd.read_file(out)
        self.assertGreater(len(gdf), 0)
        self.assertIn('gridcode', gdf.columns)
        print(f"  Vectorized into {len(gdf)} polygons.")

    def test_surface_parameters(self):
        print("\nTesting surface_parameters (Slope)...")
        out = surface_parameters(self.raster_path, "SLOPE")
        self.assertTrue(os.path.exists(out))
        with rasterio.open(out) as src:
            slope = src.read(1)
            self.assertEqual(slope.shape, (10, 10))
            print(f"  Mean Slope: {np.mean(slope):.2f} degrees")

    def test_zonal_statistics(self):
        print("\nTesting zonal_statistics_as_table...")
        # Create zones (two polygons)
        zones_shp = os.path.join(self.test_dir, "zones.shp")
        gpd.GeoDataFrame(
            {'id': [1, 2]}, 
            geometry=[
                box(0, 0, 50, 100),   # Left half
                box(50, 0, 100, 100)  # Right half
            ],
            crs="EPSG:3857"
        ).to_file(zones_shp)
        
        out = zonal_statistics_as_table(zones_shp, self.raster_path)
        self.assertTrue(os.path.exists(out))
        df = pd.read_csv(out)
        self.assertEqual(len(df), 2)
        self.assertIn('mean', df.columns)
        print(f"  Zonal Stats:\n{df.head()}")

if __name__ == "__main__":
    unittest.main()
