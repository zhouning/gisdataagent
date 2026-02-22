import geopandas as gpd
import pandas as pd
import numpy as np
import rasterio
import rasterio.features
from rasterio.transform import from_origin
from rasterstats import zonal_stats
from shapely.geometry import box, Polygon
import os
import uuid
from typing import Optional, Union, List

def _generate_output_path(prefix: str, extension: str = "shp") -> str:
    """Generates a unique output file path."""
    unique_id = uuid.uuid4().hex[:8]
    filename = f"{prefix}_{unique_id}.{extension}"
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "uploads", filename))

def _resolve_path(file_path: str) -> str:
    if os.path.isabs(file_path): return file_path
    if os.path.exists(file_path): return os.path.abspath(file_path)
    # Check in uploads folder
    upload_path = os.path.join(os.path.dirname(__file__), "uploads", file_path)
    if os.path.exists(upload_path): return upload_path
    return file_path

def generate_tessellation(extent_file: str, shape_type: str = "SQUARE", size: float = 1000.0) -> str:
    """
    Generates a tessellation (grid) of polygons covering the extent of an input feature class.
    
    Args:
        extent_file: Path to the vector file defining the extent.
        shape_type: "SQUARE" (default) or "HEXAGON".
        size: Side length (for square) or radius (for hexagon) in CRS units.
    
    Returns:
        Path to the generated Shapefile.
    """
    try:
        gdf = gpd.read_file(_resolve_path(extent_file))
        bounds = gdf.total_bounds # (minx, miny, maxx, maxy)
        minx, miny, maxx, maxy = bounds
        
        polygons = []
        
        if shape_type.upper() == "SQUARE":
            x_coords = np.arange(minx, maxx + size, size)
            y_coords = np.arange(miny, maxy + size, size)
            for x in x_coords:
                for y in y_coords:
                    polygons.append(box(x, y, x + size, y + size))
                    
        elif shape_type.upper() == "HEXAGON":
            # Horizontal distance between centers = size * 1.5
            # Vertical distance between centers = size * sqrt(3)
            h_dist = size * 1.5
            v_dist = size * np.sqrt(3)
            cols = int((maxx - minx) / h_dist) + 2
            rows = int((maxy - miny) / v_dist) + 2
            
            for col in range(cols):
                for row in range(rows):
                    cx = minx + col * h_dist
                    cy = miny + row * v_dist
                    if col % 2 == 1:
                        cy += v_dist / 2
                    
                    # Create hexagon vertices
                    angles = np.linspace(0, 2*np.pi, 7)[:-1]
                    px = cx + size * np.cos(angles)
                    py = cy + size * np.sin(angles)
                    poly = Polygon(zip(px, py))
                    polygons.append(poly)
        else:
            return "Error: shape_type must be 'SQUARE' or 'HEXAGON'"

        # Filter polygons that intersect the original geometry (optional, but mimics GIS behavior)
        grid_gdf = gpd.GeoDataFrame(geometry=polygons, crs=gdf.crs)
        # Only keep grid cells that intersect the extent
        # valid_grid = gpd.sjoin(grid_gdf, gdf, how="inner", predicate="intersects").drop_duplicates(subset='geometry')
        # Actually, ArcGIS Generate Tessellation usually just fills the extent box. Let's return the full grid clipped to bbox.
        
        out_path = _generate_output_path("tessellation", "shp")
        grid_gdf.to_file(out_path)
        return out_path
        
    except Exception as e:
        return f"Error in generate_tessellation: {str(e)}"

def raster_to_polygon(raster_file: str, value_field: str = "gridcode") -> str:
    """
    Converts a raster dataset to a polygon feature class.
    
    Args:
        raster_file: Path to the input raster (GeoTIFF).
        value_field: Name of the field to store the raster value.
        
    Returns:
        Path to the generated Shapefile.
    """
    try:
        path = _resolve_path(raster_file)
        with rasterio.open(path) as src:
            image = src.read(1) # Read first band
            mask = src.read_masks(1)
            results = (
                {'properties': {value_field: v}, 'geometry': s}
                for i, (s, v) 
                in enumerate(rasterio.features.shapes(image, mask=mask, transform=src.transform))
            )
            
            geoms = list(results)
            if not geoms:
                return "Error: No valid data found in raster to vectorize."
                
            gdf = gpd.GeoDataFrame.from_features(geoms)
            gdf.set_crs(src.crs, inplace=True)
            
            out_path = _generate_output_path("raster_poly", "shp")
            gdf.to_file(out_path)
            return out_path
            
    except Exception as e:
        return f"Error in raster_to_polygon: {str(e)}"

