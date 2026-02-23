import os
import geopandas as gpd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import urllib.parse

# Load env from data_agent folder
load_dotenv(os.path.join(os.path.dirname(__file__), 'data_agent', '.env'))

def get_engine():
    user = os.environ.get("POSTGRES_USER")
    password = os.environ.get("POSTGRES_PASSWORD")
    host = os.environ.get("POSTGRES_HOST")
    port = os.environ.get("POSTGRES_PORT")
    db = os.environ.get("POSTGRES_DATABASE")
    
    if not all([user, password, db]):
        raise ValueError("Missing DB credentials in .env")
        
    password = urllib.parse.quote_plus(password)
    url = f"postgresql://{user}:{password}@{host}:{port}/{db}"
    return create_engine(url)

def import_shp(shp_path, table_name):
    engine = get_engine()
    
    # Try to enable PostGIS but proceed even if it fails (maybe it's already there)
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
            conn.commit()
            print("✅ PostGIS extension enabled.")
    except Exception as e:
        print(f"⚠️ Could not enable PostGIS (Permissions?): {e}")
        print("   -> Attempting import anyway...")

    print(f"Reading Shapefile: {shp_path}...")
    gdf = gpd.read_file(shp_path)
    print(f"  Rows: {len(gdf)}")
    print(f"  CRS: {gdf.crs}")
    
    # Ensure column names are lower case
    gdf.columns = [c.lower() for c in gdf.columns]
    
    print(f"Importing to table '{table_name}'...")
    try:
        # if_exists='replace' will DROP the table if it exists!
        gdf.to_postgis(table_name, engine, if_exists='replace', index=False)
        print(f"✅ Successfully imported '{table_name}'.")
        
        # Verify
        with engine.connect() as conn:
            count = conn.execute(text(f"SELECT count(*) FROM {table_name}")).scalar()
            print(f"  Verification: Table '{table_name}' now has {count} rows.")
            
    except Exception as e:
        print(f"❌ Import failed: {e}")

if __name__ == "__main__":
    shp_file = "斑竹村10000.shp"
    if not os.path.exists(shp_file):
        print(f"File not found: {shp_file}")
    else:
        import_shp(shp_file, "banzhu_village_10000")
