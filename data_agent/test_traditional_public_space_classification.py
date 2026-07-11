import pytest
from data_agent.uwm.traditional_public_space import classify_public_space
@pytest.mark.parametrize('secondary,tertiary,expected',[('公园',None,'core_open_space'),('公园广场','城市广场','core_open_space'),('公园广场','植物园','core_open_space'),('公园广场','动物园','core_open_space'),('图书馆','图书馆','civic_cultural_space'),('博物馆','博物馆','civic_cultural_space'),('科技馆',None,'civic_cultural_space'),('运动场馆','综合体育馆','public_recreation_space')])
def test_allow_list(secondary,tertiary,expected):
 r=classify_public_space({'raw_primary_class':'x','raw_secondary_class':secondary,'raw_tertiary_class':tertiary});assert r['classification_decision']=='included';assert r['canonical_space_category']==expected;assert r['classification_reason']
@pytest.mark.parametrize('secondary,tertiary',[('娱乐场所','网吧'),('娱乐场所','KTV'),('度假疗养场所','度假村'),('影剧院','电影院'),('休闲场所','休闲场所'),('洗浴推拿场所',None)])
def test_deny_list_never_enters_product(secondary,tertiary):
 r=classify_public_space({'raw_primary_class':'体育休闲服务','raw_secondary_class':secondary,'raw_tertiary_class':tertiary});assert r['classification_decision'].startswith('excluded');assert r['canonical_space_category'] is None
