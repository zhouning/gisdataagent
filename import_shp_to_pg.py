import os
import sys
import geopandas as gpd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import urllib.parse
import argparse

# Load env from data_agent folder
load_dotenv(os.path.join(os.path.dirname(__file__), 'data_agent', '.env'))

# Must match TABLE_PREFIX in data_agent/database_tools.py
TABLE_OWNERSHIP = "agent_table_ownership"

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

def import_shp(shp_path, table_name, owner="admin", shared=False):
    engine = get_engine()

    # Try to enable PostGIS
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
            conn.commit()
            print("PostGIS extension enabled.")
    except Exception as e:
        print(f"Could not enable PostGIS: {e}")

    print(f"Reading Shapefile: {shp_path}...")
    gdf = gpd.read_file(shp_path)
    print(f"  Rows: {len(gdf)}")
    print(f"  CRS: {gdf.crs}")

    # Ensure column names are lower case
    gdf.columns = [c.lower() for c in gdf.columns]

    print(f"Importing to table '{table_name}'...")
    try:
        gdf.to_postgis(table_name, engine, if_exists='replace', index=False)
        print(f"Successfully imported '{table_name}'.")

        with engine.connect() as conn:
            count = conn.execute(text(f"SELECT count(*) FROM {table_name}")).scalar()
            print(f"  Verification: Table '{table_name}' now has {count} rows.")

            # Register ownership
            conn.execute(text(f"""
                INSERT INTO {TABLE_OWNERSHIP} (table_name, owner_username, is_shared, description)
                VALUES (:t, :u, :s, :d)
                ON CONFLICT (table_name) DO UPDATE
                SET owner_username = :u, is_shared = :s, description = :d
            """), {"t": table_name, "u": owner, "s": shared,
                   "d": f"Imported from {os.path.basename(shp_path)}"})
            conn.commit()
            print(f"  Registered ownership: owner={owner}, shared={shared}")
    except Exception as e:
        print(f"Import failed: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import Shapefile to PostGIS")
    parser.add_argument("shp_file", nargs="?", default="斑竹村10000.shp",
                        help="Path to the Shapefile")
    parser.add_argument("table_name", nargs="?", default="banzhu_village_10000",
                        help="Target table name in PostgreSQL")
    parser.add_argument("--owner", default="admin",
                        help="Owner username for table_ownership registry (default: admin)")
    parser.add_argument("--shared", action="store_true",
                        help="Mark the table as shared (accessible to all users)")
    args = parser.parse_args()

    if not os.path.exists(args.shp_file):
        print(f"File not found: {args.shp_file}")
    else:
        import_shp(args.shp_file, args.table_name,
                   owner=args.owner, shared=args.shared)
