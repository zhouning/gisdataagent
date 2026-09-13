from __future__ import annotations
import hashlib,json
from copy import deepcopy
CHANNELS=('approved_land_use','floor_area_ratio','building_density','building_height','green_space_ratio','setback','building_spacing','parking_requirement','public_service_requirement','land_use_compatibility','special_control_zone','approval_document','rule_priority','effective_period')
def build_development_control_product(*,rule_assets,source_artifacts):
 assets=deepcopy(rule_assets)
 for x in assets:
  if x.get('rule_asset_class')=='reference_standard' and x.get('execution_status')=='executable':raise ValueError('reference_standard_cannot_be_executable')
  if not x.get('source_path'):raise ValueError('rule_source_path_required')
 channels={k:{'status':'unavailable','value':None,'production_blockers':['approved_site_specific_dcr_missing']} for k in CHANNELS}
 contracts={'executable_rule':{'required_fields':['authoritative_source','approved_or_published_identifier','version','effective_period','spatial_applicability','object_type','parameter_definition','unit_and_calculation_method','conflict_priority','citation_reference']}}
 gate={'status':'closed','mechanisms':{'site_rule_applicability':'closed','legal_parameter_extraction':'closed','rule_conflict_resolution':'closed','project_compliance_decision':'closed','constraint_propagation':'closed','automatic_scheme_modification':'closed'}}
 digest={'assets':assets,'channels':channels};bid='development-control-'+hashlib.sha256(json.dumps(digest,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:20]
 return {'schema':'uwm.development_control_rule_readiness.v1','bundle_id':bid,'summary':{'rule_asset_count':len(assets),'executable_site_rule_count':sum(x.get('execution_status')=='executable' for x in assets),'dcr_channel_count':len(channels),'available_dcr_channel_count':0},'rule_assets':assets,'dcr_channels':channels,'data_contracts':contracts,'execution_gate':gate,'source_artifacts':sorted(map(str,source_artifacts)),'claim_boundary':{'max_claim_level':'planning_rule_asset_catalog_and_site_specific_dcr_execution_readiness','reference_standard_not_site_specific_dcr':True,'rule_text_not_approved_planning_condition':True,'static_screening_distance_not_legal_setback':True,'land_use_class_not_development_permission':True,'rule_match_not_project_approval':True,'missing_rule_not_unrestricted_development':True},'fabricated_value_count':0}
