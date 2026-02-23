import os
import pandas as pd
import geopandas as gpd
from sqlalchemy import create_engine, text
from .gis_processors import _generate_output_path

import urllib.parse

def get_db_connection_url():
    """Constructs database URL from environment variables."""
    user = os.environ.get("POSTGRES_USER")
    password = os.environ.get("POSTGRES_PASSWORD")
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DATABASE")
    
    if not all([user, password, db]):
        return None
        
    password = urllib.parse.quote_plus(password)
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"

def query_database(sql_query: str) -> dict:
    """
    [Database Tool] Executes a SQL query against the configured PostgreSQL/PostGIS database.
    
    Args:
        sql_query: The SQL statement to execute. SELECT statements return data.
    
    Returns:
        Dict with status, message, and path to results (CSV/SHP).
    """
    db_url = get_db_connection_url()
    if not db_url:
        return {"status": "error", "message": "Database credentials not configured in .env"}
        
    try:
        engine = create_engine(db_url)
        
        # Check if it's a spatial query (contains 'geometry' or 'geom')
        # Also assume SELECT * on a known spatial table is spatial.
        # But for safety, just check for common geometry column names.
        is_spatial = any(k in sql_query.lower() for k in ['geometry', 'geom', 'the_geom'])
        
        # Special case: If it's "SELECT *", we might not see the column name in the query string.
        # We can inspect the result cursor description?
        # For simplicity, let's just make the test query explicit or assume it returns geometry if the user asks for it.
        # BUT for the test case "SELECT * FROM banzhu...", it failed.
        
        # Better approach: Try reading with Pandas first? No, we want GeoPandas for geometry.
        # Let's inspect the columns using SQLAlchemy first?
        
        with engine.connect() as conn:
            # Execute query to get cursor/result proxy
            result_proxy = conn.execute(text(sql_query))
            keys = list(result_proxy.keys())
            
            # Check if any column looks like geometry
            geom_col = next((k for k in keys if k.lower() in ['geometry', 'geom', 'shape']), None)
            
            if geom_col:
                # Use GeoPandas
                # We need to re-execute or fetch from result_proxy? 
                # gpd.read_postgis requires a connection or engine, and SQL.
                # It executes the SQL again.
                gdf = gpd.read_postgis(sql_query, conn, geom_col=geom_col)
                out_path = _generate_output_path("query_result", "shp")
                # Fix for Shapefile field length limit (10 chars)
                # Rename columns if needed or warn?
                # For now just save.
                gdf.to_file(out_path, encoding='utf-8')
                return {
                    "status": "success", 
                    "output_path": out_path, 
                    "rows": len(gdf),
                    "message": f"Spatial query returned {len(gdf)} rows. Saved to {out_path}"
                }
            else:
                # Use Pandas
                # result_proxy is already executed/consumed? No, we just read keys.
                # fetchall
                df = pd.DataFrame(result_proxy.fetchall(), columns=keys)
                out_path = _generate_output_path("query_result", "csv")
                df.to_csv(out_path, index=False)
                return {
                    "status": "success", 
                    "output_path": out_path, 
                    "rows": len(df),
                    "message": f"Query returned {len(df)} rows. Saved to {out_path}"
                }
                
    except Exception as e:
        return {"status": "error", "message": str(e)}

def list_tables() -> dict:
    """[Database Tool] Lists all tables in the database."""
    return query_database("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
