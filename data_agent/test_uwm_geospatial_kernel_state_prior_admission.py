import copy
from dataclasses import replace

import pytest
import torch

from data_agent.uwm.dam_geospatial_kernel import (
    DAMGKBatch,
    DAMGKConfig,
    bind_admitted_state_prior_node_context,
    verify_dam_gk_state_prior_context_binding,
    with_state_prior_context_control,
)
from data_agent.uwm.geospatial_kernel.state_prior_admission import (
    ADMISSION_GATES,
    STATE_PRIOR_ADMISSION_SCHEMA,
    STATE_PRIOR_ARTIFACT_SCHEMA,
    STATE_PRIOR_CONTEXT_SCHEMA,
    build_state_prior_admission,
    validate_state_prior_admission,
    validate_state_prior_artifact,
)
from data_agent.uwm.geospatial_state_prior_benchmark import (
    REQUIRED_GEOMETRY_ROUTES,
    REQUIRED_SPLITS,
    UWM_GEOSPATIAL_STATE_PRIOR_BENCHMARK_SCHEMA,
)


def test_observed_ready_benchmark_admits_only_calibrated_state_context():
    benchmark = _ready_benchmark()
    artifact = _state_prior_artifact(benchmark)

    admission = build_state_prior_admission(
        benchmark=benchmark,
        state_prior_artifact=artifact,
        admission_id="fixture-state-prior-admission",
        created_at="2026-08-04T15:00:00Z",
    )

    assert validate_state_prior_artifact(artifact) == {"valid": True, "errors": []}
    assert validate_state_prior_admission(admission) == {"valid": True, "errors": []}
    assert admission["schema"] == STATE_PRIOR_ADMISSION_SCHEMA
    assert admission["status"] == "admitted"
    assert admission["state_prior_context_ready"] is True
    assert set(admission["gate_results"]) == set(ADMISSION_GATES)
    assert all(admission["gate_results"].values())
    assert admission["rejection_reasons"] == []
    assert admission["enabled_support_levels"] == ["learned_calibrated"]
    assert admission["calibration_evidence_refs"]
    assert admission["context_envelope"]["schema"] == STATE_PRIOR_CONTEXT_SCHEMA
    assert admission["context_envelope"]["allowed_uses"] == [
        "node_context",
        "region_context",
        "state_initializer",
    ]
    assert "action_model" in admission["context_envelope"]["forbidden_uses"]
    assert "forcing" in admission["context_envelope"]["forbidden_uses"]
    assert "topology" in admission["context_envelope"]["forbidden_uses"]


@pytest.mark.parametrize("mutation", ["forged_ready", "missing_evidence", "missing_gate"])
def test_forged_or_incomplete_benchmark_is_rejected_without_context(mutation):
    benchmark = _ready_benchmark()
    if mutation == "forged_ready":
        benchmark["geospatial_state_prior_benchmark_ready"] = False
    elif mutation == "missing_evidence":
        benchmark["evidence_refs"] = []
    else:
        benchmark["readiness_gates"].pop("split_conformal_coverage_passed")

    admission = build_state_prior_admission(
        benchmark=benchmark,
        state_prior_artifact=_state_prior_artifact(benchmark),
        admission_id=f"{mutation}-admission",
        created_at="2026-08-04T15:05:00Z",
    )

    assert admission["status"] == "rejected"
    assert admission["state_prior_context_ready"] is False
    assert admission["enabled_support_levels"] == []
    assert admission["calibration_evidence_refs"] == []
    assert admission["context_envelope"] is None
    assert admission["claim_boundary"]["max_claim_level"] == "not_for_claim"
    assert admission["rejection_reasons"]
    assert validate_state_prior_admission(admission) == {"valid": True, "errors": []}


@pytest.mark.parametrize("mutation", ["uncalibrated", "downscaled"])
def test_uncalibrated_or_downscaled_prior_is_rejected(mutation):
    benchmark = _ready_benchmark()
    artifact = _state_prior_artifact(benchmark)
    if mutation == "uncalibrated":
        artifact["uncertainty"]["calibrated"] = False
    else:
        artifact["derivation_kind"] = "downscaled_proxy"

    admission = build_state_prior_admission(
        benchmark=benchmark,
        state_prior_artifact=artifact,
        admission_id=f"{mutation}-prior-admission",
        created_at="2026-08-04T15:10:00Z",
    )

    assert admission["status"] == "rejected"
    assert admission["gate_results"]["prior_artifact_contract_valid"] is False
    assert admission["context_envelope"] is None
    if mutation == "uncalibrated":
        assert admission["gate_results"]["uncertainty_calibrated"] is False
    assert validate_state_prior_admission(admission) == {"valid": True, "errors": []}


