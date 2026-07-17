"""Research losses for DAM-GK."""

from __future__ import annotations

import torch
from torch.nn import functional as functional

from .contracts import DAMGKOutput


def gaussian_transition_nll(
    output: DAMGKOutput, target_delta: torch.Tensor
) -> torch.Tensor:
    if target_delta.shape != output.state_delta_mean.shape:
        raise ValueError("target_delta_shape_mismatch")
    variance = output.state_delta_scale.square()
    return 0.5 * (
        torch.log(variance) + (target_delta - output.state_delta_mean).square() / variance
    ).mean()


def multiscale_consistency_loss(
    fine_prediction: torch.Tensor,
    coarse_prediction: torch.Tensor,
    fine_to_coarse: torch.Tensor,
) -> torch.Tensor:
    """Compare explicit fine-to-coarse aggregation with coarse predictions."""

    if fine_prediction.ndim != 3 or coarse_prediction.ndim != 3:
        raise ValueError("predictions_must_be_node_horizon_feature")
    if fine_to_coarse.ndim != 2:
        raise ValueError("fine_to_coarse_must_be_matrix")
    if fine_to_coarse.shape != (coarse_prediction.shape[0], fine_prediction.shape[0]):
        raise ValueError("fine_to_coarse_shape_mismatch")
    row_mass = fine_to_coarse.sum(dim=1, keepdim=True).clamp_min(1e-8)
    normalized = fine_to_coarse / row_mass
    aggregated = torch.einsum("cf,fhd->chd", normalized, fine_prediction)
    return torch.mean(torch.abs(aggregated - coarse_prediction))


def edge_sparsity_loss(output: DAMGKOutput) -> torch.Tensor:
    return output.effective_edge_gate.mean()


def topology_stability_loss(
    output: DAMGKOutput, prior_edge_probability: torch.Tensor
) -> torch.Tensor:
    if prior_edge_probability.shape != output.topology_rewrite_probability.shape:
        raise ValueError("prior_edge_probability_shape_mismatch")
    return torch.mean(
        torch.abs(output.topology_rewrite_probability - prior_edge_probability)
    )


def dam_gk_objective(
    output: DAMGKOutput,
    target_delta: torch.Tensor,
    *,
    coarse_prediction: torch.Tensor | None = None,
    fine_to_coarse: torch.Tensor | None = None,
    prior_edge_probability: torch.Tensor | None = None,
    target_effective_gate: torch.Tensor | None = None,
    target_topology_probability: torch.Tensor | None = None,
    target_lag_distribution: torch.Tensor | None = None,
    scale_weight: float = 0.0,
    sparsity_weight: float = 0.0,
    topology_weight: float = 0.0,
    gate_supervision_weight: float = 0.0,
    topology_supervision_weight: float = 0.0,
    lag_supervision_weight: float = 0.0,
) -> dict[str, torch.Tensor]:
    transition = gaussian_transition_nll(output, target_delta)
    zero = transition.new_zeros(())
    scale = zero
    if coarse_prediction is not None or fine_to_coarse is not None:
        if coarse_prediction is None or fine_to_coarse is None:
            raise ValueError("coarse_prediction_and_mapping_must_be_provided_together")
        scale = multiscale_consistency_loss(
            output.state_delta_mean, coarse_prediction, fine_to_coarse
        )
    topology = zero
    if prior_edge_probability is not None:
        topology = topology_stability_loss(output, prior_edge_probability)
    sparsity = edge_sparsity_loss(output)
    gate_supervision = zero
    if target_effective_gate is not None:
        if target_effective_gate.shape != output.effective_edge_gate.shape:
            raise ValueError("target_effective_gate_shape_mismatch")
        gate_supervision = functional.binary_cross_entropy(
            output.effective_edge_gate.clamp(1e-6, 1.0 - 1e-6),
            target_effective_gate,
        )
    topology_supervision = zero
    if target_topology_probability is not None:
        if target_topology_probability.shape != output.topology_rewrite_probability.shape:
            raise ValueError("target_topology_probability_shape_mismatch")
        topology_supervision = functional.binary_cross_entropy(
            output.topology_rewrite_probability.clamp(1e-6, 1.0 - 1e-6),
            target_topology_probability,
        )
    lag_supervision = zero
    if target_lag_distribution is not None:
        if target_lag_distribution.shape != output.lag_distribution.shape:
            raise ValueError("target_lag_distribution_shape_mismatch")
        lag_supervision = -torch.mean(
            torch.sum(
                target_lag_distribution
                * torch.log(output.lag_distribution.clamp_min(1e-8)),
                dim=-1,
            )
        )
    total = (
        transition
        + scale_weight * scale
        + sparsity_weight * sparsity
        + topology_weight * topology
        + gate_supervision_weight * gate_supervision
        + topology_supervision_weight * topology_supervision
        + lag_supervision_weight * lag_supervision
    )
    return {
        "total": total,
        "transition_nll": transition,
        "multiscale_consistency": scale,
        "edge_sparsity": sparsity,
        "topology_stability": topology,
        "gate_supervision": gate_supervision,
        "topology_supervision": topology_supervision,
        "lag_supervision": lag_supervision,
    }
