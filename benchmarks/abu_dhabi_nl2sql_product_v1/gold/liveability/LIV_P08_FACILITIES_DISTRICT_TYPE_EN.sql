SELECT d.name_en AS district_name, f.facility_type,
       COUNT(*) AS facility_count
FROM public.dim_facilities AS f
JOIN public.dim_districts AS d ON d.district_id = f.district_id
GROUP BY d.name_en, f.facility_type
ORDER BY d.name_en, f.facility_type
LIMIT 1000;