def test_admission_validator_rejects_policy_or_dynamics_claim_escalation():
    admission = build_state_prior_admission(
        benchmark=_ready_benchmark(),
        state_prior_artifact=_state_prior_artifact(_ready_benchmark()),
        admission_id="claim-escalation-admission",
        created_at="2026-08-04T15:15:00Z",
    )
    forged = copy.deepcopy(admission)
    forged["action_conditioned_dynamics_claim"] = True
    forged["context_envelope"]["policy_causal_effect_claim"] = True

    validation = validate_state_prior_admission(forged)

    assert not validation["valid"]
    assert "admission_action_conditioned_dynamics_claim_must_be_false" in validation["errors"]
    assert "context_envelope_policy_causal_effect_claim_must_be_false" in validation["errors"]


def test_malformed_gate_or_geometry_metadata_fails_closed_without_validator_error():
    malformed_admission = {"schema": STATE_PRIOR_ADMISSION_SCHEMA, "gate_results": []}

    validation = validate_state_prior_admission(malformed_admission)

    assert not validation["valid"]
    assert "admission_gate_set_mismatch" in validation["errors"]

    benchmark = _ready_benchmark()
    artifact = _state_prior_artifact(benchmark)
    artifact["geometry_coverage"]["routes"] = [{}]
    admission = build_state_prior_admission(
        benchmark=benchmark,
        state_prior_artifact=artifact,
        admission_id="malformed-geometry-admission",
        created_at="2026-08-04T15:20:00Z",
    )

    assert admission["status"] == "rejected"
    assert admission["gate_results"]["geometry_coverage_complete"] is False
    assert admission["context_envelope"] is None


def test_admitted_prior_binds_to_dam_gk_context_and_preserves_kernel_inputs():
    batch, config = _dam_gk_batch_and_config()
    prior_values = torch.tensor([[0.15], [0.35], [0.75]], dtype=torch.float32)

    binding = bind_admitted_state_prior_node_context(
        batch=batch,
        config=config,
        admission=_admitted_fixture(),
        node_keys=["node-a", "node-b", "node-c"],
        base_context_feature_names=["x", "y"],
        state_prior_feature_names=["fixture_state"],
        state_prior_values=prior_values,
        context_artifact_sha256="a" * 64,
    )

    verify_dam_gk_state_prior_context_binding(binding)
    assert binding.config.context_dim == 3
    assert binding.context_feature_names == ("x", "y", "fixture_state")
    assert binding.state_prior_feature_indices == (2,)
    assert torch.equal(binding.batch.node_context[:, :2], batch.node_context)
    assert torch.equal(binding.batch.node_context[:, 2:], prior_values)
    assert torch.equal(
        binding.batch.node_context_by_step[:, :, 2],
        prior_values.expand(-1, config.horizon),
    )
    assert torch.equal(binding.batch.node_action, batch.node_action)
    assert torch.equal(binding.batch.edge_index, batch.edge_index)
    assert torch.equal(binding.batch.edge_features, batch.edge_features)
    assert binding.context_artifact_sha256 == "a" * 64
    assert binding.as_dict()["claim_boundary"]["transition_skill_improvement_claim"] is False

    with pytest.raises(ValueError, match="context_artifact_sha256_mismatch"):
        bind_admitted_state_prior_node_context(
            batch=batch,
            config=config,
            admission=_admitted_fixture(),
            node_keys=["node-a", "node-b", "node-c"],
            base_context_feature_names=["x", "y"],
            state_prior_feature_names=["fixture_state"],
            state_prior_values=prior_values,
            context_artifact_sha256="c" * 64,
        )


def test_rejected_admission_cannot_reach_dam_gk_batch():
    benchmark = _ready_benchmark()
    benchmark["geospatial_state_prior_benchmark_ready"] = False
    rejected = build_state_prior_admission(
        benchmark=benchmark,
        state_prior_artifact=_state_prior_artifact(benchmark),
        admission_id="rejected-dam-gk-binding",
        created_at="2026-08-04T15:25:00Z",
    )
    batch, config = _dam_gk_batch_and_config()

    with pytest.raises(ValueError, match="state_prior_admission_blocked"):
        bind_admitted_state_prior_node_context(
            batch=batch,
            config=config,
            admission=rejected,
            node_keys=["node-a", "node-b", "node-c"],
            base_context_feature_names=["x", "y"],
            state_prior_feature_names=["fixture_state"],
            state_prior_values=torch.ones((3, 1)),
            context_artifact_sha256="a" * 64,
        )


