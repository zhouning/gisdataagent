"""Geographic negative controls required by the DAM-GK research protocol."""

from __future__ import annotations

import torch

from .contracts import DAMGKBatch


def shuffle_action_assignments(batch: DAMGKBatch, permutation: torch.Tensor) -> DAMGKBatch:
    """Reassign actions across nodes while preserving the graph and state."""

    if permutation.dtype != torch.long or permutation.shape != (batch.node_state.shape[0],):
        raise ValueError("action_permutation_shape_mismatch")
    return _replace(batch, node_action=batch.node_action[permutation])


def shuffle_relation_types(batch: DAMGKBatch, permutation: torch.Tensor) -> DAMGKBatch:
    """Break relation semantics while preserving candidate edge endpoints."""

    if permutation.dtype != torch.long or permutation.shape != (batch.edge_types.shape[0],):
        raise ValueError("relation_permutation_shape_mismatch")
    return _replace(batch, edge_types=batch.edge_types[permutation])


def rewire_edge_targets(batch: DAMGKBatch, target_permutation: torch.Tensor) -> DAMGKBatch:
    """Destroy the geographic topology while retaining source-node frequency."""

    if target_permutation.dtype != torch.long or target_permutation.shape != (
        batch.edge_index.shape[1],
    ):
        raise ValueError("target_permutation_shape_mismatch")
    edge_index = batch.edge_index.clone()
    edge_index[1] = edge_index[1, target_permutation]
    return _replace(batch, edge_index=edge_index)


def permute_coordinate_context(
    batch: DAMGKBatch, permutation: torch.Tensor
) -> DAMGKBatch:
    """Destroy absolute spatial placement while preserving non-spatial context."""

    if batch.node_context is None or batch.node_context.shape[1] < 2:
        raise ValueError("coordinate_context_required")
    if permutation.dtype != torch.long or permutation.shape != (
        batch.node_state.shape[0],
    ):
        raise ValueError("coordinate_permutation_shape_mismatch")
    node_context = batch.node_context.clone()
    node_context[:, :2] = node_context[permutation, :2]
    return _replace(batch, node_context=node_context)


def permute_edge_geometry(
    batch: DAMGKBatch,
    permutation: torch.Tensor,
    *,
    geometry_start_index: int,
) -> DAMGKBatch:
    """Break relative geometry while preserving endpoints and other edge evidence."""

    edge_count = batch.edge_features.shape[0]
    if permutation.dtype != torch.long or permutation.shape != (edge_count,):
        raise ValueError("edge_geometry_permutation_shape_mismatch")
    if geometry_start_index < 0 or geometry_start_index >= batch.edge_features.shape[1]:
        raise ValueError("edge_geometry_start_index_out_of_range")
    edge_features = batch.edge_features.clone()
    edge_features[:, geometry_start_index:] = batch.edge_features[
        permutation, geometry_start_index:
    ]
    return _replace(batch, edge_features=edge_features)


def zero_temporal_context_features(
    batch: DAMGKBatch, feature_indices: torch.Tensor
) -> DAMGKBatch:
    """Remove selected forcing channels without changing model dimensions."""

    indices = _validate_context_feature_indices(batch, feature_indices)
    node_context = (
        None if batch.node_context is None else batch.node_context.clone()
    )
    context_by_step = (
        None
        if batch.node_context_by_step is None
        else batch.node_context_by_step.clone()
    )
    if node_context is not None:
        node_context[:, indices] = 0.0
    if context_by_step is not None:
        context_by_step[:, :, indices] = 0.0
        node_context = context_by_step[:, 0]
    return _replace(
        batch,
        node_context=node_context,
        node_context_by_step=context_by_step,
    )


def permute_temporal_context_features(
    batch: DAMGKBatch,
    node_permutation: torch.Tensor,
    feature_indices: torch.Tensor,
) -> DAMGKBatch:
    """Break forcing alignment while preserving other state and context."""

    node_count = batch.node_state.shape[0]
    if node_permutation.dtype != torch.long or node_permutation.shape != (
        node_count,
    ):
        raise ValueError("temporal_context_node_permutation_shape_mismatch")
    if sorted(node_permutation.tolist()) != list(range(node_count)):
        raise ValueError("temporal_context_node_permutation_must_be_bijective")
    indices = _validate_context_feature_indices(batch, feature_indices)
    node_context = (
        None if batch.node_context is None else batch.node_context.clone()
    )
    context_by_step = (
        None
        if batch.node_context_by_step is None
        else batch.node_context_by_step.clone()
    )
    if node_context is not None:
        node_context[:, indices] = batch.node_context[
            node_permutation[:, None], indices[None, :]
        ]
    if context_by_step is not None:
        context_by_step[:, :, indices] = batch.node_context_by_step[
            node_permutation[:, None, None],
            torch.arange(batch.node_context_by_step.shape[1])[None, :, None],
            indices[None, None, :],
        ]
        node_context = context_by_step[:, 0]
    return _replace(
        batch,
        node_context=node_context,
        node_context_by_step=context_by_step,
    )


def _validate_context_feature_indices(
    batch: DAMGKBatch, feature_indices: torch.Tensor
) -> torch.Tensor:
    context = (
        batch.node_context_by_step
        if batch.node_context_by_step is not None
        else batch.node_context
    )
    if context is None:
        raise ValueError("temporal_context_required")
    if feature_indices.dtype != torch.long or feature_indices.ndim != 1:
        raise ValueError("temporal_context_feature_indices_must_be_long_vector")
    if feature_indices.numel() == 0:
        raise ValueError("temporal_context_feature_indices_required")
    if len(set(feature_indices.tolist())) != feature_indices.numel():
        raise ValueError("temporal_context_feature_indices_must_be_unique")
    context_dim = context.shape[-1]
    if feature_indices.min() < 0 or feature_indices.max() >= context_dim:
        raise ValueError("temporal_context_feature_index_out_of_range")
    return feature_indices


def _replace(
    batch: DAMGKBatch, **changes: torch.Tensor | None
) -> DAMGKBatch:
    values = {
        "node_state": batch.node_state,
        "node_action": batch.node_action,
        "edge_index": batch.edge_index,
        "edge_features": batch.edge_features,
        "edge_types": batch.edge_types,
        "node_context": batch.node_context,
        "node_context_by_step": batch.node_context_by_step,
        "teacher_state_by_step": batch.teacher_state_by_step,
        "region_context": batch.region_context,
        "edge_valid_mask": batch.edge_valid_mask,
    }
    values.update(changes)
    return DAMGKBatch(**values)
