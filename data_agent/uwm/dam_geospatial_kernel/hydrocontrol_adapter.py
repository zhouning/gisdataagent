"""HydroControl hourly data adapter for real-action DAM-GK experiments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd
import torch

from .contracts import DAMGKBatch


HYDROCONTROL_DAM_GK_ADAPTER_SCHEMA = (
    "gwm.dam_gk.hydrocontrol_hourly_adapter.v1"
)
HYDROCONTROL_ELIGIBLE_HORIZONS = (3, 6, 12, 24)
HYDROCONTROL_SIGNAL_LOG_SCALE = 10.0


@dataclass(frozen=True)
class HydroControlDAMGKDataset:
    schema: str
    horizon_hours: int
    batch: DAMGKBatch
    target_node_index: torch.Tensor
    target_flow_state: torch.Tensor
    current_flow_cfs: torch.Tensor
    target_flow_cfs: torch.Tensor
    system_ids: tuple[str, ...]
    input_timestamps: tuple[pd.Timestamp, ...]
    target_timestamps: tuple[pd.Timestamp, ...]
    context_feature_names: tuple[str, ...] = ("hour_sin", "hour_cos")
    context_audit: dict[str, Any] | None = None

    @property
    def sample_count(self) -> int:
        return len(self.system_ids)


def signed_log_state(values: np.ndarray | torch.Tensor) -> torch.Tensor:
    if isinstance(values, torch.Tensor):
        tensor = values.to(dtype=torch.float32)
    else:
        tensor = torch.tensor(
            np.asarray(values).copy(), dtype=torch.float32
        )
    return torch.sign(tensor) * torch.log1p(torch.abs(tensor)) / float(
        HYDROCONTROL_SIGNAL_LOG_SCALE
    )


def inverse_signed_log_state(values: torch.Tensor) -> torch.Tensor:
    scaled = values * float(HYDROCONTROL_SIGNAL_LOG_SCALE)
    return torch.sign(scaled) * torch.expm1(torch.abs(scaled))


def prepare_hydrocontrol_targets(
    panel: pd.DataFrame, *, horizon_hours: int
) -> pd.DataFrame:
    if horizon_hours not in HYDROCONTROL_ELIGIBLE_HORIZONS:
        raise ValueError("unsupported_hydrocontrol_horizon")
    required = {
        "system_id",
        "timestamp",
        "temporal_split",
        "effective_release_cfs",
        "effective_release_change_cfs",
        "downstream_flow_cfs",
        "admitted_current_state_action",
        "dst_transition_day",
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"hydrocontrol_panel_missing_columns:{','.join(missing)}")

    frame = panel.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="raise")
    frame = frame.sort_values(["system_id", "timestamp"]).reset_index(drop=True)
    if frame.duplicated(["system_id", "timestamp"]).any():
        raise ValueError("duplicate_system_timestamp")

    frame["target_timestamp"] = frame["timestamp"] + pd.Timedelta(
        hours=horizon_hours
    )
    target = frame[
        ["system_id", "timestamp", "downstream_flow_cfs", "dst_transition_day"]
    ].rename(
        columns={
            "timestamp": "target_timestamp",
            "downstream_flow_cfs": "target_flow_cfs",
            "dst_transition_day": "target_dst_transition_day",
        }
    )
    return frame.merge(
        target,
        on=["system_id", "target_timestamp"],
        how="left",
        validate="many_to_one",
    )


def build_hydrocontrol_dam_gk_dataset(
    panel: pd.DataFrame,
    *,
    horizon_hours: int,
    systems: Iterable[str] | None = None,
    temporal_split: str | None = None,
    target_before: str | pd.Timestamp | None = None,
) -> HydroControlDAMGKDataset:
    frame = prepare_hydrocontrol_targets(
        panel, horizon_hours=horizon_hours
    )
    valid = (
        frame["admitted_current_state_action"].fillna(False).astype(bool)
        & ~frame["dst_transition_day"].fillna(True).astype(bool)
        & ~frame["target_dst_transition_day"].fillna(True).astype(bool)
    )
    if systems is not None:
        requested = set(systems)
        valid &= frame["system_id"].isin(requested)
    if temporal_split is not None:
        valid &= frame["temporal_split"] == temporal_split
    if target_before is not None:
        valid &= frame["target_timestamp"] < pd.Timestamp(target_before)

    required_values = [
        "effective_release_cfs",
        "effective_release_change_cfs",
        "downstream_flow_cfs",
        "target_flow_cfs",
    ]
    selected = frame.loc[valid].dropna(subset=required_values).copy()
    selected = selected.sort_values(["system_id", "timestamp"]).reset_index(
        drop=True
    )
    if selected.empty:
        raise ValueError("no_admissible_hydrocontrol_samples")

    sample_count = len(selected)
    source_nodes = torch.arange(0, sample_count * 2, 2, dtype=torch.long)
    target_nodes = source_nodes + 1
    node_state = torch.zeros((sample_count * 2, 2), dtype=torch.float32)
    node_state[source_nodes, 1] = 1.0
    node_state[target_nodes, 0] = signed_log_state(
        selected["downstream_flow_cfs"].to_numpy(dtype=float)
    )

    node_action = torch.zeros((sample_count * 2, 2), dtype=torch.float32)
    node_action[source_nodes, 0] = signed_log_state(
        selected["effective_release_cfs"].to_numpy(dtype=float)
    )
    node_action[source_nodes, 1] = signed_log_state(
        selected["effective_release_change_cfs"].to_numpy(dtype=float)
    )

    hours = selected["timestamp"].dt.hour.to_numpy(dtype=float)
    phase = 2.0 * np.pi * hours / 24.0
    context_values = torch.tensor(
        np.column_stack([np.sin(phase), np.cos(phase)]), dtype=torch.float32
    )
    node_context = torch.repeat_interleave(context_values, 2, dim=0)
    batch = DAMGKBatch(
        node_state=node_state,
        node_action=node_action,
        node_context=node_context,
        edge_index=torch.stack([source_nodes, target_nodes]),
        edge_features=torch.ones((sample_count, 1), dtype=torch.float32),
        edge_types=torch.zeros(sample_count, dtype=torch.long),
    )
    return HydroControlDAMGKDataset(
        schema=HYDROCONTROL_DAM_GK_ADAPTER_SCHEMA,
        horizon_hours=horizon_hours,
        batch=batch,
        target_node_index=target_nodes,
        target_flow_state=signed_log_state(
            selected["target_flow_cfs"].to_numpy(dtype=float)
        ),
        current_flow_cfs=torch.tensor(
            selected["downstream_flow_cfs"].to_numpy(dtype=float),
            dtype=torch.float32,
        ),
        target_flow_cfs=torch.tensor(
            selected["target_flow_cfs"].to_numpy(dtype=float),
            dtype=torch.float32,
        ),
        system_ids=tuple(selected["system_id"].astype(str)),
        input_timestamps=tuple(selected["timestamp"]),
        target_timestamps=tuple(selected["target_timestamp"]),
        context_feature_names=("hour_sin", "hour_cos"),
    )


def select_hydrocontrol_samples(
    dataset: HydroControlDAMGKDataset,
    indices: np.ndarray | torch.Tensor | list[int],
) -> HydroControlDAMGKDataset:
    sample_indices = torch.as_tensor(indices, dtype=torch.long)
    source_nodes = sample_indices * 2
    target_nodes = source_nodes + 1
    old_nodes = torch.stack([source_nodes, target_nodes], dim=1).reshape(-1)
    sample_count = int(sample_indices.numel())
    new_sources = torch.arange(0, sample_count * 2, 2, dtype=torch.long)
    new_targets = new_sources + 1
    batch = dataset.batch
    selected_batch = DAMGKBatch(
        node_state=batch.node_state[old_nodes],
        node_action=batch.node_action[old_nodes],
        node_context=(
            None if batch.node_context is None else batch.node_context[old_nodes]
        ),
        node_context_by_step=(
            None
            if batch.node_context_by_step is None
            else batch.node_context_by_step[old_nodes]
        ),
        teacher_state_by_step=(
            None
            if batch.teacher_state_by_step is None
            else batch.teacher_state_by_step[old_nodes]
        ),
        region_context=(
            None
            if batch.region_context is None
            else batch.region_context[old_nodes]
        ),
        edge_index=torch.stack([new_sources, new_targets]),
        edge_features=batch.edge_features[sample_indices],
        edge_types=batch.edge_types[sample_indices],
        edge_valid_mask=(
            None
            if batch.edge_valid_mask is None
            else batch.edge_valid_mask[sample_indices]
        ),
    )
    python_indices = sample_indices.tolist()
    return HydroControlDAMGKDataset(
        schema=dataset.schema,
        horizon_hours=dataset.horizon_hours,
        batch=selected_batch,
        target_node_index=new_targets,
        target_flow_state=dataset.target_flow_state[sample_indices],
        current_flow_cfs=dataset.current_flow_cfs[sample_indices],
        target_flow_cfs=dataset.target_flow_cfs[sample_indices],
        system_ids=tuple(dataset.system_ids[index] for index in python_indices),
        input_timestamps=tuple(
            dataset.input_timestamps[index] for index in python_indices
        ),
        target_timestamps=tuple(
            dataset.target_timestamps[index] for index in python_indices
        ),
        context_feature_names=dataset.context_feature_names,
        context_audit=dataset.context_audit,
    )