@pytest.mark.parametrize(
    ("node_keys", "feature_names", "values", "error"),
    [
        (
            ["node-a", "node-b"],
            ["fixture_state"],
            torch.ones((3, 1)),
            "node_count_mismatch",
        ),
        (
            ["node-a", "node-b", "node-c"],
            ["wrong_feature"],
            torch.ones((3, 1)),
            "feature_order_mismatch",
        ),
        (
            ["node-a", "node-b", "node-c"],
            ["fixture_state"],
            torch.tensor([[0.1], [float("nan")], [0.3]]),
            "values_must_be_finite",
        ),
    ],
)
def test_dam_gk_binding_rejects_misaligned_or_nonfinite_context(
    node_keys, feature_names, values, error
):
    batch, config = _dam_gk_batch_and_config()

    with pytest.raises(ValueError, match=error):
        bind_admitted_state_prior_node_context(
            batch=batch,
            config=config,
            admission=_admitted_fixture(),
            node_keys=node_keys,
            base_context_feature_names=["x", "y"],
            state_prior_feature_names=feature_names,
            state_prior_values=values,
            context_artifact_sha256="a" * 64,
        )


def test_state_prior_controls_change_only_the_appended_prior_channels():
    batch, config = _dam_gk_batch_and_config()
    binding = bind_admitted_state_prior_node_context(
        batch=batch,
        config=config,
        admission=_admitted_fixture(),
        node_keys=["node-a", "node-b", "node-c"],
        base_context_feature_names=["x", "y"],
        state_prior_feature_names=["fixture_state"],
        state_prior_values=torch.tensor([[0.15], [0.35], [0.75]]),
        context_artifact_sha256="a" * 64,
    )

    zero = with_state_prior_context_control(binding, mode="zero", seed=11)
    shuffled = with_state_prior_context_control(binding, mode="shuffle_nodes", seed=11)

    assert torch.count_nonzero(zero.batch.node_context[:, 2:]) == 0
    assert not torch.equal(shuffled.batch.node_context[:, 2:], binding.batch.node_context[:, 2:])
    for controlled in (zero, shuffled):
        verify_dam_gk_state_prior_context_binding(controlled)
        assert torch.equal(controlled.batch.node_context[:, :2], batch.node_context)
        assert torch.equal(controlled.batch.node_action, batch.node_action)
        assert torch.equal(controlled.batch.edge_index, batch.edge_index)
        assert torch.equal(controlled.batch.edge_features, batch.edge_features)
        assert torch.equal(controlled.batch.edge_types, batch.edge_types)


def test_binding_verifier_rejects_forged_tensor_digest():
    batch, config = _dam_gk_batch_and_config()
    binding = bind_admitted_state_prior_node_context(
        batch=batch,
        config=config,
        admission=_admitted_fixture(),
        node_keys=["node-a", "node-b", "node-c"],
        base_context_feature_names=["x", "y"],
        state_prior_feature_names=["fixture_state"],
        state_prior_values=torch.tensor([[0.15], [0.35], [0.75]]),
        context_artifact_sha256="a" * 64,
    )

    with pytest.raises(ValueError, match="context_digest_mismatch"):
        verify_dam_gk_state_prior_context_binding(replace(binding, context_values_sha256="0" * 64))

    tampered_admission = copy.deepcopy(dict(binding.admission))
    tampered_admission["action_conditioned_dynamics_claim"] = True
    with pytest.raises(ValueError, match="binding_admission_invalid"):
        verify_dam_gk_state_prior_context_binding(replace(binding, admission=tampered_admission))

    with pytest.raises(ValueError, match="admission_metadata_mismatch"):
        verify_dam_gk_state_prior_context_binding(
            replace(binding, context_artifact_sha256="c" * 64)
        )

    tampered_action = binding.batch.node_action.clone()
    tampered_action[0, 0] = 0.0
    with pytest.raises(ValueError, match="fixed_inputs_digest_mismatch"):
        verify_dam_gk_state_prior_context_binding(
            replace(binding, batch=replace(binding.batch, node_action=tampered_action))
        )


