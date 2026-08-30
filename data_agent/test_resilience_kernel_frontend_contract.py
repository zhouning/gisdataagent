from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_resilience_panel_uses_real_state_and_fail_closed_scenario_routes():
    text = (ROOT / 'frontend/src/components/datapanel/ResilienceWorldModelTab.tsx').read_text(encoding='utf-8')
    for required in [
        '/api/uwm/resilience-kernel/nodes',
        '/api/uwm/resilience-kernel/scenario-readiness',
        '审查情景是否可推演',
        '空间邻接不是灾害传播系数',
        '动态推演已阻断：证据不足',
        '__handleMapUpdate',
    ]:
        assert required in text
