import pytest
from data_agent.uwm.traditional_daily_convenience import classify_place
@pytest.mark.parametrize('primary,secondary,expected',[('购物服务','便民商店/便利店','convenience_store'),('购物','超市','supermarket'),('购物服务','综合市场','market'),('医疗保健服务','医药保健销售店','pharmacy'),('餐饮服务','咖啡厅','cafe'),('餐饮服务','快餐厅','fast_food'),('生活服务','邮局','postal_service'),('生活服务','洗衣店','laundry'),('生活服务','维修站点','repair_service'),('生活服务','电讯营业厅','telecom_outlet'),('金融保险服务','银行','bank_branch'),('金融保险服务','自动提款机','atm_access_point')])
def test_daily_allow_list(primary,secondary,expected):
 r=classify_place({'raw_primary_class':primary,'raw_secondary_class':secondary,'raw_tertiary_class':None});assert r['classification_decision']=='included';assert r['canonical_category']==expected;assert r['view_membership']==['daily_convenience']
def test_company_is_business_evidence_not_employment():
 r=classify_place({'raw_primary_class':'公司企业','raw_secondary_class':'公司','raw_tertiary_class':None});assert r['view_membership']==['business_activity_evidence'];assert r['canonical_category']=='company_poi'
@pytest.mark.parametrize('primary,secondary',[('购物服务','家居建材市场'),('汽车销售','汽车销售'),('休闲娱乐','ktv'),('体育休闲服务','娱乐场所'),('酒店','酒店'),('生活服务','殡葬服务'),('生活服务','洗浴推拿场所'),('生活服务','生活服务场所'),('购物','其他'),('购物',None),('美食','住宅区')])
def test_daily_deny_or_ambiguous(primary,secondary):
 r=classify_place({'raw_primary_class':primary,'raw_secondary_class':secondary,'raw_tertiary_class':None});assert 'daily_convenience' not in r['view_membership']
