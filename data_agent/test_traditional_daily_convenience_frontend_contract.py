from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];P=ROOT/'frontend/src/components/datapanel/TraditionalLivabilityDailyConveniencePanel.tsx';T=ROOT/'frontend/src/components/datapanel/TraditionalLivabilityTab.tsx'
def test_panel_contract():
 text=P.read_text()
 for x in ['/api/uwm/traditional-livability/daily-convenience/overview','/api/uwm/traditional-livability/daily-convenience/places','/api/uwm/traditional-livability/daily-convenience/admin-units','/api/uwm/traditional-livability/daily-convenience/map','日常便利与商业活动证据（需求14）','daily_convenience','business_activity_evidence','bank_branch','atm_access_point','POI存在不代表实际营业','企业POI不代表就业岗位','相对缺口不代表权威市场短缺','relative_daily_convenience_evidence_gap','数据未就绪','__handleMapUpdate']:assert x in text
 for x in ['权威经济活力','就业岗位数量','盈利机会','经济激活效果已验证']:assert x not in text
def test_registered():
 text=T.read_text();assert 'TraditionalLivabilityDailyConveniencePanel' in text and '<TraditionalLivabilityDailyConveniencePanel />' in text
