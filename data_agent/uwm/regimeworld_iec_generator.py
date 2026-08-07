"""Standalone controlled graph dynamics for IEC component development.

This module does not bind to or validate the shared GWM Geospatial Kernel and
must not be treated as evidence from a GWM-based UWM instance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np


GENERATOR_ROLE = "standalone_controlled_simulator"
SHARED_GWM_GEOSPATIAL_KERNEL_BOUND = False


ResponseFamily = Literal["linear", "saturating", "threshold", "interaction", "delayed"]
ActionGeometry = Literal["independent", "bundled"]
ImplementationMode = Literal["exact", "partial_delayed"]
ContaminationMode = Literal["absent", "latent"]
ResponseInvariance = Literal["shared", "environment_specific"]
TargetSupport = Literal["interpolation", "extrapolation"]
ShortcutMode = Literal["absent", "event_environment_correlated"]


@dataclass(frozen=True)
class ControlledScenarioSpec:
    name: str
    seed: int
    response_family: ResponseFamily
    action_geometry: ActionGeometry = "independent"
    implementation_mode: ImplementationMode = "exact"
    contamination_mode: ContaminationMode = "absent"
    response_invariance: ResponseInvariance = "shared"
    target_support: TargetSupport = "interpolation"
    shortcut_mode: ShortcutMode = "absent"
    n_environments: int = 4
    n_nodes: int = 16
    n_steps: int = 64
    state_dim: int = 4
    action_dim: int = 4
    noise_std: float = 0.01

    def __post_init__(self) -> None:
        allowed = {
            "response_family": {
                "linear",
                "saturating",
                "threshold",
                "interaction",
                "delayed",
            },
            "action_geometry": {"independent", "bundled"},
            "implementation_mode": {"exact", "partial_delayed"},
            "contamination_mode": {"absent", "latent"},
            "response_invariance": {"shared", "environment_specific"},
            "target_support": {"interpolation", "extrapolation"},
            "shortcut_mode": {"absent", "event_environment_correlated"},
        }
        for field_name, choices in allowed.items():
            value = getattr(self, field_name)
            if value not in choices:
                raise ValueError(f"invalid {field_name}: {value!r}")
        if self.n_environments < 2:
            raise ValueError("n_environments must include development and external environments")
        if self.n_nodes < 4 or self.n_steps < 8:
            raise ValueError("controlled scenario is too small")
        if self.state_dim != 4 or self.action_dim != 4:
            raise ValueError("v1 generator fixes state_dim=4 and action_dim=4")
        if self.noise_std < 0:
            raise ValueError("noise_std must be non-negative")


@dataclass(frozen=True)
class ControlledTrajectory:
    environment_id: int
    states: np.ndarray
    intended_actions: np.ndarray
    implemented_actions: np.ndarray
    contamination: np.ndarray
    shortcuts: np.ndarray
    transition_means: np.ndarray
    action_responses: np.ndarray
    innovations: np.ndarray


@dataclass(frozen=True)
class ControlledScenario:
    spec: ControlledScenarioSpec
    graph: np.ndarray
    trajectories: tuple[ControlledTrajectory, ...]


def _row_normalized_graph(n_nodes: int, rng: np.random.Generator) -> np.ndarray:
    graph = np.zeros((n_nodes, n_nodes), dtype=np.float64)
    for node in range(n_nodes):
        graph[node, (node - 1) % n_nodes] = 1.0
        graph[node, (node + 1) % n_nodes] = 1.0
    candidates = [
        (source, target)
        for source in range(n_nodes)
        for target in range(source + 2, n_nodes)
        if target != (source - 1) % n_nodes
    ]
    for index in rng.choice(len(candidates), size=max(1, n_nodes // 2), replace=False):
        source, target = candidates[int(index)]
        graph[source, target] = 1.0
        graph[target, source] = 1.0
    return graph / graph.sum(axis=1, keepdims=True)


class ControlledUrbanDynamics:
    """Stable urban graph dynamics exposing the exact transition response."""

    def __init__(self, spec: ControlledScenarioSpec):
        self.spec = spec
        rng = np.random.default_rng(spec.seed)
        self.graph = _row_normalized_graph(spec.n_nodes, rng)
        self.state_matrix = np.array(
            [
                [0.42, 0.04, 0.00, 0.00],
                [0.02, 0.38, 0.03, 0.00],
                [0.00, 0.02, 0.34, 0.04],
                [0.03, 0.00, 0.02, 0.30],
            ],
            dtype=np.float64,
        )
        self.graph_matrix = np.diag([0.12, 0.10, 0.08, 0.06])
        raw_response = rng.normal(0.0, 1.0, size=(spec.state_dim, spec.action_dim))
        self.shared_response_matrix = 0.08 * raw_response / np.maximum(
            np.linalg.norm(raw_response, axis=0, keepdims=True), 1e-12
        )
        raw_contamination = rng.normal(
            0.0, 1.0, size=(spec.state_dim, spec.action_dim)
        )
        self.contamination_matrix = 0.04 * raw_contamination / np.maximum(
            np.linalg.norm(raw_contamination, axis=0, keepdims=True), 1e-12
        )
        self.environment_biases = rng.normal(
            0.0, 0.015, size=(spec.n_environments, spec.state_dim)
        )
        self.node_implementation = np.linspace(0.55, 0.95, spec.n_nodes)[:, None]
        self.action_scale = np.array([0.7, 0.9, 0.8, 1.0], dtype=np.float64)
        self.threshold = np.array([0.20, 0.25, 0.20, 0.30], dtype=np.float64)

    def response_matrix(self, environment_id: int) -> np.ndarray:
        if not 0 <= environment_id < self.spec.n_environments:
            raise ValueError("invalid environment_id")
        matrix = self.shared_response_matrix
        if self.spec.response_invariance == "environment_specific":
            scales = np.array([1.0, 0.9, 1.1, 1.35], dtype=np.float64)
            scale = scales[environment_id % len(scales)]
            matrix = matrix * scale
            if environment_id == self.spec.n_environments - 1:
                matrix = matrix[:, [1, 0, 3, 2]]
        return matrix

    def transformed_action(
        self,
        action: np.ndarray,
        previous_action: np.ndarray,
    ) -> np.ndarray:
        action = np.asarray(action, dtype=np.float64)
        previous_action = np.asarray(previous_action, dtype=np.float64)
        if action.shape != (self.spec.n_nodes, self.spec.action_dim):
            raise ValueError("action shape does not match scenario")
        if previous_action.shape != action.shape:
            raise ValueError("previous_action shape does not match action")
        family = self.spec.response_family
        if family == "linear":
            return action
        if family == "saturating":
            return np.tanh(action / self.action_scale)
        if family == "threshold":
            return np.sign(action) * np.maximum(np.abs(action) - self.threshold, 0.0)
        if family == "interaction":
            interactions = np.column_stack(
                [
                    action[:, 0] * action[:, 1],
                    action[:, 1] * action[:, 2],
                    action[:, 2] * action[:, 3],
                    action[:, 3] * action[:, 0],
                ]
            )
            return action + 0.35 * interactions
        if family == "delayed":
            return 0.35 * action + 0.65 * previous_action
        raise AssertionError(f"unhandled response family: {family}")

    def action_response(
        self,
        action: np.ndarray,
        previous_action: np.ndarray,
        environment_id: int,
    ) -> np.ndarray:
        transformed = self.transformed_action(action, previous_action)
        direct = transformed @ self.response_matrix(environment_id).T
        return direct + 0.15 * (self.graph @ direct)

    def action_jacobian(
        self,
        action: np.ndarray,
        previous_action: np.ndarray,
        environment_id: int,
    ) -> np.ndarray:
        """Full derivative by source-node current primitive action.

        The returned axes are receiving node, state component, source node,
        and primitive action component.
        """

        action = np.asarray(action, dtype=np.float64)
        previous_action = np.asarray(previous_action, dtype=np.float64)
        self.transformed_action(action, previous_action)
        n_nodes = self.spec.n_nodes
        matrix = self.response_matrix(environment_id)
        transform_jacobian = np.zeros(
            (n_nodes, self.spec.action_dim, self.spec.action_dim), dtype=np.float64
        )
        family = self.spec.response_family
        if family == "linear":
            transform_jacobian[:] = np.eye(self.spec.action_dim)
        elif family == "saturating":
            derivative = (
                1.0 - np.tanh(action / self.action_scale) ** 2
            ) / self.action_scale
            for node in range(n_nodes):
                transform_jacobian[node] = np.diag(derivative[node])
        elif family == "threshold":
            derivative = (np.abs(action) > self.threshold).astype(np.float64)
            for node in range(n_nodes):
                transform_jacobian[node] = np.diag(derivative[node])
        elif family == "interaction":
            for node in range(n_nodes):
                a0, a1, a2, a3 = action[node]
                transform_jacobian[node] = np.array(
                    [
                        [1.0 + 0.35 * a1, 0.35 * a0, 0.0, 0.0],
                        [0.0, 1.0 + 0.35 * a2, 0.35 * a1, 0.0],
                        [0.0, 0.0, 1.0 + 0.35 * a3, 0.35 * a2],
                        [0.35 * a3, 0.0, 0.0, 1.0 + 0.35 * a0],
                    ],
                    dtype=np.float64,
                )
        elif family == "delayed":
            transform_jacobian[:] = 0.35 * np.eye(self.spec.action_dim)
        else:
            raise AssertionError(f"unhandled response family: {family}")

        local = np.einsum("sq,nqp->nsp", matrix, transform_jacobian)
        propagation = np.eye(n_nodes) + 0.15 * self.graph
        return np.einsum("ij,jsp->isjp", propagation, local)

    def transition_mean(
        self,
        state: np.ndarray,
        action: np.ndarray,
        previous_action: np.ndarray,
        contamination: np.ndarray,
        environment_id: int,
    ) -> np.ndarray:
        state = np.asarray(state, dtype=np.float64)
        contamination = np.asarray(contamination, dtype=np.float64)
        if state.shape != (self.spec.n_nodes, self.spec.state_dim):
            raise ValueError("state shape does not match scenario")
        if contamination.shape != (self.spec.n_nodes, self.spec.action_dim):
            raise ValueError("contamination shape does not match scenario")
        base = state @ self.state_matrix.T
        base += (self.graph @ state) @ self.graph_matrix.T
        base += self.environment_biases[environment_id]
        response = self.action_response(action, previous_action, environment_id)
        contamination_response = contamination @ self.contamination_matrix.T
        return base + response + contamination_response

    def _intended_action_schedule(self, environment_id: int) -> np.ndarray:
        steps = np.arange(self.spec.n_steps, dtype=np.float64)
        schedule = np.zeros(
            (self.spec.n_steps, self.spec.n_nodes, self.spec.action_dim),
            dtype=np.float64,
        )
        node_scale = np.linspace(0.65, 1.0, self.spec.n_nodes)[:, None]
        development_offsets = (-0.04, 0.0, 0.04)
        environment_offset = (
            development_offsets[environment_id]
            if environment_id < self.spec.n_environments - 1
            else 0.0
        )
        if self.spec.action_geometry == "independent":
            for action_index in range(self.spec.action_dim):
                period = 11 + 3 * action_index
                phase = 2 * environment_id + action_index
                pulse = ((steps + phase) % period < (3 + action_index % 2)).astype(
                    np.float64
                )
                amplitude = 0.32 + 0.08 * action_index + environment_offset
                schedule[:, :, action_index] = pulse[:, None] * amplitude
                schedule[:, :, action_index] *= node_scale[:, 0]
        else:
            bundle = np.array([0.30, 0.45, 0.25, 0.55], dtype=np.float64)
            bundle *= 1.0 + environment_offset
            pulse = ((steps + 2 * environment_id) % 13 < 5).astype(np.float64)
            schedule = pulse[:, None, None] * node_scale[None, :, :] * bundle

        if (
            environment_id == self.spec.n_environments - 1
            and self.spec.target_support == "extrapolation"
        ):
            schedule *= 1.8
        return schedule

    def _implemented_action_schedule(self, intended: np.ndarray) -> np.ndarray:
        if self.spec.implementation_mode == "exact":
            return intended.copy()
        implemented = np.zeros_like(intended)
        for step in range(self.spec.n_steps):
            previous = implemented[step - 1] if step else 0.0
            implemented[step] = 0.65 * previous + 0.35 * (
                intended[step] * self.node_implementation
            )
        return implemented

    def _contamination_schedule(
        self,
        implemented: np.ndarray,
        environment_id: int,
    ) -> np.ndarray:
        if self.spec.contamination_mode == "absent":
            return np.zeros_like(implemented)
        active = (np.abs(implemented).sum(axis=2, keepdims=True) > 0).astype(np.float64)
        direction = np.roll(implemented, shift=1, axis=2)
        environment_scale = 0.20 + 0.04 * environment_id
        return active * (environment_scale * direction + 0.04)

    def _shortcut_schedule(
        self,
        intended: np.ndarray,
        environment_id: int,
    ) -> np.ndarray:
        if self.spec.shortcut_mode == "absent":
            return np.zeros((self.spec.n_steps, self.spec.n_nodes, 2), dtype=np.float64)
        event_active = (np.abs(intended).sum(axis=2) > 0).astype(np.float64)
        environment = np.full_like(
            event_active, environment_id / max(self.spec.n_environments - 1, 1)
        )
        return np.stack([event_active, environment], axis=2)

    def simulate_environment(self, environment_id: int) -> ControlledTrajectory:
        if not 0 <= environment_id < self.spec.n_environments:
            raise ValueError("invalid environment_id")
        intended = self._intended_action_schedule(environment_id)
        implemented = self._implemented_action_schedule(intended)
        contamination = self._contamination_schedule(implemented, environment_id)
        shortcuts = self._shortcut_schedule(intended, environment_id)
        states = np.zeros(
            (self.spec.n_steps + 1, self.spec.n_nodes, self.spec.state_dim),
            dtype=np.float64,
        )
        transition_means = np.zeros_like(states[:-1])
        action_responses = np.zeros_like(states[:-1])
        innovations = np.zeros_like(states[:-1])
        initial_rng = np.random.default_rng(self.spec.seed + 10_000 + environment_id)
        states[0] = initial_rng.normal(0.0, 0.04, size=states[0].shape)
        innovation_rng = np.random.default_rng(self.spec.seed + 20_000 + environment_id)
        for step in range(self.spec.n_steps):
            previous_action = implemented[step - 1] if step else np.zeros_like(implemented[0])
            action_responses[step] = self.action_response(
                implemented[step], previous_action, environment_id
            )
            transition_means[step] = self.transition_mean(
                states[step],
                implemented[step],
                previous_action,
                contamination[step],
                environment_id,
            )
            innovations[step] = innovation_rng.normal(
                0.0, self.spec.noise_std, size=states[step].shape
            )
            states[step + 1] = transition_means[step] + innovations[step]
        return ControlledTrajectory(
            environment_id=environment_id,
            states=states,
            intended_actions=intended,
            implemented_actions=implemented,
            contamination=contamination,
            shortcuts=shortcuts,
            transition_means=transition_means,
            action_responses=action_responses,
            innovations=innovations,
        )

    def generate(self) -> ControlledScenario:
        trajectories = tuple(
            self.simulate_environment(environment_id)
            for environment_id in range(self.spec.n_environments)
        )
        return ControlledScenario(
            spec=self.spec,
            graph=self.graph.copy(),
            trajectories=trajectories,
        )
