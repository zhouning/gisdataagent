from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];P=ROOT/'frontend/src/components/datapanel/TraditionalLivabilitySafetyComfortPanel.tsx';T=ROOT/'frontend/src/components/datapanel/TraditionalLivabilityTab.tsx'
def test_panel_contract():
 text=P.read_text()
 for x in ['/api/uwm/traditional-livability/safety-comfort/overview','/api/uwm/traditional-livability/safety-comfort/admin-units','/api/uwm/traditional-livability/safety-comfort/evidence-sources','/api/uwm/traditional-livability/safety-comfort/map','安全与舒适证据诊断（需求10）','证据缺口排名不代表危险程度','温度上下文不等于热舒适','路网上下文不等于道路安全','relative_safety_comfort_evidence_gap','field_collection_priorities','reference_only','数据未就绪','__handleMapUpdate']:assert x in text
 for x in ['权威行人风险','犯罪风险等级','安全路线已验证','无障碍合规','安全干预效果已验证']:assert x not in text
def test_registered():
 text=T.read_text();assert 'TraditionalLivabilitySafetyComfortPanel' in text and '<TraditionalLivabilitySafetyComfortPanel />' in text
