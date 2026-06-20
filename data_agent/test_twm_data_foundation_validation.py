from pathlib import Path

import importlib.util


SCRIPT = Path("scripts/validate_twm_data_foundation.py")
RUNNER_SCRIPT = Path("scripts/run_twm_synthetic_experiment.py")


def _load_script_module():
    spec = importlib.util.spec_from_file_location("validate_twm_data_foundation", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_runner_module():
    spec = importlib.util.spec_from_file_location("run_twm_synthetic_experiment", RUNNER_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_paper7_rows_to_causal_records_maps_empirical_dataset(tmp_path):
    module = _load_script_module()
    path = tmp_path / "causal_dataset.csv"
    path.write_text(
        "\n".join(
            [
                "treatment,outcome,budget_remaining,global_slope,global_cont,step_frac,slope_improvement,block_farm_slope,block_forest_slope,block_slope_gap,block_swap_potential,block_invested",
                "1,0.31,1.0,0.21,0.35,0.0,0.0,0.49,0.34,0.15,0.33,0.0",
                "0,-0.12,0.52,0.22,0.31,0.48,0.02,0.25,0.18,0.07,0.20,1.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    records = module.paper7_rows_to_causal_records(path)

    assert len(records) == 2
    assert records[0]["treatment"] == 1
    assert records[1]["treatment"] == 0
    assert records[0]["stratum"] == "step_decile_0"
    assert records[1]["stratum"] == "step_decile_4"
    assert records[0]["cluster"] == "budget_decile_0"
    assert records[1]["cluster"] == "budget_decile_4"
    assert records[0]["source"] == "paper7_causal_mbrl_dataset"
    assert records[0]["source_path"] == str(path)
    assert records[0]["covariates"]["global_slope"] == 0.21
    assert records[1]["covariates"]["block_invested"] == 1.0
    assert records[0]["synthetic"] is False
    assert records[0]["not_for_production"] is False


def test_observed_history_rows_with_project_neighbors_uses_shared_parcels(tmp_path):
    module = _load_script_module()
    tables_dir = tmp_path / "tables"
    relations_dir = tmp_path / "relations"
    tables_dir.mkdir()
    relations_dir.mkdir()
    (tables_dir / "approval_records.csv").write_text(
        "\n".join(
            [
                "approval_id,project_id,approval_status,outcome,DKXZQDM,synthetic,not_for_production",
                "APR-1,PRJ-1,approved,0.2,500227,True,True",
                "APR-2,PRJ-2,in_review,0.1,500227,True,True",
                "APR-3,PRJ-3,returned,0.0,500227,True,True",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (relations_dir / "project_parcel_rel.csv").write_text(
        "\n".join(
            [
                "relation_id,relation_type,project_id,bsm_norm,right_role,overlap_area_m2,synthetic,not_for_production",
                "REL-1,PROJECT_OVERLAPS_PARCEL,PRJ-1,PARCEL-A,parcel,10,True,True",
                "REL-2,PROJECT_OVERLAPS_PARCEL,PRJ-2,PARCEL-A,parcel,9,True,True",
                "REL-3,PROJECT_OVERLAPS_PARCEL,PRJ-3,PARCEL-B,parcel,8,True,True",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    neighbor_map = module.build_project_neighbor_map(tmp_path)
    rows = module.observed_history_rows_with_project_neighbors(tmp_path)

    assert neighbor_map == {"PRJ-1": {"PRJ-2"}, "PRJ-2": {"PRJ-1"}}
    by_project = {row["project_id"]: row for row in rows}
    assert by_project["PRJ-1"]["unit_id"] == "PRJ-1"
    assert by_project["PRJ-1"]["neighbors"] == "PRJ-2"
    assert by_project["PRJ-2"]["neighbors"] == "PRJ-1"
    assert "neighbors" not in by_project["PRJ-3"]


def test_audit_observed_history_schema_accepts_production_ready_rows(tmp_path):
    module = _load_script_module()
    path = tmp_path / "production_observed_history.csv"
    path.write_text(
        "\n".join(
            [
                "unit_id,approval_id,project_id,approval_status,outcome,cluster,neighbors,x,y,area_m2,quality_score,synthetic,not_for_production",
                "C-1,APR-C-1,PRJ-C-1,in_review,0.10,block-1,T-1,106.20,29.60,1000,0.82,False,False",
                "T-1,APR-T-1,PRJ-T-1,approved,0.20,block-1,C-1,106.21,29.61,1000,0.82,False,False",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    audit = module.audit_observed_history_schema(path)

    assert audit["schema"] == "territory_world_model.observed_history_schema_audit.v1"
    assert audit["status"] == "pass"
    assert audit["missing_required_groups"] == []
    assert audit["missing_data_gates"] == []
    assert audit["row_quality"]["production_candidate_row_count"] == 2
    assert audit["row_quality"]["production_treated_count"] == 1
    assert audit["row_quality"]["production_control_count"] == 1
    assert audit["row_quality"]["rows_with_neighbors"] == 2


def test_audit_observed_history_schema_reviews_demo_flags(tmp_path):
    module = _load_script_module()
    path = tmp_path / "demo_observed_history.csv"
    path.write_text(
        "\n".join(
            [
                "approval_id,project_id,approval_status,DKMJ,DKXZQDM,synthetic,not_for_production",
                "APR-1,PRJ-1,approved,1000,500227,True,True",
                "APR-2,PRJ-2,in_review,1000,500227,True,True",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    audit = module.audit_observed_history_schema(path)

    assert audit["status"] == "review"
    assert audit["missing_required_groups"] == []
    assert "production_usable_rows" in audit["missing_data_gates"]
    assert audit["row_quality"]["production_candidate_row_count"] == 0
    assert audit["row_quality"]["synthetic_count"] == 2
    assert audit["row_quality"]["not_for_production_count"] == 2


def test_write_observed_history_template_outputs_expected_columns(tmp_path):
    module = _load_script_module()
    path = tmp_path / "template.csv"

    module.write_observed_history_template(path)

    header = path.read_text(encoding="utf-8").splitlines()[0].split(",")
    assert "unit_id" in header
    assert "approval_status" in header
    assert "neighbors" in header
    assert "synthetic" in header
    assert "not_for_production" in header


def test_write_twm_structural_validation_observed_history_generates_balanced_fixture(tmp_path):
    module = _load_script_module()
    dataset_root = tmp_path / "dataset"
    tables_dir = dataset_root / "tables"
    relations_dir = dataset_root / "relations"
    tables_dir.mkdir(parents=True)
    relations_dir.mkdir()
    (tables_dir / "approval_records.csv").write_text(
        "\n".join(
            [
                "approval_id,project_id,approval_status,outcome,DKMJ,synthetic,not_for_production",
                "APR-1,PRJ-1,approved,0.20,1000,True,True",
                "APR-2,PRJ-2,in_review,0.10,1200,True,True",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tables_dir / "rule_evaluation.csv").write_text(
        "\n".join(
            [
                "rule_eval_id,project_id,severity,finding_status,metric_value,synthetic,not_for_production",
                "RULE-1,PRJ-1,high,hit_requires_review,10,True,True",
                "RULE-2,PRJ-2,info,pass,0,True,True",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (relations_dir / "project_parcel_rel.csv").write_text(
        "\n".join(
            [
                "relation_id,relation_type,project_id,bsm_norm,right_role,overlap_area_m2,synthetic,not_for_production",
                "REL-1,PROJECT_OVERLAPS_PARCEL,PRJ-1,PARCEL-A,parcel,10,True,True",
                "REL-2,PROJECT_OVERLAPS_PARCEL,PRJ-2,PARCEL-A,parcel,10,True,True",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    path = tmp_path / "structural_fixture.csv"

    summary = module.write_twm_structural_validation_observed_history(path, dataset_root, pair_count=6)
    rows = module.read_csv(path)
    quality = module._observed_history_row_quality(rows)

    assert summary["status"] == "generated"
    assert summary["pair_count"] == 6
    assert len(rows) == 12
    assert quality["treated_count"] == 6
    assert quality["control_count"] == 6
    assert quality["rows_with_neighbors"] == 12
    assert quality["synthetic_count"] == 12
    assert quality["not_for_production_count"] == 12
    assert {row["data_role"] for row in rows} == {"synthetic_structural_validation"}


def test_structural_validation_fixture_default_gate_reviews_but_structural_check_passes(tmp_path):
    module = _load_script_module()
    dataset_root = tmp_path / "dataset"
    (dataset_root / "tables").mkdir(parents=True)
    (dataset_root / "relations").mkdir()
    path = tmp_path / "structural_fixture.csv"
    module.write_twm_structural_validation_observed_history(path, dataset_root, pair_count=12)

    svc = module._build_validation_service()
    state_id = module._create_minimal_state(svc)

    default_summary = module.validate_twm_structural_validation_fixture(svc, state_id, path)
    structural_summary = module.validate_twm_structural_validation_fixture_structural_check(svc, state_id, path)

    assert default_summary["status"] == "review"
    assert "synthetic_records" in default_summary["evidence_gate"]["missing"]
    assert "not_for_production_records" in default_summary["evidence_gate"]["missing"]
    assert structural_summary["status"] == "pass"
    assert structural_summary["evidence_gate"]["missing"] == []
    assert structural_summary["estimate"]["spatial"]["neighbor_edge_count"] == 12
    assert structural_summary["estimate"]["spatial_estimator"]["status"] == "pass"


def test_write_twm_synthetic_experiment_foundation_generates_splits_and_roles(tmp_path):
    module = _load_script_module()
    dataset_root = tmp_path / "dataset"
    tables_dir = dataset_root / "tables"
    relations_dir = dataset_root / "relations"
    tables_dir.mkdir(parents=True)
    relations_dir.mkdir()
    (tables_dir / "approval_records.csv").write_text(
        "\n".join(
            [
                "approval_id,project_id,approval_status,outcome,DKMJ,synthetic,not_for_production",
                "APR-1,PRJ-1,approved,0.20,1000,True,True",
                "APR-2,PRJ-2,in_review,0.10,1200,True,True",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    path = tmp_path / "synthetic_experiment.csv"

    summary = module.write_twm_synthetic_experiment_foundation(
        path,
        dataset_root,
        region_count=2,
        period_count=4,
        component_count=3,
    )
    rows = module.read_csv(path)
    quality = module._observed_history_row_quality(rows)

    assert summary["status"] == "generated"
    assert summary["row_count"] == 48
    assert summary["pair_count"] == 24
    assert summary["region_count"] == 2
    assert summary["period_count"] == 4
    assert summary["holdout_period_count"] == 2
    assert summary["split_counts"] == {"test": 12, "train": 24, "validation": 12}
    assert summary["holdout_oracle_group_count"] == 4
    assert summary["holdout_oracle_action_type_count"] >= 2
    assert len(summary["holdout_oracle_action_counts"]) >= 2
    assert "action_mask_allowed" in rows[0]
    assert "action_mask_policy" in rows[0]
    assert set(summary["mixed_action_mask_action_types"]) - {"defer_review"}
    assert quality["treated_count"] == 24
    assert quality["control_count"] == 24
    assert quality["rows_with_neighbors"] == 48
    assert quality["synthetic_count"] == 48
    assert quality["not_for_production_count"] == 48
    assert {row["data_role"] for row in rows} == {"synthetic_experiment_foundation"}
    assert {"region_code", "period", "scenario_id", "split", "action_type", "next_state_score"}.issubset(rows[0])
    assert [module.synthetic_experiment_split_for_period(idx, 4) for idx in range(4)] == [
        "train",
        "train",
        "validation",
        "test",
    ]
    assert [module.synthetic_experiment_split_for_period(idx, 8) for idx in range(8)] == [
        "train",
        "train",
        "train",
        "train",
        "validation",
        "validation",
        "test",
        "test",
    ]


def test_synthetic_experiment_default_gate_reviews_but_structural_check_passes(tmp_path):
    module = _load_script_module()
    dataset_root = tmp_path / "dataset"
    (dataset_root / "tables").mkdir(parents=True)
    (dataset_root / "relations").mkdir()
    path = tmp_path / "synthetic_experiment.csv"
    module.write_twm_synthetic_experiment_foundation(
        path,
        dataset_root,
        region_count=3,
        period_count=4,
        component_count=3,
    )

    svc = module._build_validation_service()
    state_id = module._create_minimal_state(svc)

    default_summary = module.validate_twm_synthetic_experiment_foundation(svc, state_id, path)
    structural_summary = module.validate_twm_synthetic_experiment_foundation_structural_check(svc, state_id, path)

    assert default_summary["status"] == "review"
    assert "synthetic_records" in default_summary["evidence_gate"]["missing"]
    assert "not_for_production_records" in default_summary["evidence_gate"]["missing"]
    assert default_summary["foundation"]["split_counts"] == {"test": 18, "train": 36, "validation": 18}
    assert default_summary["foundation"]["holdout_oracle_action_type_count"] >= 2
    assert structural_summary["status"] == "pass"
    assert structural_summary["evidence_gate"]["missing"] == []
    assert structural_summary["estimate"]["spatial"]["neighbor_edge_count"] == 36
    assert structural_summary["estimate"]["spatial_estimator"]["status"] == "pass"


def test_synthetic_experiment_runner_converts_csv_to_dynamics_dataset(tmp_path):
    module = _load_script_module()
    runner = _load_runner_module()
    dataset_root = tmp_path / "dataset"
    (dataset_root / "tables").mkdir(parents=True)
    (dataset_root / "relations").mkdir()
    path = tmp_path / "synthetic_experiment.csv"
    module.write_twm_synthetic_experiment_foundation(
        path,
        dataset_root,
        region_count=2,
        period_count=4,
        component_count=3,
    )
    rows = runner.read_csv(path)
    svc = runner.build_experiment_service()
    state_id = runner.create_synthetic_experiment_state(svc, rows, source_path=path)
    state = svc.repository.get_state_version(state_id)

    dataset = runner.synthetic_rows_to_dynamics_dataset(
        rows,
        state_id=state_id,
        project_id=state.project_id,
        source_path=path,
        state_summary=state.summary,
    )

    assert dataset["schema"] == "territory_world_model.dynamics_training_dataset.v1"
    assert dataset["summary"]["example_count"] == 24
    assert dataset["summary"]["candidate_example_count"] == 12
    assert dataset["summary"]["holdout_example_count"] == 12
    assert dataset["summary"]["holdout_period_count"] == 2
    assert dataset["summary"]["max_holdout_steps_per_region"] == 2
    assert set(dataset["summary"]["mixed_action_mask_action_types"]) - {"defer_review"}
    assert dataset["summary"]["claim_boundary"] == "synthetic_experiment_only_not_for_production"
    assert {item["labels"]["supervision_source"] for item in dataset["examples"]} == {"state_snapshots"}
    assert {item["provenance"]["data_role"] for item in dataset["examples"]} == {"synthetic_experiment_foundation"}
    assert all(item["provenance"]["synthetic"] for item in dataset["examples"])
    assert all(item["provenance"]["not_for_production"] for item in dataset["examples"])
    assert all(not item["not_for_training_reasons"] for item in dataset["examples"])


def test_synthetic_experiment_runner_executes_simulator_planner_loop(tmp_path):
    module = _load_script_module()
    runner = _load_runner_module()
    dataset_root = tmp_path / "dataset"
    (dataset_root / "tables").mkdir(parents=True)
    (dataset_root / "relations").mkdir()
    path = tmp_path / "synthetic_experiment.csv"
    module.write_twm_synthetic_experiment_foundation(
        path,
        dataset_root,
        region_count=3,
        period_count=4,
        component_count=3,
    )

    report = runner.run_synthetic_experiment(path)

    assert report["schema"] == "territory_world_model.synthetic_experiment_runner_report.v1"
    assert report["claim_boundary"] == "synthetic_experiment_only_not_for_production"
    assert report["status"] in {"pass", "review"}
    assert report["dataset_summary"]["example_count"] == 36
    assert report["dataset_summary"]["holdout_ground_truth_example_count"] == 18
    assert report["readiness"]["status"] == "pass"
    assert report["fit"]["prediction_count"] == 36
    assert report["evaluation"]["status"] in {"pass", "review"}
    assert report["backend_comparison"]["schema"] == "territory_world_model.synthetic_backend_comparison.v1"
    assert report["backend_comparison"]["candidate_count"] == 5
    assert {
        item["training_method"]
        for item in report["backend_comparison"]["ranking"]
    } == {
        "evidence_supported_action_group_means",
        "weighted_multi_head_group_means",
        "torch_multi_head_mlp",
        "torch_multi_head_mlp+action_mask_calibration",
        "torch_multi_head_mlp+context_action_mask_calibration",
    }
    assert all(item["prediction_count"] == 36 for item in report["backend_comparison"]["ranking"])
    assert report["backend_comparison"]["action_mask_summary"]["schema"] == "territory_world_model.backend_action_mask_summary.v1"
    assert len(report["backend_comparison"]["action_mask_summary"]["rows"]) == 5
    assert report["backend_comparison"]["mixed_action_mask_generalization"]["schema"] == "territory_world_model.mixed_action_mask_generalization.v1"
    assert set(report["backend_comparison"]["mixed_action_mask_generalization"]["mixed_action_types"]) - {"defer_review"}
    assert report["backend_comparison"]["mixed_action_mask_generalization"]["action_type_only_failure_count"] >= 1
    assert report["backend_comparison"]["mixed_action_mask_generalization"]["context_zero_false_allow_count"] >= 1
    assert report["backend_comparison"]["mixed_action_mask_generalization"]["selected_calibration"] == "context"
    default_ranking = {
        item["candidate_id"]: item
        for item in report["backend_comparison"]["ranking"]
    }
    assert default_ranking["torch_multi_head_mlp_action_mask_calibrated"]["action_mask_diagnostics"]["confusion"]["false_allow"] > 0
    assert default_ranking["torch_multi_head_mlp_context_action_mask_calibrated"]["action_mask_diagnostics"]["confusion"]["false_allow"] == 0
    assert default_ranking["torch_multi_head_mlp"]["feature_contract_summary"]["has_action_mask_policy_context"] is True
    assert default_ranking["torch_multi_head_mlp"]["feature_contract_summary"]["has_action_mask_risk_context"] is True
    assert all(
        item["action_mask_diagnostics"]["schema"] == "territory_world_model.action_mask_diagnostics.v1"
        for item in report["backend_comparison"]["ranking"]
    )
    assert all(
        "confusion" in item["action_mask_diagnostics"]
        for item in report["backend_comparison"]["ranking"]
    )
    assert report["backend_comparison"]["selected"]["candidate_id"]
    assert report["action_mask_stress"]["schema"] == "territory_world_model.action_mask_calibration_stress.v1"
    assert {
        item["variant_id"]
        for item in report["action_mask_stress"]["variants"]
    } == {"raw_predictions", "action_type_calibration", "context_calibration"}
    assert report["backend_comparison"]["planner_holdout_summary"]["schema"] == "territory_world_model.backend_planner_holdout_summary.v1"
    assert len(report["backend_comparison"]["planner_holdout_summary"]["rows"]) == 5
    assert all(
        item["planner_holdout_analysis"]["schema"] == "territory_world_model.planner_holdout_analysis.v1"
        for item in report["backend_comparison"]["ranking"]
    )
    assert all(
        item["planner_holdout_analysis"]["by_region"]
        and item["planner_holdout_analysis"]["by_period"]
        and item["planner_holdout_analysis"]["by_action_type"]
        and item["planner_holdout_analysis"]["rollout_matrix"]["schema"] == "territory_world_model.planner_rollout_matrix.v1"
        and item["planner_holdout_analysis"]["rollout_matrix"]["trajectories"]
        for item in report["backend_comparison"]["ranking"]
    )
    assert report["planner_holdout_analysis"]["schema"] == "territory_world_model.planner_holdout_analysis.v1"
    assert "mean_regret" in report["planner_holdout_analysis"]["metrics"]
    assert len(report["planner_holdout_analysis"]["oracle_action_counts"]) >= 2
    assert report["planner_rollout_matrix"]["schema"] == "territory_world_model.planner_rollout_matrix.v1"
    assert report["planner_rollout_matrix"]["trajectory_count"] >= 1
    assert report["planner_rollout_matrix"]["step_count"] == 6
    assert "mean_cumulative_regret" in report["planner_rollout_matrix"]["metrics"]
    assert report["planner"]["ranking"]
    assert report["innovation_focus"]["simulator"].startswith("action-conditioned")


def test_synthetic_experiment_runner_calibrates_graph_and_transformer_action_masks(tmp_path):
    module = _load_script_module()
    runner = _load_runner_module()
    dataset_root = tmp_path / "dataset"
    (dataset_root / "tables").mkdir(parents=True)
    (dataset_root / "relations").mkdir()
    path = tmp_path / "synthetic_experiment.csv"
    module.write_twm_synthetic_experiment_foundation(
        path,
        dataset_root,
        region_count=3,
        period_count=4,
        component_count=3,
    )

    report = runner.run_synthetic_experiment(path, include_graph=True, include_transformer=True)

    ranking = {
        item["candidate_id"]: item
        for item in report["backend_comparison"]["ranking"]
    }
    assert "torch_hierarchical_graph_action_mask_calibrated" in ranking
    assert "torch_hierarchical_graph_context_action_mask_calibrated" in ranking
    assert "torch_spatiotemporal_transformer_action_mask_calibrated" in ranking
    assert "torch_spatiotemporal_transformer_context_action_mask_calibrated" in ranking
    assert "torch_spatiotemporal_transformer_constraint_risk_calibrated" in ranking
    assert "torch_spatiotemporal_transformer_constraint_risk_context_action_mask_calibrated" in ranking
    assert ranking["torch_hierarchical_graph_action_mask_calibrated"]["action_mask_diagnostics"]["confusion"]["false_allow"] > 0
    assert ranking["torch_hierarchical_graph_context_action_mask_calibrated"]["action_mask_diagnostics"]["confusion"]["false_allow"] == 0
    assert ranking["torch_spatiotemporal_transformer_action_mask_calibrated"]["action_mask_diagnostics"]["confusion"]["false_allow"] > 0
    assert ranking["torch_spatiotemporal_transformer_context_action_mask_calibrated"]["action_mask_diagnostics"]["confusion"]["false_allow"] == 0
    transformer_raw_error = ranking["torch_spatiotemporal_transformer"]["metrics"]["mean_constraint_error"]
    assert ranking["torch_spatiotemporal_transformer"]["training_diagnostics"]["constraint_risk_calibration_weight"] == 0.0
    assert ranking["torch_spatiotemporal_transformer"]["training_diagnostics"]["risk_head_mode"] == "context_residual"
    assert ranking["torch_spatiotemporal_transformer"]["architecture_summary"]["constraint_risk_head"] == "context_residual"
    assert set(ranking["torch_spatiotemporal_transformer"]["architecture_summary"]["constraint_risk_context_tokens"]) == {
        "action",
        "context",
        "temporal",
    }
    assert ranking["torch_hierarchical_graph_context_action_mask_calibrated"]["training_diagnostics"]["constraint_risk_calibration_weight"] == 0
    transformer_calibrated = ranking["torch_spatiotemporal_transformer_constraint_risk_context_action_mask_calibrated"]
    assert transformer_calibrated["architecture_summary"]["constraint_risk_head"] == "context_residual"
    risk_calibration = transformer_calibrated["constraint_risk_calibration"]
    assert risk_calibration["status"] in {"pass", "review"}
    if risk_calibration["status"] == "pass":
        assert transformer_calibrated["metrics"]["mean_constraint_error"] < transformer_raw_error
    else:
        assert set(risk_calibration["review_reasons"]) & {"low_prediction_variance", "degenerate_calibration_slope"}
    assert transformer_calibrated["action_mask_diagnostics"]["confusion"]["false_allow"] == 0
    head_probe = report["transformer_risk_head_probe"]
    assert head_probe["schema"] == "territory_world_model.transformer_risk_head_probe.v1"
    assert head_probe["selected"]["risk_head_mode"] == "context_residual"
    probe_rows = {row["risk_head_mode"]: row for row in head_probe["rows"]}
    assert probe_rows["context_residual"]["selected_candidate_split_mae_before"] < probe_rows["shared"]["selected_candidate_split_mae_before"]
    assert report["backend_comparison"]["candidate_count"] == 13


def test_synthetic_runner_probes_transformer_risk_calibration_weights(tmp_path):
    module = _load_script_module()
    runner = _load_runner_module()
    dataset_root = tmp_path / "dataset"
    (dataset_root / "tables").mkdir(parents=True)
    (dataset_root / "relations").mkdir()
    path = tmp_path / "synthetic_experiment.csv"
    module.write_twm_synthetic_experiment_foundation(
        path,
        dataset_root,
        region_count=3,
        period_count=4,
        component_count=3,
    )

    report = runner.run_synthetic_experiment(
        path,
        include_transformer=True,
        probe_transformer_risk_weights=[0.0, 0.7, 1.2],
    )

    probe = report["transformer_risk_weight_probe"]
    assert probe["schema"] == "territory_world_model.transformer_risk_weight_probe.v1"
    assert probe["status"] == "pass"
    assert report["backend_comparison"]["candidate_count"] == 10
    assert [row["weight"] for row in probe["rows"]] == [0.0, 0.7, 1.2]
    assert probe["selected"]["weight"] in {0.0, 0.7, 1.2}
    for row in probe["rows"]:
        assert row["risk_head_mode"] == "context_residual"
        assert set(row["risk_head_context_tokens"]) == {"action", "context", "temporal"}
        assert row["training_status"] == "pass"
        assert "candidate_split_mae_before" in row
        assert "candidate_split_mae_after" in row
        assert "false_allow" in row
        assert "planner_mean_regret" in row
    numeric_rows = [row for row in probe["rows"] if row["candidate_split_mae_before"] is not None]
    if numeric_rows:
        assert probe["selected"]["candidate_split_mae_before"] <= numeric_rows[0]["candidate_split_mae_before"]


def test_synthetic_runner_action_mask_diagnostics_identifies_false_allow():
    runner = _load_runner_module()
    dataset = {
        "examples": [
            {
                "id": "allow-1",
                "split": "holdout",
                "action": {"action_type": "protect"},
                "scenario_context": {"region_code": "R1", "period": "P1"},
                "targets": {
                    "action_mask": {"allowed": True, "required_reviews": [], "hard_blocks": []},
                    "constraint_violation_probability": 0.1,
                    "planning_utility_delta": 0.2,
                },
            },
            {
                "id": "block-1",
                "split": "holdout",
                "action": {"action_type": "defer_review"},
                "scenario_context": {"region_code": "R1", "period": "P1"},
                "targets": {
                    "action_mask": {"allowed": False, "required_reviews": ["synthetic_defer_review"], "hard_blocks": []},
                    "constraint_violation_probability": 0.4,
                    "planning_utility_delta": 0.01,
                },
            },
        ]
    }
    predictions = {
        "allow-1": {"action_mask": {"allowed": True, "confidence": 0.9}},
        "block-1": {"action_mask": {"allowed": True, "confidence": 0.7}},
    }

    diagnostics = runner.action_mask_diagnostics_for_predictions(dataset, predictions)
    worst = runner.worst_action_type(diagnostics)

    assert diagnostics["accuracy"] == 0.5
    assert diagnostics["confusion"]["false_allow"] == 1
    assert diagnostics["confusion"]["false_block"] == 0
    assert diagnostics["by_action_type"]["defer_review"]["accuracy"] == 0.0
    assert worst["action_type"] == "defer_review"
    assert worst["accuracy"] == 0.0
    assert diagnostics["mismatches"][0]["mismatch_type"] == "false_allow"


def test_synthetic_runner_action_mask_calibration_blocks_review_actions():
    runner = _load_runner_module()
    dataset = {
        "examples": [
            {
                "id": "candidate-block",
                "split": "candidate",
                "action": {"action_type": "defer_review"},
                "targets": {
                    "action_mask": {
                        "allowed": False,
                        "required_reviews": ["synthetic_defer_review"],
                        "hard_blocks": [],
                        "confidence": 0.8,
                    }
                },
            },
            {
                "id": "holdout-block",
                "split": "holdout",
                "action": {"action_type": "defer_review"},
                "targets": {
                    "action_mask": {
                        "allowed": False,
                        "required_reviews": ["synthetic_defer_review"],
                        "hard_blocks": [],
                        "confidence": 0.8,
                    }
                },
            },
        ]
    }
    candidate = {
        "schema": "territory_world_model.neural_multi_head_dynamics_candidate_report.v1",
        "status": "pass",
        "candidate": {"model_name": "mlp", "model_family": "test"},
        "predictions": {
            "candidate-block": {"action_mask": {"allowed": True, "confidence": 0.7}},
            "holdout-block": {"action_mask": {"allowed": True, "confidence": 0.7}},
        },
        "evidence_gate": {"status": "pass"},
    }

    calibrated = runner.calibrated_action_mask_candidate_report(candidate, dataset)
    diagnostics = runner.action_mask_diagnostics_for_predictions(dataset, calibrated["predictions"])

    assert calibrated["schema"] == "territory_world_model.action_mask_calibrated_candidate_report.v1"
    assert calibrated["candidate"]["action_mask_calibrated"] is True
    assert calibrated["action_mask_calibration"]["by_action_type"]["defer_review"]["force_block"] is True
    assert calibrated["predictions"]["holdout-block"]["action_mask"]["allowed"] is False
    assert calibrated["predictions"]["holdout-block"]["action_mask"]["required_reviews"] == ["synthetic_defer_review"]
    assert diagnostics["confusion"]["false_allow"] == 0
    assert diagnostics["accuracy"] == 1.0


def test_synthetic_runner_context_action_mask_calibration_handles_mixed_action_type():
    runner = _load_runner_module()
    examples = []
    predictions = {}
    for split in ("candidate", "holdout"):
        for risk, allowed in ((0.18, True), (0.27, False)):
            example_id = f"{split}-{risk}"
            examples.append(
                {
                    "id": example_id,
                    "split": split,
                    "action": {"action_type": "defer_review"},
                    "targets": {
                        "constraint_violation_probability": risk,
                        "planning_utility_delta": 0.02,
                        "action_mask": {
                            "allowed": allowed,
                            "required_reviews": [] if allowed else ["stress_context_review"],
                            "hard_blocks": [],
                            "confidence": 0.8,
                        },
                    },
                }
            )
            predictions[example_id] = {
                "constraint_violation_probability": risk,
                "planning_utility_delta": 0.02,
                "action_mask": {"allowed": True, "required_reviews": [], "hard_blocks": [], "confidence": 0.7},
            }
    dataset = {"examples": examples}
    candidate = {
        "schema": "territory_world_model.neural_multi_head_dynamics_candidate_report.v1",
        "status": "pass",
        "candidate": {"model_name": "mlp", "model_family": "test"},
        "predictions": predictions,
        "evidence_gate": {"status": "pass"},
    }

    action_type_calibrated = runner.calibrated_action_mask_candidate_report(candidate, dataset)
    context_calibrated = runner.context_calibrated_action_mask_candidate_report(candidate, dataset)
    action_type_diagnostics = runner.action_mask_diagnostics_for_predictions(dataset, action_type_calibrated["predictions"])
    context_diagnostics = runner.action_mask_diagnostics_for_predictions(dataset, context_calibrated["predictions"])

    action_type_rule = action_type_calibrated["action_mask_calibration"]["by_action_type"]["defer_review"]
    assert action_type_rule["blocked_rate"] == 0.5
    assert action_type_rule["force_block"] is False
    assert action_type_diagnostics["confusion"]["false_allow"] == 2
    assert context_diagnostics["confusion"]["false_allow"] == 0
    assert context_diagnostics["accuracy"] == 1.0
    assert context_calibrated["action_mask_calibration"]["context_key"] == "action_type+risk_bucket+mask_policy"


def test_synthetic_runner_context_action_mask_calibration_fallback_blocks_unseen_high_risk_context():
    runner = _load_runner_module()
    dataset = {
        "examples": [
            {
                "id": "candidate-approve-high",
                "split": "candidate",
                "action": {"action_type": "approve_with_conditions"},
                "targets": {
                    "constraint_violation_probability": 0.34,
                    "planning_utility_delta": 0.01,
                    "action_mask": {
                        "allowed": False,
                        "required_reviews": ["stress_context_review"],
                        "hard_blocks": ["stress_high_constraint"],
                        "confidence": 0.88,
                    },
                },
            },
            {
                "id": "candidate-restore-low",
                "split": "candidate",
                "action": {"action_type": "restore"},
                "targets": {
                    "constraint_violation_probability": 0.16,
                    "planning_utility_delta": 0.04,
                    "action_mask": {
                        "allowed": True,
                        "required_reviews": [],
                        "hard_blocks": [],
                        "confidence": 0.86,
                    },
                },
            },
            {
                "id": "holdout-restore-high",
                "split": "holdout",
                "action": {"action_type": "restore"},
                "targets": {
                    "constraint_violation_probability": 0.35,
                    "planning_utility_delta": 0.02,
                    "action_mask": {
                        "allowed": False,
                        "required_reviews": ["stress_context_review"],
                        "hard_blocks": ["stress_high_constraint"],
                        "confidence": 0.9,
                    },
                },
            },
        ]
    }
    predictions = {
        item["id"]: {
            "constraint_violation_probability": item["targets"]["constraint_violation_probability"],
            "planning_utility_delta": item["targets"]["planning_utility_delta"],
            "action_mask": {"allowed": True, "required_reviews": [], "hard_blocks": [], "confidence": 0.7},
        }
        for item in dataset["examples"]
    }
    candidate = {
        "schema": "territory_world_model.neural_multi_head_dynamics_candidate_report.v1",
        "status": "pass",
        "candidate": {"model_name": "mlp", "model_family": "test"},
        "predictions": predictions,
        "evidence_gate": {"status": "pass"},
    }

    context_calibrated = runner.context_calibrated_action_mask_candidate_report(candidate, dataset)
    diagnostics = runner.action_mask_diagnostics_for_predictions(dataset, context_calibrated["predictions"])
    holdout_mask = context_calibrated["predictions"]["holdout-restore-high"]["action_mask"]

    assert holdout_mask["allowed"] is False
    assert holdout_mask["calibrated_block_reason"] == "missing_candidate_split_high_risk_context"
    assert "context_calibration_missing_high_risk_support" in holdout_mask["required_reviews"]
    assert context_calibrated["action_mask_calibration"]["fallback_rule_prediction_count"] == 1
    assert diagnostics["confusion"]["false_allow"] == 0


def test_synthetic_runner_context_action_mask_calibration_allows_mitigated_high_risk_policy_context():
    runner = _load_runner_module()
    dataset = {
        "examples": [
            {
                "id": "candidate-restore-low",
                "split": "candidate",
                "action": {"action_type": "restore"},
                "scenario_context": {"action_mask_policy": "low_risk_allowed"},
                "targets": {
                    "constraint_violation_probability": 0.16,
                    "planning_utility_delta": 0.04,
                    "action_mask": {
                        "allowed": True,
                        "required_reviews": [],
                        "hard_blocks": [],
                        "confidence": 0.86,
                    },
                },
            },
            {
                "id": "holdout-restore-high-allowed",
                "split": "holdout",
                "action": {"action_type": "restore"},
                "scenario_context": {"action_mask_policy": "mixed_risk_restore_allowed"},
                "targets": {
                    "constraint_violation_probability": 0.35,
                    "planning_utility_delta": 0.03,
                    "action_mask": {
                        "allowed": True,
                        "required_reviews": [],
                        "hard_blocks": [],
                        "confidence": 0.82,
                    },
                },
            },
            {
                "id": "holdout-protect-high-allowed-medium-prediction",
                "split": "holdout",
                "action": {"action_type": "protect"},
                "scenario_context": {"action_mask_policy": "mixed_risk_protect_allowed"},
                "targets": {
                    "constraint_violation_probability": 0.32,
                    "planning_utility_delta": 0.02,
                    "action_mask": {
                        "allowed": True,
                        "required_reviews": [],
                        "hard_blocks": [],
                        "confidence": 0.81,
                    },
                },
            },
        ]
    }
    candidate = {
        "schema": "territory_world_model.neural_multi_head_dynamics_candidate_report.v1",
        "status": "pass",
        "candidate": {"model_name": "mlp", "model_family": "test"},
        "predictions": {
            "candidate-restore-low": {
                "constraint_violation_probability": 0.16,
                "planning_utility_delta": 0.04,
                "action_mask": {"allowed": True, "required_reviews": [], "hard_blocks": [], "confidence": 0.78},
            },
            "holdout-restore-high-allowed": {
                "constraint_violation_probability": 0.18,
                "planning_utility_delta": 0.03,
                "action_mask": {"allowed": True, "required_reviews": [], "hard_blocks": [], "confidence": 0.72},
            },
            "holdout-protect-high-allowed-medium-prediction": {
                "constraint_violation_probability": 0.28,
                "planning_utility_delta": 0.02,
                "action_mask": {"allowed": True, "required_reviews": [], "hard_blocks": [], "confidence": 0.7},
            },
        },
        "evidence_gate": {"status": "pass"},
    }

    context_calibrated = runner.context_calibrated_action_mask_candidate_report(candidate, dataset)
    diagnostics = runner.action_mask_diagnostics_for_predictions(dataset, context_calibrated["predictions"])
    holdout_mask = context_calibrated["predictions"]["holdout-restore-high-allowed"]["action_mask"]
    medium_mask = context_calibrated["predictions"]["holdout-protect-high-allowed-medium-prediction"]["action_mask"]

    assert holdout_mask["allowed"] is True
    assert holdout_mask["calibration"]["source_split"] == "predicted_mitigated_high_risk_fallback"
    assert holdout_mask["calibrated_allow_reason"] == "missing_candidate_split_high_risk_context_but_prediction_mitigates_risk"
    assert "context_calibration_mitigated_high_risk_review" in holdout_mask["required_reviews"]
    assert medium_mask["allowed"] is True
    assert medium_mask["calibration"]["source_split"] == "predicted_mitigated_high_risk_fallback"
    assert context_calibrated["action_mask_calibration"]["fallback_rule_prediction_count"] == 2
    assert context_calibrated["action_mask_calibration"]["mitigated_high_risk_fallback_prediction_count"] == 2
    assert diagnostics["confusion"]["false_allow"] == 0
    assert diagnostics["confusion"]["false_block"] == 0


def test_render_data_foundation_health_markdown_includes_key_gates():
    module = _load_script_module()
    report = {
        "inputs": {
            "twm_dataset": "/tmp/twm",
            "paper7_causal_dataset": "/tmp/paper7.csv",
            "production_observed_history": None,
            "structural_validation_observed_history": "/tmp/structural.csv",
            "synthetic_experiment_foundation": "/tmp/synthetic_experiment.csv",
        },
        "outputs": {
            "report": "/tmp/report.json",
            "markdown_report": "/tmp/report.md",
            "production_observed_history_template": "/tmp/template.csv",
            "structural_validation_observed_history": "/tmp/structural.csv",
            "synthetic_experiment_foundation": "/tmp/synthetic_experiment.csv",
        },
        "summary": {
            "twm_dataset_rows": {"approval_records.csv": 90},
            "twm_production_ready_observed_history_rows": 0,
            "twm_structural_fixture_row_count": 48,
            "twm_structural_fixture_pair_count": 24,
            "twm_structural_fixture_default_status": "review",
            "twm_structural_fixture_default_missing": ["synthetic_records", "not_for_production_records"],
            "twm_structural_fixture_structural_status": "pass",
            "twm_structural_fixture_structural_missing": [],
            "twm_structural_fixture_structural_neighbor_edge_count": 24,
            "twm_structural_fixture_structural_spatial_estimator_status": "pass",
            "twm_structural_fixture_structural_balance_max_smd": 0.0,
            "twm_synthetic_experiment_row_count": 192,
            "twm_synthetic_experiment_pair_count": 96,
            "twm_synthetic_experiment_region_count": 4,
            "twm_synthetic_experiment_period_count": 6,
            "twm_synthetic_experiment_action_mask_allowed_count": 72,
            "twm_synthetic_experiment_action_mask_blocked_count": 24,
            "twm_synthetic_experiment_mixed_action_mask_action_types": ["approve_with_conditions", "protect", "restore"],
            "twm_synthetic_experiment_action_mask_counts_by_action_type": {
                "approve_with_conditions": {"allowed": 18, "blocked": 6, "total": 24},
                "protect": {"allowed": 18, "blocked": 6, "total": 24},
                "restore": {"allowed": 18, "blocked": 6, "total": 24},
                "defer_review": {"allowed": 18, "blocked": 6, "total": 24},
            },
            "twm_synthetic_experiment_split_counts": {"train": 128, "validation": 32, "test": 32},
            "twm_synthetic_experiment_default_status": "review",
            "twm_synthetic_experiment_default_missing": ["synthetic_records", "not_for_production_records"],
            "twm_synthetic_experiment_structural_status": "pass",
            "twm_synthetic_experiment_structural_missing": [],
            "twm_synthetic_experiment_structural_neighbor_edge_count": 96,
            "twm_synthetic_experiment_structural_spatial_estimator_status": "pass",
            "twm_synthetic_experiment_structural_balance_max_smd": 0.0,
            "twm_observed_history_status": "review",
            "twm_observed_history_missing": ["synthetic_records"],
            "twm_evidence_matched_pair_count": 33,
            "twm_evidence_matched_structural_status": "review",
            "twm_evidence_matched_structural_missing": ["covariate_balance"],
            "paper7_caliper_matched_status": "pass",
            "paper7_caliper_matched_pair_count": 2445,
            "paper7_caliper_matched_missing": [],
            "next_data_work": ["replace demo rows"],
        },
    }

    markdown = module.render_data_foundation_health_markdown(report)

    assert "# TWM Data Foundation Health" in markdown
    assert "Structural fixture structural check" in markdown
    assert "Synthetic experiment structural check" in markdown
    assert "`pass`" in markdown
    assert "synthetic_records" in markdown
    assert "/tmp/structural.csv" in markdown
    assert "/tmp/synthetic_experiment.csv" in markdown
    assert "synthetic action-mask blocked rows" in markdown
    assert "Mixed action-mask action types" in markdown


def test_payload_records_string_neighbors_drive_spatial_edges():
    module = _load_script_module()
    svc = module._build_validation_service()
    state_id = module._create_minimal_state(svc)
    records = []
    for idx in range(6):
        records.append(
            {
                "unit_id": f"C-{idx}",
                "treatment": 0,
                "outcome": 0.10,
                "stratum": "county",
                "cluster": f"block-{idx}",
                "neighbors": f"T-{idx}",
                "covariates": {"area_m2": 1000 + idx},
            }
        )
        records.append(
            {
                "unit_id": f"T-{idx}",
                "treatment": 1,
                "outcome": 0.20,
                "stratum": "county",
                "cluster": f"block-{idx}",
                "neighbors": f"C-{idx}",
                "covariates": {"area_m2": 1000 + idx},
            }
        )

    report = svc.causal_calibration_report(
        state_id,
        {
            "model_effect": 0.05,
            "records": records,
            "thresholds": {
                "min_records": 10,
                "min_treated": 5,
                "min_control": 5,
                "max_neighbor_exposure_gap": 1.0,
                "max_spatial_residual_moran": 1.0,
            },
        },
    )

    assert report["status"] == "pass"
    assert report["estimate"]["spatial"]["neighbor_edge_count"] == 6
    assert report["estimate"]["spatial_estimator"]["support"]["cross_treatment_neighbor_edge_count"] == 6
    assert report["estimate"]["spatial_estimator"]["status"] == "pass"


def test_validate_twm_spatial_relation_augmented_structural_check_uses_shared_parcels(tmp_path):
    module = _load_script_module()
    tables_dir = tmp_path / "tables"
    relations_dir = tmp_path / "relations"
    tables_dir.mkdir()
    relations_dir.mkdir()
    approval_rows = ["approval_id,project_id,approval_status,outcome,cluster,DKMJ,synthetic,not_for_production"]
    relation_rows = ["relation_id,relation_type,project_id,bsm_norm,right_role,overlap_area_m2,synthetic,not_for_production"]
    for idx in range(10):
        control_project = f"PRJ-C-{idx}"
        treated_project = f"PRJ-T-{idx}"
        parcel = f"PARCEL-{idx}"
        approval_rows.append(f"APR-C-{idx},{control_project},in_review,0.10,block-{idx},1000,True,True")
        approval_rows.append(f"APR-T-{idx},{treated_project},approved,0.20,block-{idx},1000,True,True")
        relation_rows.append(f"REL-C-{idx},PROJECT_OVERLAPS_PARCEL,{control_project},{parcel},parcel,10,True,True")
        relation_rows.append(f"REL-T-{idx},PROJECT_OVERLAPS_PARCEL,{treated_project},{parcel},parcel,10,True,True")
    (tables_dir / "approval_records.csv").write_text("\n".join(approval_rows) + "\n", encoding="utf-8")
    (relations_dir / "project_parcel_rel.csv").write_text("\n".join(relation_rows) + "\n", encoding="utf-8")

    svc = module._build_validation_service()
    state_id = module._create_minimal_state(svc)

    summary = module.validate_twm_spatial_relation_augmented_structural_check(svc, state_id, tmp_path)

    assert summary["status"] == "pass"
    assert summary["estimate"]["spatial"]["neighbor_edge_count"] == 10
    assert summary["estimate"]["spatial_estimator"]["support"]["cross_treatment_neighbor_edge_count"] == 10
    assert "synthetic_records" not in summary["evidence_gate"]["missing"]
    assert "not_for_production_records" not in summary["evidence_gate"]["missing"]


def test_build_project_review_context_aggregates_rule_and_review_tables(tmp_path):
    module = _load_script_module()
    tables_dir = tmp_path / "tables"
    tables_dir.mkdir()
    (tables_dir / "rule_evaluation.csv").write_text(
        "\n".join(
            [
                "rule_eval_id,project_id,severity,finding_status,metric_value,synthetic,not_for_production",
                "RULE-1,PRJ-1,critical,hit_requires_review,10,True,True",
                "RULE-2,PRJ-1,info,pass,0,True,True",
                "RULE-3,PRJ-2,high,hit_requires_review,5,True,True",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tables_dir / "review_tasks.csv").write_text(
        "\n".join(
            [
                "review_task_id,project_id,task_status,review_result,synthetic,not_for_production",
                "REV-1,PRJ-1,completed,requires_supplementary_evidence,True,True",
                "REV-2,PRJ-1,open,pending,True,True",
                "REV-3,PRJ-2,completed,suspected_violation_confirmed,True,True",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    context = module.build_project_review_context(tmp_path)
    audit = module.audit_project_review_context(context)

    assert context["PRJ-1"]["rule_eval_count"] == 2
    assert context["PRJ-1"]["rule_hit_count"] == 1
    assert context["PRJ-1"]["critical_rule_hit_count"] == 1
    assert context["PRJ-1"]["review_task_count"] == 2
    assert context["PRJ-1"]["open_review_count"] == 1
    assert context["PRJ-1"]["supplement_required_review_count"] == 1
    assert context["PRJ-2"]["confirmed_violation_count"] == 1
    assert context["PRJ-2"]["review_penalty"] == 1.0
    assert audit["project_count"] == 2
    assert audit["total_rule_eval_count"] == 3
    assert audit["total_review_task_count"] == 3


def test_observed_history_rows_with_project_evidence_adds_review_covariates_and_components(tmp_path):
    module = _load_script_module()
    tables_dir = tmp_path / "tables"
    relations_dir = tmp_path / "relations"
    tables_dir.mkdir()
    relations_dir.mkdir()
    (tables_dir / "approval_records.csv").write_text(
        "\n".join(
            [
                "approval_id,project_id,approval_status,outcome,DKXZQDM,DKMJ,synthetic,not_for_production",
                "APR-1,PRJ-1,approved,0.2,500227,1000,True,True",
                "APR-2,PRJ-2,in_review,0.1,500227,1000,True,True",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tables_dir / "rule_evaluation.csv").write_text(
        "\n".join(
            [
                "rule_eval_id,project_id,severity,finding_status,metric_value,synthetic,not_for_production",
                "RULE-1,PRJ-1,high,hit_requires_review,10,True,True",
                "RULE-2,PRJ-2,info,pass,0,True,True",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tables_dir / "review_tasks.csv").write_text(
        "\n".join(
            [
                "review_task_id,project_id,task_status,review_result,synthetic,not_for_production",
                "REV-1,PRJ-1,completed,requires_supplementary_evidence,True,True",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (relations_dir / "project_parcel_rel.csv").write_text(
        "\n".join(
            [
                "relation_id,relation_type,project_id,bsm_norm,right_role,overlap_area_m2,synthetic,not_for_production",
                "REL-1,PROJECT_OVERLAPS_PARCEL,PRJ-1,PARCEL-A,parcel,10,True,True",
                "REL-2,PROJECT_OVERLAPS_PARCEL,PRJ-2,PARCEL-A,parcel,9,True,True",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rows = module.observed_history_rows_with_project_evidence(tmp_path)
    by_project = {row["project_id"]: row for row in rows}

    assert by_project["PRJ-1"]["neighbors"] == "PRJ-2"
    assert by_project["PRJ-1"]["cluster"].startswith("shared_parcel_component_")
    assert by_project["PRJ-1"]["rule_eval_count"] == 1
    assert by_project["PRJ-1"]["rule_hit_count"] == 1
    assert by_project["PRJ-1"]["review_task_count"] == 1
    assert by_project["PRJ-1"]["review_penalty"] == 0.65
    assert by_project["PRJ-2"]["cluster"] == by_project["PRJ-1"]["cluster"]


def test_validate_twm_evidence_augmented_structural_check_uses_component_clusters(tmp_path):
    module = _load_script_module()
    tables_dir = tmp_path / "tables"
    relations_dir = tmp_path / "relations"
    tables_dir.mkdir()
    relations_dir.mkdir()
    approval_rows = ["approval_id,project_id,approval_status,outcome,DKMJ,synthetic,not_for_production"]
    rule_rows = ["rule_eval_id,project_id,severity,finding_status,metric_value,synthetic,not_for_production"]
    review_rows = ["review_task_id,project_id,task_status,review_result,synthetic,not_for_production"]
    relation_rows = ["relation_id,relation_type,project_id,bsm_norm,right_role,overlap_area_m2,synthetic,not_for_production"]
    for idx in range(6):
        control_project = f"PRJ-C-{idx}"
        treated_project = f"PRJ-T-{idx}"
        parcel = f"PARCEL-{idx}"
        approval_rows.append(f"APR-C-{idx},{control_project},in_review,0.10,1000,True,True")
        approval_rows.append(f"APR-T-{idx},{treated_project},approved,0.20,1000,True,True")
        rule_rows.append(f"RULE-C-{idx},{control_project},info,pass,0,True,True")
        rule_rows.append(f"RULE-T-{idx},{treated_project},high,hit_requires_review,10,True,True")
        review_rows.append(f"REV-T-{idx},{treated_project},completed,requires_supplementary_evidence,True,True")
        relation_rows.append(f"REL-C-{idx},PROJECT_OVERLAPS_PARCEL,{control_project},{parcel},parcel,10,True,True")
        relation_rows.append(f"REL-T-{idx},PROJECT_OVERLAPS_PARCEL,{treated_project},{parcel},parcel,10,True,True")
    (tables_dir / "approval_records.csv").write_text("\n".join(approval_rows) + "\n", encoding="utf-8")
    (tables_dir / "rule_evaluation.csv").write_text("\n".join(rule_rows) + "\n", encoding="utf-8")
    (tables_dir / "review_tasks.csv").write_text("\n".join(review_rows) + "\n", encoding="utf-8")
    (relations_dir / "project_parcel_rel.csv").write_text("\n".join(relation_rows) + "\n", encoding="utf-8")

    svc = module._build_validation_service()
    state_id = module._create_minimal_state(svc)

    summary = module.validate_twm_evidence_augmented_structural_check(svc, state_id, tmp_path)

    assert summary["status"] == "review"
    assert "covariate_balance" in summary["evidence_gate"]["missing"]
    assert summary["evidence_augmentation"]["rows_with_review_context"] == 12
    assert summary["evidence_augmentation"]["mixed_component_cluster_count"] == 6
    assert summary["estimate"]["spatial_estimator"]["status"] == "pass"
    assert summary["estimate"]["spatial_estimator"]["support"]["mixed_spatial_unit_count"] == 6
    assert summary["estimate"]["spatial"]["neighbor_edge_count"] == 6


def test_match_paper7_records_pairs_controls_to_nearest_treated(tmp_path):
    module = _load_script_module()
    path = tmp_path / "causal_dataset.csv"
    path.write_text(
        "\n".join(
            [
                "treatment,outcome,budget_remaining,global_slope,global_cont,step_frac,slope_improvement,block_farm_slope,block_forest_slope,block_slope_gap,block_swap_potential,block_invested",
                "0,0.10,1.0,0.20,0.30,0.0,0.00,0.20,0.30,-0.10,0.20,0.0",
                "1,0.20,0.99,0.21,0.31,0.01,0.01,0.21,0.31,-0.10,0.21,0.0",
                "1,0.50,0.20,0.90,0.80,0.80,0.40,0.90,0.80,0.10,0.90,1.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    records = module.paper7_rows_to_causal_records(path)

    matched, report = module.match_paper7_records(records)

    assert report["method"] == "greedy_standardized_nearest_neighbor"
    assert report["pair_count"] == 1
    assert report["matched_record_count"] == 2
    assert report["mean_standardized_distance"] is not None
    assert matched[0]["treatment"] == 0
    assert matched[1]["treatment"] == 1
    assert matched[0]["match_group"] == matched[1]["match_group"]
    assert matched[0]["matching_method"] == "greedy_standardized_nearest_neighbor"
    assert matched[1]["outcome"] == 0.20


def test_match_paper7_records_applies_standardized_distance_caliper(tmp_path):
    module = _load_script_module()
    path = tmp_path / "causal_dataset.csv"
    path.write_text(
        "\n".join(
            [
                "treatment,outcome,budget_remaining,global_slope,global_cont,step_frac,slope_improvement,block_farm_slope,block_forest_slope,block_slope_gap,block_swap_potential,block_invested",
                "0,0.10,1.0,0.20,0.30,0.0,0.00,0.20,0.30,-0.10,0.20,0.0",
                "1,0.20,0.99,0.21,0.31,0.01,0.01,0.21,0.31,-0.10,0.21,0.0",
                "0,-0.20,0.95,0.20,0.30,0.02,0.00,0.20,0.30,-0.10,0.20,0.0",
                "1,0.80,0.10,0.95,0.90,0.90,0.50,0.95,0.90,0.30,0.95,1.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    records = module.paper7_rows_to_causal_records(path)

    matched, report = module.match_paper7_records(records, max_standardized_distance=2.0)

    assert report["caliper_max_standardized_distance"] == 2.0
    assert report["pair_count"] == 1
    assert report["matched_record_count"] == 2
    assert len(matched) == 2
    assert {row["outcome"] for row in matched} == {0.10, 0.20}


def test_match_twm_evidence_augmented_records_prefers_component_pairs(tmp_path):
    module = _load_script_module()
    rows = [
        {
            "project_id": "PRJ-C-1",
            "approval_status": "in_review",
            "outcome": "0.10",
            "cluster": "shared_parcel_component_001",
            "neighbors": "PRJ-T-1",
            "DKMJ": "1000",
            "risk_score": "0.20",
            "review_penalty": "0.10",
            "rule_eval_count": "2",
            "rule_hit_count": "1",
            "review_task_count": "1",
            "synthetic": "True",
            "not_for_production": "True",
        },
        {
            "project_id": "PRJ-T-1",
            "approval_status": "approved",
            "outcome": "0.20",
            "cluster": "shared_parcel_component_001",
            "neighbors": "PRJ-C-1",
            "DKMJ": "1010",
            "risk_score": "0.21",
            "review_penalty": "0.10",
            "rule_eval_count": "2",
            "rule_hit_count": "1",
            "review_task_count": "1",
            "synthetic": "True",
            "not_for_production": "True",
        },
        {
            "project_id": "PRJ-T-2",
            "approval_status": "approved",
            "outcome": "0.80",
            "cluster": "shared_parcel_component_999",
            "DKMJ": "9000",
            "risk_score": "0.90",
            "review_penalty": "1.00",
            "rule_eval_count": "4",
            "rule_hit_count": "4",
            "review_task_count": "3",
            "synthetic": "True",
            "not_for_production": "True",
        },
    ]

    matched, report = module.match_twm_evidence_augmented_records(rows)

    assert report["method"] == "twm_evidence_greedy_standardized_nearest_neighbor"
    assert report["pair_count"] == 1
    assert report["same_component_cluster_pair_count"] == 1
    assert report["global_fallback_pair_count"] == 0
    assert report["matched_record_count"] == 2
    assert matched[0]["project_id"] == "PRJ-C-1"
    assert matched[1]["project_id"] == "PRJ-T-1"
    assert matched[0]["match_group"] == matched[1]["match_group"]
    assert matched[0]["cluster"] == "shared_parcel_component_001"
    assert matched[0]["neighbors"] == "PRJ-T-1"
    assert matched[0]["synthetic"] == "True"
    assert matched[0]["not_for_production"] == "True"


def test_validate_twm_evidence_augmented_matched_history_keeps_synthetic_gate(tmp_path):
    module = _load_script_module()
    tables_dir = tmp_path / "tables"
    relations_dir = tmp_path / "relations"
    tables_dir.mkdir()
    relations_dir.mkdir()
    approval_rows = ["approval_id,project_id,approval_status,outcome,DKMJ,synthetic,not_for_production"]
    rule_rows = ["rule_eval_id,project_id,severity,finding_status,metric_value,synthetic,not_for_production"]
    review_rows = ["review_task_id,project_id,task_status,review_result,synthetic,not_for_production"]
    relation_rows = ["relation_id,relation_type,project_id,bsm_norm,right_role,overlap_area_m2,synthetic,not_for_production"]
    for idx in range(4):
        control_project = f"PRJ-C-{idx}"
        treated_project = f"PRJ-T-{idx}"
        parcel = f"PARCEL-{idx}"
        approval_rows.append(f"APR-C-{idx},{control_project},in_review,0.10,1000,True,True")
        approval_rows.append(f"APR-T-{idx},{treated_project},approved,0.20,1005,True,True")
        rule_rows.append(f"RULE-C-{idx},{control_project},info,pass,0,True,True")
        rule_rows.append(f"RULE-T-{idx},{treated_project},info,pass,0,True,True")
        review_rows.append(f"REV-C-{idx},{control_project},completed,resolved,True,True")
        review_rows.append(f"REV-T-{idx},{treated_project},completed,resolved,True,True")
        relation_rows.append(f"REL-C-{idx},PROJECT_OVERLAPS_PARCEL,{control_project},{parcel},parcel,10,True,True")
        relation_rows.append(f"REL-T-{idx},PROJECT_OVERLAPS_PARCEL,{treated_project},{parcel},parcel,10,True,True")
    (tables_dir / "approval_records.csv").write_text("\n".join(approval_rows) + "\n", encoding="utf-8")
    (tables_dir / "rule_evaluation.csv").write_text("\n".join(rule_rows) + "\n", encoding="utf-8")
    (tables_dir / "review_tasks.csv").write_text("\n".join(review_rows) + "\n", encoding="utf-8")
    (relations_dir / "project_parcel_rel.csv").write_text("\n".join(relation_rows) + "\n", encoding="utf-8")

    svc = module._build_validation_service()
    state_id = module._create_minimal_state(svc)

    summary = module.validate_twm_evidence_augmented_matched_history(svc, state_id, tmp_path)

    assert summary["status"] == "review"
    assert summary["matching"]["pair_count"] == 4
    assert summary["matching"]["same_component_cluster_pair_count"] == 4
    assert "synthetic_records" in summary["evidence_gate"]["missing"]
    assert "not_for_production_records" in summary["evidence_gate"]["missing"]
    assert summary["record_inventory"]["synthetic_record_count"] == 8


def test_validate_twm_evidence_augmented_matched_structural_check_runs_spatial_estimator(tmp_path):
    module = _load_script_module()
    tables_dir = tmp_path / "tables"
    relations_dir = tmp_path / "relations"
    tables_dir.mkdir()
    relations_dir.mkdir()
    approval_rows = ["approval_id,project_id,approval_status,outcome,DKMJ,synthetic,not_for_production"]
    rule_rows = ["rule_eval_id,project_id,severity,finding_status,metric_value,synthetic,not_for_production"]
    review_rows = ["review_task_id,project_id,task_status,review_result,synthetic,not_for_production"]
    relation_rows = ["relation_id,relation_type,project_id,bsm_norm,right_role,overlap_area_m2,synthetic,not_for_production"]
    for idx in range(6):
        control_project = f"PRJ-C-{idx}"
        treated_project = f"PRJ-T-{idx}"
        parcel = f"PARCEL-{idx}"
        approval_rows.append(f"APR-C-{idx},{control_project},in_review,0.10,1000,True,True")
        approval_rows.append(f"APR-T-{idx},{treated_project},approved,0.20,1000,True,True")
        rule_rows.append(f"RULE-C-{idx},{control_project},info,pass,0,True,True")
        rule_rows.append(f"RULE-T-{idx},{treated_project},info,pass,0,True,True")
        review_rows.append(f"REV-C-{idx},{control_project},completed,resolved,True,True")
        review_rows.append(f"REV-T-{idx},{treated_project},completed,resolved,True,True")
        relation_rows.append(f"REL-C-{idx},PROJECT_OVERLAPS_PARCEL,{control_project},{parcel},parcel,10,True,True")
        relation_rows.append(f"REL-T-{idx},PROJECT_OVERLAPS_PARCEL,{treated_project},{parcel},parcel,10,True,True")
    (tables_dir / "approval_records.csv").write_text("\n".join(approval_rows) + "\n", encoding="utf-8")
    (tables_dir / "rule_evaluation.csv").write_text("\n".join(rule_rows) + "\n", encoding="utf-8")
    (tables_dir / "review_tasks.csv").write_text("\n".join(review_rows) + "\n", encoding="utf-8")
    (relations_dir / "project_parcel_rel.csv").write_text("\n".join(relation_rows) + "\n", encoding="utf-8")

    svc = module._build_validation_service()
    state_id = module._create_minimal_state(svc)

    summary = module.validate_twm_evidence_augmented_matched_structural_check(svc, state_id, tmp_path)

    assert summary["matching"]["pair_count"] == 6
    assert "synthetic_records" not in summary["evidence_gate"]["missing"]
    assert "not_for_production_records" not in summary["evidence_gate"]["missing"]
    assert summary["estimate"]["spatial"]["neighbor_edge_count"] == 6
    assert summary["estimate"]["spatial_estimator"]["status"] == "pass"
    assert summary["estimate"]["spatial_estimator"]["support"]["mixed_spatial_unit_count"] == 6
