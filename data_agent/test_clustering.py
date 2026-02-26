import unittest
import pandas as pd
import geopandas as gpd
import numpy as np
import os
import shutil
from shapely.geometry import Point

# Add project root to path
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_agent.gis_processors import perform_clustering
from data_agent.agent import visualize_interactive_map

class TestClustering(unittest.TestCase):
    def setUp(self):
        self.test_dir = "test_cluster_data"
        os.makedirs(self.test_dir, exist_ok=True)
        
        # Create 3 clusters of points
        # Cluster 1: Around (0,0)
        c1 = np.random.normal(0, 50, (20, 2))
        # Cluster 2: Around (500, 500)
        c2 = np.random.normal(500, 50, (20, 2))
        # Cluster 3: Around (1000, 0)
        c3 = np.random.normal(1000, 50, (20, 2))
        
        data = np.vstack([c1, c2, c3])
        df = pd.DataFrame(data, columns=['x', 'y'])
        
        # Create GeoDataFrame (Projected CRS for clustering: EPSG:3857)
        gdf = gpd.GeoDataFrame(
            df, 
            geometry=gpd.points_from_xy(df.x, df.y),
            crs="EPSG:3857"
        )
        
        self.shp_path = os.path.join(self.test_dir, "points.shp")
        gdf.to_file(self.shp_path)

    def tearDown(self):
        try:
            shutil.rmtree(self.test_dir)
        except:
            pass

    def test_clustering_and_viz(self):
        print("\nTesting DBSCAN Clustering...")
        
        # 1. Run Clustering
        # eps=200 meters should easily separate the clusters (centers are ~500m apart)
        clustered_path = perform_clustering(self.shp_path, eps=200, min_samples=5)
        
        self.assertTrue(os.path.exists(clustered_path))
        gdf_out = gpd.read_file(clustered_path)
        
        self.assertIn('cluster_id', gdf_out.columns)
        n_clusters = len(gdf_out[gdf_out['cluster_id'] != -1]['cluster_id'].unique())
        print(f"  Found {n_clusters} clusters.")
        self.assertGreaterEqual(n_clusters, 3)
        
        # 2. Run Visualization (Heatmap + Cluster Points)
        print("\nTesting Interactive Map Visualization...")
        
        html_msg = visualize_interactive_map(clustered_path)
        
        self.assertIn("saved to", html_msg)
        html_path = html_msg.split("saved to ")[1].strip()
        self.assertTrue(os.path.exists(html_path))
        
        # Check if HeatMap is in HTML content
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()
            # Folium renders HeatMap as L.heatLayer
            self.assertIn("L.heatLayer", content)
            self.assertIn("L.circleMarker", content) # Clustered markers
            
        print(f"  Map generated at: {html_path}")

if __name__ == "__main__":
    unittest.main()
