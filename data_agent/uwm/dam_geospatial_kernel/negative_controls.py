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


def _replace(batch: DAMGKBatch, **changes: torch.Tensor) -> DAMGKBatch:
    values = {
        "node_state": batch.node_state,
        "node_action": batch.node_action,
        "edge_index": batch.edge_index,
        "edge_features": batch.edge_features,
        "edge_types": batch.edge_types,
        "node_context": batch.node_context,
        "region_context": batch.region_context,
        "edge_valid_mask": batch.edge_valid_mask,
    }
    values.update(changes)
    return DAMGKBatch(**values)
