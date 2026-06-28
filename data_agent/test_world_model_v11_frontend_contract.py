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
    assert "statusBadgeClass" in text
    assert "BOUNDARY_DEFAULTS" in text
    assert "normalizeEvidence" in text
    assert "claim_scope: BOUNDARY_DEFAULTS.claim_scope" in text
    assert "runtime_dependency: BOUNDARY_DEFAULTS.runtime_dependency" in text
    assert "geofm_runtime_allowed: BOUNDARY_DEFAULTS.geofm_runtime_allowed" in text
    assert "twm_generator_role: BOUNDARY_DEFAULTS.twm_generator_role" in text
    assert "primary_twm_route: BOUNDARY_DEFAULTS.primary_twm_route" in text
    assert "blocks_validation: BOUNDARY_DEFAULTS.blocks_validation" in text
    assert "can_promote_claim_ladder: BOUNDARY_DEFAULTS.can_promote_claim_ladder" in text
    assert "claim_boundary: BOUNDARY_DEFAULTS.claim_boundary" in text
    assert "Array.isArray" in text
    assert "isRecord" in text
    assert "loadEvidence" in text
    assert "refreshEvidence" in text
    assert "method: 'POST'" in text
    assert "body: JSON.stringify({})" in text
    assert "metric_summary" in text
    assert "best_paper58_metrics" in text
    assert "baseline_metrics" in text
    assert "normalizeMetricValues" in text
    assert "mean_change_f1" in text
    assert "mean_fom" in text
    assert "mean_transition_accuracy" in text
    assert "mean_allocation_disagreement" in text
    assert "<th>Paper58</th>" in text
    assert "<th>GeoSOS-FLUS</th>" in text
    assert "<th>Delta</th>" in text
    assert "source_files" in text
    assert "paper58_benchmark_dir" in text
    assert "read_errors" in text
