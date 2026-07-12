import pytest
from data_agent.uwm.development_control import build_development_control_product

def test_reference_standard_is_not_executable_dcr():
 assets=[{'rule_asset_id':'s1','title':'GB standard','rule_asset_class':'reference_standard','source_path':'x.yaml','version':'1','execution_status':'reference_only','max_claim_level':'reference'}]
 p=build_development_control_product(rule_assets=assets,source_artifacts=['x.yaml'])
 assert p['schema']=='uwm.development_control_rule_readiness.v1'
 assert all(x['status']=='unavailable' and x['value'] is None for x in p['dcr_channels'].values())
 assert all(v=='closed' for v in p['execution_gate']['mechanisms'].values())
 assert p['claim_boundary']['reference_standard_not_site_specific_dcr'] is True
 assert p['fabricated_value_count']==0

def test_reference_standard_cannot_be_executable():
 with pytest.raises(ValueError,match='reference_standard'):
  build_development_control_product(rule_assets=[{'rule_asset_id':'s','rule_asset_class':'reference_standard','source_path':'x','execution_status':'executable'}],source_artifacts=['x'])
