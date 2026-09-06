SELECT stage, facility_type, COUNT(*) AS facility_count
FROM public.dim_facilities
GROUP BY stage, facility_type
ORDER BY stage, facility_type
LIMIT 1000;
