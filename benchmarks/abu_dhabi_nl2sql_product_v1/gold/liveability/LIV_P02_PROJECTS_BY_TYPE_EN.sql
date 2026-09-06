SELECT project_type, COUNT(*) AS project_count
FROM public.dim_projects
GROUP BY project_type
ORDER BY project_type
LIMIT 1000;
