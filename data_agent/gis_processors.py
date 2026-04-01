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

from .user_context import get_user_upload_dir

_BASE_UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")


def _generate_output_path(prefix: str, extension: str = "shp") -> str:
    """Generates a unique output file path in the current user's upload directory.

    When DEFAULT_STORAGE_BACKEND=cloud, also schedules async upload after write.
    The returned path is always local (tools write locally first).
    """
    unique_id = uuid.uuid4().hex[:8]
    filename = f"{prefix}_{unique_id}.{extension}"
    user_dir = get_user_upload_dir()
    return os.path.abspath(os.path.join(user_dir, filename))


def sync_to_obs(local_path: str) -> None:
    """Upload to cloud storage and register in data catalog. Silent on failure.

    Uses StorageManager for consistent cloud I/O.
    """
    try:
        from .storage_manager import get_storage_manager
        from .user_context import current_user_id
        uid = current_user_id.get()
        sm = get_storage_manager()
        if sm.cloud_available:
            uri = sm.store(local_path, user_id=uid)
            # Register cloud asset in catalog
            if uri.startswith("s3://"):
                try:
                    from .data_catalog import auto_register_from_path
                    # Extract key from URI
                    key = uri.split("://", 1)[1].split("/", 1)[1] if "/" in uri else ""
                    auto_register_from_path(
                        local_path, storage_backend="cloud", cloud_key=key,
                    )
                except Exception:
                    pass
    except Exception:
        pass


def _resolve_path(file_path: str) -> str:
    """Resolve file path, checking URI schemes → user sandbox → subdirs → LOCAL_DATA_DIRS → shared → cloud.

    Supports s3://, obs://, postgis:// URIs via StorageManager.
    """
    # Handle URI schemes (s3://, obs://, postgis://, file://)
    if "://" in file_path:
        try:
            from .storage_manager import get_storage_manager
            return get_storage_manager().resolve(file_path)
        except Exception:
            pass
    if os.path.isabs(file_path):
        if os.path.exists(file_path):
            return file_path
    if os.path.exists(file_path):
        return os.path.abspath(file_path)
    # Check in user's upload folder first
    user_dir = get_user_upload_dir()
    user_path = os.path.join(user_dir, os.path.basename(file_path))
    if os.path.exists(user_path):
        return user_path
    # Check subdirectories of user folder (recursive basename search)
    basename = os.path.basename(file_path)
    for root, dirs, files in os.walk(user_dir):
        if basename in files:
            return os.path.join(root, basename)
        # Limit depth to avoid excessive scanning
        depth = root[len(user_dir):].count(os.sep)
        if depth >= 3:
            dirs.clear()
    # Check LOCAL_DATA_DIRS (read-only mounted directories)
    local_data_dirs = os.environ.get("LOCAL_DATA_DIRS", "")
    if local_data_dirs:
        for entry in local_data_dirs.split(","):
            entry = entry.strip()
            if not entry:
                continue
            # Strip label if present (label:path format)
            if ":" in entry and not (len(entry) > 1 and entry[1] == ":"):
                _, entry = entry.split(":", 1)
            entry = entry.strip()
            # Try exact relative path under this dir
            candidate = os.path.join(entry, file_path)
            if os.path.exists(candidate):
                return os.path.abspath(candidate)
            # Try basename match
            candidate = os.path.join(entry, basename)
            if os.path.exists(candidate):
                return os.path.abspath(candidate)
    # Fallback: check shared uploads folder (backward compat)
    upload_path = os.path.join(_BASE_UPLOAD_DIR, file_path)
    if os.path.exists(upload_path):
        return upload_path
    # Fallback: check by basename in shared uploads
    shared_path = os.path.join(_BASE_UPLOAD_DIR, os.path.basename(file_path))
    if os.path.exists(shared_path):
        return shared_path
    # Cloud fallback: download from OBS if not found locally
    try:
        from .obs_storage import is_obs_configured, download_file_smart
        from .user_context import current_user_id
        if is_obs_configured():
            uid = current_user_id.get()
            s3_key = f"{uid}/{os.path.basename(file_path)}"
            local_path = download_file_smart(s3_key, user_dir)
            if local_path and os.path.exists(local_path):
                return local_path
    except Exception:
        pass
    return file_path