def _ready_benchmark() -> dict:
    return {
        "schema": UWM_GEOSPATIAL_STATE_PRIOR_BENCHMARK_SCHEMA,
        "version": "0.1",
        "benchmark_id": "observed-ready-state-prior-fixture",
        "created_at": "2026-08-04T14:55:00Z",
        "source_evidence_kind": "observed_holdout",
        "evidence_refs": ["fixture://observed-holdout"],
        "geometry_routes": {
            "raster": {"geometry_type": "raster"},
            "admin": {"geometry_type": "polygon"},
            "graph_object": {"geometry_type": "network"},
        },
        "split_results": {split: {"leakage_audit": {"passed": True}} for split in REQUIRED_SPLITS},
        "aggregate_results": {},
        "dynamic_context": None,
        "dynamic_context_audit": {"declared": False},
        "uncertainty_calibration": {
            "method": "split_conformal_absolute_residual",
            "confidence_level": 0.9,
            "calibration_count": 30,
            "holdout_count": 30,
            "coverage_gate_passed": True,
        },
        "readiness_gates": {
            "three_native_geometry_routes_present": True,
            "strict_holdout_leakage_audits_passed": True,
            "candidate_beats_required_baselines_on_every_split": True,
            "geometry_shuffle_negative_controls_passed": True,
            "dynamic_context_ablation_gate_passed": True,
            "dynamic_context_sample_support_gate_passed": True,
            "split_conformal_coverage_passed": True,
            "observed_holdout_evidence_present": True,
        },
        "remaining_gates": [],
        "geospatial_state_prior_benchmark_ready": True,
        "supported_claim": ("multi_geometry_state_reconstruction_advantage_under_strict_holdout"),
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "policy_causal_effect_claim": False,
        "action_conditioned_dynamics_claim": False,
        "general_geospatial_world_model_validation_claim": False,
    }


def _state_prior_artifact(benchmark: dict) -> dict:
    benchmark_id = benchmark["benchmark_id"]
    evidence_refs = [
        "fixture://observed-holdout",
        "fixture://model-parameters",
        "fixture://split-conformal-calibration",
    ]
    confidence_level = benchmark["uncertainty_calibration"]["confidence_level"]
    return {
        "schema": STATE_PRIOR_ARTIFACT_SCHEMA,
        "version": "0.1",
        "state_prior_id": "fixture-calibrated-state-prior",
        "benchmark_id": benchmark_id,
        "context_ref": "fixture://state-prior-context",
        "context_sha256": "a" * 64,
        "source_evidence_kind": "observed_holdout",
        "derivation_kind": "observed_holdout_state_reconstruction",
        "support_level": "learned_calibrated",
        "state_variables": ["fixture_state"],
        "evidence_refs": evidence_refs,
        "provenance": {
            "model_id": "fixture-multi-geometry-prior",
            "model_version": "0.1",
            "parameter_ref": "fixture://model-parameters",
            "evidence_refs": [
                "fixture://observed-holdout",
                "fixture://model-parameters",
            ],
        },
        "geometry_coverage": {
            "routes": list(REQUIRED_GEOMETRY_ROUTES),
            "coverage_scope": "benchmark_geometry_routes",
        },
        "uncertainty": {
            "calibrated": True,
            "representation": "two_sided_prediction_interval",
            "confidence_level": confidence_level,
        },
        "calibration": {
            "method": benchmark["uncertainty_calibration"]["method"],
            "benchmark_id": benchmark_id,
            "holdout_validated": True,
            "confidence_level": confidence_level,
            "evidence_refs": ["fixture://split-conformal-calibration"],
        },
        "target_leakage_audit": {
            "passed": True,
            "uses_target_values": False,
            "holdout_membership_used_for_fit": False,
        },
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "policy_causal_effect_claim": False,
        "action_conditioned_dynamics_claim": False,
        "general_geospatial_world_model_validation_claim": False,
        "empirical_policy_effect_claim": False,
    }


def _admitted_fixture() -> dict:
    benchmark = _ready_benchmark()
    return build_state_prior_admission(
        benchmark=benchmark,
        state_prior_artifact=_state_prior_artifact(benchmark),
        admission_id="dam-gk-admitted-state-prior-fixture",
        created_at="2026-08-04T15:30:00Z",
    )


def _dam_gk_batch_and_config() -> tuple[DAMGKBatch, DAMGKConfig]:
    config = DAMGKConfig(
        node_state_dim=2,
        action_dim=1,
        edge_feature_dim=1,
        relation_type_count=1,
        context_dim=2,
        horizon=2,
    )
    node_context = torch.tensor([[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]], dtype=torch.float32)
    batch = DAMGKBatch(
        node_state=torch.tensor([[1.0, 0.0], [0.7, 0.3], [0.2, 0.8]], dtype=torch.float32),
        node_action=torch.tensor([[1.0], [0.0], [0.0]], dtype=torch.float32),
        edge_index=torch.tensor([[0, 1], [1, 2]], dtype=torch.long),
        edge_features=torch.tensor([[0.8], [0.6]], dtype=torch.float32),
        edge_types=torch.zeros(2, dtype=torch.long),
        node_context=node_context,
        node_context_by_step=node_context[:, None, :].expand(-1, 2, -1).clone(),
        edge_valid_mask=torch.ones(2, dtype=torch.bool),
    )
    batch.validate(config)
    return batch, config
