import json
import importlib.util
from dataclasses import replace
from pathlib import Path

import torch

from data_agent.uwm.dam_geospatial_kernel import (
    DAMGKBatch,
    DAMGKConfig,
    DynamicActionConditionedMultiscaleKernel,
    TWMLandTransitionModel,
    build_dam_gk_experiment_contract,
    build_chongqing_dam_gk_graph,
    build_twm_dynamic_world_transition,
    build_twm_dynamic_world_sequence,
    TWM_SEQUENCE_CONTEXT_DIM,
    dam_gk_objective,
    multiscale_consistency_loss,
    permute_coordinate_context,
    permute_edge_geometry,
    rewire_edge_targets,
    generate_controlled_sample,
    shuffle_action_assignments,
    shuffle_relation_types,
    validate_dam_gk_experiment_contract,
)
from data_agent.uwm.dam_geospatial_kernel.twm_adapter import (
    DRIVER_TRANSFORM_SCHEMA,
    TERRAIN_SIMILARITY_MAX_GRID_STEPS,
    TWM_REGION_CONTEXT_DIM,
    _build_region_descriptor,
    _transform_physical_drivers,
    _valid_continuous,
)
from data_agent.uwm.dam_geospatial_kernel.twm_benchmark import (
    _grouped_permutation,
    _stack_transitions,
)


ROOT = Path(__file__).resolve().parents[1]
CHONGQING_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"


