# Seed Data

Place seed data files here in CSV format:

```
point_id,name,longitude,latitude,elevation,datum,accuracy_class,source,survey_date
CP-SH-001,上海基准点A,121.4737,31.2304,4.2,CGCS2000,B,国家测绘基准,2023-06-15
CP-SH-002,上海基准点B,121.5100,31.2400,3.8,CGCS2000,C,国家测绘基准,2023-06-15
```

Load with:
```sql
COPY control_points(point_id, name, geom, elevation, datum, accuracy_class, source, survey_date)
FROM '/path/to/seed.csv' WITH CSV HEADER;
```

Note: The `geom` column requires PostGIS `ST_MakePoint(longitude, latitude, elevation)` transformation during import.
