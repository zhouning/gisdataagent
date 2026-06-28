from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_PANEL = ROOT / "frontend" / "src" / "components" / "DataPanel.tsx"
WORLD_MODEL_V11_TAB = ROOT / "frontend" / "src" / "components" / "datapanel" / "WorldModelV11Tab.tsx"


def test_world_model_v11_tab_is_registered_in_datapanel():
    text = DATA_PANEL.read_text(encoding="utf-8")

    assert "WorldModelV11Tab" in text
    assert "worldmodel_v11" in text
    assert "世界模型v1.1" in text
    assert "{activeTab === 'worldmodel_v11' && <WorldModelV11Tab />}" in text

    world_model_tab_positions = [
        text.index("{ key: 'worldmodel', label: '世界模型'"),
        text.index("{ key: 'worldmodel_v11', label: '世界模型v1.1'"),
        text.index("{ key: 'worldmodel_v2', label: '世界模型v2'"),
        text.index("{ key: 'worldmodel_v21', label: '世界模型v2.1'"),
    ]
    assert world_model_tab_positions == sorted(world_model_tab_positions)


def test_world_model_v11_tab_file_contains_boundary_contract():
    text = WORLD_MODEL_V11_TAB.read_text(encoding="utf-8")

    assert "/api/twm/paper58-benchmark" in text
    assert "/api/twm/paper58-benchmark/refresh" in text
    assert "Paper58 is external benchmark support only" in text
    assert "runtime_dependency=none" in text
    assert "geofm_runtime_allowed=false" in text
    assert "not_a_runtime_generator" in text
    assert "刷新证据" in text
    assert "disabled" in text
    assert "Task 3 wires the local evidence refresh endpoint" in text