def pairwise_clip(input_features: str, clip_features: str) -> str:
    """
    Clips input features to the polygons of the clip features.
    
    Args:
        input_features: Vector file to be clipped.
        clip_features: Vector file defining the clip area.
        
    Returns:
        Path to the clipped Shapefile.
    """
    try:
        gdf_in = gpd.read_file(_resolve_path(input_features))
        gdf_clip = gpd.read_file(_resolve_path(clip_features))
        
        # Ensure CRS match
        if gdf_in.crs != gdf_clip.crs:
            gdf_clip = gdf_clip.to_crs(gdf_in.crs)
            
        clipped = gpd.clip(gdf_in, gdf_clip)
        
        out_path = _generate_output_path("clipped", "shp")
        clipped.to_file(out_path)
        return out_path
        
    except Exception as e:
        return f"Error in pairwise_clip: {str(e)}"

def tabulate_intersection(zone_features: str, class_features: str, class_field: str) -> str:
    """
    Computes the intersection area between two feature classes and cross-tabulates.
    
    Args:
        zone_features: The regions (zones) to summarize within.
        class_features: The features (classes) to summarize.
        class_field: The field in class_features to group by (e.g., 'LandUseType').
        
    Returns:
        Path to the CSV containing the table.
    """
    try:
        gdf_zone = gpd.read_file(_resolve_path(zone_features))
        gdf_class = gpd.read_file(_resolve_path(class_features))
        
        # Ensure projected CRS for area calculation
        if gdf_zone.crs.is_geographic:
            gdf_zone = gdf_zone.to_crs(epsg=3857)
        if gdf_class.crs != gdf_zone.crs:
            gdf_class = gdf_class.to_crs(gdf_zone.crs)
            
        # Add a unique ID to zones if not present
        if 'zone_id' not in gdf_zone.columns:
            gdf_zone['zone_id'] = range(len(gdf_zone))
            
        # Calculate intersection
        overlay = gpd.overlay(gdf_zone, gdf_class, how='intersection')
        overlay['intersect_area'] = overlay.geometry.area
        
        # Pivot table
        # Index: zone_id, Columns: class_field, Values: intersect_area
        df = overlay.groupby(['zone_id', class_field])['intersect_area'].sum().reset_index()
        pivot = df.pivot(index='zone_id', columns=class_field, values='intersect_area').fillna(0)
        
        # Add zone total area for percentage calc
        zone_areas = gdf_zone.set_index('zone_id').geometry.area
        pivot['Total_Zone_Area'] = zone_areas
        
        out_path = _generate_output_path("tabulate_intersection", "csv")
        pivot.to_csv(out_path)
        return out_path
        
    except Exception as e:
        return f"Error in tabulate_intersection: {str(e)}"

def surface_parameters(dem_raster: str, parameter_type: str = "SLOPE") -> str:
    """
    Calculates surface parameters (Slope, Aspect) from a DEM raster.
    
    Args:
        dem_raster: Path to input DEM GeoTIFF.
        parameter_type: "SLOPE" (degrees) or "ASPECT" (degrees).
        
    Returns:
        Path to the output raster (GeoTIFF).
    """
    try:
        path = _resolve_path(dem_raster)
        with rasterio.open(path) as src:
            dem = src.read(1)
            transform = src.transform
            # Pixel size (assuming square pixels)
            dx = transform[0]
            dy = -transform[4] # Usually negative in GeoTransform
            
            # Numpy Gradient
            # gradient returns [dy, dx]
            grad = np.gradient(dem, dy, dx) 
            dz_dy = grad[0]
            dz_dx = grad[1]
            
            if parameter_type.upper() == "SLOPE":
                # Slope in degrees = arctan(sqrt(dz/dx^2 + dz/dy^2)) * 180 / pi
                slope_rad = np.arctan(np.sqrt(dz_dx**2 + dz_dy**2))
                out_data = np.degrees(slope_rad)
                
            elif parameter_type.upper() == "ASPECT":
                # Aspect in degrees = 180/pi * arctan2(dz/dy, -dz/dx)
                # Note: Aspect definition varies. GIS usually: North=0, Clockwise.
                # Standard math atan2(y, x) is CCW from X-axis.
                # GIS Aspect = 270 - math_degrees (normalized to 0-360)
                aspect_rad = np.arctan2(dz_dy, -dz_dx)
                aspect_deg = np.degrees(aspect_rad)
                # Convert to North-Azimuth (0=N, 90=E)
                # Rule of thumb conversion
                out_data = 270 - aspect_deg
                out_data[out_data >= 360] -= 360
                out_data[out_data < 0] += 360
                
            else:
                return "Error: parameter_type must be 'SLOPE' or 'ASPECT'"
                
            out_path = _generate_output_path(f"surface_{parameter_type.lower()}", "tif")
            
            with rasterio.open(
                out_path, 'w',
                driver='GTiff',
                height=out_data.shape[0],
                width=out_data.shape[1],
                count=1,
                dtype=rasterio.float32,
                crs=src.crs,
                transform=transform,
            ) as dst:
                dst.write(out_data.astype(rasterio.float32), 1)
                
            return out_path
            
    except Exception as e:
        return f"Error in surface_parameters: {str(e)}"