def _resolve_and_extract_zip(file_path: str) -> str:
    """Resolve path and auto-extract ZIP if needed, returning the spatial file inside.

    If the resolved path is a .zip, extract it and search for spatial files
    (.shp, .geojson, .gpkg, .kml, .json) inside. Returns the first spatial
    file found, or the original zip path if none found.
    """
    resolved = _resolve_path(file_path)

    if not resolved.lower().endswith(".zip") or not os.path.exists(resolved):
        return resolved

    # Extract ZIP
    extract_dir = os.path.join(os.path.dirname(resolved), os.path.splitext(os.path.basename(resolved))[0])
    os.makedirs(extract_dir, exist_ok=True)

    try:
        import zipfile as _zf
        with _zf.ZipFile(resolved, "r") as zr:
            zr.extractall(extract_dir)
    except Exception:
        return resolved  # Can't extract, return zip path

    # Search for spatial files in priority order
    for target_ext in (".shp", ".geojson", ".gpkg", ".kml", ".json"):
        for root, _dirs, files in os.walk(extract_dir):
            for fname in files:
                if fname.lower().endswith(target_ext):
                    return os.path.abspath(os.path.join(root, fname))

    return resolved  # No spatial file found, return zip path


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

from scipy.stats import gaussian_kde
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def generate_heatmap(file_path: str, bandwidth: float = None, resolution: int = 300, weight_field: str = None) -> str:
    """
    [Business Analysis] Generates a Kernel Density Estimation (KDE) heatmap from point data.

    Args:
        file_path: Path to point vector file (SHP/GeoJSON/CSV with lat/lon).
        bandwidth: KDE bandwidth (smoothing). If None, auto-selected via Scott's rule.
        resolution: Grid resolution (pixels per axis). Default 300.
        weight_field: Optional numeric column to use as weight for weighted KDE.

    Returns:
        Path to the generated heatmap PNG image.
    """
    try:
        gdf = gpd.read_file(_resolve_path(file_path))

        # Project to metric CRS for distance-based bandwidth
        original_crs = gdf.crs
        if gdf.crs and gdf.crs.is_geographic:
            gdf_proj = gdf.to_crs(epsg=3857)
        else:
            gdf_proj = gdf.copy()

        # Extract coordinates
        points = gdf_proj[~gdf_proj.geometry.is_empty & gdf_proj.geometry.notna()]
        if len(points) < 2:
            return "Error in generate_heatmap: Need at least 2 valid points"

        x = points.geometry.x.values
        y = points.geometry.y.values
        coords = np.vstack([x, y])

        # Build KDE
        if weight_field and weight_field in points.columns:
            weights = points[weight_field].values.astype(float)
            weights = np.abs(weights)  # Ensure non-negative
            if weights.sum() == 0:
                weights = None
            kde = gaussian_kde(coords, bw_method=bandwidth, weights=weights)
        else:
            kde = gaussian_kde(coords, bw_method=bandwidth)

        # Create evaluation grid
        margin = 0.05  # 5% margin
        x_range = x.max() - x.min()
        y_range = y.max() - y.min()
        xmin = x.min() - margin * x_range
        xmax = x.max() + margin * x_range
        ymin = y.min() - margin * y_range
        ymax = y.max() + margin * y_range

        xi = np.linspace(xmin, xmax, resolution)
        yi = np.linspace(ymin, ymax, resolution)
        xi_grid, yi_grid = np.meshgrid(xi, yi)
        grid_coords = np.vstack([xi_grid.ravel(), yi_grid.ravel()])

        # Evaluate KDE
        zi = kde(grid_coords).reshape(xi_grid.shape)

        # Plot
        fig, ax = plt.subplots(1, 1, figsize=(12, 10))
        im = ax.imshow(
            zi, origin='lower', aspect='auto',
            extent=[xmin, xmax, ymin, ymax],
            cmap='YlOrRd', interpolation='bilinear'
        )

        # Overlay original points
        ax.scatter(x, y, c='black', s=3, alpha=0.3, zorder=5)

        plt.colorbar(im, ax=ax, label='Density', shrink=0.8)
        ax.set_title('Kernel Density Estimation (KDE) Heatmap', fontsize=14)
        ax.set_axis_off()

        out_path = _generate_output_path("heatmap", "png")
        plt.savefig(out_path, dpi=200, bbox_inches='tight', facecolor='white')
        plt.close()

        return out_path

    except Exception as e:
        return f"Error in generate_heatmap: {str(e)}"

