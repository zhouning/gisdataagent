from pathlib import Path

import importlib.util
import json
import subprocess


SCRIPT = Path("scripts/validate_twm_data_foundation.py")
RUNNER_SCRIPT = Path("scripts/run_twm_synthetic_experiment.py")
VALIDATION_BUNDLE_SCRIPT = Path("scripts/run_twm_validation_bundle.py")


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


def _load_validation_bundle_module():
    spec = importlib.util.spec_from_file_location("run_twm_validation_bundle", VALIDATION_BUNDLE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_policy_benchmark_csv(path: Path) -> None:
    header = (
        "unit_id,approval_id,project_id,approval_status,outcome,cluster,neighbors,x,y,area_m2,quality_score,"
        "region_code,period,split,action_type,action_mask_policy,action_mask_allowed,synthetic,not_for_production"
    )
    rows = [header]
    policies = [
        ("mixed_risk_allowed_with_conditions", "approve_with_conditions", "True"),
        ("mixed_risk_protect_allowed", "protect", "True"),
        ("mixed_risk_restore_allowed", "restore", "True"),
        ("mixed_risk_blocked_condition_review", "approve_with_conditions", "False"),
        ("mixed_risk_protect_blocked", "protect", "False"),
    ]
    for idx, (policy, action, allowed) in enumerate(policies):
        rows.append(
            f"U-C-{idx},APR-C-{idx},PRJ-C-{idx},approved,0.20,block-{idx},,106.{idx},29.{idx},1000,0.8,"
            f"R-C-{idx},2026Q1,candidate,{action},{policy},{allowed},True,True"
        )
        rows.append(
            f"U-H-{idx},APR-H-{idx},PRJ-H-{idx},approved,0.24,block-{idx},,106.{idx},29.{idx},1000,0.8,"
            f"R-H-{idx},2026Q2,holdout,{action},{policy},{allowed},True,True"
        )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _write_production_policy_history_csv(path: Path, *, include_all_policies: bool = True) -> None:
    header = (
        "unit_id,approval_id,project_id,approval_status,outcome,cluster,neighbors,x,y,area_m2,quality_score,"
        "action_type,action_mask_policy,action_mask_allowed,region_code,period,split,policy_effective_date,policy_version,synthetic,not_for_production"
    )
    rows = [header]
    policies = [
        ("mixed_risk_allowed_with_conditions", "approve_with_conditions", "True", "approved"),
        ("mixed_risk_protect_allowed", "protect", "True", "approved"),
        ("mixed_risk_restore_allowed", "restore", "True", "approved"),
        ("mixed_risk_blocked_condition_review", "approve_with_conditions", "False", "in_review"),
        ("mixed_risk_protect_blocked", "protect", "False", "in_review"),
    ]
    if include_all_policies:
        selected = policies + policies
    else:
        selected = [
            policies[0],
            policies[1],
            policies[3],
        ]
    for idx, (policy, action, allowed, approval_status) in enumerate(selected):
        split = "train" if idx < max(1, len(selected) // 2) else "holdout"
        rows.append(
            f"P-{idx},APR-P-{idx},PRJ-P-{idx},{approval_status},0.{30 + idx},block-{idx},,106.{idx},29.{idx},1000,0.82,"
            f"{action},{policy},{allowed},PROD-R{idx},2026Q{1 + idx},{split},2026-01-01,POLICY-V{idx % 3},False,False"
        )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


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
                "unit_id,approval_id,project_id,approval_status,outcome,cluster,neighbors,x,y,area_m2,quality_score,action_type,action_mask_policy,action_mask_allowed,region_code,period,split,policy_effective_date,policy_version,synthetic,not_for_production",
                "C-1,APR-C-1,PRJ-C-1,in_review,0.10,block-1,T-1,106.20,29.60,1000,0.82,approve_with_conditions,mixed_risk_blocked_condition_review,False,SYN-R00,2026Q1,train,2026-01-01,POLICY-V1,False,False",
                "T-1,APR-T-1,PRJ-T-1,approved,0.20,block-1,C-1,106.21,29.61,1000,0.82,restore,mixed_risk_restore_allowed,True,SYN-R03,2026Q2,holdout,2026-04-01,POLICY-V2,False,False",
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
    assert audit["policy_history_quality"]["status"] == "pass"
    assert audit["policy_history_quality"]["production_policy_row_count"] == 2
    assert audit["policy_history_quality"]["allowed_count"] == 1
    assert audit["policy_history_quality"]["blocked_count"] == 1
    assert audit["policy_history_quality"]["region_policy_key_count"] == 2
    assert audit["policy_history_quality"]["region_action_policy_key_count"] == 2
    assert audit["policy_history_quality"]["mixed_allowed_policy_counts"] == {"mixed_risk_restore_allowed": 1}
    assert audit["temporal_validation_quality"]["status"] == "pass"
    assert audit["temporal_validation_quality"]["train_row_count"] == 1
    assert audit["temporal_validation_quality"]["holdout_row_count"] == 1


def test_audit_observed_history_schema_reviews_missing_temporal_holdout_and_policy_version(tmp_path):
    module = _load_script_module()
    path = tmp_path / "production_observed_history_no_temporal_gate.csv"
    path.write_text(
        "\n".join(
            [
                "unit_id,approval_id,project_id,approval_status,outcome,cluster,neighbors,x,y,area_m2,quality_score,action_type,action_mask_policy,action_mask_allowed,region_code,period,synthetic,not_for_production",
                "C-1,APR-C-1,PRJ-C-1,in_review,0.10,block-1,T-1,106.20,29.60,1000,0.82,approve_with_conditions,mixed_risk_blocked_condition_review,False,PROD-R01,2026Q1,False,False",
                "T-1,APR-T-1,PRJ-T-1,approved,0.20,block-1,C-1,106.21,29.61,1000,0.82,restore,mixed_risk_restore_allowed,True,PROD-R02,2026Q2,False,False",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    audit = module.audit_observed_history_schema(path)

    assert audit["status"] == "review"
    temporal_quality = audit["temporal_validation_quality"]
    assert temporal_quality["schema"] == "territory_world_model.production_temporal_validation_quality.v1"
    assert temporal_quality["status"] == "review"
    assert temporal_quality["period_count"] == 2
    assert temporal_quality["holdout_row_count"] == 0
    assert "explicit_train_holdout_split" in temporal_quality["missing_temporal_gates"]
    assert "policy_effective_version" in temporal_quality["missing_temporal_gates"]
    assert "temporal_holdout_support" in audit["missing_data_gates"]
    assert "policy_effective_version" in audit["missing_data_gates"]


def test_audit_observed_history_schema_keeps_policy_history_gate_separate(tmp_path):
    module = _load_script_module()
    path = tmp_path / "production_causal_only_history.csv"
    path.write_text(
        "\n".join(
            [
                "unit_id,approval_id,project_id,approval_status,outcome,cluster,neighbors,x,y,area_m2,quality_score,period,split,policy_version,synthetic,not_for_production",
                "C-1,APR-C-1,PRJ-C-1,in_review,0.10,block-1,T-1,106.20,29.60,1000,0.82,2026Q1,train,POLICY-V1,False,False",
                "T-1,APR-T-1,PRJ-T-1,approved,0.20,block-1,C-1,106.21,29.61,1000,0.82,2026Q2,holdout,POLICY-V1,False,False",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    audit = module.audit_observed_history_schema(path)

    assert audit["status"] == "pass"
    assert audit["missing_data_gates"] == []
    assert audit["policy_history_quality"]["status"] == "review"
    assert "production_policy_rows" in audit["policy_history_quality"]["missing_policy_gates"]
    assert "mixed_risk_allowed_policy_coverage" in audit["policy_history_quality"]["missing_policy_gates"]


def test_production_policy_history_alignment_passes_when_real_coverage_meets_synthetic_benchmark(tmp_path):
    module = _load_script_module()
    production_path = tmp_path / "production_policy_history.csv"
    production_path.write_text(
        "\n".join(
            [
                "unit_id,approval_id,project_id,approval_status,outcome,cluster,neighbors,x,y,area_m2,quality_score,action_type,action_mask_policy,action_mask_allowed,region_code,period,synthetic,not_for_production",
                "P-1,APR-P-1,PRJ-P-1,approved,0.31,block-1,,106.20,29.60,1000,0.82,approve_with_conditions,mixed_risk_allowed_with_conditions,True,PROD-R01,2026Q1,False,False",
                "P-2,APR-P-2,PRJ-P-2,approved,0.28,block-2,,106.21,29.61,1100,0.80,protect,mixed_risk_protect_allowed,True,PROD-R02,2026Q1,False,False",
                "P-3,APR-P-3,PRJ-P-3,approved,0.34,block-3,,106.22,29.62,1200,0.78,restore,mixed_risk_restore_allowed,True,PROD-R03,2026Q2,False,False",
                "P-4,APR-P-4,PRJ-P-4,in_review,0.08,block-4,,106.23,29.63,1300,0.76,approve_with_conditions,mixed_risk_blocked_condition_review,False,PROD-R04,2026Q2,False,False",
                "P-5,APR-P-5,PRJ-P-5,in_review,0.07,block-5,,106.24,29.64,1400,0.74,protect,mixed_risk_protect_blocked,False,PROD-R05,2026Q3,False,False",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    production_quality = module.audit_observed_history_schema(production_path)["policy_history_quality"]
    synthetic_summary = {
        "policy_coverage_benchmark": {
            "status": "generated",
            "required_allowed_count": 3,
            "required_blocked_count": 2,
            "required_region_policy_key_count": 5,
            "required_region_action_policy_key_count": 5,
            "required_mixed_allowed_policies": [
                "mixed_risk_allowed_with_conditions",
                "mixed_risk_protect_allowed",
                "mixed_risk_restore_allowed",
            ],
        }
    }

    alignment = module.production_policy_history_alignment(production_quality, synthetic_summary)

    assert alignment["schema"] == "territory_world_model.production_policy_history_alignment.v1"
    assert alignment["status"] == "pass"
    assert alignment["missing"] == []
    assert alignment["observed"]["region_policy_key_count"] == 5
    assert alignment["required"]["region_action_policy_key_count"] == 5
    assert alignment["mixed_allowed_policy_coverage"]["missing"] == []


def test_production_policy_history_alignment_reviews_undercovered_real_policy_history(tmp_path):
    module = _load_script_module()
    production_path = tmp_path / "production_policy_history_undercovered.csv"
    production_path.write_text(
        "\n".join(
            [
                "unit_id,approval_id,project_id,approval_status,outcome,cluster,neighbors,x,y,area_m2,quality_score,action_type,action_mask_policy,action_mask_allowed,region_code,period,synthetic,not_for_production",
                "P-1,APR-P-1,PRJ-P-1,approved,0.31,block-1,,106.20,29.60,1000,0.82,approve_with_conditions,mixed_risk_allowed_with_conditions,True,PROD-R01,2026Q1,False,False",
                "P-2,APR-P-2,PRJ-P-2,approved,0.28,block-2,,106.21,29.61,1100,0.80,protect,mixed_risk_protect_allowed,True,PROD-R01,2026Q1,False,False",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    production_quality = module.audit_observed_history_schema(production_path)["policy_history_quality"]
    synthetic_summary = {
        "policy_coverage_benchmark": {
            "status": "generated",
            "required_allowed_count": 3,
            "required_blocked_count": 2,
            "required_region_policy_key_count": 5,
            "required_region_action_policy_key_count": 5,
            "required_mixed_allowed_policies": [
                "mixed_risk_allowed_with_conditions",
                "mixed_risk_protect_allowed",
                "mixed_risk_restore_allowed",
            ],
        }
    }

    alignment = module.production_policy_history_alignment(production_quality, synthetic_summary)

    assert alignment["status"] == "review"
    assert "production_policy_history_quality" in alignment["missing"]
    assert "blocked_policy_count_below_synthetic_unseen_benchmark" in alignment["missing"]
    assert "region_policy_key_count_below_synthetic_unseen_benchmark" in alignment["missing"]
    assert "mixed_allowed_policy_coverage_below_synthetic_unseen_benchmark" in alignment["missing"]
    assert alignment["mixed_allowed_policy_coverage"]["missing"] == ["mixed_risk_restore_allowed"]


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
    assert "action_type" in header
    assert "action_mask_policy" in header
    assert "action_mask_allowed" in header
    assert "region_code" in header
    assert "period" in header
    assert "split" in header
    assert "policy_effective_date" in header
    assert "policy_version" in header
    assert "synthetic" in header
    assert "not_for_production" in header


def test_normalize_production_observed_history_export_maps_aliases_and_audits(tmp_path):
    module = _load_script_module()
    raw_path = tmp_path / "raw_approval_export.csv"
    output_path = tmp_path / "normalized_production_observed_history.csv"
    raw_path.write_text(
        "\n".join(
            [
                "AJBH,XMDM,review_result,observed_utility_delta,DKXZQDM,DKMJ,quality_score,decision_action,policy_code,feasibility_label,year,dataset_split,rule_version,synthetic,not_for_prod,operator_note",
                "APR-1,PRJ-1,approved,0.31,500227,1000,0.82,approve_with_conditions,mixed_risk_allowed_with_conditions,allowed,2026Q1,training,RULE-2026-A,False,False,manual check",
                "APR-2,PRJ-2,in_review,0.08,500227,1200,0.80,protect,mixed_risk_protect_blocked,blocked,2026Q2,test,RULE-2026-B,False,False,manual check",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = module.normalize_production_observed_history_export(raw_path, output_path)
    audit = module.audit_observed_history_schema(output_path)

    assert report["schema"] == "territory_world_model.production_observed_history_normalization.v1"
    assert report["status"] == "pass"
    assert report["row_count"] == 2
    assert report["audit"]["status"] == "pass"
    assert audit["status"] == "pass"
    rows = module.read_csv(output_path)
    assert rows[0]["approval_id"] == "APR-1"
    assert rows[0]["project_id"] == "PRJ-1"
    assert rows[0]["approval_status"] == "approved"
    assert rows[0]["outcome"] == "0.31"
    assert rows[0]["area_m2"] == "1000"
    assert rows[0]["action_mask_allowed"] == "true"
    assert rows[0]["split"] == "train"
    assert rows[1]["split"] == "holdout"
    assert rows[1]["policy_version"] == "RULE-2026-B"
    assert report["field_mapping"]["approval_id"]["primary_source_field"] == "AJBH"
    assert report["field_mapping"]["approval_id"]["non_empty_count"] == 2
    assert report["field_mapping"]["action_mask_allowed"]["primary_source_field"] == "feasibility_label"
    assert report["field_mapping"]["policy_version"]["primary_source_field"] == "rule_version"
    assert report["field_mapping"]["split"]["primary_source_field"] == "dataset_split"
    assert "operator_note" in report["unmapped_source_fields"]


def test_normalize_production_observed_history_export_keeps_incomplete_exports_review_only(tmp_path):
    module = _load_script_module()
    raw_path = tmp_path / "raw_incomplete_export.csv"
    output_path = tmp_path / "normalized_incomplete.csv"
    raw_path.write_text(
        "\n".join(
            [
                "AJBH,XMDM,review_result,DKMJ,synthetic,not_for_prod",
                "APR-1,PRJ-1,approved,1000,False,False",
                "APR-2,PRJ-2,in_review,1200,False,False",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = module.normalize_production_observed_history_export(raw_path, output_path)

    assert report["status"] == "review"
    assert "spatial_support" in report["audit"]["missing_data_gates"]
    assert "temporal_holdout_support" in report["audit"]["missing_data_gates"]


def test_audit_observed_history_schema_reports_gate_diagnostics_for_incomplete_export(tmp_path):
    module = _load_script_module()
    path = tmp_path / "production_missing_spatial_temporal.csv"
    path.write_text(
        "\n".join(
            [
                "unit_id,approval_status,outcome,area_m2,synthetic,not_for_production",
                "P-1,approved,0.31,1000,False,False",
                "P-2,in_review,0.08,1200,False,False",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    audit = module.audit_observed_history_schema(path)
    diagnostics = {(item["gate"], item["phase"]): item for item in audit["gate_diagnostics"]}
    spatial_schema = diagnostics[("spatial_support", "observed_history_schema")]
    temporal_holdout_data = diagnostics[("temporal_holdout_support", "observed_history_data")]
    production_flags_data = diagnostics[("explicit_production_flags", "observed_history_data")]
    production_usable_data = diagnostics[("production_usable_rows", "observed_history_data")]

    assert audit["status"] == "review"
    assert "production_usable_rows" in audit["missing_data_gates"]
    assert audit["row_quality"]["production_usable_row_count"] == 2
    assert audit["row_quality"]["production_candidate_row_count"] == 0
    assert audit["row_quality"]["production_treated_count"] == 0
    assert audit["row_quality"]["production_control_count"] == 0
    assert spatial_schema["status"] == "missing"
    assert "cluster" in spatial_schema["accepted_fields"]
    assert "Provide at least one spatial support field" in spatial_schema["remediation"]
    assert temporal_holdout_data["status"] == "missing"
    assert temporal_holdout_data["observed"]["period_count"] == 0
    assert "Provide explicit train and holdout/test splits" in temporal_holdout_data["remediation"]
    assert production_flags_data["status"] == "pass"
    assert production_flags_data["observed"] == 2
    assert production_usable_data["status"] == "missing"
    assert production_usable_data["observed"] == 2
    assert production_usable_data["remediation"].startswith("Set synthetic=false")


def test_audit_observed_history_schema_reports_synthetic_rows_as_non_production(tmp_path):
    module = _load_script_module()
    path = tmp_path / "synthetic_rows.csv"
    path.write_text(
        "\n".join(
            [
                "unit_id,approval_status,outcome,cluster,area_m2,period,split,policy_version,synthetic,not_for_production",
                "P-1,approved,0.31,R01,1000,2026Q1,train,V1,True,True",
                "P-2,in_review,0.08,R02,1200,2026Q2,holdout,V1,True,True",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    audit = module.audit_observed_history_schema(path)
    diagnostics = {(item["gate"], item["phase"]): item for item in audit["gate_diagnostics"]}
    production_usable_data = diagnostics[("production_usable_rows", "observed_history_data")]

    assert audit["status"] == "review"
    assert production_usable_data["status"] == "missing"
    assert production_usable_data["observed"] == 0
    assert production_usable_data["remediation"].startswith("Set synthetic=false")


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
    assert b"\r\n" not in path.read_bytes()
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
    required_mixed_allowed_policies = {
        "mixed_risk_allowed_with_conditions",
        "mixed_risk_protect_allowed",
        "mixed_risk_restore_allowed",
    }
    assert required_mixed_allowed_policies.issubset(summary["candidate_mixed_allowed_policy_counts"])
    assert all(summary["candidate_mixed_allowed_policy_counts"][policy] > 0 for policy in required_mixed_allowed_policies)
    assert "train" in summary["action_mask_policy_counts_by_split"]
    benchmark = summary["policy_coverage_benchmark"]
    assert benchmark["schema"] == "territory_world_model.synthetic_policy_coverage_benchmark.v1"
    assert set(benchmark["modes"]) == {"region_policy", "region_action_policy"}
    assert benchmark["required_allowed_count"] >= 0
    assert benchmark["required_blocked_count"] >= 0
    assert benchmark["required_region_policy_key_count"] == benchmark["modes"]["region_policy"]["unseen_key_count"]
    assert benchmark["required_region_action_policy_key_count"] == benchmark["modes"]["region_action_policy"]["unseen_key_count"]
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


def test_synthetic_experiment_policy_coverage_benchmark_tracks_default_unseen_fixture(tmp_path):
    module = _load_script_module()
    dataset_root = tmp_path / "dataset"
    (dataset_root / "tables").mkdir(parents=True)
    (dataset_root / "relations").mkdir()
    path = tmp_path / "synthetic_experiment.csv"

    summary = module.write_twm_synthetic_experiment_foundation(
        path,
        dataset_root,
        region_count=4,
        period_count=8,
        component_count=4,
    )

    required_mixed_allowed_policies = [
        "mixed_risk_allowed_with_conditions",
        "mixed_risk_protect_allowed",
        "mixed_risk_restore_allowed",
    ]
    benchmark = summary["policy_coverage_benchmark"]
    assert benchmark["status"] == "generated"
    assert benchmark["required_allowed_count"] == 6
    assert benchmark["required_blocked_count"] == 4
    assert benchmark["required_region_policy_key_count"] == 5
    assert benchmark["required_region_action_policy_key_count"] == 5
    assert benchmark["required_mixed_allowed_policies"] == required_mixed_allowed_policies
    assert benchmark["modes"]["region_policy"]["example_count"] == 10
    assert benchmark["modes"]["region_policy"]["allowed_count"] == 6
    assert benchmark["modes"]["region_policy"]["blocked_count"] == 4
    assert benchmark["modes"]["region_action_policy"]["example_count"] == 10
    assert benchmark["modes"]["region_action_policy"]["allowed_count"] == 6
    assert benchmark["modes"]["region_action_policy"]["blocked_count"] == 4


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
    assert {
        "mixed_risk_allowed_with_conditions",
        "mixed_risk_protect_allowed",
        "mixed_risk_restore_allowed",
    }.issubset(dataset["summary"]["candidate_mixed_allowed_policy_counts"])
    assert "holdout" in dataset["summary"]["action_mask_policy_counts_by_split"]
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
    high_risk = report["backend_comparison"]["conditional_high_risk_feasibility"]
    assert high_risk["schema"] == "territory_world_model.conditional_high_risk_feasibility.v1"
    assert high_risk["subset"]["example_count"] > 0
    assert high_risk["subset"]["conditional_allowed_count"] > 0
    assert high_risk["subset"]["conditional_blocked_count"] > 0
    assert high_risk["context_zero_false_allow_count"] >= 1
    near_boundary = report["backend_comparison"]["near_boundary_mixed_risk_feasibility"]
    assert near_boundary["schema"] == "territory_world_model.near_boundary_mixed_risk_backend_feasibility.v1"
    assert near_boundary["subset"]["schema"] == "territory_world_model.near_boundary_mixed_risk_subset.v1"
    assert near_boundary["subset"]["example_count"] > 0
    assert near_boundary["subset"]["allowed_count"] > 0
    assert near_boundary["subset"]["blocked_count"] > 0
    holdout_mixed = report["backend_comparison"]["holdout_mixed_risk_feasibility"]
    assert holdout_mixed["schema"] == "territory_world_model.holdout_mixed_risk_backend_feasibility.v1"
    assert holdout_mixed["subset"]["schema"] == "territory_world_model.holdout_mixed_risk_subset.v1"
    assert holdout_mixed["subset"]["example_count"] > 0
    assert holdout_mixed["subset"]["blocked_count"] > 0
    assert holdout_mixed["subset"]["region_count"] > 0
    assert holdout_mixed["subset"]["period_count"] > 0
    unseen_mixed = report["backend_comparison"]["unseen_mixed_risk_feasibility"]
    assert unseen_mixed["schema"] == "territory_world_model.unseen_mixed_risk_backend_feasibility.v1"
    assert unseen_mixed["subset"]["schema"] == "territory_world_model.unseen_mixed_risk_subset.v1"
    assert unseen_mixed["subset"]["primary_mode"] == "time_policy"
    assert "region_policy" in unseen_mixed["subset"]["modes"]
    assert "time_policy" in unseen_mixed["subset"]["modes"]
    default_ranking = {
        item["candidate_id"]: item
        for item in report["backend_comparison"]["ranking"]
    }
    assert default_ranking["torch_multi_head_mlp_action_mask_calibrated"]["action_mask_diagnostics"]["confusion"]["false_allow"] > 0
    assert default_ranking["torch_multi_head_mlp_context_action_mask_calibrated"]["action_mask_diagnostics"]["confusion"]["false_allow"] == 0
    assert default_ranking["torch_multi_head_mlp_action_mask_calibrated"]["conditional_high_risk_feasibility"]["confusion"]["false_allow"] > 0
    assert default_ranking["torch_multi_head_mlp_context_action_mask_calibrated"]["conditional_high_risk_feasibility"]["confusion"]["false_allow"] == 0
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
    assert ranking["torch_spatiotemporal_transformer"]["training_diagnostics"]["constraint_risk_contextual_weight"] == 1.0
    assert ranking["torch_spatiotemporal_transformer"]["training_diagnostics"]["seed"] == 19
    assert ranking["torch_spatiotemporal_transformer"]["training_diagnostics"]["configured_epoch_count"] >= 20
    assert ranking["torch_spatiotemporal_transformer"]["training_diagnostics"]["risk_head_mode"] == "context_residual"
    assert ranking["torch_spatiotemporal_transformer"]["training_diagnostics"]["feasibility_head_mode"] == "context_residual"
    assert ranking["torch_spatiotemporal_transformer"]["architecture_summary"]["constraint_risk_head"] == "context_residual"
    assert set(ranking["torch_spatiotemporal_transformer"]["architecture_summary"]["constraint_risk_context_tokens"]) == {
        "action",
        "context",
        "temporal",
    }
    assert ranking["torch_spatiotemporal_transformer"]["architecture_summary"]["action_mask_feasibility_head"] == "context_residual"
    assert set(ranking["torch_spatiotemporal_transformer"]["architecture_summary"]["action_mask_feasibility_context_tokens"]) == {
        "action",
        "context",
        "temporal",
    }
    assert ranking["torch_hierarchical_graph_context_action_mask_calibrated"]["training_diagnostics"]["constraint_risk_calibration_weight"] == 0
    transformer_calibrated = ranking["torch_spatiotemporal_transformer_constraint_risk_context_action_mask_calibrated"]
    assert transformer_calibrated["architecture_summary"]["constraint_risk_head"] == "context_residual"
    risk_calibration = transformer_calibrated["constraint_risk_calibration"]
    assert risk_calibration["status"] in {"pass", "review"}
    assert risk_calibration["application_policy"] == "apply only when candidate and holdout MAE both improve"
    if risk_calibration["status"] == "pass":
        assert risk_calibration["accepted"] is True
        assert risk_calibration["candidate_split_improved"] is True
        assert risk_calibration["holdout_improved"] is True
        assert risk_calibration["applied_prediction_count"] > 0
        assert transformer_calibrated["metrics"]["mean_constraint_error"] < transformer_raw_error
    else:
        assert risk_calibration["accepted"] is False
        assert risk_calibration["applied_prediction_count"] == 0
        assert transformer_calibrated["metrics"]["mean_constraint_error"] == transformer_raw_error
        assert set(risk_calibration["review_reasons"]) & {
            "low_prediction_variance",
            "degenerate_calibration_slope",
            "candidate_split_calibration_does_not_reduce_error",
            "holdout_calibration_does_not_reduce_error",
        }
    assert transformer_calibrated["action_mask_diagnostics"]["confusion"]["false_allow"] == 0
    head_probe = report["transformer_risk_head_probe"]
    assert head_probe["schema"] == "territory_world_model.transformer_risk_head_probe.v1"
    assert head_probe["weights"] == [0.0, 0.7, 1.2]
    assert head_probe["selected"]["risk_head_mode"] in {"shared", "context_residual", "context_direct"}
    assert head_probe["raw_selected"]["risk_head_mode"] in {"shared", "context_residual", "context_direct"}
    assert head_probe["raw_selected"]["source"] == "transformer_risk_weight_probe_row"
    assert head_probe["raw_candidate_count"] == sum(len(row["weight_rows"]) for row in head_probe["rows"])
    assert head_probe["raw_candidate_count"] == len(head_probe["raw_candidate_rows"])
    assert head_probe["raw_candidate_count"] == len(head_probe["rows"]) * len(head_probe["weights"])
    assert "affine calibration" in head_probe["raw_selection_policy"]
    raw_progress = head_probe["raw_progress_gate"]
    assert raw_progress["schema"] == "territory_world_model.transformer_raw_risk_head_progress_gate.v1"
    assert raw_progress["status"] in {"pass", "review"}
    assert raw_progress["selected_risk_head_mode"] == head_probe["selected"]["risk_head_mode"]
    assert raw_progress["raw_selected_risk_head_mode"] == head_probe["raw_selected"]["risk_head_mode"]
    assert "raw learned risk head" in raw_progress["promotion_policy"]
    assert "constraint_error_gap" in raw_progress["comparison"]
    assert "holdout_mae_gap" in raw_progress["comparison"]
    raw_grid = head_probe["raw_grid_audit"]
    assert raw_grid["schema"] == "territory_world_model.transformer_raw_risk_head_grid_audit.v1"
    assert raw_grid["candidate_count"] == head_probe["raw_candidate_count"]
    assert len(raw_grid["rows"]) == head_probe["raw_candidate_count"]
    assert raw_grid["status"] in {"pass", "review"}
    assert raw_grid["reference"]["selected_risk_head_mode"] == head_probe["selected"]["risk_head_mode"]
    assert raw_grid["reference"]["selected_weight"] == head_probe["selected"]["selected_weight"]
    assert raw_grid["promotable_candidate_count"] == sum(1 for row in raw_grid["rows"] if row["promotable"])
    assert isinstance(raw_grid["blocker_counts"], dict)
    assert "raw candidate" in raw_grid["promotion_policy"]
    promotion_candidate = head_probe["raw_promotion_candidate"]
    assert promotion_candidate["schema"] == "territory_world_model.transformer_raw_risk_head_promotion_candidate.v1"
    assert promotion_candidate["status"] in {"pass", "review"}
    assert promotion_candidate["candidate_config"]["risk_head_mode"] == head_probe["raw_selected"]["risk_head_mode"]
    assert promotion_candidate["promotion_scope"] == "synthetic_probe_candidate_only"
    if raw_progress["status"] == "pass":
        assert promotion_candidate["status"] == "pass"
    else:
        assert promotion_candidate["status"] == "review"
    assert runner.transformer_risk_head_probe_selection_key(head_probe["selected"]) == min(
        runner.transformer_risk_head_probe_selection_key(row)
        for row in head_probe["rows"]
    )
    assert runner.transformer_raw_risk_head_probe_selection_key(head_probe["raw_selected"]) == min(
        runner.transformer_raw_risk_head_probe_selection_key(row)
        for row in head_probe["raw_candidate_rows"]
    )
    probe_rows = {row["risk_head_mode"]: row for row in head_probe["rows"]}
    assert set(probe_rows) == {"shared", "context_residual", "context_direct"}
    assert probe_rows["shared"]["weight_rows"][0]["risk_head_context_tokens"] == []
    assert set(probe_rows["context_residual"]["weight_rows"][0]["risk_head_context_tokens"]) == {
        "action",
        "context",
        "temporal",
    }
    assert set(probe_rows["context_direct"]["weight_rows"][0]["risk_head_context_tokens"]) == {
        "action",
        "context",
        "temporal",
    }
    high_risk = report["backend_comparison"]["conditional_high_risk_feasibility"]
    assert high_risk["schema"] == "territory_world_model.conditional_high_risk_feasibility.v1"
    assert high_risk["raw_context_residual_candidate_count"] >= 1
    high_risk_rows = {
        item["candidate_id"]: item
        for item in high_risk["rows"]
    }
    assert high_risk_rows["torch_spatiotemporal_transformer"]["raw_context_residual_feasibility"] is True
    assert high_risk_rows["torch_spatiotemporal_transformer"]["feasibility_head_mode"] == "context_residual"
    assert high_risk_rows["torch_spatiotemporal_transformer"]["false_allow"] >= 0
    assert set(high_risk_rows["torch_spatiotemporal_transformer"]["feasibility_context_tokens"]) == {
        "action",
        "context",
        "temporal",
    }
    assert high_risk_rows["torch_spatiotemporal_transformer_context_action_mask_calibrated"]["false_allow"] == 0
    near_boundary = report["backend_comparison"]["near_boundary_mixed_risk_feasibility"]
    assert near_boundary["schema"] == "territory_world_model.near_boundary_mixed_risk_backend_feasibility.v1"
    assert near_boundary["raw_context_residual_candidate_count"] >= 1
    near_boundary_rows = {
        item["candidate_id"]: item
        for item in near_boundary["rows"]
    }
    assert near_boundary_rows["torch_spatiotemporal_transformer"]["raw_context_residual_feasibility"] is True
    assert near_boundary_rows["torch_spatiotemporal_transformer"]["feasibility_head_mode"] == "context_residual"
    assert near_boundary_rows["torch_spatiotemporal_transformer"]["example_count"] > 0
    assert near_boundary_rows["torch_spatiotemporal_transformer_context_action_mask_calibrated"]["false_allow"] == 0
    holdout_mixed = report["backend_comparison"]["holdout_mixed_risk_feasibility"]
    assert holdout_mixed["schema"] == "territory_world_model.holdout_mixed_risk_backend_feasibility.v1"
    assert holdout_mixed["raw_context_residual_candidate_count"] >= 1
    holdout_mixed_rows = {
        item["candidate_id"]: item
        for item in holdout_mixed["rows"]
    }
    assert holdout_mixed_rows["torch_spatiotemporal_transformer"]["raw_context_residual_feasibility"] is True
    assert holdout_mixed_rows["torch_spatiotemporal_transformer"]["region_count"] > 0
    assert holdout_mixed_rows["torch_spatiotemporal_transformer"]["period_count"] > 0
    assert holdout_mixed_rows["torch_spatiotemporal_transformer_context_action_mask_calibrated"]["false_allow"] == 0
    unseen_mixed = report["backend_comparison"]["unseen_mixed_risk_feasibility"]
    assert unseen_mixed["schema"] == "territory_world_model.unseen_mixed_risk_backend_feasibility.v1"
    assert unseen_mixed["raw_context_residual_candidate_count"] >= 1
    unseen_mixed_rows = {
        item["candidate_id"]: item
        for item in unseen_mixed["rows"]
    }
    assert unseen_mixed_rows["torch_spatiotemporal_transformer"]["raw_context_residual_feasibility"] is True
    assert unseen_mixed_rows["torch_spatiotemporal_transformer"]["primary_mode"] == "time_policy"
    assert unseen_mixed_rows["torch_spatiotemporal_transformer_context_action_mask_calibrated"]["false_allow"] == 0
    assert report["backend_comparison"]["candidate_count"] == 13


def test_synthetic_experiment_runner_uses_prepared_foundation_for_raw_transformer_feasibility():
    runner = _load_runner_module()
    path = Path("docs/reports/twm_synthetic_experiment_foundation.csv")
    assert path.exists()

    report = runner.run_synthetic_experiment(path, include_transformer=True)

    assert report["dataset_summary"]["example_count"] == 128
    assert report["dataset_summary"]["holdout_ground_truth_example_count"] == 64
    required_mixed_allowed_policies = {
        "mixed_risk_allowed_with_conditions",
        "mixed_risk_protect_allowed",
        "mixed_risk_restore_allowed",
    }
    assert required_mixed_allowed_policies.issubset(report["dataset_summary"]["candidate_mixed_allowed_policy_counts"])
    assert required_mixed_allowed_policies.issubset(report["dataset_summary"]["holdout_mixed_allowed_policy_counts"])
    high_risk = report["backend_comparison"]["conditional_high_risk_feasibility"]
    assert high_risk["subset"]["example_count"] >= 56
    assert high_risk["subset"]["conditional_allowed_count"] >= 24
    assert high_risk["subset"]["conditional_blocked_count"] >= 32
    rows = {
        item["candidate_id"]: item
        for item in high_risk["rows"]
    }
    raw_transformer = rows["torch_spatiotemporal_transformer"]
    assert raw_transformer["raw_context_residual_feasibility"] is True
    assert raw_transformer["false_allow"] == 0
    assert raw_transformer["false_block"] <= 7
    near_boundary = report["backend_comparison"]["near_boundary_mixed_risk_feasibility"]
    assert near_boundary["schema"] == "territory_world_model.near_boundary_mixed_risk_backend_feasibility.v1"
    assert near_boundary["subset"]["example_count"] >= 40
    assert near_boundary["subset"]["allowed_count"] > 0
    assert near_boundary["subset"]["blocked_count"] > 0
    assert near_boundary["raw_context_residual_zero_error_count"] >= 1
    near_boundary_rows = {
        item["candidate_id"]: item
        for item in near_boundary["rows"]
    }
    raw_transformer_near_boundary = near_boundary_rows["torch_spatiotemporal_transformer"]
    assert raw_transformer_near_boundary["raw_context_residual_feasibility"] is True
    assert raw_transformer_near_boundary["example_count"] >= 40
    assert raw_transformer_near_boundary["allowed_count"] > 0
    assert raw_transformer_near_boundary["blocked_count"] > 0
    assert raw_transformer_near_boundary["false_allow"] == 0
    assert raw_transformer_near_boundary["false_block"] == 0
    holdout_mixed = report["backend_comparison"]["holdout_mixed_risk_feasibility"]
    assert holdout_mixed["schema"] == "territory_world_model.holdout_mixed_risk_backend_feasibility.v1"
    assert holdout_mixed["subset"]["example_count"] >= 29
    assert holdout_mixed["subset"]["allowed_count"] >= 10
    assert holdout_mixed["subset"]["blocked_count"] >= 19
    assert holdout_mixed["subset"]["region_count"] >= 4
    assert holdout_mixed["subset"]["period_count"] >= 4
    assert holdout_mixed["raw_context_residual_zero_error_count"] >= 1
    holdout_mixed_rows = {
        item["candidate_id"]: item
        for item in holdout_mixed["rows"]
    }
    raw_transformer_holdout_mixed = holdout_mixed_rows["torch_spatiotemporal_transformer"]
    assert raw_transformer_holdout_mixed["raw_context_residual_feasibility"] is True
    assert raw_transformer_holdout_mixed["example_count"] >= 29
    assert raw_transformer_holdout_mixed["allowed_count"] >= 10
    assert raw_transformer_holdout_mixed["blocked_count"] >= 19
    assert raw_transformer_holdout_mixed["region_count"] >= 4
    assert raw_transformer_holdout_mixed["period_count"] >= 4
    assert raw_transformer_holdout_mixed["false_allow"] == 0
    assert raw_transformer_holdout_mixed["false_block"] == 0
    unseen_mixed = report["backend_comparison"]["unseen_mixed_risk_feasibility"]
    assert unseen_mixed["schema"] == "territory_world_model.unseen_mixed_risk_backend_feasibility.v1"
    assert unseen_mixed["subset"]["primary_mode"] == "time_policy"
    assert unseen_mixed["subset"]["modes"]["time_policy"]["example_count"] >= 29
    assert unseen_mixed["subset"]["modes"]["time_policy"]["allowed_count"] >= 10
    assert unseen_mixed["subset"]["modes"]["time_policy"]["blocked_count"] >= 19
    assert unseen_mixed["subset"]["modes"]["region_policy"]["example_count"] >= 10
    assert unseen_mixed["subset"]["modes"]["region_policy"]["allowed_count"] >= 6
    assert unseen_mixed["subset"]["modes"]["region_policy"]["blocked_count"] >= 4
    assert required_mixed_allowed_policies.issubset(unseen_mixed["subset"]["modes"]["region_policy"]["policy_counts"])
    assert unseen_mixed["subset"]["modes"]["region_action_policy"]["example_count"] >= 10
    assert unseen_mixed["subset"]["modes"]["region_action_policy"]["allowed_count"] >= 6
    assert unseen_mixed["subset"]["modes"]["region_action_policy"]["blocked_count"] >= 4
    assert required_mixed_allowed_policies.issubset(unseen_mixed["subset"]["modes"]["region_action_policy"]["policy_counts"])
    assert unseen_mixed["raw_context_residual_zero_error_count"] >= 1
    unseen_mixed_rows = {
        item["candidate_id"]: item
        for item in unseen_mixed["rows"]
    }
    raw_transformer_unseen = unseen_mixed_rows["torch_spatiotemporal_transformer"]
    assert raw_transformer_unseen["raw_context_residual_feasibility"] is True
    assert raw_transformer_unseen["primary_mode"] == "time_policy"
    assert raw_transformer_unseen["example_count"] >= 29
    assert raw_transformer_unseen["allowed_count"] >= 10
    assert raw_transformer_unseen["blocked_count"] >= 19
    assert raw_transformer_unseen["false_allow"] == 0
    assert raw_transformer_unseen["false_block"] == 0
    assert raw_transformer_unseen["mode_summary"]["region_policy"]["example_count"] >= 10
    assert raw_transformer_unseen["mode_summary"]["region_policy"]["allowed_count"] >= 6
    assert raw_transformer_unseen["mode_summary"]["region_policy"]["false_allow"] == 0
    assert raw_transformer_unseen["mode_summary"]["region_policy"]["false_block"] == 0
    assert raw_transformer_unseen["mode_summary"]["region_action_policy"]["example_count"] >= 10
    assert raw_transformer_unseen["mode_summary"]["region_action_policy"]["allowed_count"] >= 6
    assert raw_transformer_unseen["mode_summary"]["region_action_policy"]["false_allow"] == 0
    assert raw_transformer_unseen["mode_summary"]["region_action_policy"]["false_block"] == 0
    ranking = {
        item["candidate_id"]: item
        for item in report["backend_comparison"]["ranking"]
    }
    assert ranking["torch_spatiotemporal_transformer"]["training_diagnostics"]["configured_epoch_count"] >= 40
    assert ranking["torch_spatiotemporal_transformer"]["training_diagnostics"]["action_mask_allowed_positive_weight"] == 2.0
    assert ranking["torch_spatiotemporal_transformer"]["training_diagnostics"]["action_mask_conditioned_allowed_weight"] == 2.0
    assert ranking["torch_spatiotemporal_transformer"]["training_diagnostics"]["action_mask_mixed_blocked_weight"] >= 1.5
    assert ranking["torch_spatiotemporal_transformer"]["training_diagnostics"]["constraint_risk_contextual_weight"] == 1.0
    assert ranking["torch_spatiotemporal_transformer"]["training_diagnostics"]["seed"] == 19
    assert ranking["torch_spatiotemporal_transformer"]["architecture_summary"]["hidden_dim"] == 32
    leakage = ranking["torch_spatiotemporal_transformer"]["input_leakage_audit"]
    assert leakage["status"] == "pass"
    assert leakage["forbidden_hit_count"] == 0
    feature_names = "\n".join(ranking["torch_spatiotemporal_transformer"]["feature_contract_summary"]["action_mask_context_feature_names"])
    assert "target.action_allowed" not in feature_names
    assert "risk_proxy_source.target_fallback" not in feature_names
    assert ranking["torch_spatiotemporal_transformer"]["planner_holdout_analysis"]["metrics"]["false_allow_selection_count"] == 0


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
    assert probe["weights"] == [0.0, 0.7, 1.2]
    assert probe["selected"]["weight"] in {0.0, 0.7, 1.2}
    for row in probe["rows"]:
        assert row["risk_head_mode"] == "context_residual"
        assert set(row["risk_head_context_tokens"]) == {"action", "context", "temporal"}
        assert row["constraint_risk_contextual_weight"] == 1.0
        assert row["constraint_risk_weight_mean"] >= 1.0
        assert row["constraint_risk_weight_max"] >= 1.0
        assert row["feasibility_head_mode"] == "context_residual"
        assert set(row["feasibility_head_context_tokens"]) == {"action", "context", "temporal"}
        assert row["training_status"] == "pass"
        assert "candidate_split_mae_before" in row
        assert "candidate_split_mae_after" in row
        assert "false_allow" in row
        assert "planner_mean_regret" in row
        expected_accepted = (
            row["calibration_status"] == "pass"
            and row["candidate_split_improved"] is True
            and row["holdout_improved"] is True
        )
        assert row["calibration_accepted"] is expected_accepted
        if expected_accepted:
            assert row["applied_prediction_count"] > 0
        else:
            assert row["applied_prediction_count"] == 0
    numeric_rows = [row for row in probe["rows"] if row["candidate_split_mae_before"] is not None]
    if numeric_rows:
        assert runner.transformer_risk_weight_probe_selection_key(probe["selected"]) == min(
            runner.transformer_risk_weight_probe_selection_key(row)
            for row in probe["rows"]
        )
    if probe["selected"]["calibration_status"] == "pass":
        assert probe["selected"]["calibration_accepted"] is True
        assert probe["selected"]["candidate_split_improved"] is True
        assert probe["selected"]["holdout_improved"] is True
        assert probe["selected"]["applied_prediction_count"] > 0


def test_synthetic_runner_probes_transformer_contextual_risk_weights(tmp_path):
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
        probe_transformer_risk_weights=[0.0, 1.0],
        probe_transformer_risk_contextual_weights=[1.0, 2.5],
        probe_transformer_risk_seeds=[19],
    )

    probe = report["transformer_risk_contextual_weight_probe"]
    assert probe["schema"] == "territory_world_model.transformer_risk_contextual_weight_probe.v1"
    assert probe["status"] == "pass"
    assert probe["contextual_weights"] == [1.0, 2.5]
    assert runner.parse_weight_list("1.0,2.5", min_value=1.0, max_value=4.0) == [1.0, 2.5]
    assert runner.parse_int_list("19,23") == [19, 23]
    assert probe["risk_weights"] == [0.0, 1.0]
    assert [row["contextual_weight"] for row in probe["rows"]] == [1.0, 2.5]
    assert probe["selected"]["contextual_weight"] in {1.0, 2.5}
    assert probe["promotion_gate"]["schema"] == "territory_world_model.transformer_contextual_risk_weight_promotion_gate.v1"
    assert probe["promotion_gate"]["status"] in {"pass", "review"}
    assert probe["promotion_gate"]["promotion_scope"] == "synthetic_probe_candidate_only"
    for row in probe["rows"]:
        assert row["raw_candidate_count"] == 6
        assert row["head_probe_status"] in {"pass", "review"}
        assert row["raw_gate_status"] in {"pass", "review"}
        assert "holdout_mae_gap" in row
        assert isinstance(row["raw_gate_review_reasons"], list)
        assert isinstance(row["raw_grid_blocker_counts"], dict)
    assert runner.transformer_risk_contextual_weight_probe_selection_key(probe["selected"]) == min(
        runner.transformer_risk_contextual_weight_probe_selection_key(row)
        for row in probe["rows"]
    )
    seed_probe = report["transformer_risk_seed_reproducibility"]
    assert seed_probe["schema"] == "territory_world_model.transformer_risk_seed_reproducibility_probe.v1"
    assert seed_probe["seeds"] == [19]
    assert seed_probe["gate"]["schema"] == "territory_world_model.transformer_seed_reproducibility_gate.v1"
    assert seed_probe["gate"]["status"] == "review"
    assert "fewer_than_two_transformer_seeds" in seed_probe["gate"]["review_reasons"]
    assert len(seed_probe["rows"]) == 1
    assert seed_probe["rows"][0]["seed"] == 19
    assert seed_probe["rows"][0]["candidate_config"]["transformer_seed"] == 19
    assert seed_probe["reproducibility_policy"].startswith("require at least two transformer seeds")


def test_transformer_contextual_risk_weight_promotion_gate_passes_only_on_nonpositive_gaps():
    runner = _load_runner_module()
    selected = {
        "contextual_weight": 3.8,
        "risk_weights": [1.1, 1.2, 1.3],
        "raw_gate_status": "pass",
        "raw_selected_risk_head_mode": "shared",
        "raw_selected_weight": 1.3,
        "constraint_error_gap": -0.001,
        "holdout_mae_gap": -0.002,
        "planner_regret_gap": 0.0,
        "raw_selected_false_allow": 0,
        "raw_grid_promotable_candidate_count": 2,
    }

    gate = runner.transformer_contextual_risk_weight_promotion_gate(selected)

    assert gate["schema"] == "territory_world_model.transformer_contextual_risk_weight_promotion_gate.v1"
    assert gate["status"] == "pass"
    assert gate["candidate_config"]["constraint_risk_contextual_weight"] == 3.8
    assert gate["candidate_config"]["risk_head_mode"] == "shared"
    assert gate["candidate_config"]["risk_calibration_weight"] == 1.3
    assert gate["review_reasons"] == []

    selected["holdout_mae_gap"] = 0.000001
    blocked = runner.transformer_contextual_risk_weight_promotion_gate(selected)
    assert blocked["status"] == "review"
    assert "raw_holdout_mae_gap_positive" in blocked["review_reasons"]


def test_transformer_seed_reproducibility_gate_requires_multiple_promoted_seeds():
    runner = _load_runner_module()
    promoted = {
        "seed": 19,
        "raw_gate_status": "pass",
        "raw_promotion_candidate_status": "pass",
    }
    assert runner.transformer_seed_reproducibility_gate([promoted])["status"] == "review"

    passed = runner.transformer_seed_reproducibility_gate(
        [
            promoted,
            {
                "seed": 23,
                "raw_gate_status": "pass",
                "raw_promotion_candidate_status": "pass",
            },
        ]
    )
    assert passed["status"] == "pass"
    assert passed["pass_seed_count"] == 2

    failed = runner.transformer_seed_reproducibility_gate(
        [
            promoted,
            {
                "seed": 23,
                "raw_gate_status": "review",
                "raw_promotion_candidate_status": "review",
            },
        ]
    )
    assert failed["status"] == "review"
    assert failed["failed_seeds"] == [23]
    assert "one_or_more_seed_runs_not_promoted" in failed["review_reasons"]


def test_transformer_training_epoch_seed_stability_gate_selects_seed_stable_budget():
    runner = _load_runner_module()
    assert runner.normalize_transformer_training_epoch_probe_values([8, 80, 120, 120]) == [60, 80, 120]

    unstable_seed_rows = [
        {
            "seed": 19,
            "raw_gate_status": "review",
            "raw_promotion_candidate_status": "review",
            "raw_gate_review_reasons": ["raw_holdout_mae_above_calibrated_selection"],
            "raw_promotion_review_reasons": ["raw_progress_gate_not_pass"],
            "raw_grid_promotable_candidate_count": 0,
            "candidate_config": {"transformer_seed": 19},
            "comparison": {
                "constraint_error_gap": -0.001,
                "holdout_mae_gap": 0.002,
                "planner_regret_gap": -0.003,
                "raw_selected_false_allow": 0,
            },
        },
        {
            "seed": 23,
            "raw_gate_status": "pass",
            "raw_promotion_candidate_status": "pass",
            "raw_grid_promotable_candidate_count": 2,
            "candidate_config": {"transformer_seed": 23},
            "comparison": {
                "constraint_error_gap": -0.002,
                "holdout_mae_gap": -0.004,
                "planner_regret_gap": -0.005,
                "raw_selected_false_allow": 0,
            },
        },
    ]
    stable_seed_rows = [
        {
            "seed": 19,
            "raw_gate_status": "pass",
            "raw_promotion_candidate_status": "pass",
            "raw_grid_promotable_candidate_count": 1,
            "candidate_config": {"transformer_seed": 19},
            "comparison": {
                "constraint_error_gap": -0.001,
                "holdout_mae_gap": -0.002,
                "planner_regret_gap": 0.0,
                "raw_selected_false_allow": 0,
            },
        },
        {
            "seed": 23,
            "raw_gate_status": "pass",
            "raw_promotion_candidate_status": "pass",
            "raw_grid_promotable_candidate_count": 2,
            "candidate_config": {"transformer_seed": 23},
            "comparison": {
                "constraint_error_gap": -0.003,
                "holdout_mae_gap": -0.004,
                "planner_regret_gap": -0.005,
                "raw_selected_false_allow": 0,
            },
        },
    ]
    unstable_gate = runner.transformer_seed_reproducibility_gate(unstable_seed_rows)
    stable_gate = runner.transformer_seed_reproducibility_gate(stable_seed_rows)
    unstable = runner.transformer_training_epoch_seed_stability_row(80, unstable_gate, unstable_seed_rows)
    stable = runner.transformer_training_epoch_seed_stability_row(100, stable_gate, stable_seed_rows)

    selected = min([unstable, stable], key=runner.transformer_training_epoch_seed_stability_selection_key)
    gate = runner.transformer_training_epoch_seed_stability_gate([unstable, stable], selected)

    assert selected["training_epoch_budget"] == 100
    assert selected["seed_reproducibility_status"] == "pass"
    assert selected["min_raw_grid_promotable_candidate_count"] == 1
    assert unstable["raw_gate_blocker_counts"]["raw_holdout_mae_above_calibrated_selection"] == 1
    assert gate["schema"] == "territory_world_model.transformer_training_epoch_seed_stability_gate.v1"
    assert gate["status"] == "pass"
    assert gate["selected_training_epoch_budget"] == 100
    assert gate["pass_epoch_budget_count"] == 1

    blocked = runner.transformer_training_epoch_seed_stability_gate([unstable], unstable)
    assert blocked["status"] == "review"
    assert "no_training_epoch_budget_passed_seed_reproducibility" in blocked["review_reasons"]


def test_transformer_training_seed_stability_row_reports_near_miss_without_relaxing_gate():
    runner = _load_runner_module()
    seed_rows = [
        {
            "seed": 19,
            "raw_gate_status": "pass",
            "raw_promotion_candidate_status": "pass",
            "raw_grid_promotable_candidate_count": 2,
            "candidate_config": {"transformer_seed": 19, "learning_rate": 0.008},
            "comparison": {
                "constraint_error_gap": -0.001,
                "holdout_mae_gap": -0.002,
                "planner_regret_gap": 0.0,
                "raw_selected_false_allow": 0,
            },
        },
        {
            "seed": 31,
            "raw_gate_status": "review",
            "raw_promotion_candidate_status": "review",
            "raw_gate_review_reasons": [
                "raw_constraint_error_above_calibrated_selection",
                "raw_holdout_mae_above_calibrated_selection",
            ],
            "raw_promotion_review_reasons": [
                "raw_progress_gate_not_pass",
                "raw_grid_promotable_candidate_missing",
            ],
            "raw_grid_promotable_candidate_count": 0,
            "candidate_config": {"transformer_seed": 31, "learning_rate": 0.008},
            "comparison": {
                "constraint_error_gap": 0.000027,
                "holdout_mae_gap": 0.000028,
                "planner_regret_gap": 0.0,
                "raw_selected_false_allow": 0,
            },
        },
        {
            "seed": 37,
            "raw_gate_status": "review",
            "raw_promotion_candidate_status": "review",
            "raw_gate_review_reasons": ["raw_selected_false_allow_nonzero"],
            "raw_grid_promotable_candidate_count": 0,
            "candidate_config": {"transformer_seed": 37, "learning_rate": 0.008},
            "comparison": {
                "constraint_error_gap": 0.000001,
                "holdout_mae_gap": 0.0,
                "planner_regret_gap": 0.0,
                "raw_selected_false_allow": 1,
            },
        },
    ]

    gate = runner.transformer_seed_reproducibility_gate(seed_rows)
    row = runner.transformer_training_epoch_seed_stability_row(100, gate, seed_rows)
    audit = row["near_miss_audit"]

    assert gate["status"] == "review"
    assert row["seed_reproducibility_status"] == "review"
    assert audit["schema"] == "territory_world_model.transformer_seed_near_miss_audit.v1"
    assert audit["policy"].startswith("diagnostic only")
    assert audit["failed_seed_count"] == 2
    assert audit["near_miss_seed_count"] == 1
    assert audit["near_miss_seeds"] == [31]
    assert audit["near_miss_false_allow_count"] == 0
    assert audit["max_positive_constraint_gap"] == 0.000027
    assert audit["max_positive_holdout_gap"] == 0.000028
    assert audit["max_raw_selected_false_allow_among_failed"] == 1
    assert audit["rows"][0]["raw_promotion_review_reasons"] == [
        "raw_progress_gate_not_pass",
        "raw_grid_promotable_candidate_missing",
    ]


def test_transformer_training_hyperparameters_flow_into_backend_spec():
    runner = _load_runner_module()

    specs = runner.backend_experiment_specs(
        mlp_epochs=8,
        include_graph=False,
        include_transformer=True,
        transformer_risk_calibration_weight=0.0,
        transformer_risk_contextual_weight=3.8,
        transformer_learning_rate=0.008,
        transformer_weight_decay=0.004,
        transformer_dropout=0.15,
        transformer_risk_head_mode="shared",
        transformer_seed=23,
    )
    transformer_spec = next(item for item in specs if item["candidate_id"] == "torch_spatiotemporal_transformer")
    config = transformer_spec["training_config"]

    assert runner.transformer_training_learning_rate(0.2) == 0.05
    assert runner.transformer_training_weight_decay(-1.0) == 0.0
    assert runner.transformer_training_dropout(0.8) == 0.5
    assert runner.normalize_transformer_learning_rate_probe_values([0.012, 0.008, 0.012]) == [0.008, 0.012]
    assert runner.normalize_transformer_weight_decay_probe_values([0.0, 0.004, 0.004]) == [0.0, 0.004]
    assert runner.normalize_transformer_dropout_probe_values([0.0, 0.15, 0.15]) == [0.0, 0.15]
    assert config["epochs"] == 60
    assert config["learning_rate"] == 0.008
    assert config["weight_decay"] == 0.004
    assert config["dropout"] == 0.15
    assert config["constraint_risk_contextual_weight"] == 3.8
    assert config["risk_head_mode"] == "shared"
    assert config["seed"] == 23


def test_transformer_training_hyperparameter_seed_stability_gate_selects_stable_config():
    runner = _load_runner_module()
    unstable_seed_rows = [
        {
            "seed": 19,
            "raw_gate_status": "review",
            "raw_promotion_candidate_status": "review",
            "raw_gate_review_reasons": ["raw_planner_regret_above_calibrated_selection"],
            "raw_promotion_review_reasons": ["raw_progress_gate_not_pass"],
            "raw_grid_promotable_candidate_count": 0,
            "candidate_config": {"transformer_seed": 19, "learning_rate": 0.012},
            "comparison": {
                "constraint_error_gap": -0.001,
                "holdout_mae_gap": -0.002,
                "planner_regret_gap": 0.001,
                "raw_selected_false_allow": 0,
            },
        },
        {
            "seed": 23,
            "raw_gate_status": "pass",
            "raw_promotion_candidate_status": "pass",
            "raw_grid_promotable_candidate_count": 2,
            "candidate_config": {"transformer_seed": 23, "learning_rate": 0.012},
            "comparison": {
                "constraint_error_gap": -0.002,
                "holdout_mae_gap": -0.003,
                "planner_regret_gap": -0.004,
                "raw_selected_false_allow": 0,
            },
        },
    ]
    stable_seed_rows = [
        {
            "seed": 19,
            "raw_gate_status": "pass",
            "raw_promotion_candidate_status": "pass",
            "raw_grid_promotable_candidate_count": 1,
            "candidate_config": {"transformer_seed": 19, "learning_rate": 0.008},
            "comparison": {
                "constraint_error_gap": -0.001,
                "holdout_mae_gap": -0.002,
                "planner_regret_gap": 0.0,
                "raw_selected_false_allow": 0,
            },
        },
        {
            "seed": 23,
            "raw_gate_status": "pass",
            "raw_promotion_candidate_status": "pass",
            "raw_grid_promotable_candidate_count": 1,
            "candidate_config": {"transformer_seed": 23, "learning_rate": 0.008},
            "comparison": {
                "constraint_error_gap": -0.002,
                "holdout_mae_gap": -0.003,
                "planner_regret_gap": -0.004,
                "raw_selected_false_allow": 0,
            },
        },
    ]
    unstable = runner.transformer_training_hyperparameter_seed_stability_row(
        learning_rate=0.012,
        weight_decay=0.001,
        dropout=0.0,
        gate=runner.transformer_seed_reproducibility_gate(unstable_seed_rows),
        seed_rows=unstable_seed_rows,
    )
    stable = runner.transformer_training_hyperparameter_seed_stability_row(
        learning_rate=0.008,
        weight_decay=0.004,
        dropout=0.15,
        gate=runner.transformer_seed_reproducibility_gate(stable_seed_rows),
        seed_rows=stable_seed_rows,
    )

    selected = min([unstable, stable], key=runner.transformer_training_hyperparameter_seed_stability_selection_key)
    gate = runner.transformer_training_hyperparameter_seed_stability_gate([unstable, stable], selected)

    assert selected["learning_rate"] == 0.008
    assert selected["weight_decay"] == 0.004
    assert selected["dropout"] == 0.15
    assert selected["seed_reproducibility_status"] == "pass"
    assert unstable["raw_gate_blocker_counts"]["raw_planner_regret_above_calibrated_selection"] == 1
    assert gate["schema"] == "territory_world_model.transformer_training_hyperparameter_seed_stability_gate.v1"
    assert gate["status"] == "pass"
    assert gate["selected_config"] == {"learning_rate": 0.008, "weight_decay": 0.004, "dropout": 0.15}

    blocked = runner.transformer_training_hyperparameter_seed_stability_gate([unstable], unstable)
    assert blocked["status"] == "review"
    assert "no_training_hyperparameter_config_passed_seed_reproducibility" in blocked["review_reasons"]


def test_synthetic_runner_accepts_context_direct_transformer_risk_head(tmp_path):
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

    assert runner.risk_head_mode_or_default("context_direct") == "context_direct"
    report = runner.run_synthetic_experiment(
        path,
        include_transformer=True,
        transformer_risk_head_mode="context_direct",
    )
    ranking = {
        item["candidate_id"]: item
        for item in report["backend_comparison"]["ranking"]
    }
    raw_transformer = ranking["torch_spatiotemporal_transformer"]
    assert raw_transformer["training_diagnostics"]["risk_head_mode"] == "context_direct"
    assert raw_transformer["architecture_summary"]["constraint_risk_head"] == "context_direct"
    assert set(raw_transformer["architecture_summary"]["constraint_risk_context_tokens"]) == {
        "action",
        "context",
        "temporal",
    }
    assert raw_transformer["input_leakage_audit"]["status"] == "pass"
    assert raw_transformer["input_leakage_audit"]["forbidden_hit_count"] == 0


def test_synthetic_runner_raw_risk_head_progress_gate_reviews_when_raw_lags_calibration():
    runner = _load_runner_module()
    selected = {
        "risk_head_mode": "context_residual",
        "status": "pass",
        "selected_weight": 1.2,
        "selected_calibrated_mean_constraint_error": 0.02,
        "selected_holdout_mae_after": 0.03,
        "selected_planner_mean_regret": 0.01,
        "selected_false_allow": 0,
    }
    raw_selected = {
        "risk_head_mode": "context_direct",
        "status": "pass",
        "selected_weight": 0.0,
        "selected_raw_mean_constraint_error": 0.025,
        "selected_holdout_mae_before": 0.04,
        "selected_planner_mean_regret": 0.02,
        "selected_false_allow": 0,
    }

    gate = runner.transformer_raw_risk_head_progress_gate(selected, raw_selected)

    assert gate["schema"] == "territory_world_model.transformer_raw_risk_head_progress_gate.v1"
    assert gate["status"] == "review"
    assert "raw_constraint_error_above_calibrated_selection" in gate["review_reasons"]
    assert "raw_holdout_mae_above_calibrated_selection" in gate["review_reasons"]
    assert "raw_planner_regret_above_calibrated_selection" in gate["review_reasons"]
    assert gate["comparison"]["constraint_error_gap"] == 0.005

    audit = runner.transformer_raw_risk_head_grid_audit(selected, [raw_selected])
    assert audit["schema"] == "territory_world_model.transformer_raw_risk_head_grid_audit.v1"
    assert audit["status"] == "review"
    assert audit["candidate_count"] == 1
    assert audit["promotable_candidate_count"] == 0
    assert audit["blocker_counts"]["raw_constraint_error_above_calibrated_selection"] == 1
    assert audit["blocker_counts"]["raw_holdout_mae_above_calibrated_selection"] == 1
    assert audit["rows"][0]["promotable"] is False

    promotion_candidate = runner.transformer_raw_risk_head_promotion_candidate(raw_selected, gate, audit)
    assert promotion_candidate["schema"] == "territory_world_model.transformer_raw_risk_head_promotion_candidate.v1"
    assert promotion_candidate["status"] == "review"
    assert "raw_progress_gate_not_pass" in promotion_candidate["review_reasons"]


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


def test_synthetic_runner_constraint_risk_calibration_requires_holdout_improvement():
    runner = _load_runner_module()
    dataset = {
        "examples": [
            {
                "id": "candidate-1",
                "split": "candidate",
                "targets": {"constraint_violation_probability": 0.2},
            },
            {
                "id": "candidate-2",
                "split": "candidate",
                "targets": {"constraint_violation_probability": 0.8},
            },
            {
                "id": "holdout-1",
                "split": "holdout",
                "targets": {"constraint_violation_probability": 0.1},
            },
        ]
    }
    candidate = {
        "schema": "territory_world_model.neural_multi_head_dynamics_candidate_report.v1",
        "status": "pass",
        "candidate": {"model_name": "risk-test", "model_family": "test"},
        "predictions": {
            "candidate-1": {"constraint_violation_probability": 0.1},
            "candidate-2": {"constraint_violation_probability": 0.9},
            "holdout-1": {"constraint_violation_probability": 0.1},
        },
        "evidence_gate": {"status": "pass"},
    }

    risk_report = runner.constraint_risk_calibrated_candidate_report(candidate, dataset)
    calibration = risk_report["constraint_risk_calibration"]

    assert calibration["status"] == "review"
    assert calibration["candidate_split_improved"] is True
    assert calibration["holdout_improved"] is False
    assert calibration["accepted"] is False
    assert calibration["applied_prediction_count"] == 0
    assert "holdout_calibration_does_not_reduce_error" in calibration["review_reasons"]
    assert risk_report["candidate"]["constraint_risk_calibrated"] is False
    assert risk_report["evidence_gate"]["constraint_risk_calibrated"] is False
    assert risk_report["predictions"]["holdout-1"]["constraint_violation_probability"] == 0.1


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
            "production_policy_alignment_status": "not_provided",
            "production_policy_alignment_missing": ["production_policy_history_not_provided"],
            "production_policy_alignment_required": {
                "region_policy_key_count": 10,
                "region_action_policy_key_count": 10,
            },
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
    assert "Production policy alignment" in markdown
    assert "production policy alignment requirement" in markdown
    assert "production_policy_history_not_provided" in markdown


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


def test_twm_validation_bundle_runner_executes_offline_demo_pipeline(tmp_path):
    runner = _load_validation_bundle_module()

    report = runner.run_validation_bundle(
        bundle_dir=Path("data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion"),
        optimization_dir=Path("data_agent/test_data/twm_bishan_demo/optimization"),
        scenario="pytest_offline_validation_bundle",
        horizon=2,
    )
    markdown_path = tmp_path / "twm_validation_bundle.md"
    runner.write_validation_bundle_markdown(markdown_path, report)

    assert report["schema"] == "territory_world_model.validation_bundle.v1"
    assert report["status"] in {"pass", "review", "blocked"}
    assert report["inputs"]["evidence_coverage"] == 0.85
    assert report["state_summary"]["object_count"] > 0
    assert report["state_summary"]["relation_count"] > 0
    assert report["rule_summary"]["evaluated_rule_count"] >= 1
    assert report["selected_plan_evaluation_bundle"]["schema"] == "territory_world_model.selected_plan_evaluation_bundle.v1"
    assert report["selected_plan_evaluation_bundle"]["selected"]["candidate_id"]
    assert report["validation_summary"]["stage_count"] >= 6
    assert report["claim_ladder"]["schema"] == "territory_world_model.claim_ladder.v1"
    assert report["production_observed_history_preflight"]["schema"] == "territory_world_model.production_observed_history_preflight.v1"
    assert report["production_observed_history_preflight"]["status"] == "not_provided"
    assert report["production_readiness_gate"]["schema"] == "territory_world_model.production_readiness_gate.v1"
    assert report["production_readiness_gate"]["required"] is False
    assert report["production_readiness_gate"]["status"] == "review"
    assert "production_observed_history_preflight_pass" in report["production_readiness_gate"]["missing"]
    assert report["deployment_punch_list"]["schema"] == "territory_world_model.validation_bundle_deployment_punch_list.v1"
    assert report["deployment_punch_list"]["status"] == "review"
    bundle_gates = {item["gate"]: item for item in report["deployment_punch_list"]["actions"]}
    assert bundle_gates["production_observed_history_preflight_pass"]["phase"] == "observed_history"
    assert bundle_gates["production_observed_history_preflight_pass"]["blocks_current_run"] is False
    assert report["status"] == "review"
    assert report["sanitized_export_policy"]["exports_raw_geometries"] is False
    assert report["sanitized_export_policy"]["exports_raw_state_objects"] is False
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "raw geometries" in markdown
    assert "Deployment Punch List" in markdown
    assert "production_observed_history_preflight_pass" in markdown


def test_twm_validation_bundle_markdown_includes_production_normalization_summary():
    runner = _load_validation_bundle_module()

    report = {
        "inputs": {
            "bundle_dir": "/tmp/bundle",
            "optimization_dir": None,
            "scenario": "pytest_bundle",
            "require_scca_pass": False,
            "scca_output_dir": None,
            "scca_result_json": None,
            "production_observed_history": "/tmp/normalized_production_observed_history.csv",
            "synthetic_experiment_foundation": "/tmp/synthetic_policy_benchmark.csv",
            "production_scale_profile": None,
            "require_production_readiness": False,
        },
        "state_summary": {},
        "rule_summary": {},
        "audit_summary": {},
        "selected_plan_evaluation_bundle": {},
        "validation_summary": {},
        "claim_ladder": {},
        "scca_summary": {},
        "production_observed_history_normalization": {
            "schema": "territory_world_model.production_observed_history_normalization.v1",
            "status": "pass",
            "source_path": "/tmp/raw_approval_export.csv",
            "output_path": "/tmp/normalized_production_observed_history.csv",
            "row_count": 10,
            "field_mapping": {
                "approval_id": {"primary_source_field": "AJBH"},
                "policy_version": {"primary_source_field": "rule_version"},
            },
            "unmapped_source_fields": ["review_result"],
            "audit": {"status": "pass"},
        },
        "production_observed_history_preflight": {
            "schema": "territory_world_model.production_observed_history_preflight.v1",
            "status": "pass",
            "schema_audit": {"status": "pass", "row_quality": {"production_candidate_row_count": 10}},
            "policy_history_quality": {"status": "pass", "allowed_count": 6, "blocked_count": 4},
            "temporal_validation_quality": {"status": "pass", "train_row_count": 6, "holdout_row_count": 4, "missing_temporal_gates": []},
            "policy_history_alignment": {"status": "pass", "missing": []},
        },
        "production_scale_readiness": {},
        "production_readiness_gate": {},
        "claim_boundary": {},
        "recommendations": [],
    }

    markdown = runner.render_validation_bundle_markdown(report)

    assert "Production Observed-History Normalization" in markdown
    assert "Normalization status" in markdown
    assert "/tmp/normalized_production_observed_history.csv" in markdown
    assert "approval_id<-AJBH" in markdown
    assert "policy_version<-rule_version" in markdown
    assert "review_result" in markdown


def test_twm_validation_bundle_runner_requires_scca_stage_when_configured():
    runner = _load_validation_bundle_module()

    report = runner.run_validation_bundle(
        bundle_dir=Path("data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion"),
        optimization_dir=Path("data_agent/test_data/twm_bishan_demo/optimization"),
        scenario="pytest_offline_validation_bundle_requires_scca",
        horizon=2,
        require_scca_pass=True,
    )

    stages = {stage["stage_code"]: stage for stage in report["validation_summary"]["stages"]}
    assert "spatial_causal_evidence" in stages
    assert stages["spatial_causal_evidence"]["status"] == "review"
    assert stages["spatial_causal_evidence"]["evidence_summary"]["required"] is True
    assert stages["spatial_causal_evidence"]["evidence_summary"]["provided"] is False
    assert report["scca_summary"]["required"] is True
    assert report["scca_summary"]["provided"] is False
    assert report["scca_summary"]["status"] == "missing_required"
    assert report["claim_ladder"]["current_level"] in {"L0", "L1"}


def test_twm_validation_bundle_strict_production_readiness_blocks_missing_evidence():
    runner = _load_validation_bundle_module()

    report = runner.run_validation_bundle(
        bundle_dir=Path("data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion"),
        optimization_dir=Path("data_agent/test_data/twm_bishan_demo/optimization"),
        scenario="pytest_strict_production_readiness",
        horizon=2,
        require_production_readiness=True,
    )

    gate = report["production_readiness_gate"]
    assert gate["required"] is True
    assert gate["status"] == "blocked"
    assert report["status"] == "blocked"
    assert "production_observed_history_preflight_pass" in gate["missing"]
    assert "claim_ladder_deployable" in gate["missing"]
    assert report["deployment_punch_list"]["status"] == "blocked"
    assert report["deployment_punch_list"]["blocking_action_count"] >= 1
    assert any(
        item["gate"] == "claim_ladder_deployable" and item["blocks_current_run"] is True
        for item in report["deployment_punch_list"]["actions"]
    )


def test_twm_validation_bundle_production_readiness_gate_passes_complete_evidence():
    runner = _load_validation_bundle_module()

    gate = runner.build_production_readiness_gate(
        selected_bundle={
            "status": "pass",
            "evidence_gate": {"status": "pass"},
            "claim_boundary": {"validation_overall_status": "pass"},
        },
        validation_report={
            "overall_status": "pass",
            "stages": [{"stage_code": "gis_deployability", "status": "pass"}],
        },
        claim_ladder={"current_level": "L4"},
        production_preflight={"status": "pass"},
        production_scale_readiness={"status": "pass"},
        scca_report={"evidence_gate": {"status": "pass"}},
        require_scca_pass=True,
        require_production_readiness=True,
    )

    assert gate["required"] is True
    assert gate["status"] == "pass"
    assert gate["missing"] == []
    assert {check["gate"]: check["status"] for check in gate["checks"]} == {
        "selected_plan_bundle_pass": "pass",
        "validation_report_pass": "pass",
        "claim_ladder_deployable": "pass",
        "production_observed_history_preflight_pass": "pass",
        "production_scale_readiness_pass": "pass",
        "human_review_and_audit_pass": "pass",
        "scca_causal_evidence_pass": "pass",
    }


def test_twm_validation_bundle_production_scale_readiness_reports_not_provided():
    runner = _load_validation_bundle_module()

    report = runner.build_production_scale_readiness(
        production_scale_profile=None,
        state_summary={"object_count": 5745, "relation_count": 10349},
    )

    assert report["schema"] == "territory_world_model.production_scale_readiness.v1"
    assert report["status"] == "not_provided"
    assert report["scale_tier"] == "local_or_county_scale"
    assert report["observed"]["local_state_object_count"] == 5745
    assert "production_scale_profile_provided" in report["missing"]


def test_twm_validation_bundle_production_scale_readiness_passes_national_profile(tmp_path):
    runner = _load_validation_bundle_module()
    profile_path = tmp_path / "production_scale_profile.json"
    profile_path.write_text(
        """
{
  "schema": "territory_world_model.production_scale_profile.v1",
  "example_only": false,
  "not_for_production": false,
  "layers": [
    {
      "name": "national_parcels",
      "row_count": 120000000,
      "storage_format": "geoparquet",
      "partition_columns": ["province_code", "year"],
      "spatial_index": "s2",
      "tiling": "quadkey"
    }
  ],
  "storage": {
    "table_format": "iceberg",
    "object_store": "minio"
  },
  "compute": {
    "engine": "spark",
    "spatial_engine": "sedona",
    "distributed": true
  },
  "validation": {
    "sampling_strategy": "stratified_spatial_temporal_holdout"
  },
  "serving": {
    "tiling": "vector_tile_pyramid"
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    report = runner.build_production_scale_readiness(production_scale_profile=profile_path)

    assert report["status"] == "pass"
    assert report["scale_tier"] == "hundred_million_scale"
    assert report["observed"]["max_layer_row_count"] == 120000000
    assert report["observed"]["requires_distributed_compute"] is True
    assert report["missing"] == []


def test_twm_validation_bundle_production_scale_readiness_reviews_missing_distributed_gates(tmp_path):
    runner = _load_validation_bundle_module()
    profile_path = tmp_path / "weak_scale_profile.json"
    profile_path.write_text(
        """
{
  "schema": "territory_world_model.production_scale_profile.v1",
  "example_only": false,
  "not_for_production": false,
  "layers": [
    {
      "name": "national_parcels",
      "row_count": 120000000,
      "storage_format": "shapefile"
    }
  ],
  "compute": {
    "engine": "postgres"
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    report = runner.build_production_scale_readiness(production_scale_profile=profile_path)

    assert report["status"] == "review"
    assert report["scale_tier"] == "hundred_million_scale"
    assert "lakehouse_storage" in report["missing"]
    assert "partition_strategy" in report["missing"]
    assert "spatial_index_strategy" in report["missing"]
    assert "distributed_compute" in report["missing"]
    assert "national_scale_sampling_or_tiling" in report["missing"]


def test_twm_validation_bundle_production_scale_template_is_not_accepted_as_real_profile(tmp_path):
    runner = _load_validation_bundle_module()
    template_path = tmp_path / "twm_production_scale_profile_template.json"

    runner.write_production_scale_profile_template(template_path)
    report = runner.build_production_scale_readiness(production_scale_profile=template_path)

    assert template_path.exists()
    assert report["schema"] == "territory_world_model.production_scale_readiness.v1"
    assert report["status"] == "review"
    assert "production_scale_profile_not_example" in report["missing"]
    template = json.loads(template_path.read_text(encoding="utf-8"))
    assert template["schema"] == "territory_world_model.production_scale_profile.v1"
    assert template["example_only"] is True
    assert template["not_for_production"] is True


def test_twm_validation_bundle_exit_code_supports_strict_ci_blocking():
    runner = _load_validation_bundle_module()

    assert runner.validation_bundle_exit_code({"status": "blocked"}, fail_on_blocked=True) == 2
    assert runner.validation_bundle_exit_code({"status": "review"}, fail_on_blocked=True) == 0
    assert runner.validation_bundle_exit_code({"status": "pass"}, fail_on_blocked=True) == 0
    assert runner.validation_bundle_exit_code({"status": "blocked"}, fail_on_blocked=False) == 0


def test_twm_validation_bundle_production_preflight_reports_not_provided():
    runner = _load_validation_bundle_module()

    report = runner.build_production_observed_history_preflight(production_observed_history=None)

    assert report["schema"] == "territory_world_model.production_observed_history_preflight.v1"
    assert report["status"] == "not_provided"
    assert report["schema_audit"]["status"] == "not_provided"
    assert report["policy_history_quality"]["status"] == "not_provided"
    assert report["policy_history_alignment"]["status"] == "not_provided"
    assert "production_policy_history_not_provided" in report["policy_history_alignment"]["missing"]


def test_twm_validation_bundle_prepares_normalized_raw_production_history(tmp_path):
    runner = _load_validation_bundle_module()
    benchmark_path = tmp_path / "synthetic_policy_benchmark.csv"
    raw_path = tmp_path / "raw_approval_export.csv"
    normalized_path = tmp_path / "normalized_production_observed_history.csv"
    _write_policy_benchmark_csv(benchmark_path)
    raw_path.write_text(
        "\n".join(
            [
                "AJBH,XMDM,review_result,observed_utility_delta,DKXZQDM,DKMJ,quality_score,decision_action,policy_code,feasibility_label,year,dataset_split,rule_version,synthetic,not_for_prod",
                "APR-1,PRJ-1,approved,0.31,PROD-R01,1000,0.82,approve_with_conditions,mixed_risk_allowed_with_conditions,allowed,2026Q1,training,RULE-2026-A,False,False",
                "APR-2,PRJ-2,approved,0.28,PROD-R02,1100,0.80,protect,mixed_risk_protect_allowed,allowed,2026Q1,training,RULE-2026-B,False,False",
                "APR-3,PRJ-3,approved,0.34,PROD-R03,1200,0.78,restore,mixed_risk_restore_allowed,allowed,2026Q2,training,RULE-2026-C,False,False",
                "APR-4,PRJ-4,in_review,0.08,PROD-R04,1300,0.76,approve_with_conditions,mixed_risk_blocked_condition_review,blocked,2026Q2,training,RULE-2026-D,False,False",
                "APR-5,PRJ-5,in_review,0.07,PROD-R05,1400,0.74,protect,mixed_risk_protect_blocked,blocked,2026Q3,training,RULE-2026-E,False,False",
                "APR-6,PRJ-6,approved,0.36,PROD-R06,1500,0.73,approve_with_conditions,mixed_risk_allowed_with_conditions,allowed,2026Q3,holdout,RULE-2026-F,False,False",
                "APR-7,PRJ-7,approved,0.37,PROD-R07,1600,0.72,protect,mixed_risk_protect_allowed,allowed,2026Q4,holdout,RULE-2026-G,False,False",
                "APR-8,PRJ-8,approved,0.38,PROD-R08,1700,0.71,restore,mixed_risk_restore_allowed,allowed,2026Q4,holdout,RULE-2026-H,False,False",
                "APR-9,PRJ-9,in_review,0.09,PROD-R09,1800,0.70,approve_with_conditions,mixed_risk_blocked_condition_review,blocked,2026Q4,holdout,RULE-2026-I,False,False",
                "APR-10,PRJ-10,in_review,0.06,PROD-R10,1900,0.69,protect,mixed_risk_protect_blocked,blocked,2026Q4,holdout,RULE-2026-J,False,False",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    prepared_path, normalization = runner.prepare_production_observed_history_for_bundle(
        production_observed_history=tmp_path / "already_normalized_input.csv",
        normalize_production_observed_history_source=raw_path,
        normalized_production_observed_history_output=normalized_path,
    )
    preflight = runner.build_production_observed_history_preflight(
        production_observed_history=prepared_path,
        synthetic_experiment_foundation=benchmark_path,
    )

    assert prepared_path == normalized_path
    assert normalization["status"] == "pass"
    assert normalization["field_mapping"]["approval_id"]["primary_source_field"] == "AJBH"
    assert normalization["field_mapping"]["policy_version"]["primary_source_field"] == "rule_version"
    assert preflight["status"] == "pass"
    assert preflight["schema_audit"]["path"] == str(normalized_path)


def test_twm_validation_bundle_production_preflight_passes_real_policy_coverage(tmp_path):
    runner = _load_validation_bundle_module()
    benchmark_path = tmp_path / "synthetic_policy_benchmark.csv"
    production_path = tmp_path / "production_observed_history.csv"
    _write_policy_benchmark_csv(benchmark_path)
    _write_production_policy_history_csv(production_path, include_all_policies=True)

    report = runner.build_production_observed_history_preflight(
        production_observed_history=production_path,
        synthetic_experiment_foundation=benchmark_path,
    )

    assert report["status"] == "pass"
    assert report["schema_audit"]["status"] == "pass"
    assert report["schema_audit"]["row_quality"]["production_candidate_row_count"] == 10
    assert report["policy_history_quality"]["status"] == "pass"
    assert report["policy_history_quality"]["allowed_count"] == 6
    assert report["policy_history_quality"]["blocked_count"] == 4
    assert report["policy_history_alignment"]["status"] == "pass"
    assert report["policy_history_alignment"]["missing"] == []
    assert report["synthetic_policy_coverage_benchmark"]["required_region_policy_key_count"] == 10


def test_validate_twm_data_foundation_cli_normalizes_raw_production_history(tmp_path):
    raw_path = tmp_path / "raw_approval_export.csv"
    normalized_path = tmp_path / "normalized_production_observed_history.csv"
    output_path = tmp_path / "twm_data_foundation_validation.json"
    markdown_path = tmp_path / "twm_data_foundation_health.md"
    raw_path.write_text(
        "\n".join(
            [
                "AJBH,XMDM,review_result,observed_utility_delta,DKXZQDM,DKMJ,quality_score,decision_action,policy_code,feasibility_label,year,dataset_split,rule_version,synthetic,not_for_prod",
                "APR-1,PRJ-1,approved,0.31,PROD-R01,1000,0.82,approve_with_conditions,mixed_risk_allowed_with_conditions,allowed,2026Q1,training,RULE-2026-A,False,False",
                "APR-2,PRJ-2,approved,0.28,PROD-R02,1100,0.80,protect,mixed_risk_protect_allowed,allowed,2026Q1,training,RULE-2026-B,False,False",
                "APR-3,PRJ-3,approved,0.34,PROD-R03,1200,0.78,restore,mixed_risk_restore_allowed,allowed,2026Q2,training,RULE-2026-C,False,False",
                "APR-4,PRJ-4,in_review,0.08,PROD-R04,1300,0.76,approve_with_conditions,mixed_risk_blocked_condition_review,blocked,2026Q2,training,RULE-2026-D,False,False",
                "APR-5,PRJ-5,in_review,0.07,PROD-R05,1400,0.74,protect,mixed_risk_protect_blocked,blocked,2026Q3,training,RULE-2026-E,False,False",
                "APR-6,PRJ-6,approved,0.36,PROD-R06,1500,0.73,approve_with_conditions,mixed_risk_allowed_with_conditions,allowed,2026Q3,holdout,RULE-2026-F,False,False",
                "APR-7,PRJ-7,approved,0.37,PROD-R07,1600,0.72,protect,mixed_risk_protect_allowed,allowed,2026Q4,holdout,RULE-2026-G,False,False",
                "APR-8,PRJ-8,approved,0.38,PROD-R08,1700,0.71,restore,mixed_risk_restore_allowed,allowed,2026Q4,holdout,RULE-2026-H,False,False",
                "APR-9,PRJ-9,in_review,0.09,PROD-R09,1800,0.70,approve_with_conditions,mixed_risk_blocked_condition_review,blocked,2026Q4,holdout,RULE-2026-I,False,False",
                "APR-10,PRJ-10,in_review,0.06,PROD-R10,1900,0.69,protect,mixed_risk_protect_blocked,blocked,2026Q4,holdout,RULE-2026-J,False,False",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    subprocess.run(
        [
            "/Users/zhouning/gisdataagent/.venv/bin/python",
            str(SCRIPT),
            "--output",
            str(output_path),
            "--markdown-output",
            str(markdown_path),
            "--normalize-production-observed-history-source",
            str(raw_path),
            "--normalized-production-observed-history-output",
            str(normalized_path),
        ],
        cwd=Path("/Users/zhouning/gisdataagent"),
        check=True,
    )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert normalized_path.exists()
    assert markdown_path.exists()
    assert report["inputs"]["normalize_production_observed_history_source"] == str(raw_path)
    assert report["inputs"]["normalized_production_observed_history_output"] == str(normalized_path)
    assert report["production_observed_history_normalization"]["status"] == "pass"
    assert report["production_observed_history_schema_audit"]["status"] == "pass"
    assert report["production_observed_history_schema_audit"]["path"] == str(normalized_path)
    assert report["outputs"]["normalized_production_observed_history"] == str(normalized_path)


def test_twm_validation_bundle_production_preflight_requires_temporal_holdout_and_policy_version(tmp_path):
    runner = _load_validation_bundle_module()
    benchmark_path = tmp_path / "synthetic_policy_benchmark.csv"
    production_path = tmp_path / "production_without_temporal_gate.csv"
    _write_policy_benchmark_csv(benchmark_path)
    production_path.write_text(
        "\n".join(
            [
                "unit_id,approval_id,project_id,approval_status,outcome,cluster,neighbors,x,y,area_m2,quality_score,action_type,action_mask_policy,action_mask_allowed,region_code,period,synthetic,not_for_production",
                "P-1,APR-P-1,PRJ-P-1,approved,0.31,block-1,,106.20,29.60,1000,0.82,approve_with_conditions,mixed_risk_allowed_with_conditions,True,PROD-R01,2026Q1,False,False",
                "P-2,APR-P-2,PRJ-P-2,approved,0.28,block-2,,106.21,29.61,1100,0.80,protect,mixed_risk_protect_allowed,True,PROD-R02,2026Q1,False,False",
                "P-3,APR-P-3,PRJ-P-3,approved,0.34,block-3,,106.22,29.62,1200,0.78,restore,mixed_risk_restore_allowed,True,PROD-R03,2026Q2,False,False",
                "P-4,APR-P-4,PRJ-P-4,in_review,0.08,block-4,,106.23,29.63,1300,0.76,approve_with_conditions,mixed_risk_blocked_condition_review,False,PROD-R04,2026Q2,False,False",
                "P-5,APR-P-5,PRJ-P-5,in_review,0.07,block-5,,106.24,29.64,1400,0.74,protect,mixed_risk_protect_blocked,False,PROD-R05,2026Q3,False,False",
                "P-6,APR-P-6,PRJ-P-6,approved,0.36,block-6,,106.25,29.65,1500,0.73,approve_with_conditions,mixed_risk_allowed_with_conditions,True,PROD-R06,2026Q3,False,False",
                "P-7,APR-P-7,PRJ-P-7,approved,0.37,block-7,,106.26,29.66,1600,0.72,protect,mixed_risk_protect_allowed,True,PROD-R07,2026Q4,False,False",
                "P-8,APR-P-8,PRJ-P-8,approved,0.38,block-8,,106.27,29.67,1700,0.71,restore,mixed_risk_restore_allowed,True,PROD-R08,2026Q4,False,False",
                "P-9,APR-P-9,PRJ-P-9,in_review,0.09,block-9,,106.28,29.68,1800,0.70,approve_with_conditions,mixed_risk_blocked_condition_review,False,PROD-R09,2026Q4,False,False",
                "P-10,APR-P-10,PRJ-P-10,in_review,0.06,block-10,,106.29,29.69,1900,0.69,protect,mixed_risk_protect_blocked,False,PROD-R10,2026Q4,False,False",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = runner.build_production_observed_history_preflight(
        production_observed_history=production_path,
        synthetic_experiment_foundation=benchmark_path,
    )

    assert report["status"] == "review"
    assert report["schema_audit"]["status"] == "review"
    assert report["temporal_validation_quality"]["status"] == "review"
    assert "explicit_train_holdout_split" in report["temporal_validation_quality"]["missing_temporal_gates"]
    assert "policy_effective_version" in report["temporal_validation_quality"]["missing_temporal_gates"]


def test_twm_validation_bundle_production_preflight_reviews_undercovered_policy_history(tmp_path):
    runner = _load_validation_bundle_module()
    benchmark_path = tmp_path / "synthetic_policy_benchmark.csv"
    production_path = tmp_path / "production_undercovered_history.csv"
    _write_policy_benchmark_csv(benchmark_path)
    _write_production_policy_history_csv(production_path, include_all_policies=False)

    report = runner.build_production_observed_history_preflight(
        production_observed_history=production_path,
        synthetic_experiment_foundation=benchmark_path,
    )

    assert report["status"] == "review"
    assert report["schema_audit"]["status"] == "pass"
    assert report["policy_history_quality"]["status"] == "pass"
    assert report["policy_history_alignment"]["status"] == "review"
    assert "production_policy_history_quality" not in report["policy_history_alignment"]["missing"]
    assert "blocked_policy_count_below_synthetic_unseen_benchmark" in report["policy_history_alignment"]["missing"]
    assert "mixed_allowed_policy_coverage_below_synthetic_unseen_benchmark" in report["policy_history_alignment"]["missing"]
