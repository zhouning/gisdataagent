import geopandas as gpd
from sqlalchemy import create_engine
import pyogrio
import os

DB_URI = "postgresql://postgres:Supermap2024.@192.168.100.215:30355/gis_agent"
engine = create_engine(DB_URI)

datasets = [
    {
        "path": r"D:\adk\01数据样例\04重庆市中心城区建筑物轮廓数据2021年\中心城区建筑数据带层高.shp",
        "table": "cq_buildings_2021"
    },
    {
        "path": r"D:\adk\01数据样例\02重庆市OSM道路数据2021年\OSM_roads.shp",
        "table": "cq_osm_roads_2021"
    },
    {
        "path": r"D:\adk\01数据样例\09高德地图POI数据\高德地图POI数据2024年.gdb",
        "layer": "高德地图POI数据2024年", # Wait, what is the layer name? Let's read first layer if not specified
        "table": "cq_amap_poi_2024"
    },
    {
        "path": r"D:\adk\01数据样例\07规划编制相关数据\区县\现状用地数据\GDB.gdb",
        "layer": "DLTB",
        "table": "cq_land_use_dltb"
    }
]

for ds in datasets:
    print(f"Loading {ds['path']} ...")
    try:
        if "layer" in ds:
            # First try reading layer name
            try:
                layers = pyogrio.list_layers(ds["path"])
                layer_name = layers[0][0] # take the first layer
                gdf = pyogrio.read_dataframe(ds["path"], layer=layer_name)
            except Exception as e:
                print(f"Pyogrio read failed, trying standard gpd: {e}")
                gdf = gpd.read_file(ds["path"], layer=ds.get("layer"))
        else:
            try:
                gdf = pyogrio.read_dataframe(ds["path"])
            except:
                gdf = gpd.read_file(ds["path"])
        
        # CRS handle: convert to 4326 if it's not (though most are already or need proper set)
        if gdf.crs is None:
            print("Warning: No CRS found, assuming EPSG:4326")
            gdf.set_crs(epsg=4326, inplace=True)
        elif gdf.crs.to_epsg() != 4326:
            print(f"Converting CRS from {gdf.crs.to_epsg()} to 4326")
            gdf = gdf.to_crs(epsg=4326)

        # Handle column names (make lowercase for postgres and remove special chars)
        # Note: We need exact case from Benchmark! Benchmark uses CQ_Buildings_2021 etc.
        # But postgres is case-insensitive unless quoted. We'll let geopandas to_postgis handle it.
        # Wait, benchmark has `Floor` and `maxspeed`.
        # To avoid postgres case quoting issues, let's keep original column names but ensure geometry column is 'geometry'
        if gdf.active_geometry_name != 'geometry':
            gdf = gdf.rename_geometry('geometry')

        print(f"Writing to PostGIS table {ds['table']} ... (rows: {len(gdf)})")
        gdf.to_postgis(ds['table'], engine, if_exists="replace", index=False)
        print(f"Successfully imported {ds['table']}")
    except Exception as e:
        print(f"Failed to import {ds['table']}: {e}")

print("All imports completed.")
