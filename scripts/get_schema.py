import pandas as pd
from sqlalchemy import create_engine, text
import json

DB_URI = 'postgresql://postgres:Supermap2024.@192.168.100.215:30355/gis_agent'
engine = create_engine(DB_URI)

tables = ['cq_buildings_2021', 'cq_osm_roads_2021', 'cq_amap_poi_2024', 'cq_land_use_dltb']
schema_info = {}

try:
    with engine.connect() as conn:
        for t in tables:
            # Get columns
            res = conn.execute(text(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{t}'")).fetchall()
            cols = {row[0]: row[1] for row in res}
            
            # Get samples
            try:
                samples = pd.read_sql(text(f'SELECT * FROM {t} LIMIT 2;'), conn)
                if 'geometry' in samples.columns:
                    samples = samples.drop(columns=['geometry'])
                sample_dict = samples.to_dict(orient='records')
            except Exception as e:
                sample_dict = str(e)
                
            schema_info[t] = {'columns': cols, 'samples': sample_dict}

    print(json.dumps(schema_info, ensure_ascii=False, indent=2, default=str))
except Exception as e:
    print(e)