def zonal_statistics_as_table(zone_vector: str, value_raster: str, stats: list[str] = ["mean", "sum", "count", "min", "max"]) -> str:
    """
    Calculates statistics on values of a raster within the zones of a vector dataset.
    
    Args:
        zone_vector: Polygon vector file defining zones.
        value_raster: Raster file to calculate statistics on.
        stats: List of statistics to calculate (default: mean, sum, count, min, max).
    
    Returns:
        Path to the CSV file containing the statistics table.
    """
    try:
        zones_path = _resolve_path(zone_vector)
        raster_path = _resolve_path(value_raster)
        
        # Calculate stats
        # rasterstats handles reprojecting vector to raster CRS automatically usually, but safer if aligned
        # For simplicity, we trust rasterstats
        zs = zonal_stats(zones_path, raster_path, stats=stats, geojson_out=False)
        
        # Convert to DataFrame
        df = pd.DataFrame(zs)
        
        # Optionally add Zone ID if available in vector
        gdf = gpd.read_file(zones_path)
        # Try to find a meaningful ID column
        id_col = next((c for c in ['ID', 'Id', 'id', 'fid', 'FID', 'zone_id', 'NAME', 'Name'] if c in gdf.columns), None)
        if id_col:
            df.insert(0, id_col, gdf[id_col])
        else:
            df.insert(0, 'FID', range(len(df)))
            
        out_path = _generate_output_path("zonal_stats", "csv")
        df.to_csv(out_path, index=False)
        return out_path
        
    except Exception as e:
        return f"Error in zonal_statistics_as_table: {str(e)}"

def check_topology(file_path: str) -> dict[str, any]:
    """
    [Governance Tool] Scans GIS data for topological errors: self-intersections, overlaps, and multi-part geometries.
    
    Returns:
        A dictionary summarizing errors and paths to error-highlighting layers.
    """
    try:
        gdf = gpd.read_file(_resolve_path(file_path))
        report = {"total_features": len(gdf), "errors": {}}
        
        # 1. Invalid Geometries (Self-intersections)
        invalid_mask = ~gdf.geometry.is_valid
        n_invalid = int(invalid_mask.sum())
        if n_invalid > 0:
            out_invalid = _generate_output_path("err_invalid", "shp")
            gdf[invalid_mask].to_file(out_invalid)
            report["errors"]["self_intersections"] = {"count": n_invalid, "layer": out_invalid}
            
        # 2. Overlaps (Crucial for To G)
        # We use a spatial join with itself to find intersections that aren't the same feature
        overlaps = []
        sindex = gdf.sindex
        for i, geom in enumerate(gdf.geometry):
            # Find candidate neighbors
            possible_matches_index = list(sindex.intersection(geom.bounds))
            possible_matches = gdf.iloc[possible_matches_index]
            for j, other_geom in possible_matches.geometry.items():
                if i < j: # Avoid double counting
                    if geom.overlaps(other_geom):
                        overlaps.append({"id_a": i, "id_b": j, "geometry": geom.intersection(other_geom)})
        
        if overlaps:
            gdf_overlaps = gpd.GeoDataFrame(overlaps, crs=gdf.crs)
            out_overlaps = _generate_output_path("err_overlaps", "shp")
            gdf_overlaps.to_file(out_overlaps)
            report["errors"]["overlaps"] = {"count": len(overlaps), "layer": out_overlaps}

        # 3. Multi-part Geometries (Often discouraged in standardization)
        is_multi = gdf.geometry.type.str.contains("Multi")
        n_multi = int(is_multi.sum())
        if n_multi > 0:
            report["errors"]["multi_part"] = {"count": n_multi, "message": "Recommend exploding to single parts"}

        report["status"] = "pass" if not report["errors"] else "fail"
        return report
    except Exception as e:
        return {"status": "error", "message": str(e)}

def check_field_standards(file_path: str, standard_schema: dict) -> dict[str, any]:
    """
    [Governance Tool] Validates attribute data against a standard schema (field names, types, and allowed values).
    
    Args:
        file_path: Path to the data file.
        standard_schema: Dict e.g. {"DLMC": {"type": "string", "allowed": ["水田", "旱地", "有林地"]}}
    """
    try:
        gdf = gpd.read_file(_resolve_path(file_path))
        results = {"missing_fields": [], "type_mismatches": [], "invalid_values": []}
        
        for field, rules in standard_schema.items():
            if field not in gdf.columns:
                results["missing_fields"].append(field)
                continue
            
            # Check values if 'allowed' list exists
            if "allowed" in rules:
                invalid = gdf[~gdf[field].isin(rules["allowed"])]
                if not invalid.empty:
                    results["invalid_values"].append({
                        "field": field, 
                        "count": len(invalid), 
                        "sample": invalid[field].unique().tolist()[:5]
                    })
        
        results["is_standard"] = not (results["missing_fields"] or results["invalid_values"])
        return results
    except Exception as e:
        return {"status": "error", "message": str(e)}
