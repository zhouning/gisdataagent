"""Leakage-controlled candidate views, matched baselines, and metrics for IEC."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from typing import Iterable, Mapping

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.neural_network import MLPRegressor

from data_agent.uwm.regimeworld_iec_generator import (
    ControlledScenario,
    ControlledTrajectory,
)
from data_agent.uwm.regimeworld_iec_execution_guard import (
    ExternalEvaluationAuthorization,
)


class ModelVariant(StrEnum):
    NO_ACTION = "no_action_transition"
    MAGNITUDE = "magnitude_only_action"
    OPAQUE_TOKEN = "opaque_event_token"
    PRIMITIVE = "primitive_compositional_uwm"
    COMPONENT_SHUFFLED = "component_shuffled"
    ACTION_PERMUTED = "action_permuted"
    ENVIRONMENT_SPECIFIC = "environment_specific_response"


class Architecture(StrEnum):
    LINEAR_GRAPH = "transparent_linear_graph_transition"
    NONLINEAR_GRAPH_MLP = "nonlinear_graph_history_mlp"


@dataclass(frozen=True)
class TemporalWindow:
    start_inclusive: int
    stop_exclusive: int

    def validate(self, n_steps: int) -> None:
        if self.start_inclusive < 1:
            raise ValueError("two-step feature history requires start_inclusive >= 1")
        if not self.start_inclusive < self.stop_exclusive <= n_steps:
            raise ValueError("temporal window is outside the trajectory")


@dataclass(frozen=True)
class CandidateTrajectoryView:
    """The complete field surface available to candidate models and scalers."""

    scenario_name: str
    scenario_seed: int
    environment_id: int
    graph: np.ndarray
    states: np.ndarray
    intended_actions: np.ndarray

    @property
    def n_steps(self) -> int:
        return int(self.intended_actions.shape[0])

    @property
    def n_nodes(self) -> int:
        return int(self.intended_actions.shape[1])


@dataclass(frozen=True)
class AuditorTrajectoryView:
    """Oracle fields that are prohibited from candidate construction and selection."""

    scenario_name: str
    environment_id: int
    implemented_actions: np.ndarray
    contamination: np.ndarray
    transition_means: np.ndarray
    action_responses: np.ndarray


@dataclass(frozen=True)
class ControlOnlyTrajectoryView:
    """Fields available only to explicitly declared shortcut-positive controls."""

    scenario_name: str
    environment_id: int
    event_token: np.ndarray
    environment_shortcut: np.ndarray


@dataclass(frozen=True)
class CandidateRows:
    features: np.ndarray
    targets: np.ndarray
    environment_ids: np.ndarray
    transition_indices: np.ndarray
    node_indices: np.ndarray
    action_active: np.ndarray
    feature_names: tuple[str, ...]


@dataclass(frozen=True)
class FrozenRobustScaler:
    center: np.ndarray
    scale: np.ndarray

    @classmethod
    def fit(cls, features: np.ndarray) -> "FrozenRobustScaler":
        features = _as_2d(features, "features")
        center = np.median(features, axis=0)
        q25, q75 = np.percentile(features, [25.0, 75.0], axis=0)
        scale = q75 - q25
        scale[np.abs(scale) < 1e-12] = 1.0
        return cls(center=center, scale=scale)

    def transform(self, features: np.ndarray) -> np.ndarray:
        features = _as_2d(features, "features")
        if features.shape[1] != self.center.shape[0]:
            raise ValueError("feature width does not match frozen scaler")
        return (features - self.center) / self.scale


@dataclass(frozen=True)
class FittedCandidateModel:
    variant: ModelVariant
    architecture: Architecture
    hyperparameter: float
    scaler: FrozenRobustScaler
    estimator: Ridge | MLPRegressor
    feature_names: tuple[str, ...]
    validation_macro_nmae: float

    def predict(self, rows: CandidateRows) -> np.ndarray:
        if rows.feature_names != self.feature_names:
            raise ValueError("candidate feature schema changed after model freeze")
        return np.asarray(
            self.estimator.predict(self.scaler.transform(rows.features)),
            dtype=np.float64,
        )

    def artifact_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "variant": self.variant.value,
            "architecture": self.architecture.value,
            "hyperparameter": self.hyperparameter,
            "feature_names": list(self.feature_names),
            "scaler_center": self.scaler.center.tolist(),
            "scaler_scale": self.scaler.scale.tolist(),
            "validation_macro_nmae": self.validation_macro_nmae,
        }
        if isinstance(self.estimator, Ridge):
            payload["coefficient"] = np.asarray(self.estimator.coef_).tolist()
            payload["intercept"] = np.asarray(self.estimator.intercept_).tolist()
        else:
            payload["coefs"] = [np.asarray(value).tolist() for value in self.estimator.coefs_]
            payload["intercepts"] = [
                np.asarray(value).tolist() for value in self.estimator.intercepts_
            ]
        return payload


def candidate_model_sha256(model: FittedCandidateModel) -> str:
    payload = model.artifact_payload()
    payload.pop("scaler_center")
    payload.pop("scaler_scale")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def candidate_scaler_sha256(model: FittedCandidateModel) -> str:
    payload = {
        "feature_names": list(model.feature_names),
        "center": model.scaler.center.tolist(),
        "scale": model.scaler.scale.tolist(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _readonly_copy(value: np.ndarray) -> np.ndarray:
    copied = np.array(value, dtype=np.float64, copy=True)
    copied.flags.writeable = False
    return copied


def candidate_view(
    scenario: ControlledScenario,
    trajectory: ControlledTrajectory,
) -> CandidateTrajectoryView:
    if trajectory.environment_id >= scenario.spec.n_environments:
        raise ValueError("trajectory does not belong to scenario")
    return CandidateTrajectoryView(
        scenario_name=scenario.spec.name,
        scenario_seed=scenario.spec.seed,
        environment_id=trajectory.environment_id,
        graph=_readonly_copy(scenario.graph),
        states=_readonly_copy(trajectory.states),
        intended_actions=_readonly_copy(trajectory.intended_actions),
    )


def development_candidate_views(
    scenario: ControlledScenario,
) -> tuple[CandidateTrajectoryView, ...]:
    return tuple(
        candidate_view(scenario, trajectory)
        for trajectory in scenario.trajectories[:-1]
    )


def external_candidate_view(
    scenario: ControlledScenario,
    *,
    external_authorization: ExternalEvaluationAuthorization,
) -> CandidateTrajectoryView:
    if scenario.spec.name != external_authorization.scenario_name:
        raise PermissionError("external authorization does not cover this scenario")
    return candidate_view(scenario, scenario.trajectories[-1])


def auditor_view(
    scenario: ControlledScenario,
    trajectory: ControlledTrajectory,
) -> AuditorTrajectoryView:
    return AuditorTrajectoryView(
        scenario_name=scenario.spec.name,
        environment_id=trajectory.environment_id,
        implemented_actions=_readonly_copy(trajectory.implemented_actions),
        contamination=_readonly_copy(trajectory.contamination),
        transition_means=_readonly_copy(trajectory.transition_means),
        action_responses=_readonly_copy(trajectory.action_responses),
    )


def control_only_view(
    scenario: ControlledScenario,
    trajectory: ControlledTrajectory,
) -> ControlOnlyTrajectoryView:
    return ControlOnlyTrajectoryView(
        scenario_name=scenario.spec.name,
        environment_id=trajectory.environment_id,
        event_token=_readonly_copy(
            (np.abs(trajectory.intended_actions).sum(axis=2) > 1e-12).astype(
                np.float64
            )
        ),
        environment_shortcut=_readonly_copy(trajectory.shortcuts[:, :, 1]),
    )


def _stable_seed(*parts: object) -> int:
    raw = "|".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") % (2**32)


def _opaque_control_code(
    control: ControlOnlyTrajectoryView,
    *,
    intended_actions: np.ndarray | None,
) -> np.ndarray:
    if intended_actions is None:
        event_active = control.event_token
    else:
        event_active = (np.abs(intended_actions).sum(axis=2) > 1e-12).astype(np.float64)
    environment = control.environment_shortcut
    return np.stack(
        [
            event_active,
            environment,
            event_active * environment,
            event_active * (1.0 - environment),
        ],
        axis=2,
    )


def _component_shuffle(actions: np.ndarray, view: CandidateTrajectoryView) -> np.ndarray:
    shuffled = np.empty_like(actions)
    for step in range(actions.shape[0]):
        for node in range(actions.shape[1]):
            rng = np.random.default_rng(
                _stable_seed(view.scenario_seed, view.environment_id, "component", step, node)
            )
            shuffled[step, node] = actions[step, node, rng.permutation(4)]
    return shuffled


def _action_permutation(actions: np.ndarray, view: CandidateTrajectoryView) -> np.ndarray:
    flat = actions.reshape(-1, actions.shape[-1])
    rng = np.random.default_rng(
        _stable_seed(view.scenario_seed, view.environment_id, "action_rows")
    )
    return flat[rng.permutation(flat.shape[0])].reshape(actions.shape)


def represented_actions(
    view: CandidateTrajectoryView,
    variant: ModelVariant | str,
    *,
    intended_actions: np.ndarray | None = None,
    control: ControlOnlyTrajectoryView | None = None,
) -> np.ndarray:
    variant = ModelVariant(variant)
    actions = np.asarray(
        view.intended_actions if intended_actions is None else intended_actions,
        dtype=np.float64,
    )
    if actions.shape != view.intended_actions.shape:
        raise ValueError("action override shape does not match candidate view")
    if variant is ModelVariant.NO_ACTION:
        return np.zeros_like(actions)
    if variant is ModelVariant.MAGNITUDE:
        magnitude = np.linalg.norm(actions, axis=-1, keepdims=True)
        return np.repeat(magnitude / 2.0, 4, axis=-1)
    if variant is ModelVariant.OPAQUE_TOKEN:
        if control is None:
            raise PermissionError("opaque-token variant requires its control-only view")
        if (
            control.scenario_name != view.scenario_name
            or control.environment_id != view.environment_id
        ):
            raise ValueError("control-only view does not match candidate view")
        return _opaque_control_code(
            control,
            intended_actions=None if intended_actions is None else actions,
        )
    if variant in {ModelVariant.PRIMITIVE, ModelVariant.ENVIRONMENT_SPECIFIC}:
        return actions.copy()
    if variant is ModelVariant.COMPONENT_SHUFFLED:
        return _component_shuffle(actions, view)
    if variant is ModelVariant.ACTION_PERMUTED:
        return _action_permutation(actions, view)
    raise AssertionError(f"unhandled model variant: {variant}")


def _base_feature_names() -> tuple[str, ...]:
    names: list[str] = []
    for block in ("state_t", "state_tm1", "graph_state_t", "graph_state_tm1"):
        names.extend(f"{block}_{index}" for index in range(4))
    return tuple(names)


def _action_feature_names(variant: ModelVariant) -> tuple[str, ...]:
    names: list[str] = []
    for block in ("action_t", "action_tm1", "graph_action_t", "graph_action_tm1"):
        names.extend(f"{variant.value}_{block}_{index}" for index in range(4))
    if variant is not ModelVariant.ENVIRONMENT_SPECIFIC:
        return tuple(names)
    return tuple(f"development_env_{environment}_{name}" for environment in range(3) for name in names)


def build_candidate_rows(
    view: CandidateTrajectoryView,
    variant: ModelVariant | str,
    window: TemporalWindow,
    *,
    intended_actions: np.ndarray | None = None,
    control: ControlOnlyTrajectoryView | None = None,
) -> CandidateRows:
    variant = ModelVariant(variant)
    window.validate(view.n_steps)
    represented = represented_actions(
        view,
        variant,
        intended_actions=intended_actions,
        control=control,
    )
    features: list[np.ndarray] = []
    targets: list[np.ndarray] = []
    transitions: list[np.ndarray] = []
    active_rows: list[np.ndarray] = []
    nodes = np.arange(view.n_nodes, dtype=np.int64)
    for step in range(window.start_inclusive, window.stop_exclusive):
        state_block = np.concatenate(
            [
                view.states[step],
                view.states[step - 1],
                view.graph @ view.states[step],
                view.graph @ view.states[step - 1],
            ],
            axis=1,
        )
        action_block = np.concatenate(
            [
                represented[step],
                represented[step - 1],
                view.graph @ represented[step],
                view.graph @ represented[step - 1],
            ],
            axis=1,
        )
        if variant is ModelVariant.ENVIRONMENT_SPECIFIC:
            interacted = np.zeros((view.n_nodes, 48), dtype=np.float64)
            if view.environment_id < 3:
                offset = 16 * view.environment_id
                interacted[:, offset : offset + 16] = action_block
            action_block = interacted
        features.append(np.concatenate([state_block, action_block], axis=1))
        targets.append(view.states[step + 1])
        transitions.append(np.full(view.n_nodes, step, dtype=np.int64))
        active_rows.append(
            (np.abs(view.intended_actions[step]).sum(axis=1) > 1e-12).astype(np.int8)
        )
    matrix = np.concatenate(features, axis=0)
    target = np.concatenate(targets, axis=0)
    transition_index = np.concatenate(transitions)
    feature_names = _base_feature_names() + _action_feature_names(variant)
    if matrix.shape[1] != len(feature_names):
        raise AssertionError("feature schema and matrix width diverged")
    row_count = matrix.shape[0]
    return CandidateRows(
        features=matrix,
        targets=target,
        environment_ids=np.full(row_count, view.environment_id, dtype=np.int64),
        transition_indices=transition_index,
        node_indices=np.tile(nodes, window.stop_exclusive - window.start_inclusive),
        action_active=np.concatenate(active_rows),
        feature_names=feature_names,
    )


def concatenate_rows(rows: Iterable[CandidateRows]) -> CandidateRows:
    rows = tuple(rows)
    if not rows:
        raise ValueError("at least one candidate row block is required")
    schema = rows[0].feature_names
    if any(row.feature_names != schema for row in rows[1:]):
        raise ValueError("candidate row schemas do not match")
    return CandidateRows(
        features=np.concatenate([row.features for row in rows], axis=0),
        targets=np.concatenate([row.targets for row in rows], axis=0),
        environment_ids=np.concatenate([row.environment_ids for row in rows]),
        transition_indices=np.concatenate([row.transition_indices for row in rows]),
        node_indices=np.concatenate([row.node_indices for row in rows]),
        action_active=np.concatenate([row.action_active for row in rows]),
        feature_names=schema,
    )


def deterministic_stratified_sample(
    rows: CandidateRows,
    *,
    budget: int,
    seed: int,
) -> CandidateRows:
    """Sample equal candidate keys with proportional environment/action strata."""

    row_count = rows.features.shape[0]
    if budget <= 0:
        raise ValueError("row budget must be positive")
    if budget >= row_count:
        return rows
    strata = np.column_stack([rows.environment_ids, rows.action_active])
    unique, inverse, counts = np.unique(
        strata,
        axis=0,
        return_inverse=True,
        return_counts=True,
    )
    exact = budget * counts / row_count
    allocations = np.floor(exact).astype(np.int64)
    allocations = np.minimum(allocations, counts)
    remaining = budget - int(allocations.sum())
    order = sorted(
        range(unique.shape[0]),
        key=lambda index: (
            -(exact[index] - allocations[index]),
            int(unique[index, 0]),
            int(unique[index, 1]),
        ),
    )
    for index in order:
        if remaining == 0:
            break
        if allocations[index] < counts[index]:
            allocations[index] += 1
            remaining -= 1
    if remaining:
        raise AssertionError("stratified allocation did not exhaust the row budget")

    selected: list[int] = []
    for stratum_index, allocation in enumerate(allocations):
        candidates = np.flatnonzero(inverse == stratum_index)
        ranked = sorted(
            candidates.tolist(),
            key=lambda row_index: _stable_seed(
                seed,
                int(rows.environment_ids[row_index]),
                int(rows.action_active[row_index]),
                int(rows.transition_indices[row_index]),
                int(rows.node_indices[row_index]),
            ),
        )
        selected.extend(ranked[: int(allocation)])
    selected_indices = np.asarray(sorted(selected), dtype=np.int64)
    if selected_indices.shape != (budget,) or np.unique(selected_indices).size != budget:
        raise AssertionError("stratified sample is not a unique fixed-size subset")
    return CandidateRows(
        features=rows.features[selected_indices],
        targets=rows.targets[selected_indices],
        environment_ids=rows.environment_ids[selected_indices],
        transition_indices=rows.transition_indices[selected_indices],
        node_indices=rows.node_indices[selected_indices],
        action_active=rows.action_active[selected_indices],
        feature_names=rows.feature_names,
    )


def _as_2d(value: np.ndarray, label: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != 2 or array.shape[0] == 0:
        raise ValueError(f"{label} must be a non-empty two-dimensional array")
    return array


def prediction_metrics(observed: np.ndarray, predicted: np.ndarray) -> dict[str, object]:
    observed = _as_2d(observed, "observed")
    predicted = _as_2d(predicted, "predicted")
    if observed.shape != predicted.shape:
        raise ValueError("observed and predicted shapes do not match")
    errors = predicted - observed
    mae = np.mean(np.abs(errors), axis=0)
    rmse = np.sqrt(np.mean(errors**2, axis=0))
    denominator = np.maximum(np.mean(np.abs(observed), axis=0), 1e-8)
    nmae = mae / denominator
    wape = np.sum(np.abs(errors), axis=0) / np.maximum(
        np.sum(np.abs(observed), axis=0), 1e-8
    )
    return {
        "component_mae": mae.tolist(),
        "component_rmse": rmse.tolist(),
        "component_nmae": nmae.tolist(),
        "component_wape": wape.tolist(),
        "macro_nmae": float(np.mean(nmae)),
        "row_count": int(observed.shape[0]),
    }


def _fit_estimator(
    architecture: Architecture,
    hyperparameter: float,
    features: np.ndarray,
    targets: np.ndarray,
    *,
    random_state: int,
) -> Ridge | MLPRegressor:
    if architecture is Architecture.LINEAR_GRAPH:
        estimator: Ridge | MLPRegressor = Ridge(alpha=hyperparameter, fit_intercept=True)
    else:
        estimator = MLPRegressor(
            hidden_layer_sizes=(64, 32),
            activation="tanh",
            solver="adam",
            alpha=hyperparameter,
            batch_size=min(512, features.shape[0]),
            learning_rate_init=0.001,
            max_iter=40,
            early_stopping=False,
            random_state=random_state,
        )
    estimator.fit(features, targets)
    return estimator


def fit_candidate_model(
    train: CandidateRows,
    validation: CandidateRows,
    *,
    variant: ModelVariant | str,
    architecture: Architecture | str,
    hyperparameters: Iterable[float],
    random_state: int,
) -> FittedCandidateModel:
    variant = ModelVariant(variant)
    architecture = Architecture(architecture)
    if train.feature_names != validation.feature_names:
        raise ValueError("train and validation feature schemas differ")
    scaler = FrozenRobustScaler.fit(train.features)
    scaled_train = scaler.transform(train.features)
    candidates: list[tuple[float, float, Ridge | MLPRegressor]] = []
    for hyperparameter in tuple(hyperparameters):
        estimator = _fit_estimator(
            architecture,
            float(hyperparameter),
            scaled_train,
            train.targets,
            random_state=random_state,
        )
        predicted = estimator.predict(scaler.transform(validation.features))
        score = float(prediction_metrics(validation.targets, predicted)["macro_nmae"])
        candidates.append((score, float(hyperparameter), estimator))
    if not candidates:
        raise ValueError("at least one frozen hyperparameter is required")
    score, hyperparameter, _ = min(candidates, key=lambda item: (item[0], item[1]))
    combined = concatenate_rows((train, validation))
    estimator = _fit_estimator(
        architecture,
        hyperparameter,
        scaler.transform(combined.features),
        combined.targets,
        random_state=random_state,
    )
    return FittedCandidateModel(
        variant=variant,
        architecture=architecture,
        hyperparameter=hyperparameter,
        scaler=scaler,
        estimator=estimator,
        feature_names=train.feature_names,
        validation_macro_nmae=score,
    )


def semantic_prediction_gate(
    metrics: Mapping[str, Mapping[str, object]],
    *,
    primitive_name: str = ModelVariant.PRIMITIVE.value,
) -> bool:
    primitive = metrics[primitive_name]
    primitive_macro = float(primitive["macro_nmae"])
    primitive_components = np.asarray(primitive["component_nmae"], dtype=np.float64)
    controls = (
        ModelVariant.NO_ACTION.value,
        ModelVariant.MAGNITUDE.value,
        ModelVariant.OPAQUE_TOKEN.value,
        ModelVariant.COMPONENT_SHUFFLED.value,
        ModelVariant.ACTION_PERMUTED.value,
    )
    for control_name in controls:
        control = metrics[control_name]
        if primitive_macro >= float(control["macro_nmae"]):
            return False
        control_components = np.asarray(control["component_nmae"], dtype=np.float64)
        if int(np.count_nonzero(primitive_components < control_components)) < 3:
            return False
    return True


def predict_action_response(
    model: FittedCandidateModel,
    view: CandidateTrajectoryView,
    window: TemporalWindow,
    *,
    intended_actions: np.ndarray | None = None,
    control: ControlOnlyTrajectoryView | None = None,
) -> np.ndarray:
    actions = np.asarray(
        view.intended_actions if intended_actions is None else intended_actions,
        dtype=np.float64,
    )
    factual_rows = build_candidate_rows(
        view,
        model.variant,
        window,
        intended_actions=actions,
        control=control,
    )
    zero_rows = build_candidate_rows(
        view,
        model.variant,
        window,
        intended_actions=np.zeros_like(actions),
        control=control,
    )
    response = model.predict(factual_rows) - model.predict(zero_rows)
    return response.reshape(
        window.stop_exclusive - window.start_inclusive,
        view.n_nodes,
        -1,
    )


def finite_difference_action_jacobian(
    model: FittedCandidateModel,
    view: CandidateTrajectoryView,
    *,
    transition_index: int,
    epsilon: float = 1e-5,
    control: ControlOnlyTrajectoryView | None = None,
) -> np.ndarray:
    if not 1 <= transition_index < view.n_steps:
        raise ValueError("transition_index is outside the two-step candidate window")
    if epsilon <= 0:
        raise ValueError("epsilon must be positive")
    base_actions = np.array(view.intended_actions, copy=True)
    jacobian = np.zeros((view.n_nodes, 4, view.n_nodes, 4), dtype=np.float64)
    window = TemporalWindow(transition_index, transition_index + 1)
    for source_node in range(view.n_nodes):
        for action_index in range(4):
            plus = base_actions.copy()
            minus = base_actions.copy()
            plus[transition_index, source_node, action_index] += epsilon
            minus[transition_index, source_node, action_index] -= epsilon
            plus_prediction = model.predict(
                build_candidate_rows(
                    view,
                    model.variant,
                    window,
                    intended_actions=plus,
                    control=control,
                )
            )
            minus_prediction = model.predict(
                build_candidate_rows(
                    view,
                    model.variant,
                    window,
                    intended_actions=minus,
                    control=control,
                )
            )
            jacobian[:, :, source_node, action_index] = (
                plus_prediction - minus_prediction
            ) / (2.0 * epsilon)
    return jacobian


def response_recovery_metrics(
    predicted_response: np.ndarray,
    reference_response: np.ndarray,
) -> dict[str, float]:
    predicted = np.asarray(predicted_response, dtype=np.float64)
    reference = np.asarray(reference_response, dtype=np.float64)
    if predicted.shape != reference.shape or predicted.size == 0:
        raise ValueError("response arrays must be non-empty with matching shapes")
    rmse = float(np.sqrt(np.mean((predicted - reference) ** 2)))
    reference_rms = float(np.sqrt(np.mean(reference**2)))
    return {
        "rmse": rmse,
        "reference_rms": reference_rms,
        "relative_rmse": rmse / max(reference_rms, 1e-8),
    }


def jacobian_recovery_metrics(
    predicted_jacobian: np.ndarray,
    reference_jacobian: np.ndarray,
    *,
    nonzero_tolerance: float = 1e-10,
) -> dict[str, float | int | None]:
    predicted = np.asarray(predicted_jacobian, dtype=np.float64)
    reference = np.asarray(reference_jacobian, dtype=np.float64)
    if predicted.shape != reference.shape or predicted.size == 0:
        raise ValueError("Jacobian arrays must be non-empty with matching shapes")
    difference_norm = float(np.linalg.norm(predicted - reference))
    reference_norm = float(np.linalg.norm(reference))
    mask = np.abs(reference) > nonzero_tolerance
    nonzero_count = int(np.count_nonzero(mask))
    sign_agreement = (
        float(np.mean(np.sign(predicted[mask]) == np.sign(reference[mask])))
        if nonzero_count
        else None
    )
    return {
        "frobenius_error": difference_norm,
        "reference_frobenius_norm": reference_norm,
        "relative_frobenius_error": difference_norm / max(reference_norm, 1e-8),
        "nonzero_reference_count": nonzero_count,
        "nonzero_sign_agreement": sign_agreement,
    }