from sklearn.cluster import DBSCAN

def perform_clustering(file_path: str, eps: float = 500, min_samples: int = 5) -> str:
    """
    [Business Analysis] Performs DBSCAN clustering on point data.
    
    Args:
        file_path: Path to point vector file (SHP/GeoJSON).
        eps: The maximum distance between two samples for one to be considered as in the neighborhood of the other (in meters if projected).
        min_samples: The number of samples (or total weight) in a neighborhood for a point to be considered as a core point.
        
    Returns:
        Path to the new Shapefile with 'cluster_id' field.
    """
    try:
        gdf = gpd.read_file(_resolve_path(file_path))
        
        # DBSCAN requires projected coordinates (meters), not Lat/Lon
        # If geographic, reproject temporarily for calculation
        original_crs = gdf.crs
        if gdf.crs and gdf.crs.is_geographic:
            gdf_proj = gdf.to_crs(epsg=3857) # Web Mercator
        else:
            gdf_proj = gdf
            
        coords = np.array(list(zip(gdf_proj.geometry.x, gdf_proj.geometry.y)))
        
        # Run DBSCAN
        db = DBSCAN(eps=eps, min_samples=min_samples).fit(coords)
        
        # Add labels to original GDF
        gdf['cluster_id'] = db.labels_
        
        # Save
        out_path = _generate_output_path("clustering", "shp")
        gdf.to_file(out_path)
        
        return out_path
        
    except Exception as e:
        return f"Error in perform_clustering: {str(e)}"

def create_buffer(file_path: str, distance: float = 500.0, dissolve: bool = False) -> str:
    """
    [Spatial Tool] Creates a buffer zone around features at a specified distance.
    
    Args:
        file_path: Input vector file.
        distance: Buffer distance in meters.
        dissolve: If True, merges all overlapping buffers into a single polygon.
    """
    try:
        gdf = gpd.read_file(_resolve_path(file_path))
        
        # Buffering must be done in a projected CRS (meters)
        original_crs = gdf.crs
        if not gdf.crs or gdf.crs.is_geographic:
            gdf = gdf.to_crs(epsg=3857)
            
        gdf['geometry'] = gdf.geometry.buffer(distance)
        
        if dissolve:
            # Union all geometries
            unified_geom = gdf.geometry.unary_union
            gdf = gpd.GeoDataFrame(geometry=[unified_geom], crs=gdf.crs)
            
        # Back to original CRS if it was geographic
        if original_crs and original_crs.is_geographic:
            gdf = gdf.to_crs(original_crs)
            
        out_path = _generate_output_path("buffer", "shp")
        gdf.to_file(out_path)
        return out_path
    except Exception as e:
        return f"Error in create_buffer: {str(e)}"