def _load_summary_module():
    path = ROOT / "scripts/summarize_dam_gk_twm_runs.py"
    spec = importlib.util.spec_from_file_location("summarize_dam_gk_twm_runs", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_cross_validation_module():
    path = ROOT / "scripts/run_dam_gk_twm_region_cross_validation.py"
    spec = importlib.util.spec_from_file_location(
        "run_dam_gk_twm_region_cross_validation", path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _config() -> DAMGKConfig:
    return DAMGKConfig(
        node_state_dim=4,
        action_dim=3,
        edge_feature_dim=2,
        relation_type_count=3,
        context_dim=2,
        hidden_dim=16,
        horizon=3,
    )


def _batch(action_type: int = 0, *, mask_last_edge: bool = False) -> DAMGKBatch:
    node_state = torch.tensor(
        [
            [0.8, 0.2, 0.4, 0.1],
            [0.7, 0.3, 0.5, 0.2],
            [0.2, 0.9, 0.1, 0.8],
            [0.1, 0.8, 0.2, 0.7],
        ],
        dtype=torch.float32,
    )
    action = torch.zeros((4, 3), dtype=torch.float32)
    action[0, action_type] = 1.0
    return DAMGKBatch(
        node_state=node_state,
        node_action=action,
        node_context=torch.tensor(
            [[0.1, 0.2], [0.2, 0.3], [0.7, 0.8], [0.8, 0.9]]
        ),
        edge_index=torch.tensor(
            [[0, 0, 1, 2, 3], [1, 2, 2, 3, 0]], dtype=torch.long
        ),
        edge_features=torch.tensor(
            [[1.0, 0.1], [0.2, 0.8], [0.6, 0.4], [0.9, 0.2], [0.3, 0.7]],
            dtype=torch.float32,
        ),
        edge_types=torch.tensor([0, 1, 2, 0, 1], dtype=torch.long),
        edge_valid_mask=torch.tensor(
            [1, 1, 1, 1, 0 if mask_last_edge else 1], dtype=torch.bool
        ),
    )


def test_dam_gk_outputs_action_conditioned_lagged_probabilistic_dynamics():
    torch.manual_seed(7)
    model = DynamicActionConditionedMultiscaleKernel(_config())
    output_a = model(_batch(action_type=0))
    output_b = model(_batch(action_type=1))

    assert output_a.state_delta_mean.shape == (4, 3, 4)
    assert output_a.state_delta_scale.shape == (4, 3, 4)
    assert output_a.propagated_state.shape == (4, 3, 16)
    assert output_a.transition_latent.shape == (4, 3, 48)
    assert output_a.relation_channel_weights.shape == (4, 3, 3)
    assert output_a.rolled_state.shape == (4, 3, 4)
    assert output_a.predicted_state.shape == (4, 3, 4)
    assert output_a.edge_gate_by_step.shape == (5, 3)
    assert output_a.topology_probability_by_step.shape == (5, 3)
    assert output_a.transition_destination_logits.shape == (4, 3, 4)
    assert torch.all(output_a.state_delta_scale > 0)
    assert torch.allclose(output_a.lag_distribution.sum(dim=1), torch.ones(5))
    assert not torch.allclose(output_a.effective_edge_gate, output_b.effective_edge_gate)
    assert not torch.allclose(output_a.state_delta_mean, output_b.state_delta_mean)
    assert not torch.allclose(
        output_a.edge_gate_by_step[:, 0], output_a.edge_gate_by_step[:, -1]
    )


def test_dam_gk_writes_back_only_mutable_simplex_state_and_recomputes_topology():
    torch.manual_seed(17)
    config = DAMGKConfig(
        node_state_dim=12,
        action_dim=1,
        edge_feature_dim=2,
        relation_type_count=3,
        context_dim=2,
        hidden_dim=16,
        horizon=3,
        state_output_dim=9,
        mutable_state_dim=9,
        state_writeback_mode="simplex_additive",
    )
    base = _batch()
    land_state = torch.nn.functional.one_hot(
        torch.tensor([0, 1, 2, 3]), num_classes=9
    ).float()
    drivers = torch.tensor(
        [[0.2, 0.3, 0.4], [0.4, 0.5, 0.6], [0.6, 0.7, 0.8], [0.8, 0.9, 1.0]]
    )
    batch = replace(
        base,
        node_state=torch.cat([land_state, drivers], dim=1),
        node_action=torch.zeros((4, 1)),
    )

    output = DynamicActionConditionedMultiscaleKernel(config)(batch)

    assert output.rolled_state.shape == (4, 3, 12)
    assert not torch.allclose(output.rolled_state[:, 0, :9], land_state)
    assert torch.allclose(
        output.rolled_state[:, :, 9:],
        drivers[:, None, :].expand(-1, config.horizon, -1),
    )
    assert torch.all(output.rolled_state[:, :, :9] >= 0.0)
    assert torch.allclose(
        output.rolled_state[:, :, :9].sum(dim=-1),
        torch.ones((4, config.horizon)),
    )
    assert not torch.allclose(
        output.edge_gate_by_step[:, 0], output.edge_gate_by_step[:, 1]
    )
    assert not torch.allclose(
        output.topology_probability_by_step[:, 0],
        output.topology_probability_by_step[:, 1],
    )


def test_dam_gk_no_writeback_ablation_freezes_recursive_world_state():
    torch.manual_seed(17)
    writeback_config = replace(_config(), state_writeback_mode="additive")
    frozen_config = replace(writeback_config, state_writeback_mode="none")
    writeback_model = DynamicActionConditionedMultiscaleKernel(writeback_config)
    frozen_model = DynamicActionConditionedMultiscaleKernel(frozen_config)
    frozen_model.load_state_dict(writeback_model.state_dict())

    writeback_output = writeback_model(_batch())
    frozen_output = frozen_model(_batch())

    assert torch.allclose(
        frozen_output.rolled_state,
        _batch().node_state[:, None, :].expand(-1, frozen_config.horizon, -1),
    )
    assert torch.allclose(
        frozen_output.edge_gate_by_step[:, 0],
        frozen_output.edge_gate_by_step[:, -1],
    )
    assert not torch.allclose(
        writeback_output.rolled_state[:, -1], frozen_output.rolled_state[:, -1]
    )


def test_dam_gk_teacher_forcing_uses_observed_intermediate_world_states():
    config = replace(_config(), state_writeback_mode="teacher_forced")
    base = _batch()
    teacher_states = torch.stack(
        [base.node_state + 0.1, base.node_state + 0.2, base.node_state + 0.3], dim=1
    )
    batch = replace(base, teacher_state_by_step=teacher_states)

    output = DynamicActionConditionedMultiscaleKernel(config)(batch)

    assert torch.allclose(output.rolled_state, teacher_states)
    assert not torch.allclose(output.predicted_state, teacher_states)
    assert not torch.allclose(
        output.edge_gate_by_step[:, 0], output.edge_gate_by_step[:, 1]
    )


def test_twm_transition_head_emits_each_recursive_horizon():
    config = DAMGKConfig(
        node_state_dim=12,
        action_dim=1,
        edge_feature_dim=2,
        relation_type_count=3,
        context_dim=2,
        hidden_dim=16,
        horizon=3,
        state_output_dim=9,
        mutable_state_dim=9,
        state_writeback_mode="simplex_additive",
    )
    base = _batch()
    batch = replace(
        base,
        node_state=torch.cat(
            [
                torch.nn.functional.one_hot(
                    torch.tensor([0, 1, 2, 3]), num_classes=9
                ).float(),
                torch.full((4, 3), 0.5),
            ],
            dim=1,
        ),
        node_action=torch.zeros((4, 1)),
    )

    output = TWMLandTransitionModel(config)(batch)

    assert output.change_logit.shape == (4, 3)
    assert output.destination_logits.shape == (4, 3, 9)
    assert output.coarse_state_logits.shape == (4, 3, 9)


def test_twm_categorical_transition_conserves_probability_and_persistence_gate():
    config = DAMGKConfig(
        node_state_dim=12,
        action_dim=1,
        edge_feature_dim=2,
        relation_type_count=3,
        context_dim=2,
        hidden_dim=16,
        horizon=3,
        state_output_dim=9,
        mutable_state_dim=9,
        state_writeback_mode="categorical_mixture",
    )
    base = _batch()
    land_state = torch.nn.functional.one_hot(
        torch.tensor([0, 1, 2, 3]), num_classes=9
    ).float()
    batch = replace(
        base,
        node_state=torch.cat([land_state, torch.full((4, 3), 0.5)], dim=1),
        node_action=torch.zeros((4, 1)),
    )

    output = TWMLandTransitionModel(config)(batch)

    assert output.kernel_output.transition_change_logit.shape == (4, 3)
    assert output.kernel_output.transition_destination_logits.shape == (4, 3, 9)
    assert torch.allclose(
        output.kernel_output.predicted_state[:, :, :9].sum(dim=-1),
        torch.ones((4, 3)),
    )
    assert torch.all(output.kernel_output.predicted_state[:, :, :9] >= 0.0)
    assert torch.allclose(
        torch.softmax(output.destination_logits, dim=-1).sum(dim=-1),
        torch.ones((4, 3)),
    )
    change_probability = torch.sigmoid(output.change_logit).unsqueeze(-1)
    conditional_destination = torch.softmax(output.destination_logits, dim=-1)
    current_state = batch.node_state[:, :9]
    reconstructed_steps = []
    for step_index in range(config.horizon):
        current_state = (
            (1.0 - change_probability[:, step_index]) * current_state
            + change_probability[:, step_index]
            * conditional_destination[:, step_index]
        )
        reconstructed_steps.append(current_state)
    reconstructed_state = torch.stack(reconstructed_steps, dim=1)
    assert torch.allclose(
        reconstructed_state, output.kernel_output.predicted_state[:, :, :9]
    )


def test_twm_sequence_uses_one_geographic_node_set_and_stepwise_time_context():
    region_id = "上海市_浦东新区_祝桥镇"
    sequence = build_twm_dynamic_world_sequence(
        region_dir=ROOT / "data/twm_public_landcover/gee_dynamic_world" / region_id,
        region_id=region_id,
        years=(2020, 2021, 2022, 2023),
        sample_stride=24,
        coarse_block_size=3,
        terrain_similarity_scope="local_spatial_window",
    )

    node_count = sequence.batch.node_state.shape[0]
    assert sequence.target_delta.shape == (node_count, 3, 9)
    assert sequence.target_state.shape == (node_count, 3, 9)
    assert sequence.future_class.shape[1] == 3
    assert sequence.batch.node_context_by_step.shape == (
        node_count,
        3,
        TWM_SEQUENCE_CONTEXT_DIM,
    )
    assert sequence.batch.teacher_state_by_step.shape == (node_count, 3, 12)
    assert torch.allclose(
        sequence.batch.teacher_state_by_step[:, :, :9], sequence.target_state
    )
    assert torch.allclose(sequence.target_state.sum(dim=-1), torch.ones((node_count, 3)))
    assert torch.all(
        sequence.batch.node_context_by_step[:, 1:, 3]
        > sequence.batch.node_context_by_step[:, :-1, 3]
    )
    assert sequence.metadata["consistent_node_set"] is True
    temporal_metadata = sequence.metadata["temporal_history_context"]
    assert temporal_metadata["uses_future_target_state"] is False
    assert temporal_metadata["history_years"] == list(range(2017, 2024))
    temporal_features = sequence.batch.node_context_by_step[:, :, 4:]
    assert torch.all(temporal_features >= 0.0)
    assert torch.all(temporal_features <= 1.0)
    assert sequence.metadata["claim_boundary"]["policy_effect_claim"] is False


def test_dam_gk_masks_geographically_invalid_candidate_edges():
    model = DynamicActionConditionedMultiscaleKernel(_config())
    output = model(_batch(mask_last_edge=True))

    assert output.effective_edge_gate[-1].item() == 0.0
    assert output.topology_rewrite_probability[-1].item() == 0.0


def test_dam_gk_can_normalize_propagation_by_effective_geographic_mass():
    config = _config()
    normalized = DynamicActionConditionedMultiscaleKernel(
        replace(config, normalize_propagation_mass=True)
    )
    normalized.load_state_dict(
        DynamicActionConditionedMultiscaleKernel(config).state_dict()
    )

    output = normalized(_batch())

    assert torch.isfinite(output.propagated_state).all()


def test_dam_gk_relation_channels_are_state_dependent_and_normalized():
    model = DynamicActionConditionedMultiscaleKernel(
        replace(_config(), use_relation_channel_fusion=True)
    )

    output = model(_batch())

    assert torch.allclose(
        output.relation_channel_weights.sum(dim=-1),
        torch.ones((4, 3)),
    )
    assert not torch.allclose(
        output.relation_channel_weights[0],
        output.relation_channel_weights[1],
    )
    loss = output.state_delta_mean.square().mean()
    loss.backward()
    assert model.relation_channel_projection[0].weight.grad is not None
    assert model.relation_channel_residual_gate[0].weight.grad is not None


def test_dam_gk_can_mask_optional_edge_geometry_without_changing_contract():
    torch.manual_seed(93)
    config = replace(
        _config(),
        use_edge_geometry=False,
        edge_geometry_start_index=1,
    )
    model = DynamicActionConditionedMultiscaleKernel(config)
    batch = _batch()
    changed_geometry = replace(
        batch,
        edge_features=torch.cat(
            [batch.edge_features[:, :1], batch.edge_features[:, 1:] + 100.0],
            dim=1,
        ),
    )

    output_a = model(batch)
    output_b = model(changed_geometry)

    assert torch.allclose(output_a.state_delta_mean, output_b.state_delta_mean)


def test_multiscale_consistency_uses_explicit_spatial_aggregation():
    fine = torch.tensor(
        [
            [[1.0], [2.0]],
            [[3.0], [4.0]],
            [[10.0], [12.0]],
            [[14.0], [16.0]],
        ]
    )
    mapping = torch.tensor([[1.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 1.0]])
    coarse = torch.tensor([[[2.0], [3.0]], [[12.0], [14.0]]])

    assert multiscale_consistency_loss(fine, coarse, mapping).item() == 0.0
    assert multiscale_consistency_loss(fine, coarse + 1.0, mapping).item() > 0.0


def test_dam_gk_objective_backpropagates_through_relation_and_topology_heads():
    torch.manual_seed(11)
    model = DynamicActionConditionedMultiscaleKernel(_config())
    output = model(_batch())
    target = torch.zeros_like(output.state_delta_mean)
    mapping = torch.tensor([[1.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 1.0]])
    coarse = torch.zeros((2, 3, 4))
    losses = dam_gk_objective(
        output,
        target,
        coarse_prediction=coarse,
        fine_to_coarse=mapping,
        prior_edge_probability=torch.ones(5),
        scale_weight=0.2,
        sparsity_weight=0.01,
        topology_weight=0.1,
    )
    losses["total"].backward()

    assert model.relation_gate[0].weight.grad is not None
    assert model.topology_rewrite_head[0].weight.grad is not None
    assert model.transition_mean[0].weight.grad is not None


def test_dam_gk_negative_controls_break_claimed_geographic_or_action_semantics():
    batch = _batch()
    action_control = shuffle_action_assignments(batch, torch.tensor([1, 0, 2, 3]))
    relation_control = shuffle_relation_types(batch, torch.tensor([4, 3, 2, 1, 0]))
    rewire_control = rewire_edge_targets(batch, torch.tensor([4, 3, 2, 1, 0]))
    coordinate_control = permute_coordinate_context(
        batch, torch.tensor([3, 2, 1, 0])
    )
    geometry_control = permute_edge_geometry(
        batch,
        torch.tensor([4, 3, 2, 1, 0]),
        geometry_start_index=1,
    )

    assert not torch.equal(action_control.node_action, batch.node_action)
    assert not torch.equal(relation_control.edge_types, batch.edge_types)
    assert not torch.equal(rewire_control.edge_index[1], batch.edge_index[1])
    assert torch.equal(rewire_control.edge_index[0], batch.edge_index[0])
    assert not torch.equal(
        coordinate_control.node_context[:, :2], batch.node_context[:, :2]
    )
    assert torch.equal(
        coordinate_control.node_context[:, 2:], batch.node_context[:, 2:]
    )
    assert torch.equal(geometry_control.edge_features[:, :1], batch.edge_features[:, :1])
    assert not torch.equal(geometry_control.edge_features[:, 1:], batch.edge_features[:, 1:])


def test_dam_gk_experiment_contract_blocks_policy_causal_overclaim():
    contract = build_dam_gk_experiment_contract()

    assert validate_dam_gk_experiment_contract(contract) == {
        "valid": True,
        "errors": [],
    }
    assert "identified_policy_causal_effect" in contract["blocked_claims"]
    assert "action_assignment_shuffle" in contract["required_negative_controls"]


def test_controlled_geographic_dynamics_contains_action_specific_mechanism_truth():
    sample_a = generate_controlled_sample(grid_size=4, seed=101)
    sample_b = generate_controlled_sample(grid_size=4, seed=102)

    assert sample_a.target_delta.shape == (16, 3, 3)
    assert sample_a.target_effective_gate.shape == sample_a.batch.edge_types.shape
    assert torch.allclose(sample_a.target_lag_distribution.sum(dim=1), torch.ones_like(sample_a.target_effective_gate))
    assert torch.count_nonzero(sample_a.target_effective_gate) > 0
    assert torch.count_nonzero(sample_a.affected_node_mask) > 0
    assert not torch.equal(sample_a.batch.node_action, sample_b.batch.node_action)


def test_chongqing_adapter_builds_real_multirelational_multiscale_graph():
    graph = build_chongqing_dam_gk_graph(
        admin_livability_panel=_read_json(
            CHONGQING_ROOT
            / "admin_livability_target_full_admin_graph_2024_07_2026_07_08/uwm_admin_livability_target_full_admin_graph_panel.json"
        ),
        admin_spatial_graph=_read_json(
            CHONGQING_ROOT
            / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
        ),
        mobility_graph=_read_json(
            CHONGQING_ROOT
            / "full_admin_mobility_graph_2026_07_10/full_admin_mobility_graph.json"
        ),
        similarity_kernel=_read_json(
            CHONGQING_ROOT
            / "geographic_similarity_kernel_2026_07_08/uwm_geographic_similarity_kernel.json"
        ),
        action={
            "action_type": "add_community_service",
            "target_units": ["涪陵区|蔺市镇|498"],
            "intensity": 0.8,
        },
    )

    assert graph.fine_node_count == 1017
    assert graph.coarse_node_count > 20
    assert graph.batch.node_state.shape == (
        graph.fine_node_count + graph.coarse_node_count,
        10,
    )
    assert graph.batch.node_context.shape[1] == 4
    assert graph.batch.edge_features.shape[1] == 6
    assert set(graph.batch.edge_types.tolist()) == {0, 1, 2, 3, 4}
    assert graph.fine_to_coarse.shape == (graph.coarse_node_count, 1017)
    assert torch.all(graph.fine_to_coarse.sum(dim=0) == 1.0)
    target_index = graph.node_ids.index("涪陵区|蔺市镇|498")
    assert graph.batch.node_action[target_index, 2].item() == 1.0
    assert graph.metadata["claim_boundary"]["observed_policy_effect_claim"] is False


def test_twm_adapter_builds_observed_cross_year_multiscale_transition_without_fake_action():
    region_id = "上海市_浦东新区_祝桥镇"
    transition = build_twm_dynamic_world_transition(
        region_dir=ROOT / "data/twm_public_landcover/gee_dynamic_world" / region_id,
        region_id=region_id,
        current_year=2021,
        next_year=2022,
        sample_stride=12,
        coarse_block_size=3,
        terrain_similarity_scope="local_spatial_window",
    )

    assert transition.batch.node_state.shape[1] == 12
    assert transition.target_delta.shape[1:] == (1, 9)
    assert transition.batch.edge_features.shape[1] == 7
    assert transition.metadata["edge_geometry"]["features"] == [
        "relative_dx",
        "relative_dy",
        "relative_distance",
    ]
    assert transition.metadata["edge_geometry"]["unit"] == "sampled_grid_step"
    geometry = transition.batch.edge_features[:, -3:]
    assert torch.all(geometry[:, 2] >= 0.0)
    assert torch.allclose(
        geometry[:, 2], torch.linalg.vector_norm(geometry[:, :2], dim=1)
    )
    adjacency_geometry = geometry[transition.batch.edge_types == 0]
    assert torch.allclose(
        adjacency_geometry[:, 2], torch.ones_like(adjacency_geometry[:, 2])
    )
    assert set(transition.batch.edge_types.tolist()) == {0, 1, 2, 3}
    assert torch.count_nonzero(transition.batch.node_action) == 0
    assert torch.all(transition.fine_to_coarse.sum(dim=0) == 1.0)
    assert transition.metadata["observed_transition"] is True
    assert transition.metadata["observed_action"] is False
    assert transition.metadata["claim_boundary"]["action_conditioning_claim"] is False
    assert transition.metadata["driver_transform"] == DRIVER_TRANSFORM_SCHEMA
    assert transition.batch.region_context.shape[1] == TWM_REGION_CONTEXT_DIM
    assert transition.metadata["region_context"]["uses_next_year_label"] is False
    assert torch.allclose(
        transition.batch.region_context,
        transition.batch.region_context[0].unsqueeze(0).repeat(
            transition.batch.node_state.shape[0], 1
        ),
    )
    assert torch.all(transition.batch.node_state[:, 9:] >= 0.0)
    assert torch.all(transition.batch.node_state[:, 9:] <= 1.0)
    assert torch.all(transition.batch.node_context[:, :2] >= -1.0)
    assert torch.all(transition.batch.node_context[:, :2] <= 1.0)
    assert transition.metadata["terrain_similarity_constraint"] == {
        "scope": "local_spatial_window",
        "maximum_grid_steps": TERRAIN_SIMILARITY_MAX_GRID_STEPS,
        "maximum_neighbors": 2,
    }

    fine_count = transition.current_class.numel()
    relation_mask = transition.batch.edge_types == 1
    relation_edges = transition.batch.edge_index[:, relation_mask]
    assert torch.all(relation_edges < fine_count)
    row_column = []
    for node_id in transition.node_ids[:fine_count]:
        _, row, column = node_id.rsplit("::", 2)
        row_column.append((int(row), int(column)))
    for source, target in relation_edges.t().tolist():
        row_distance = abs(row_column[source][0] - row_column[target][0])
        column_distance = abs(row_column[source][1] - row_column[target][1])
        assert row_distance <= 12 * TERRAIN_SIMILARITY_MAX_GRID_STEPS
        assert column_distance <= 12 * TERRAIN_SIMILARITY_MAX_GRID_STEPS


def test_twm_driver_transform_has_cross_region_physical_semantics():
    values = torch.tensor(
        [
            [0.0, 0.0, 0.0],
            [2000.0, 32.5, 10.0],
            [4000.0, 65.0, 320.0],
        ]
    )

    transformed = _transform_physical_drivers(values)

    assert transformed[0, 0].item() > 0.0
    assert torch.all(transformed[1] > transformed[0])
    assert torch.all(transformed[2] >= transformed[1])
    assert _valid_continuous(-32768.0, -32768.0) is False


def test_twm_region_descriptor_uses_current_state_and_physical_context_only():
    current = torch.nn.functional.one_hot(
        torch.tensor([0, 0, 1, 2]), num_classes=9
    ).float()
    drivers = torch.tensor(
        [[0.1, 0.2, 0.3], [0.2, 0.3, 0.4], [0.3, 0.4, 0.5], [0.4, 0.5, 0.6]]
    )
    coordinates = torch.tensor(
        [[0.5, 0.2], [0.6, 0.2], [0.5, 0.3], [0.6, 0.3]]
    )

    descriptor = _build_region_descriptor(
        current_one_hot=current,
        physical_drivers=drivers,
        normalized_coordinates=coordinates,
    )

    assert descriptor.shape == (TWM_REGION_CONTEXT_DIM,)
    assert torch.allclose(descriptor[:3], torch.tensor([0.5, 0.25, 0.25]))
    assert torch.isclose(descriptor.sum(), descriptor.sum())


def test_twm_multiseed_summary_accepts_pre_geographic_split_reports(tmp_path):
    module = _load_summary_module()
    reports = []
    for seed in (31, 47):
        report = {
            "seed": seed,
            "region_ids": ["region-a", "region-b"],
            "variant_metrics": {
                name: {"test": {"change_f1": 0.3}}
                for name in module.VARIANT_NAMES
            },
            "hypothesis_checks": {name: True for name in module.CHECK_NAMES},
        }
        path = tmp_path / f"{seed}.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        reports.append(path)

    summary = module.summarize(reports)

    assert summary["geographic_split"] == "same_regions_strict_future_year"
    assert summary["training_region_count"] == 2
    assert summary["test_region_ids"] == ["region-a", "region-b"]


def test_twm_round_robin_region_folds_cover_each_region_once():
    module = _load_cross_validation_module()
    region_ids = [f"region-{index}" for index in range(20)]

    folds = module.build_round_robin_folds(region_ids, 5)

    assert [len(fold) for fold in folds] == [4, 4, 4, 4, 4]
    assert {region for fold in folds for region in fold} == set(region_ids)


def test_twm_cross_validation_summary_requires_stable_all_run_claims():
    module = _load_cross_validation_module()
    reports = []
    for fold in (1, 2):
        for seed in (31, 47):
            checks = {name: True for name in module.CHECKS}
            if fold == 2 and seed == 47:
                checks["dynamic_topology_improves_change_f1"] = False
            reports.append(
                {
                    "cross_validation_fold": fold,
                    "seed": seed,
                    "test_region_ids": [f"region-{fold}"],
                    "variant_metrics": {
                        name: {"test": {"change_f1": 0.3}}
                        for name in module.VARIANTS
                    },
                    "hypothesis_checks": checks,
                }
            )

    summary = module.summarize_cross_validation(reports)

    assert summary["run_count"] == 4
    assert summary["each_region_tested_once_per_seed"] is True
    assert summary["claim_boundary"]["dynamic_topology_necessity_stable"] is False


def test_twm_grouped_permutation_never_crosses_region_components():
    groups = torch.tensor([0, 0, 0, 1, 1, 2, 2, 2])

    permutation = _grouped_permutation(
        groups, generator=torch.Generator().manual_seed(19)
    )

    assert torch.equal(groups[permutation], groups)
    assert not torch.equal(permutation, torch.arange(groups.numel()))


def test_twm_stacked_transition_builds_block_diagonal_fine_to_coarse_mapping():
    root = ROOT / "data/twm_public_landcover/gee_dynamic_world"
    transitions = []
    for region_id in ("上海市_浦东新区_祝桥镇", "北京市_密云县_石城镇"):
        transitions.append(
            build_twm_dynamic_world_transition(
                region_dir=root / region_id,
                region_id=region_id,
                current_year=2021,
                next_year=2022,
                sample_stride=24,
                coarse_block_size=3,
            )
        )

    stacked = _stack_transitions(transitions)

    assert stacked.fine_to_coarse.shape == (
        sum(row.fine_to_coarse.shape[0] for row in transitions),
        sum(row.fine_to_coarse.shape[1] for row in transitions),
    )
    assert torch.all(stacked.fine_to_coarse.sum(dim=0) == 1.0)
    first_coarse = transitions[0].fine_to_coarse.shape[0]
    first_fine = transitions[0].fine_to_coarse.shape[1]
    assert torch.count_nonzero(
        stacked.fine_to_coarse[:first_coarse, first_fine:]
    ).item() == 0
    assert torch.count_nonzero(
        stacked.fine_to_coarse[first_coarse:, :first_fine]
    ).item() == 0


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
