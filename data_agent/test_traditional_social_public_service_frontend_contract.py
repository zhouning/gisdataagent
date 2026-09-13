from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];PANEL=ROOT/'frontend/src/components/datapanel/TraditionalLivabilitySocialPublicServicePanel.tsx';TAB=ROOT/'frontend/src/components/datapanel/TraditionalLivabilityTab.tsx'
def test_panel_exposes_two_evidence_bounded_views():
 text=PANEL.read_text(encoding='utf-8')
 for required in ['/api/uwm/traditional-livability/social-public-service/overview','/api/uwm/traditional-livability/social-public-service/facilities','/api/uwm/traditional-livability/social-public-service/admin-units','/api/uwm/traditional-livability/social-public-service/map','社会基础设施（需求12）','政府与公共服务（需求21）','social_infrastructure','government_public_service','relative_evidence_gap','数据未就绪','虚构值','__handleMapUpdate']:
  assert required in text
 for forbidden in ['设施超负荷','权威服务不足','未来设施需求预测','政策效果已验证']:
  assert forbidden not in text
def test_panel_is_registered_in_traditional_tab():
 text=TAB.read_text(encoding='utf-8');assert 'TraditionalLivabilitySocialPublicServicePanel' in text;assert '<TraditionalLivabilitySocialPublicServicePanel />' in text