def summarize_within(zone_file: str, data_file: str, stats_field: str = None) -> str:
    """
    [Analysis Tool] Calculates statistics for features that fall within polygon zones.
    Example: How many POIs are within a 500m buffer?
    
    Args:
        zone_file: Path to polygon zones (e.g. buffers).
        data_file: Path to features to be summarized (e.g. POI points or land parcels).
        stats_field: Optional numeric field to sum up (if None, only count is returned).
        
    Returns:
        Path to a CSV with summary results per zone.
    """
    try:
        gdf_zones = gpd.read_file(_resolve_path(zone_file))
        gdf_data = gpd.read_file(_resolve_path(data_file))
        
        # Ensure CRS match
        if gdf_zones.crs != gdf_data.crs:
            gdf_data = gdf_data.to_crs(gdf_zones.crs)
            
        # Add temporary ID to zones
        gdf_zones['temp_zone_id'] = range(len(gdf_zones))
        
        # Spatial Join
        joined = gpd.sjoin(gdf_data, gdf_zones, how="inner", predicate="within")
        
        if stats_field and stats_field in joined.columns:
            # Aggregate: Count and Sum of the field
            summary = joined.groupby('temp_zone_id')[stats_field].agg(['count', 'sum']).reset_index()
            summary.columns = ['zone_id', 'feature_count', f'total_{stats_field}']
        else:
            # Just Count
            summary = joined.groupby('temp_zone_id').size().reset_index()
            summary.columns = ['zone_id', 'feature_count']
            
        # Merge back to zones to keep all zones (even those with 0 count)
        final_df = pd.merge(gdf_zones[['temp_zone_id']], summary, left_on='temp_zone_id', right_on='zone_id', how='left').fillna(0)
        final_df.drop(columns=['temp_zone_id'], inplace=True)
        
        out_path = _generate_output_path("summarize_within", "csv")
        final_df.to_csv(out_path, index=False)
        return out_path
    except Exception as e:
        return f"Error in summarize_within: {str(e)}"

def overlay_difference(input_file: str, erase_file: str) -> str:
    """
    [Spatial Tool] Erases the area of 'erase_file' from 'input_file'.
    Useful for 'exclusion' analysis (e.g., land strictly OUTSIDE a buffer zone).
    
    Args:
        input_file: The main features to process.
        erase_file: The polygon features to erase/subtract from input.
    
    Returns:
        Path to the resulting Shapefile.
    """
    try:
        gdf_in = gpd.read_file(_resolve_path(input_file))
        gdf_erase = gpd.read_file(_resolve_path(erase_file))
        
        # Ensure CRS match
        if gdf_in.crs != gdf_erase.crs:
            gdf_erase = gdf_erase.to_crs(gdf_in.crs)
            
        # Perform Difference (Erase)
        # overlay(how='difference') keeps parts of input that do NOT intersect erase
        result = gpd.overlay(gdf_in, gdf_erase, how='difference')
        
        out_path = _generate_output_path("difference", "shp")
        result.to_file(out_path)
        return out_path
    except Exception as e:
        return f"Error in overlay_difference: {str(e)}"

def find_within_distance(target_file: str, reference_file: str, distance: float = 1000.0, mode: str = "within") -> str:
    """
    [Spatial Tool] Filters target features based on distance to reference features.

    Use cases:
    - Site selection: "Find parcels within 500m of schools"
    - Exclusion analysis: "Find land beyond 2000m from factories"

    Args:
        target_file: Features to filter (e.g., parcels, candidate sites).
        reference_file: Features to measure distance from (e.g., schools, factories).
        distance: Distance threshold in meters.
        mode: "within" keeps features within the distance; "beyond" keeps features beyond the distance.

    Returns:
        Path to the filtered Shapefile.
    """
    try:
        gdf_target = gpd.read_file(_resolve_path(target_file))
        gdf_ref = gpd.read_file(_resolve_path(reference_file))

        # Project to metric CRS for accurate distance calculation
        target_crs = gdf_target.crs
        if gdf_target.crs and gdf_target.crs.is_geographic:
            gdf_target_proj = gdf_target.to_crs(epsg=3857)
        else:
            gdf_target_proj = gdf_target.copy()

        if gdf_ref.crs != gdf_target_proj.crs:
            gdf_ref_proj = gdf_ref.to_crs(gdf_target_proj.crs)
        else:
            gdf_ref_proj = gdf_ref.copy()

        # Buffer reference features by the distance threshold
        ref_buffer = gdf_ref_proj.copy()
        ref_buffer['geometry'] = ref_buffer.geometry.buffer(distance)
        # Dissolve all buffers into one polygon for efficient spatial join
        ref_buffer_union = gpd.GeoDataFrame(
            geometry=[ref_buffer.geometry.unary_union],
            crs=gdf_target_proj.crs
        )

        # Spatial join: find target features that intersect the buffer zone
        joined = gpd.sjoin(gdf_target_proj, ref_buffer_union, how="left", predicate="intersects")

        if mode.lower() == "within":
            # Keep features that ARE within distance (matched in join)
            result_mask = joined['index_right'].notna()
        else:
            # Keep features that are BEYOND distance (not matched)
            result_mask = joined['index_right'].isna()

        result_indices = joined[result_mask].index.unique()
        result = gdf_target.loc[result_indices]

        if len(result) == 0:
            return f"No features found {mode} {distance}m of reference features."

        out_path = _generate_output_path("distance_filter", "shp")
        result.to_file(out_path)
        return out_path

    except Exception as e:
        return f"Error in find_within_distance: {str(e)}"

