from data_agent.uwm.traditional_safety_comfort import decide_join_status,build_safety_comfort_product

def test_exact_and_aggregate_require_explicit_keys():
 assert decide_join_status(source_unit='township',target_unit='township',source_join_key='admin_unit_id',target_join_key='admin_unit_id',crosswalk_available=False)=='exact_supported'
 assert decide_join_status(source_unit='township',target_unit='county',source_join_key='township_id',target_join_key='county_id',crosswalk_available=True)=='aggregate_supported'
def test_names_centroids_and_missing_crosswalk_never_create_supported_join():
 assert decide_join_status(source_unit='township',target_unit='county',source_join_key='name',target_join_key='name',crosswalk_available=False)=='reference_only'
 assert decide_join_status(source_unit='grid',target_unit='township',source_join_key='centroid',target_join_key='centroid',crosswalk_available=False)=='incompatible'
 assert decide_join_status(source_unit='township',target_unit='county',source_join_key='township_id',target_join_key='county_id',crosswalk_available=False)=='reference_only'
def test_product_exposes_source_join_status_without_forced_fusion():
 p=build_safety_comfort_product(admin_units=[{'admin_unit_id':'A','county':'甲'}],mobility_rows=[],meteorology_rows=[],air_quality_rows=[],public_safety_facilities=[],evidence_sources=[{'source_id':'met','source_spatial_unit':'grid','source_spatial_unit_count':10,'source_time_range':'2024-07','join_key':'centroid','target_spatial_unit':'county','target_join_key':'centroid','crosswalk_available':False}])
 s=p['evidence_sources'][0];assert s['join_status']=='incompatible';assert s['join_reason']=='centroid_join_forbidden';assert p['admin_units'][0]['meteorology_context']['temperature_2m_mean_c'] is None
