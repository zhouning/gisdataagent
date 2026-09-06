SELECT d.name_en AS district_name, f.facility_type,
       COUNT(*) AS facility_count
FROM public.dim_districts AS d
JOIN public.dim_facilities AS f
  ON ST_Covers(d.geom, f.geom)
GROUP BY d.name_en, f.facility_type
ORDER BY d.name_en, f.facility_type
LIMIT 1000;
