from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];P=ROOT/'frontend/src/components/datapanel/TraditionalLivabilityPublicSpacePanel.tsx';T=ROOT/'frontend/src/components/datapanel/TraditionalLivabilityTab.tsx'
def test_panel_contract():
 text=P.read_text(encoding='utf-8')
 for x in ['/api/uwm/traditional-livability/public-space/overview','/api/uwm/traditional-livability/public-space/spaces','/api/uwm/traditional-livability/public-space/admin-units','/api/uwm/traditional-livability/public-space/map','公共空间与场所营造（需求9）','core_open_space','civic_cultural_space','public_recreation_space','排除记录','relative_public_space_evidence_gap','数据未就绪','虚构值','__handleMapUpdate']:assert x in text
 for x in ['权威公共空间不足','已观测景观品质','已观测街道活力','政策效果已验证']:assert x not in text
def test_registered():
 text=T.read_text(encoding='utf-8');assert 'TraditionalLivabilityPublicSpacePanel' in text and '<TraditionalLivabilityPublicSpacePanel />' in text