def filter_vector_data(file_path: str, expression: str) -> str:
    """
    [GIS Tool] Filters vector data using a query expression and saves the result to a new file.
    
    Args:
        file_path: Path to the input spatial file or PostGIS table name.
        expression: A pandas-style query expression, e.g., "dlbm == '0101'" or "area > 1000".
                   If input is a table, simple SQL-like field names are supported.
    Returns:
        Path to the filtered output Shapefile.
    """
    try:
        from .utils import _load_spatial_data
        gdf = _load_spatial_data(file_path)
        if gdf.empty:
            return f"Error: Input data is empty."
        
        # Clean expression (replace !field! or "field" if LLM uses them)
        import re
        clean_expr = re.sub(r'!(\w+)!', r'`\1`', expression)
        
        filtered_gdf = gdf.query(clean_expr)
        if filtered_gdf.empty:
            return f"Warning: Filter expression '{expression}' returned no records."
            
        out_path = _generate_output_path("filtered", "shp")
        filtered_gdf.to_file(out_path, encoding='utf-8')
        return out_path
    except Exception as e:
        return f"Error filtering data: {str(e)}"


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


def list_fgdb_layers(file_path: str) -> dict:
    """列出 Esri File Geodatabase (.gdb) 中的所有图层及其要素数、几何类型。

    Args:
        file_path: File Geodatabase 目录路径（xxx.gdb）。

    Returns:
        包含图层列表的字典，每个图层有 name、count、geometry_type 字段。
    """
    try:
        import fiona
        path = _resolve_path(file_path)
        layers = fiona.listlayers(path)
        if not layers:
            return {"status": "ok", "layers": [], "message": "GDB 为空"}
        result = []
        for name in layers:
            try:
                with fiona.open(path, layer=name) as src:
                    result.append({
                        "name": name,
                        "count": len(src),
                        "geometry_type": src.schema.get("geometry", "Unknown"),
                        "fields": list(src.schema.get("properties", {}).keys()),
                    })
            except Exception as e:
                result.append({"name": name, "error": str(e)[:100]})
        return {"status": "ok", "layer_count": len(result), "layers": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def list_dxf_layers(file_path: str) -> dict:
    """列出 DXF/DWG 文件中的图层及其实体类型和数量。

    Args:
        file_path: DXF 或 DWG 文件路径。

    Returns:
        包含图层列表的字典，每个图层有 name、entity_types、count 字段。
    """
    try:
        import ezdxf
        path = _resolve_path(file_path)
        doc = ezdxf.readfile(str(path))
        msp = doc.modelspace()
        layer_stats: dict = {}
        for entity in msp:
            layer = entity.dxf.layer if hasattr(entity.dxf, 'layer') else '0'
            etype = entity.dxftype()
            if layer not in layer_stats:
                layer_stats[layer] = {"name": layer, "entity_types": {}, "count": 0}
            layer_stats[layer]["count"] += 1
            layer_stats[layer]["entity_types"][etype] = layer_stats[layer]["entity_types"].get(etype, 0) + 1
        layers = sorted(layer_stats.values(), key=lambda x: x["count"], reverse=True)
        return {"status": "ok", "layer_count": len(layers), "layers": layers}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def check_field_standards(file_path: str, standard_schema: str = "") -> dict[str, any]:
    """
    [Governance Tool] 按数据标准校验属性字段：字段存在性、必填约束(M/C/O)、值域枚举、类型兼容、长度限制。

    Args:
        file_path: Path to the data file.
        standard_schema: Either a standard ID (e.g. "dltb_2023") to auto-load from Standard Registry,
                         or a JSON dict string e.g. '{"DLMC": {"type": "string", "allowed": ["水田", "旱地"]}}'
    """
    try:
        standard_obj = None  # Full DataStandard for M/C/O + max_length checks

        # Resolve schema: standard_id or inline JSON
        if standard_schema and not standard_schema.strip().startswith("{"):
            from .standard_registry import StandardRegistry
            std_id = standard_schema.strip()
            schema = StandardRegistry.get_field_schema(std_id)
            standard_obj = StandardRegistry.get(std_id)
            if not schema:
                return {"status": "error", "message": f"未找到标准定义: {standard_schema}"}
        elif standard_schema:
            import json as _json
            schema = _json.loads(standard_schema)
        else:
            return {"status": "error", "message": "请提供标准ID (如 'dltb_2023') 或 JSON schema"}

        gdf = gpd.read_file(_resolve_path(file_path))
        results = {
            "missing_fields": [],
            "missing_mandatory": [],
            "mandatory_nulls": [],
            "type_mismatches": [],
            "length_violations": [],
            "invalid_values": [],
        }

        # --- Enumeration / allowed-value checks (existing logic) ---
        for field_name, rules in schema.items():
            if field_name not in gdf.columns:
                results["missing_fields"].append(field_name)
                continue
            if "allowed" in rules and rules["allowed"]:
                non_null = gdf[field_name].dropna()
                if not non_null.empty:
                    invalid = non_null[~non_null.astype(str).isin([str(v) for v in rules["allowed"]])]
                    if not invalid.empty:
                        results["invalid_values"].append({
                            "field": field_name,
                            "count": len(invalid),
                            "sample": invalid.unique().tolist()[:5],
                        })

        # --- Extended checks when full standard is available ---
        TYPE_MAP = {
            "string": ["object", "str", "string"],
            "numeric": ["float64", "float32", "int64", "int32", "Float64", "Int64"],
            "integer": ["int64", "int32", "Int64", "int16"],
            "date": ["datetime64"],
        }

        if standard_obj:
            for fspec in standard_obj.fields:
                # M/C/O mandatory check
                if fspec.required == "M":
                    if fspec.name not in gdf.columns:
                        if fspec.name not in results["missing_mandatory"]:
                            results["missing_mandatory"].append(fspec.name)
                    else:
                        null_count = int(gdf[fspec.name].isna().sum())
                        empty_count = 0
                        if gdf[fspec.name].dtype == object:
                            empty_count = int((gdf[fspec.name] == "").sum())
                        total_missing = null_count + empty_count
                        if total_missing > 0:
                            results["mandatory_nulls"].append({
                                "field": fspec.name, "null_count": total_missing,
                            })

                # Type compatibility check
                if fspec.name in gdf.columns and fspec.type in TYPE_MAP:
                    actual = str(gdf[fspec.name].dtype)
                    if not any(t in actual for t in TYPE_MAP[fspec.type]):
                        results["type_mismatches"].append({
                            "field": fspec.name,
                            "expected": fspec.type,
                            "actual": actual,
                        })

                # max_length check (string fields)
                if fspec.max_length and fspec.name in gdf.columns:
                    try:
                        str_col = gdf[fspec.name].dropna().astype(str)
                        over = str_col[str_col.str.len() > fspec.max_length]
                        if not over.empty:
                            results["length_violations"].append({
                                "field": fspec.name,
                                "max_length": fspec.max_length,
                                "violation_count": len(over),
                                "sample": over.head(3).tolist(),
                            })
                    except Exception:
                        pass

        # --- Compliance rate ---
        total_checks = len(schema)
        issue_fields = set(results["missing_fields"]) | {v["field"] for v in results["invalid_values"]}
        passed = total_checks - len(issue_fields)
        results["compliance_rate"] = round(passed / total_checks * 100, 1) if total_checks else 100.0
        results["is_standard"] = not (results["missing_mandatory"] or results["invalid_values"])
        return results
    except Exception as e:
        return {"status": "error", "message": str(e)}


def polygon_neighbors(file_path: str) -> str:
    """面邻域分析：找出每个面要素的相邻面及共享边界长度。
    输出CSV包含: src_FID, nbr_FID, LENGTH(共享边长度), NODE_COUNT(共享节点数)。
    Args:
        file_path: 面数据文件路径（Shapefile/GeoJSON/GPKG等）
    Returns:
        输出CSV文件路径，或错误信息
    """
    try:
        gdf = gpd.read_file(_resolve_path(file_path))
        if gdf.empty:
            return "错误：数据为空"
        # Project to planar CRS for accurate length measurement
        if gdf.crs and gdf.crs.is_geographic:
            gdf_proj = gdf.to_crs(epsg=3857)
        else:
            gdf_proj = gdf
        sindex = gdf_proj.sindex
        records = []
        for i, geom_i in enumerate(gdf_proj.geometry):
            if geom_i is None or geom_i.is_empty:
                continue
            candidates = list(sindex.intersection(geom_i.bounds))
            for j in candidates:
                if j <= i:
                    continue
                geom_j = gdf_proj.geometry.iloc[j]
                if geom_j is None or geom_j.is_empty:
                    continue
                if geom_i.touches(geom_j) or (geom_i.intersects(geom_j) and not geom_i.overlaps(geom_j)):
                    shared = geom_i.intersection(geom_j)
                    node_count = 0
                    if hasattr(shared, 'coords'):
                        node_count = len(list(shared.coords))
                    elif hasattr(shared, 'geoms'):
                        node_count = sum(len(list(g.coords)) for g in shared.geoms if hasattr(g, 'coords'))
                    records.append({
                        "src_FID": i,
                        "nbr_FID": j,
                        "LENGTH": round(shared.length, 4),
                        "NODE_COUNT": node_count,
                    })
        result = pd.DataFrame(records, columns=["src_FID", "nbr_FID", "LENGTH", "NODE_COUNT"])
        out_path = _generate_output_path("neighbors", "csv")
        result.to_csv(out_path, index=False, encoding='utf-8')
        return out_path
    except Exception as e:
        return f"面邻域分析失败: {str(e)}"


def add_field(file_path: str, field_name: str, field_type: str = "TEXT",
              default_value: str = None) -> str:
    """在属性表中添加新字段。
    Args:
        file_path: 数据文件路径
        field_name: 新字段名
        field_type: 字段类型，TEXT/FLOAT/INTEGER/DOUBLE（默认TEXT）
        default_value: 默认值（可选）
    Returns:
        输出Shapefile路径，或错误信息
    """
    try:
        gdf = gpd.read_file(_resolve_path(file_path))
        type_map = {"TEXT": str, "FLOAT": float, "INTEGER": int, "DOUBLE": float}
        py_type = type_map.get(field_type.upper(), str)
        if default_value is not None:
            gdf[field_name] = py_type(default_value)
        else:
            gdf[field_name] = None
        out_path = _generate_output_path("add_field", "shp")
        gdf.to_file(out_path, encoding='utf-8')
        return out_path
    except Exception as e:
        return f"添加字段失败: {str(e)}"


def add_join(target_file: str, join_file: str,
             target_field: str, join_field: str) -> str:
    """属性表连接：基于共同字段将 join_file 的属性附加到 target_file（左连接）。
    Args:
        target_file: 目标数据文件路径（带几何）
        join_file: 连接数据文件路径（CSV或Shapefile等）
        target_field: 目标数据中的连接字段名
        join_field: 连接数据中的连接字段名
    Returns:
        输出Shapefile路径，或错误信息
    """
    try:
        gdf_target = gpd.read_file(_resolve_path(target_file))
        join_path = _resolve_path(join_file)
        if join_path.lower().endswith('.csv'):
            df_join = pd.read_csv(join_path, encoding='utf-8')
        else:
            df_join = gpd.read_file(join_path).drop(columns=['geometry'], errors='ignore')
        result = gdf_target.merge(
            df_join, left_on=target_field, right_on=join_field,
            how='left', suffixes=('', '_join')
        )
        out_path = _generate_output_path("joined", "shp")
        result.to_file(out_path, encoding='utf-8')
        return out_path
    except FileNotFoundError as e:
        return f"属性连接失败: {e}。Recovery: 请先调用 search_data_assets 或 list_user_files 检查可用文件"
    except Exception as e:
        err = str(e)
        recovery = ""
        if "column" in err.lower() or "not in" in err.lower() or "KeyError" in err:
            recovery = " Recovery: 连接字段不存在，请先调用 describe_geodataframe 查看可用字段列表"
        elif "CRS" in err or "crs" in err:
            recovery = " Recovery: 两个数据集坐标系不一致，请先调用 reproject_spatial_data 统一坐标系"
        return f"属性连接失败: {err}{recovery}"


def calculate_field(file_path: str, field_name: str, expression: str) -> str:
    """字段计算：用表达式计算字段值。
    表达式语法：字段引用用 !field_name! 包裹，支持算术运算。
    示例：!area! * 0.0001、!col_a! + !col_b!
    Args:
        file_path: 数据文件路径
        field_name: 目标字段名（已有则覆盖，不存在则新建）
        expression: 计算表达式
    Returns:
        输出Shapefile路径，或错误信息
    """
    try:
        import re
        gdf = gpd.read_file(_resolve_path(file_path))
        # Convert ArcGIS !field! syntax to pandas backtick syntax
        pandas_expr = re.sub(r'!(\w+)!', r'`\1`', expression)
        gdf[field_name] = gdf.eval(pandas_expr)
        out_path = _generate_output_path("calculated", "shp")
        gdf.to_file(out_path, encoding='utf-8')
        return out_path
    except Exception as e:
        return f"字段计算失败: {str(e)}"


def summary_statistics(file_path: str, stats_fields: str,
                       case_field: str = None) -> str:
    """汇总统计：按分组字段计算多种统计量。
    Args:
        file_path: 数据文件路径
        stats_fields: 统计规则，格式 "field1 SUM;field2 MEAN;field3 COUNT"
            支持: SUM, MEAN, MIN, MAX, COUNT, STD, FIRST, LAST
        case_field: 分组字段（可选，多字段用分号分隔）
    Returns:
        输出CSV文件路径，或错误信息
    """
    try:
        gdf = gpd.read_file(_resolve_path(file_path))
        df = pd.DataFrame(gdf.drop(columns=['geometry'], errors='ignore'))
        stat_map = {
            "SUM": "sum", "MEAN": "mean", "MIN": "min", "MAX": "max",
            "COUNT": "count", "STD": "std", "FIRST": "first", "LAST": "last",
        }
        agg_dict = {}
        for rule in stats_fields.split(';'):
            parts = rule.strip().split()
            if len(parts) < 2:
                continue
            field, stat = parts[0], parts[1].upper()
            agg_dict.setdefault(field, []).append(stat_map.get(stat, stat.lower()))
        if not agg_dict:
            return "错误：未能解析统计规则，格式应为 'field1 SUM;field2 MEAN'"
        if case_field:
            case_fields = [f.strip() for f in case_field.split(';')]
            result = df.groupby(case_fields).agg(agg_dict)
        else:
            result = df.groupby(lambda _: 'ALL').agg(agg_dict)
            result.index.name = None
        # Flatten MultiIndex columns
        if isinstance(result.columns, pd.MultiIndex):
            result.columns = [f"{col}_{stat.upper()}" for col, stat in result.columns]
        result = result.reset_index()
        out_path = _generate_output_path("summary_stats", "csv")
        result.to_csv(out_path, index=False, encoding='utf-8')
        return out_path
    except Exception as e:
        return f"汇总统计失败: {str(e)}"
