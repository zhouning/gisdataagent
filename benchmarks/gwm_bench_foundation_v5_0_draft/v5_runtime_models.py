"""Model core for GWM-Bench V5 Runtime-R4.

This module has no path, constant or loader for an outer-fold test-target file.
Training-event post-action rows are admitted only through each fold's development bundle.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, replace
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
class ResidualConfig:
    name: str
    hidden_size: int
    embedding_size: int
    learning_rate: float
    weight_decay: float
    epochs: int
    gradient_clip: float = 1.0


CONFIGS = (
    ResidualConfig("compact", 32, 8, 2.0e-3, 1.0e-4, 24),
    ResidualConfig("base", 48, 8, 1.2e-3, 1.0e-5, 34),
    ResidualConfig("regularized", 48, 8, 7.0e-4, 5.0e-4, 44),
)


@dataclass
class WeeklyEvent:
    name: str
    relative_week: np.ndarray
    dates: pd.DatetimeIndex
    raw_state: np.ndarray
    action: np.ndarray
    calendar: np.ndarray


@dataclass
class WeeklyTestInput:
    dates_history: pd.DatetimeIndex
    dates_future: pd.DatetimeIndex
    raw_history: np.ndarray
    action_future: np.ndarray
    calendar_history: np.ndarray
    calendar_future: np.ndarray


@dataclass
class ResidualExample:
    name: str
    test: WeeklyTestInput
    backbone_prediction: np.ndarray
    truth: np.ndarray
    scale: np.ndarray
    target_delta: np.ndarray
    relations: np.ndarray


@dataclass(frozen=True)
class ActionScaler:
    values: np.ndarray

    def to_json(self) -> dict[str, Any]:
        return {
            "values": self.values.tolist(),
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


def canonical_reshape(frame: pd.DataFrame, columns: Iterable[str]) -> np.ndarray:
    column_list = list(columns)
    week_count = frame["relative_week"].nunique()
    expected = np.tile(np.arange(1, N_ZONES + 1), week_count)
    if not np.array_equal(frame["zone_id"].to_numpy(), expected):
        raise ValueError("zone order is not canonical")
    return frame[column_list].to_numpy(dtype=np.float32).reshape(
        week_count, N_ZONES, len(column_list)
    )


def load_development(path: Path, expected_event_ids: Iterable[str]) -> dict[str, WeeklyEvent]:
    frame = pd.read_parquet(path).sort_values(
        ["event_id_audit_only", "relative_week", "zone_id"]
    )
    events: dict[str, WeeklyEvent] = {}
    expected_weeks = np.asarray(list(range(-52, 0)) + list(range(1, 13)), dtype=np.int16)
    for name, selected in frame.groupby("event_id_audit_only", sort=True, observed=True):
        selected = selected.sort_values(["relative_week", "zone_id"]).reset_index(drop=True)
        weeks = selected["relative_week"].drop_duplicates().to_numpy(dtype=np.int16)
        if not np.array_equal(weeks, expected_weeks) or len(selected) != 64 * N_ZONES:
            raise ValueError(f"incomplete weekly event: {name}")
        dates = pd.DatetimeIndex(selected["week_start"].drop_duplicates())
        events[str(name)] = WeeklyEvent(
            name=str(name),
            relative_week=weeks,
            dates=dates,
            raw_state=canonical_reshape(selected, STATE_COLUMNS),
            action=canonical_reshape(selected, ACTION_COLUMNS),
            calendar=calendar_features(dates, weeks),
        )
    if set(events) != set(expected_event_ids):
        raise ValueError(
            f"development event mismatch: expected={sorted(expected_event_ids)} "
            f"actual={sorted(events)}"
        )
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
    raw_history = canonical_reshape(history, STATE_COLUMNS)
    action_future = future[list(ACTION_COLUMNS)].to_numpy(dtype=np.float32).reshape(
        12, N_ZONES, len(ACTION_COLUMNS)
    )
    dates_history = pd.DatetimeIndex(history["week_start"].drop_duplicates())
    dates_future = pd.DatetimeIndex(future["week_start"].drop_duplicates())
    return WeeklyTestInput(
        dates_history=dates_history,
        dates_future=dates_future,
        raw_history=raw_history,
        action_future=action_future,
        calendar_history=calendar_features(dates_history, history_weeks),
        calendar_future=calendar_features(dates_future, future_weeks),
    )


def event_as_test(event: WeeklyEvent) -> WeeklyTestInput:
    return WeeklyTestInput(
        dates_history=event.dates[:52],
        dates_future=event.dates[52:],
        raw_history=event.raw_state[:52],
        action_future=event.action[52:],
        calendar_history=event.calendar[:52],
        calendar_future=event.calendar[52:],
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
    return values, {
        "path": str(path),
        "sha256": sha256_file(path),
        "relation_counts": counts,
        "relation_digests": [
            hashlib.sha256(value.tobytes()).hexdigest() for value in values
        ],
    }


def event_log_residual(event: WeeklyEvent) -> tuple[np.ndarray, np.ndarray]:
    baseline_log = np.log1p(event.raw_state[:52]).mean(axis=0).astype(np.float32)
    residual = (np.log1p(event.raw_state) - baseline_log[None, ...]).astype(np.float32)
    return residual, baseline_log


def fit_ridge_models(
    events: dict[str, WeeklyEvent],
    adjacency: np.ndarray,
    *,
    spatial: bool,
    alpha: float = 5.0,
) -> list[Ridge]:
    x_by_zone: list[list[np.ndarray]] = [[] for _ in range(N_ZONES)]
    y_by_zone: list[list[np.ndarray]] = [[] for _ in range(N_ZONES)]
    for event in events.values():
        state, _ = event_log_residual(event)
        for index in range(max(LAGS), len(event.relative_week)):
            lag_features = np.concatenate([state[index - lag] for lag in LAGS], axis=-1)
            parts = [lag_features]
            if spatial:
                parts.append(adjacency @ state[index - 1])
            parts.append(np.repeat(event.calendar[index][None, :], N_ZONES, axis=0))
            features = np.concatenate(parts, axis=-1)
            for zone in range(N_ZONES):
                x_by_zone[zone].append(features[zone])
                y_by_zone[zone].append(state[index, zone])
    if not events:
        raise ValueError("history AR requires at least one training event")
    models: list[Ridge] = []
    for zone in range(N_ZONES):
        model = Ridge(alpha=alpha)
        model.fit(np.asarray(x_by_zone[zone]), np.asarray(y_by_zone[zone]))
        models.append(model)
    return models


def predict_ridge_recursive(
    models: list[Ridge],
    test: WeeklyTestInput,
    adjacency: np.ndarray,
    *,
    spatial: bool,
) -> np.ndarray:
    baseline_log = np.log1p(test.raw_history).mean(axis=0).astype(np.float32)
    history = [
        value.copy()
        for value in (np.log1p(test.raw_history) - baseline_log[None, ...]).astype(
            np.float32
        )
    ]
    outputs = []
    for horizon_index in range(12):
        index = len(history)
        lag_features = np.concatenate([history[index - lag] for lag in LAGS], axis=-1)
        parts = [lag_features]
        if spatial:
            parts.append(adjacency @ history[-1])
        parts.append(np.repeat(test.calendar_future[horizon_index][None, :], N_ZONES, axis=0))
        features = np.concatenate(parts, axis=-1)
        prediction = np.stack(
            [models[zone].predict(features[zone][None, :])[0] for zone in range(N_ZONES)]
        ).astype(np.float32)
        prediction = np.clip(prediction, -12.0, 12.0)
        history.append(prediction)
        outputs.append(prediction)
    return np.maximum(
        np.expm1(baseline_log[None, ...] + np.stack(outputs)), 0.0
    ).astype(np.float32)


def prepare_residual_example(
    event: WeeklyEvent,
    backbone_training_events: dict[str, WeeklyEvent],
    adjacency: np.ndarray,
    relations: np.ndarray,
) -> ResidualExample:
    test = event_as_test(event)
    backbone_models = fit_ridge_models(
        backbone_training_events, adjacency, spatial=False, alpha=5.0
    )
    backbone = predict_ridge_recursive(
        backbone_models, test, adjacency, spatial=False
    )
    truth = event.raw_state[52:].astype(np.float32)
    scale = np.maximum(test.raw_history.mean(axis=0), 1.0).astype(np.float32)
    target_delta = ((truth - backbone) / scale[None, ...]).astype(np.float32)
    return ResidualExample(
        name=event.name,
        test=test,
        backbone_prediction=backbone,
        truth=truth,
        scale=scale,
        target_delta=target_delta,
        relations=relations,
    )


def graph_messages(values: np.ndarray, relations: np.ndarray) -> np.ndarray:
    return np.einsum("rij,hjf->hirf", relations, values, optimize=True).astype(
        np.float32
    )


def example_features(
    example: ResidualExample,
    relations: np.ndarray,
    action_future: np.ndarray,
    action_age: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    history_mean = np.maximum(example.test.raw_history.mean(axis=0), 1.0)
    base = np.clip(
        (example.backbone_prediction - history_mean[None, ...])
        / example.scale[None, ...],
        -12.0,
        12.0,
    ).astype(np.float32)
    last = np.clip(
        (example.test.raw_history[-1] - history_mean) / example.scale,
        -12.0,
        12.0,
    ).astype(np.float32)
    trend = np.clip(
        (example.test.raw_history[-1] - example.test.raw_history[-4]) / example.scale,
        -12.0,
        12.0,
    ).astype(np.float32)
    state = np.concatenate(
        [
            base,
            np.repeat(last[None, ...], 12, axis=0),
            np.repeat(trend[None, ...], 12, axis=0),
        ],
        axis=-1,
    )
    messages = graph_messages(base, relations).reshape(12, N_ZONES, -1)
    horizon = np.arange(1, 13, dtype=np.float32)
    phase = np.column_stack(
        [horizon / 12.0, np.asarray(action_age, dtype=np.float32) / 12.0]
    )
    calendar_phase = np.concatenate([example.test.calendar_future, phase], axis=-1)
    return state, messages, calendar_phase.astype(np.float32), action_future.astype(np.float32)


def fit_action_scaler(examples: Iterable[ResidualExample]) -> ActionScaler:
    selected = list(examples)
    action = np.concatenate([example.test.action_future for example in selected], axis=0)
    values = np.maximum(np.max(np.abs(action), axis=(0, 1)), 0.1).astype(np.float32)
    return ActionScaler(values=values)


class DamGkResidualKernel(nn.Module):
    def __init__(self, config: ResidualConfig) -> None:
        super().__init__()
        self.config = config
        self.node_embedding = nn.Embedding(N_ZONES, config.embedding_size)
        state_input = 12 + 12 + 7 + config.embedding_size
        self.state_encoder = nn.Sequential(
            nn.Linear(state_input, config.hidden_size),
            nn.SiLU(),
            nn.Linear(config.hidden_size, config.hidden_size),
            nn.SiLU(),
        )
        self.action_encoder = nn.Sequential(
            nn.Linear(len(ACTION_COLUMNS), 24),
            nn.SiLU(),
            nn.Linear(24, 16),
            nn.SiLU(),
        )
        self.head = nn.Sequential(
            nn.Linear(config.hidden_size + 16, config.hidden_size),
            nn.SiLU(),
            nn.Linear(config.hidden_size, 4),
        )
        nn.init.zeros_(self.head[-1].weight)
        nn.init.zeros_(self.head[-1].bias)

    def forward(
        self,
        state: torch.Tensor,
        messages: torch.Tensor,
        calendar_phase: torch.Tensor,
        action: torch.Tensor,
        *,
        action_conditioned: bool,
    ) -> torch.Tensor:
        steps, zones, _ = state.shape
        node_ids = torch.arange(zones, device=state.device)
        embeddings = self.node_embedding(node_ids)[None, :, :].expand(steps, -1, -1)
        state_hidden = self.state_encoder(
            torch.cat([state, messages, calendar_phase[:, None, :].expand(-1, zones, -1), embeddings], dim=-1)
        )
        action_hidden = self.action_encoder(action)
        raw_delta = self.head(torch.cat([state_hidden, action_hidden], dim=-1))
        if not action_conditioned:
            return raw_delta
        presence = action.abs().sum(dim=-1, keepdim=True).gt(1.0e-8).to(raw_delta.dtype)
        return raw_delta * presence


def train_residual_model(
    examples: list[ResidualExample],
    config: ResidualConfig,
    seed: int,
    *,
    action_conditioned: bool,
) -> tuple[DamGkResidualKernel, ActionScaler, dict[str, Any]]:
    if not examples:
        raise ValueError("residual kernel requires at least one training event")
    set_seed(seed)
    scaler = fit_action_scaler(examples)
    model = DamGkResidualKernel(config)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay
    )
    criterion = nn.SmoothL1Loss(beta=0.35)
    rng = np.random.default_rng(seed)
    arrays = []
    for example in examples:
        action = (
            example.test.action_future
            if action_conditioned
            else np.zeros_like(example.test.action_future)
        )
        state, messages, calendar_phase, action_values = example_features(
            example,
            example.relations,
            action,
            np.arange(1, 13, dtype=np.float32),
        )
        arrays.append(
            (
                state,
                messages,
                calendar_phase,
                action_values / scaler.values,
                example.target_delta,
            )
        )
    history = []
    for epoch in range(1, config.epochs + 1):
        model.train()
        losses = []
        for index in rng.permutation(len(arrays)):
            state, messages, calendar_phase, action, target = arrays[int(index)]
            optimizer.zero_grad(set_to_none=True)
            prediction = model(
                torch.from_numpy(state),
                torch.from_numpy(messages),
                torch.from_numpy(calendar_phase),
                torch.from_numpy(action),
                action_conditioned=action_conditioned,
            )
            loss = criterion(prediction, torch.from_numpy(target))
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), config.gradient_clip)
            optimizer.step()
            losses.append(float(loss.detach()))
        history.append({"epoch": epoch, "smooth_l1": float(np.mean(losses))})
    report = {
        "seed": seed,
        "config": asdict(config),
        "action_conditioned": action_conditioned,
        "parameter_count": int(sum(parameter.numel() for parameter in model.parameters())),
        "train_events": [example.name for example in examples],
        "history": history,
        "action_scaler": scaler.to_json(),
        "zero_action_anchor_is_architectural": action_conditioned,
    }
    return model, scaler, report


def predict_residual(
    model: DamGkResidualKernel,
    scaler: ActionScaler,
    example: ResidualExample,
    *,
    relations: np.ndarray | None = None,
    action_future: np.ndarray | None = None,
    action_age: np.ndarray | None = None,
    action_conditioned: bool,
) -> tuple[np.ndarray, np.ndarray]:
    relation_values = example.relations if relations is None else relations
    future = example.test.action_future if action_future is None else action_future
    age = np.arange(1, 13, dtype=np.float32) if action_age is None else action_age
    if not action_conditioned:
        future = np.zeros_like(future)
    state, messages, calendar_phase, action = example_features(
        example, relation_values, future, age
    )
    model.eval()
    with torch.no_grad():
        normalized_delta = model(
            torch.from_numpy(state),
            torch.from_numpy(messages),
            torch.from_numpy(calendar_phase),
            torch.from_numpy((action / scaler.values).astype(np.float32)),
            action_conditioned=action_conditioned,
        ).numpy()
    normalized_delta = np.clip(normalized_delta, -12.0, 12.0).astype(np.float32)
    raw_delta = normalized_delta * example.scale[None, ...]
    final = np.maximum(example.backbone_prediction + raw_delta, 0.0).astype(np.float32)
    return final, raw_delta.astype(np.float32)


def macro_pre_action_nmae(
    prediction: np.ndarray, example: ResidualExample
) -> float:
    indices = np.asarray([value - 1 for value in REPORT_HORIZONS], dtype=int)
    return float(
        (
            np.abs(prediction[indices] - example.truth[indices])
            / example.scale[None, ...]
        ).mean()
    )


def select_residual_config(
    events: dict[str, WeeklyEvent],
    relations_by_event: dict[str, np.ndarray],
    adjacency: np.ndarray,
    *,
    seed: int = 31,
    configs: Iterable[ResidualConfig] = CONFIGS,
) -> tuple[ResidualConfig, dict[str, Any]]:
    event_names = sorted(events)
    rows = []
    prediction_cache: dict[tuple[str, tuple[str, ...]], ResidualExample] = {}

    def residual_example(target_name: str, train_names: Iterable[str]) -> ResidualExample:
        key = (target_name, tuple(sorted(train_names)))
        if key not in prediction_cache:
            prediction_cache[key] = prepare_residual_example(
                events[target_name],
                {name: events[name] for name in key[1]},
                adjacency,
                relations_by_event[target_name],
            )
        return prediction_cache[key]

    selected_configs = list(configs)
    for config in selected_configs:
        for validation_name in event_names:
            train_names = [name for name in event_names if name != validation_name]
            training_examples = [
                residual_example(name, [other for other in train_names if other != name])
                for name in train_names
            ]
            validation_example = residual_example(validation_name, train_names)
            model, scaler, training = train_residual_model(
                training_examples,
                config,
                seed,
                action_conditioned=True,
            )
            prediction, _ = predict_residual(
                model,
                scaler,
                validation_example,
                action_conditioned=True,
            )
            rows.append(
                {
                    "config": config.name,
                    "training_events": train_names,
                    "validation_event": validation_name,
                    "primary_metric": macro_pre_action_nmae(
                        prediction, validation_example
                    ),
                    "training_final_loss": training["history"][-1]["smooth_l1"],
                }
            )
    summary = {
        config.name: float(
            np.mean(
                [row["primary_metric"] for row in rows if row["config"] == config.name]
            )
        )
        for config in selected_configs
    }
    selected_name = min(summary, key=summary.get)
    selected = next(config for config in selected_configs if config.name == selected_name)
    return selected, {
        "selection_rule": "lowest mean three-fold leave-one-training-action-out macro pre-action normalized MAE",
        "seed": seed,
        "rows": rows,
        "summary": summary,
        "selected_config": selected_name,
        "backbone_crossfit_rule": (
            "inner validation backbone uses the two residual-training actions; each residual-training "
            "event backbone uses only the other residual-training action"
        ),
    }


def final_crossfit_examples(
    events: dict[str, WeeklyEvent],
    relations_by_event: dict[str, np.ndarray],
    adjacency: np.ndarray,
) -> list[ResidualExample]:
    names = sorted(events)
    return [
        prepare_residual_example(
            events[name],
            {other: events[other] for other in names if other != name},
            adjacency,
            relations_by_event[name],
        )
        for name in names
    ]


def test_residual_example(
    name: str,
    test: WeeklyTestInput,
    backbone_prediction: np.ndarray,
    relations: np.ndarray,
) -> ResidualExample:
    scale = np.maximum(test.raw_history.mean(axis=0), 1.0).astype(np.float32)
    return ResidualExample(
        name=name,
        test=test,
        backbone_prediction=backbone_prediction,
        truth=np.zeros_like(backbone_prediction, dtype=np.float32),
        scale=scale,
        target_delta=np.zeros_like(backbone_prediction, dtype=np.float32),
        relations=relations,
    )


def action_control_inputs(
    control_id: str,
    example: ResidualExample,
    zone_metadata: pd.DataFrame,
    *,
    swap_action: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    future = example.test.action_future.copy()
    relations = example.relations.copy()
    age = np.arange(1, 13, dtype=np.float32)
    audit: dict[str, Any] = {"control_id": control_id}
    if control_id == "correct_action":
        return future, age, relations, audit
    if control_id == "action_deleted":
        future[:] = 0.0
        age[:] = 0.0
        relations[2] = 0.0
    elif control_id == "effective_date_minus_4w":
        age += 4.0
    elif control_id == "effective_date_plus_4w":
        shifted = np.zeros_like(future)
        shifted[4:] = future[:8]
        future = shifted
        age = np.concatenate(
            [np.zeros(4, dtype=np.float32), np.arange(1, 9, dtype=np.float32)]
        )
    elif control_id == "action_component_permutation":
        permutation = np.roll(np.arange(COMPONENT_COUNT), 1)
        future[..., :COMPONENT_COUNT] = future[..., permutation]
        audit["component_permutation"] = permutation.tolist()
        audit["permutation_has_fixed_points"] = bool(
            np.equal(permutation, np.arange(COMPONENT_COUNT)).any()
        )
    elif control_id == "wrong_spatial_scope":
        cbd = zone_metadata.sort_values("zone_id")["cbd_exposure"].to_numpy(
            dtype=np.float32
        )
        future[..., :12] *= cbd[None, :, None]
        future[..., 12] = cbd[None, :]
        relations[2] = np.diag(cbd).astype(np.float32)
        audit["wrong_scope"] = "CBD-only for every held-out action"
        audit["nonzero_zone_count"] = int(cbd.sum())
    elif control_id == "cross_event_action_swap":
        if swap_action is None:
            raise ValueError("cross-event action swap requires a training-event action")
        future = swap_action.copy()
        exposure = future[0, :, 12]
        relations[2] = np.diag(exposure).astype(np.float32)
        audit["swap_action_sha256"] = hashlib.sha256(future.tobytes()).hexdigest()
    elif control_id == "zone_exposure_shuffle_seed_20260723":
        permutation = np.random.default_rng(20260723).permutation(N_ZONES)
        future = future[:, permutation, :]
        exposure = future[0, :, 12]
        relations[2] = np.diag(exposure).astype(np.float32)
        audit["zone_permutation_sha256"] = hashlib.sha256(
            permutation.astype(np.int16).tobytes()
        ).hexdigest()
    else:
        raise ValueError(f"unknown control: {control_id}")
    return future, age, relations, audit


def prediction_frame(fold_id: str, prediction: np.ndarray) -> pd.DataFrame:
    rows = []
    for horizon_index in range(12):
        frame = pd.DataFrame(
            {
                "fold_id": fold_id,
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
        ["fold_id", "zone_id", "horizon_week"]
    ).reset_index(drop=True)


def smoke_config() -> ResidualConfig:
    return replace(CONFIGS[0], name="smoke_compact", epochs=2)


def save_checkpoint(
    path: Path,
    model: DamGkResidualKernel,
    scaler: ActionScaler,
    training: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "schema": "gwm_bench.foundation_v5_dam_gk_residual_kernel.v1",
            "state_dict": model.state_dict(),
            "config": training["config"],
            "action_scaler": scaler.to_json(),
            "training": training,
        },
        path,
    )


def load_checkpoint(
    path: Path,
) -> tuple[DamGkResidualKernel, ActionScaler, dict[str, Any]]:
    payload = torch.load(path, map_location="cpu", weights_only=False)
    config = ResidualConfig(**payload["config"])
    model = DamGkResidualKernel(config)
    model.load_state_dict(payload["state_dict"])
    scaler = ActionScaler(
        values=np.asarray(payload["action_scaler"]["values"], dtype=np.float32)
    )
    return model, scaler, payload["training"]


def json_sha256(payload: Any) -> str:
    value = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(value).hexdigest()
