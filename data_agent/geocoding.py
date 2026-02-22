import pandas as pd
import geopandas as gpd
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
import time
import os
from .gis_processors import _generate_output_path

def batch_geocode(file_path: str, address_col: str, city: str = None) -> dict:
    """
    [Data Processing Tool] Converts addresses in a table (Excel/CSV) to coordinates.
    
    Args:
        file_path: Path to .xlsx or .csv file.
        address_col: Name of the column containing addresses.
        city: Optional city context to improve accuracy (e.g., "Beijing").
    
    Returns:
        Dict with status and path to the generated Shapefile.
    """
    try:
        # 1. Load Data
        if file_path.endswith('.xlsx') or file_path.endswith('.xls'):
            df = pd.read_excel(file_path)
        else:
            df = pd.read_csv(file_path)
            
        if address_col not in df.columns:
            return {"status": "error", "message": f"Column '{address_col}' not found. Available: {list(df.columns)}"}
            
        # 2. Init Geocoder (Nominatim is free but slow/limited)
        # In production, replace/augment with Gaode/Baidu API
        geolocator = Nominatim(user_agent="data_agent_v3")
        geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1.1) # Respect OSM policy
        
        results = []
        success_count = 0
        
        print(f"Starting geocoding for {len(df)} records using address column: '{address_col}'...")
        
        # 3. Batch Process
        for idx, row in df.iterrows():
            addr = str(row[address_col])
            if city and city not in addr:
                query = f"{city} {addr}"
            else:
                query = addr
                
            try:
                location = geocode(query)
                if location:
                    results.append({
                        "geometry": gpd.points_from_xy([location.longitude], [location.latitude])[0],
                        **row.to_dict(),
                        "geocode_match": "High"
                    })
                    success_count += 1
                else:
                    # Keep record but without geometry? Or skip?
                    # For GIS analysis, we usually skip or mark as failed.
                    print(f"  [Warn] Failed to geocode: {query}")
            except Exception as e:
                print(f"  [Error] Geocoding error for {query}: {e}")
                
        if success_count == 0:
            return {"status": "error", "message": "No addresses could be geocoded."}
            
        # 4. Create GeoDataFrame
        gdf = gpd.GeoDataFrame(results, crs="EPSG:4326")
        
        # 5. Save as SHP (Standardize)
        out_path = _generate_output_path("geocoded", "shp")
        gdf.to_file(out_path, encoding='utf-8')
        
        return {
            "status": "success",
            "output_path": out_path,
            "total": len(df),
            "success": success_count,
            "message": f"Geocoded {success_count}/{len(df)} addresses."
        }
        
    except Exception as e:
        return {"status": "error", "message": str(e)}
