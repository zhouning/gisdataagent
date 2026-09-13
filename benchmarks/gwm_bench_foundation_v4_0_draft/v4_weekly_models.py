"""Weekly model implementations for GWM Benchmark V4 Runtime-R3.

This module intentionally has no path or API for the V4 test-target bundle.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import torch
from sklearn.linear_model import Ridge
from torch import nn


N_ZONES = 263
STATE_COLUMNS = ("pickup_count", "dropoff_count", "cbd_inflow", "cbd_outflow")
ACTION_COLUMNS = (
    "fixed_spatial_surcharge_contribution_usd",
    "flag_fall_contribution_usd",
    "improvement_surcharge_contribution_usd",
    "metered_unit_contribution_usd",
    "rush_hour_contribution_usd",
    "night_contribution_usd",
    "jfk_flat_contribution_usd",
    "jfk_rush_contribution_usd",
    "lga_contribution_usd",
    "newark_contribution_usd",
    "expected_total_delta_usd",
    "expected_fractional_fare_delta",
    "spatial_applicability_share",
    "temporal_applicability_share",
    "implementation_share",
)
LAGS = (1, 2, 4, 8)
REPORT_HORIZONS = (1, 2, 4, 8, 12)
COMPONENT_COUNT = 10


@dataclass(frozen=True)
class ModelConfig:
    name: str
    hidden_size: int
    embedding_size: int
    learning_rate: float
    weight_decay: float
    epochs: int
    post_weight: float
    gradient_clip: float = 1.0


CONFIGS = (
    ModelConfig("compact", 32, 8, 2.0e-3, 1.0e-4, 18, 2.0),
    ModelConfig("base", 48, 8, 1.5e-3, 1.0e-5, 26, 3.0),
    ModelConfig("regularized", 48, 8, 8.0e-4, 1.0e-4, 32, 5.0),
)


@dataclass
class WeeklyEvent:
    name: str
    relative_week: np.ndarray
    dates: pd.DatetimeIndex
    raw_state: np.ndarray
    residual_state: np.ndarray
    baseline_log: np.ndarray
    action: np.ndarray
    calendar: np.ndarray


@dataclass
class WeeklyTestInput:
    dates_history: pd.DatetimeIndex
    dates_future: pd.DatetimeIndex
    raw_history: np.ndarray
    residual_history: np.ndarray
    baseline_log: np.ndarray
    action_future: np.ndarray
    calendar_history: np.ndarray
    calendar_future: np.ndarray


@dataclass(frozen=True)
class Scalers:
    state_scale: np.ndarray
    action_scale: np.ndarray

    def to_json(self) -> dict[str, Any]:
        return {
            "state_scale": self.state_scale.tolist(),
            "action_scale": self.action_scale.tolist(),
            "action_columns": list(ACTION_COLUMNS),
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(min(6, max(1, torch.get_num_threads())))
    torch.use_deterministic_algorithms(True)


def calendar_features(dates: pd.DatetimeIndex, relative: np.ndarray) -> np.ndarray:
    day_of_year = dates.dayofyear.to_numpy(dtype=np.float32)
    relative = relative.astype(np.float32)
    return np.column_stack(
        [
            np.sin(2.0 * np.pi * day_of_year / 365.25),
            np.cos(2.0 * np.pi * day_of_year / 365.25),
            np.clip(relative / 52.0, -1.0, 1.0),
            (relative > 0).astype(np.float32),
            np.ones(len(dates), dtype=np.float32),
        ]
    ).astype(np.float32)


def _canonical_reshape(frame: pd.DataFrame, columns: Iterable[str]) -> np.ndarray:
    expected = np.tile(np.arange(1, N_ZONES + 1), frame["relative_week"].nunique())
    if not np.array_equal(frame["zone_id"].to_numpy(), expected):
        raise ValueError("zone order is not canonical")
    return frame[list(columns)].to_numpy(dtype=np.float32).reshape(
        frame["relative_week"].nunique(), N_ZONES, len(tuple(columns))
    )


def load_development(path: Path) -> dict[str, WeeklyEvent]:
    frame = pd.read_parquet(path).sort_values(
        ["event_id_audit_only", "relative_week", "zone_id"]
    )
    events: dict[str, WeeklyEvent] = {}
    for name, selected in frame.groupby("event_id_audit_only", sort=True, observed=True):
        selected = selected.sort_values(["relative_week", "zone_id"]).reset_index(drop=True)
        weeks = selected["relative_week"].drop_duplicates().to_numpy(dtype=np.int16)
        expected_weeks = np.asarray(list(range(-52, 0)) + list(range(1, 13)), dtype=np.int16)
        if not np.array_equal(weeks, expected_weeks) or len(selected) != 64 * N_ZONES:
            raise ValueError(f"incomplete weekly event: {name}")
        raw = _canonical_reshape(selected, STATE_COLUMNS)
        action = _canonical_reshape(selected, ACTION_COLUMNS)
        pre = weeks < 0
        baseline_log = np.log1p(raw[pre]).mean(axis=0).astype(np.float32)
        residual = (np.log1p(raw) - baseline_log[None, ...]).astype(np.float32)
        dates = pd.DatetimeIndex(selected["week_start"].drop_duplicates())
        events[str(name)] = WeeklyEvent(
            name=str(name),
            relative_week=weeks,
            dates=dates,
            raw_state=raw,
            residual_state=residual,
            baseline_log=baseline_log,
            action=action,
            calendar=calendar_features(dates, weeks),
        )
    if set(events) != {
        "train_2019_nys_congestion_surcharge",
        "train_2022_tlc_taximeter_adjustment",
    }:
        raise ValueError(f"unexpected training event set: {sorted(events)}")
    return events


def load_test_input(history_path: Path, action_path: Path) -> WeeklyTestInput:
    history = pd.read_parquet(history_path).sort_values(["relative_week", "zone_id"])
    future = pd.read_parquet(action_path).sort_values(["horizon_week", "zone_id"])
    history_weeks = history["relative_week"].drop_duplicates().to_numpy(dtype=np.int16)
    future_weeks = future["horizon_week"].drop_duplicates().to_numpy(dtype=np.int16)
    if not np.array_equal(history_weeks, np.arange(-52, 0, dtype=np.int16)):
        raise ValueError("test history week contract failed")
    if not np.array_equal(future_weeks, np.arange(1, 13, dtype=np.int16)):
        raise ValueError("future action week contract failed")
    raw_history = _canonical_reshape(history, STATE_COLUMNS)
    action_future = (
        future[list(ACTION_COLUMNS)]
        .to_numpy(dtype=np.float32)
        .reshape(12, N_ZONES, len(ACTION_COLUMNS))
    )
    baseline_log = np.log1p(raw_history).mean(axis=0).astype(np.float32)
    residual_history = (np.log1p(raw_history) - baseline_log[None, ...]).astype(np.float32)
    dates_history = pd.DatetimeIndex(history["week_start"].drop_duplicates())
    dates_future = pd.DatetimeIndex(future["week_start"].drop_duplicates())
    return WeeklyTestInput(
        dates_history=dates_history,
        dates_future=dates_future,
        raw_history=raw_history,
        residual_history=residual_history,
        baseline_log=baseline_log,
        action_future=action_future,
        calendar_history=calendar_features(dates_history, history_weeks),
        calendar_future=calendar_features(dates_future, future_weeks),
    )


def normalize_rows(matrix: np.ndarray) -> np.ndarray:
    denominator = matrix.sum(axis=1, keepdims=True)
    return np.divide(
        matrix,
        denominator,
        out=np.zeros_like(matrix, dtype=np.float32),
        where=denominator > 0,
    ).astype(np.float32)


def load_relations(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    frame = pd.read_parquet(path)
    relations = []
    counts: dict[str, int] = {}
    for relation in (
        "geographic_adjacency",
        "origin_destination_flow",
        "action_exposure",
    ):
        selected = frame.loc[frame["relation"].eq(relation)]
        matrix = np.zeros((N_ZONES, N_ZONES), dtype=np.float32)
        for row in selected.itertuples(index=False):
            matrix[int(row.target_zone) - 1, int(row.source_zone) - 1] += float(row.weight)
        relations.append(normalize_rows(matrix))
        counts[relation] = len(selected)
    values = np.stack(relations).astype(np.float32)
    audit = {
        "path": str(path),
        "sha256": sha256_file(path),
        "relation_counts": counts,
        "relation_digests": [hashlib.sha256(value.tobytes()).hexdigest() for value in values],
    }
    return values, audit


def fit_scalers(events: Iterable[WeeklyEvent], action_mode: str) -> Scalers:
    selected = list(events)
    state = np.concatenate([event.residual_state for event in selected], axis=0)
    state_scale = np.maximum(state.std(axis=(0, 1)), 1e-3).astype(np.float32)
    if action_mode == "no_action":
        action = np.zeros((1, 1, len(ACTION_COLUMNS)), dtype=np.float32)
    else:
        action = np.concatenate([event.action for event in selected], axis=0)
    action_scale = np.maximum(np.max(np.abs(action), axis=(0, 1)), 0.1).astype(np.float32)
    return Scalers(state_scale=state_scale, action_scale=action_scale)


class WeeklyActionGraphGRU(nn.Module):
    def __init__(self, config: ModelConfig) -> None:
        super().__init__()
        self.config = config
        self.node_embedding = nn.Embedding(N_ZONES, config.embedding_size)
        self.action_encoder = nn.Sequential(
            nn.Linear(len(ACTION_COLUMNS), 24),
            nn.SiLU(),
            nn.Linear(24, 16),
            nn.SiLU(),
        )
        nn.init.zeros_(self.action_encoder[0].weight)
        nn.init.zeros_(self.action_encoder[0].bias)
        nn.init.zeros_(self.action_encoder[2].bias)
        self.relation_gate = nn.Sequential(
            nn.Linear(5 + 16, 16), nn.Tanh(), nn.Linear(16, 3), nn.Sigmoid()
        )
        input_size = 16 + 12 + 5 + 16 + config.embedding_size
        self.input_projection = nn.Sequential(nn.Linear(input_size, config.hidden_size), nn.SiLU())
        self.gru = nn.GRU(config.hidden_size, config.hidden_size, batch_first=True)
        self.film = nn.Linear(16, config.hidden_size * 2)
        self.head = nn.Sequential(
            nn.Linear(config.hidden_size, config.hidden_size),
            nn.SiLU(),
            nn.Linear(config.hidden_size, 4),
        )
        nn.init.zeros_(self.head[-1].weight)
        nn.init.zeros_(self.head[-1].bias)

    def forward_sequence(
        self,
        lags: torch.Tensor,
        messages: torch.Tensor,
        calendar: torch.Tensor,
        action: torch.Tensor,
        hidden: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        steps, zones, _ = lags.shape
        action_embedding = self.action_encoder(action)
        calendar_nodes = calendar[:, None, :].expand(steps, zones, -1)
        gates = self.relation_gate(torch.cat([calendar_nodes, action_embedding], dim=-1))
        weighted_messages = (messages * gates[..., None]).reshape(steps, zones, -1)
        node_ids = torch.arange(zones, device=lags.device)
        embeddings = self.node_embedding(node_ids)[None, :, :].expand(steps, -1, -1)
        projected = self.input_projection(
            torch.cat(
                [lags, weighted_messages, calendar_nodes, action_embedding, embeddings],
                dim=-1,
            )
        ).transpose(0, 1)
        output, hidden_out = self.gru(projected, hidden)
        output = output.transpose(0, 1)
        scale, shift = self.film(action_embedding).chunk(2, dim=-1)
        modulated = output * (1.0 + 0.25 * torch.tanh(scale)) + 0.25 * shift
        prediction = lags[..., :4] + self.head(modulated)
        return prediction, hidden_out


def _messages(state: np.ndarray, relations: np.ndarray) -> np.ndarray:
    return np.einsum("rij,jf->irf", relations, state, optimize=True).astype(np.float32)


def _training_arrays(
    event: WeeklyEvent,
    scalers: Scalers,
    relations: np.ndarray,
    action_mode: str,
) -> tuple[np.ndarray, ...]:
    state = (event.residual_state / scalers.state_scale).astype(np.float32)
    action = (
        np.zeros_like(event.action)
        if action_mode == "no_action"
        else event.action.copy()
    )
    action = (action / scalers.action_scale).astype(np.float32)
    indices = np.arange(max(LAGS), len(event.relative_week))
    lags = np.concatenate([state[indices - lag] for lag in LAGS], axis=-1)
    messages = np.stack([_messages(state[index - 1], relations) for index in indices])
    target = state[indices]
    calendar = event.calendar[indices]
    action_values = action[indices]
    weights = np.where(event.relative_week[indices] > 0, 1.0, 0.0).astype(np.float32)
    return lags, messages, calendar, action_values, target, weights


def train_graph_model(
    events: list[WeeklyEvent],
    relations: np.ndarray,
    config: ModelConfig,
    seed: int,
    action_mode: str,
) -> tuple[WeeklyActionGraphGRU, Scalers, dict[str, Any]]:
    set_seed(seed)
    scalers = fit_scalers(events, action_mode)
    arrays = [_training_arrays(event, scalers, relations, action_mode) for event in events]
    model = WeeklyActionGraphGRU(config)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay
    )
    criterion = nn.SmoothL1Loss(beta=0.35, reduction="none")
    rng = np.random.default_rng(seed)
    history = []
    for epoch in range(1, config.epochs + 1):
        model.train()
        losses = []
        for event_index in rng.permutation(len(arrays)):
            lags, messages, calendar, action, target, post = arrays[int(event_index)]
            optimizer.zero_grad(set_to_none=True)
            prediction, _ = model.forward_sequence(
                torch.from_numpy(lags),
                torch.from_numpy(messages),
                torch.from_numpy(calendar),
                torch.from_numpy(action),
            )
            raw = criterion(prediction, torch.from_numpy(target)).mean(dim=(1, 2))
            weights = torch.from_numpy(1.0 + post * (config.post_weight - 1.0))
            loss = (raw * weights).sum() / weights.sum()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), config.gradient_clip)
            optimizer.step()
            losses.append(float(loss.detach()))
        history.append({"epoch": epoch, "weighted_smooth_l1": float(np.mean(losses))})
    report = {
        "seed": seed,
        "config": asdict(config),
        "action_mode": action_mode,
        "parameter_count": int(sum(parameter.numel() for parameter in model.parameters())),
        "train_events": [event.name for event in events],
        "history": history,
        "scalers": scalers.to_json(),
    }
    return model, scalers, report


def event_as_test(event: WeeklyEvent) -> WeeklyTestInput:
    return WeeklyTestInput(
        dates_history=event.dates[:52],
        dates_future=event.dates[52:],
        raw_history=event.raw_state[:52],
        residual_history=event.residual_state[:52],
        baseline_log=event.baseline_log,
        action_future=event.action[52:],
        calendar_history=event.calendar[:52],
        calendar_future=event.calendar[52:],
    )


def predict_graph_recursive(
    model: WeeklyActionGraphGRU,
    scalers: Scalers,
    test: WeeklyTestInput,
    relations: np.ndarray,
    *,
    action_future: np.ndarray | None = None,
    action_history: np.ndarray | None = None,
) -> np.ndarray:
    future = test.action_future if action_future is None else action_future
    past_action = (
        np.zeros((52, N_ZONES, len(ACTION_COLUMNS)), dtype=np.float32)
        if action_history is None
        else action_history
    )
    state_history = [
        value.copy() for value in (test.residual_history / scalers.state_scale).astype(np.float32)
    ]
    past_action = (past_action / scalers.action_scale).astype(np.float32)
    future = (future / scalers.action_scale).astype(np.float32)
    warm_indices = np.arange(max(LAGS), 52)
    warm_lags = np.stack(
        [
            np.concatenate([state_history[index - lag] for lag in LAGS], axis=-1)
            for index in warm_indices
        ]
    )
    warm_messages = np.stack(
        [_messages(state_history[index - 1], relations) for index in warm_indices]
    )
    model.eval()
    with torch.no_grad():
        _, hidden = model.forward_sequence(
            torch.from_numpy(warm_lags),
            torch.from_numpy(warm_messages),
            torch.from_numpy(test.calendar_history[warm_indices]),
            torch.from_numpy(past_action[warm_indices]),
        )
        outputs = []
        for horizon_index in range(12):
            index = len(state_history)
            lags = np.concatenate(
                [state_history[index - lag] for lag in LAGS], axis=-1
            )
            messages = _messages(state_history[-1], relations)
            prediction, hidden = model.forward_sequence(
                torch.from_numpy(lags[None, ...]),
                torch.from_numpy(messages[None, ...]),
                torch.from_numpy(test.calendar_future[horizon_index][None, ...]),
                torch.from_numpy(future[horizon_index][None, ...]),
                hidden,
            )
            value = np.clip(prediction.numpy()[0], -12.0, 12.0)
            state_history.append(value)
            outputs.append(value)
    residual = np.stack(outputs) * scalers.state_scale
    raw = np.maximum(np.expm1(test.baseline_log[None, ...] + residual), 0.0)
    return raw.astype(np.float32)


def macro_pre_event_nmae(prediction: np.ndarray, test: WeeklyTestInput, truth: np.ndarray) -> float:
    scale = np.maximum(test.raw_history.mean(axis=0), 1.0)
    indices = np.asarray([value - 1 for value in REPORT_HORIZONS], dtype=int)
    error = np.abs(prediction[indices] - truth[indices]) / scale[None, ...]
    return float(error.mean())


def select_config(
    events: dict[str, WeeklyEvent],
    relations: np.ndarray,
    *,
    seed: int = 31,
) -> tuple[ModelConfig, dict[str, Any]]:
    rows = []
    event_names = sorted(events)
    for config in CONFIGS:
        for validation_name in event_names:
            train_name = next(name for name in event_names if name != validation_name)
            model, scalers, training = train_graph_model(
                [events[train_name]], relations, config, seed, "compositional"
            )
            validation = event_as_test(events[validation_name])
            prediction = predict_graph_recursive(model, scalers, validation, relations)
            truth = events[validation_name].raw_state[52:]
            score = macro_pre_event_nmae(prediction, validation, truth)
            rows.append(
                {
                    "config": config.name,
                    "train_event": train_name,
                    "validation_event": validation_name,
                    "primary_metric": score,
                    "training_final_loss": training["history"][-1]["weighted_smooth_l1"],
                }
            )
    summary = {
        config.name: float(
            np.mean([row["primary_metric"] for row in rows if row["config"] == config.name])
        )
        for config in CONFIGS
    }
    selected_name = min(summary, key=summary.get)
    selected = next(config for config in CONFIGS if config.name == selected_name)
    report = {
        "selection_rule": "lowest mean two-fold leave-one-intervention-out macro pre-event normalized MAE",
        "seed": seed,
        "rows": rows,
        "summary": summary,
        "selected_config": selected_name,
    }
    return selected, report


def fit_ridge_models(
    events: dict[str, WeeklyEvent],
    relations: np.ndarray,
    *,
    spatial: bool,
    alpha: float = 5.0,
) -> list[Ridge]:
    x_by_zone: list[list[np.ndarray]] = [[] for _ in range(N_ZONES)]
    y_by_zone: list[list[np.ndarray]] = [[] for _ in range(N_ZONES)]
    for event in events.values():
        state = event.residual_state
        for index in range(max(LAGS), len(event.relative_week)):
            lag_features = np.concatenate([state[index - lag] for lag in LAGS], axis=-1)
            parts = [lag_features]
            if spatial:
                geo_message = relations[0] @ state[index - 1]
                parts.append(geo_message)
            parts.append(np.repeat(event.calendar[index][None, :], N_ZONES, axis=0))
            features = np.concatenate(parts, axis=-1)
            for zone in range(N_ZONES):
                x_by_zone[zone].append(features[zone])
                y_by_zone[zone].append(state[index, zone])
    models = []
    for zone in range(N_ZONES):
        model = Ridge(alpha=alpha)
        model.fit(np.asarray(x_by_zone[zone]), np.asarray(y_by_zone[zone]))
        models.append(model)
    return models


def predict_ridge_recursive(
    models: list[Ridge],
    test: WeeklyTestInput,
    relations: np.ndarray,
    *,
    spatial: bool,
) -> np.ndarray:
    history = [value.copy() for value in test.residual_history]
    outputs = []
    for horizon_index in range(12):
        index = len(history)
        lag_features = np.concatenate([history[index - lag] for lag in LAGS], axis=-1)
        parts = [lag_features]
        if spatial:
            parts.append(relations[0] @ history[-1])
        parts.append(np.repeat(test.calendar_future[horizon_index][None, :], N_ZONES, axis=0))
        features = np.concatenate(parts, axis=-1)
        prediction = np.stack(
            [models[zone].predict(features[zone][None, :])[0] for zone in range(N_ZONES)]
        ).astype(np.float32)
        prediction = np.clip(prediction, -12.0, 12.0)
        history.append(prediction)
        outputs.append(prediction)
    residual = np.stack(outputs)
    return np.maximum(
        np.expm1(test.baseline_log[None, ...] + residual), 0.0
    ).astype(np.float32)


def seasonal_prediction(test: WeeklyTestInput) -> np.ndarray:
    return test.raw_history[:12].copy().astype(np.float32)


def control_inputs(
    control_id: str,
    test: WeeklyTestInput,
    relations: np.ndarray,
    zone_metadata: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    future = test.action_future.copy()
    history = np.zeros((52, N_ZONES, len(ACTION_COLUMNS)), dtype=np.float32)
    relation_values = relations.copy()
    audit: dict[str, Any] = {"control_id": control_id}
    if control_id == "correct_action":
        return future, history, relation_values, audit
    if control_id == "action_deleted":
        future[:] = 0.0
    elif control_id == "effective_date_minus_4w":
        history[-4:] = future[0][None, ...]
    elif control_id == "effective_date_plus_4w":
        future[:4] = 0.0
    elif control_id == "action_component_permutation":
        permutation = np.random.default_rng(20260723).permutation(COMPONENT_COUNT)
        future[..., :COMPONENT_COUNT] = future[..., permutation]
        audit["component_permutation"] = permutation.tolist()
    elif control_id in {"cbd_scope_rewire", "zone_exposure_shuffle_seed_20260723"}:
        spatial_indices = [0, 10, 11, 12]
        cbd = zone_metadata.sort_values("zone_id")["cbd_exposure"].to_numpy(dtype=np.float32)
        rng = np.random.default_rng(20260723)
        if control_id == "cbd_scope_rewire":
            candidates = np.flatnonzero(cbd == 0)
            selected = np.sort(rng.choice(candidates, size=38, replace=False))
            exposure = np.zeros(N_ZONES, dtype=np.float32)
            exposure[selected] = 1.0
            future[..., 0] = 0.75 * exposure[None, :]
            future[..., 10] = future[..., 0]
            future[..., 11] = future[..., 10] / 10.0
            future[..., 12] = exposure[None, :]
            audit["rewired_zone_ids"] = (selected + 1).tolist()
        else:
            permutation = rng.permutation(N_ZONES)
            exposure = cbd[permutation]
            future[..., spatial_indices] = future[:, permutation][:, :, spatial_indices]
            audit["zone_permutation_sha256"] = hashlib.sha256(
                permutation.astype(np.int16).tobytes()
            ).hexdigest()
        relation_values[2] = np.diag(exposure).astype(np.float32)
    else:
        raise ValueError(f"unknown control: {control_id}")
    return future, history, relation_values, audit


def prediction_frame(prediction: np.ndarray) -> pd.DataFrame:
    rows = []
    for horizon_index in range(12):
        frame = pd.DataFrame(
            {
                "zone_id": np.arange(1, N_ZONES + 1, dtype=np.int16),
                "horizon_week": horizon_index + 1,
            }
        )
        for target_index, target in enumerate(STATE_COLUMNS):
            frame[f"{target}_prediction"] = prediction[
                horizon_index, :, target_index
            ].astype(np.float64)
        rows.append(frame)
    return pd.concat(rows, ignore_index=True).sort_values(
        ["zone_id", "horizon_week"]
    ).reset_index(drop=True)


def save_checkpoint(
    path: Path,
    model: WeeklyActionGraphGRU,
    scalers: Scalers,
    training: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "schema": "gwm_bench.foundation_v4_weekly_graph_gru.v1",
            "state_dict": model.state_dict(),
            "config": training["config"],
            "scalers": scalers.to_json(),
            "training": training,
        },
        path,
    )


def load_checkpoint(path: Path) -> tuple[WeeklyActionGraphGRU, Scalers, dict[str, Any]]:
    payload = torch.load(path, map_location="cpu", weights_only=False)
    config = ModelConfig(**payload["config"])
    model = WeeklyActionGraphGRU(config)
    model.load_state_dict(payload["state_dict"])
    scalers = Scalers(
        state_scale=np.asarray(payload["scalers"]["state_scale"], dtype=np.float32),
        action_scale=np.asarray(payload["scalers"]["action_scale"], dtype=np.float32),
    )
    return model, scalers, payload["training"]
