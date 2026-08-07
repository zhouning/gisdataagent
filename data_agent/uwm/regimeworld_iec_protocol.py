"""Frozen IEC component protocol, blocked on the upstream GWM/UWM architecture."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import product
from typing import Any, Iterator

from data_agent.uwm.regimeworld_iec_generator import ControlledScenarioSpec


FACTOR_LEVELS: dict[str, tuple[str, str]] = {
    "action_geometry": ("independent", "bundled"),
    "target_support": ("interpolation", "extrapolation"),
    "shortcut_mode": ("absent", "event_environment_correlated"),
    "implementation_mode": ("exact", "partial_delayed"),
    "contamination_mode": ("absent", "latent"),
    "response_invariance": ("shared", "environment_specific"),
}
PRIMARY_RESPONSE_FAMILY = "linear"
UNTOUCHED_RESPONSE_FAMILIES = (
    "saturating",
    "threshold",
    "interaction",
    "delayed",
)
PRIMARY_SEEDS = tuple(2026071901 + index for index in range(30))

MODEL_VARIANTS = (
    "no_action_transition",
    "magnitude_only_action",
    "opaque_event_token",
    "primitive_compositional_uwm",
    "component_shuffled",
    "action_permuted",
    "environment_specific_response",
    "oracle_reference",
)

FEATURE_CONTRACT = {
    "history_steps": 2,
    "state_block": [
        "state_t",
        "state_t_minus_1",
        "graph_mean_state_t",
        "graph_mean_state_t_minus_1",
    ],
    "action_block": [
        "local_action_t",
        "local_action_t_minus_1",
        "graph_mean_action_t",
        "graph_mean_action_t_minus_1",
    ],
    "base_state_feature_count": 16,
    "matched_action_feature_count": 16,
    "target": "state_t_plus_1",
    "environment_identifier_available_to_shared_models": False,
    "calendar_features": [],
    "normalization": (
        "Per feature median and interquartile range fitted on the development "
        "training window only; constant features use scale one. The target is "
        "not normalized. The same frozen scaler is used for validation, "
        "development holdout, and external evaluation."
    ),
}

TEMPORAL_SPLIT = {
    "transition_index_definition": "t maps state[t] and action[t] to state[t+1]",
    "minimum_history_index": 1,
    "development_training": {"start_inclusive": 1, "stop_exclusive": 256},
    "development_validation": {"start_inclusive": 256, "stop_exclusive": 311},
    "development_holdout": {"start_inclusive": 311, "stop_exclusive": 365},
    "external_evaluation": {"start_inclusive": 1, "stop_exclusive": 365},
    "selection_rule": (
        "Select hyperparameters by macro state-component NMAE on the pooled "
        "validation windows of development environments 0, 1, and 2. Refit "
        "once on their training plus validation windows, retaining the "
        "training-window scaler. Development holdout is used for G4-G5 only."
    ),
}

MODEL_EXECUTION_CONTRACT = {
    "primary_architecture": {
        "id": "transparent_linear_graph_transition",
        "estimator": "multi-output ridge regression with an unpenalized intercept",
        "alpha_grid": [0.0, 1e-6, 1e-4, 1e-2, 1.0],
        "training_rows": "all eligible rows in the declared split",
        "row_budget": {
            "development_training": 8192,
            "development_validation": 2048,
            "development_holdout": 4096,
            "external_evaluation": 8192,
        },
        "sampling": (
            "Deterministic stratified sampling by environment, action-active "
            "status, transition index, and node."
        ),
        "primary_grid_coverage": "all 64 cells and all 30 seeds",
    },
    "secondary_architecture": {
        "id": "nonlinear_graph_history_mlp",
        "estimator": "two-hidden-layer multi-output MLPRegressor",
        "hidden_layer_sizes": [64, 32],
        "activation": "tanh",
        "solver": "adam",
        "learning_rate_init": 0.001,
        "alpha": 0.0001,
        "batch_size": 512,
        "max_iter": 40,
        "early_stopping": False,
        "random_state_rule": "scenario seed plus the frozen variant index",
        "row_budget": {
            "development_training": 4096,
            "development_validation": 1024,
            "development_holdout": 1024,
            "external_evaluation": 2048,
        },
        "sampling": (
            "Deterministic stratified sampling by environment, action-active "
            "status, transition index, and node."
        ),
        "primary_grid_coverage": (
            "The all-clean cell and the six one-factor-at-a-time failure cells, "
            "the first ten frozen seeds. This architecture is a prespecified "
            "robustness family "
            "and is not pooled with the transparent primary estimand."
        ),
    },
    "variant_action_representations": {
        "no_action_transition": "sixteen zero action channels",
        "magnitude_only_action": (
            "L2 magnitude copied into a frozen four-channel magnitude code before "
            "local, lagged, and graph aggregation"
        ),
        "opaque_event_token": (
            "The control-only shortcut pair [event_active, environment] expanded "
            "to [event_active, environment, their product, event_active times one "
            "minus environment]; magnitudes and component names are unavailable"
        ),
        "primitive_compositional_uwm": "declared four-dimensional intended action",
        "component_shuffled": (
            "Per-observation deterministic component permutation preserving each "
            "action vector's multiset but destroying stable component identity"
        ),
        "action_permuted": (
            "Per-environment deterministic permutation of whole action vectors "
            "across transition-node observations"
        ),
        "environment_specific_response": (
            "Primitive action block interacted with one-hot development environment; "
            "capacity-unmatched diagnostic, excluded from semantic-control decisions"
        ),
        "oracle_reference": (
            "Analytic T_star using implemented action, contamination, and the correct "
            "graph; never trained, selected, or ranked as a candidate"
        ),
    },
    "capacity_boundary": (
        "The no-action, magnitude, opaque-token, primitive, component-shuffled, "
        "and action-permuted variants share the identical state block, action-block "
        "width, estimator, split, scaler rule, and optimization budget. The "
        "environment-specific response is explicitly capacity-unmatched and "
        "diagnostic only. The analytic oracle is not a competitor."
    ),
    "compute_budget": {
        "transparent_primary_selected_models": 13440,
        "transparent_primary_estimator_fit_calls": 80640,
        "transparent_primary_rule": (
            "1920 replicates times seven trained candidate/control variants; the "
            "analytic oracle is not fitted. Each variant selects from the frozen "
            "five-alpha ridge grid using development validation, then refits once."
        ),
        "nonlinear_robustness_selected_models": 490,
        "nonlinear_robustness_estimator_fit_calls": 980,
        "nonlinear_robustness_rule": (
            "Seven selected cells times ten seeds times seven trained variants, "
            "with one fixed alpha and deterministic row budgets."
        ),
        "staging": (
            "Run one nonprotocol fixture, then one admitted primary manifest shard, "
            "then the remaining primary shards. Any compute-driven amendment must "
            "be recorded before the first formal primary shard."
        ),
    },
}

METRIC_EXECUTION_CONTRACT = {
    "prediction": {
        "per_component_nmae": (
            "mean(abs(prediction-observation)) divided by "
            "max(mean(abs(observation)), 1e-8)"
        ),
        "macro_nmae": "unweighted mean of the four component NMAE values",
        "additional_reported": ["MAE", "RMSE", "WAPE"],
        "development_gate": (
            "Primitive macro NMAE is strictly below no-action and every semantic "
            "control, with at least three of four component NMAEs improved in each "
            "comparison, on the development holdout."
        ),
        "external_gate": (
            "The frozen primitive model repeats the same comparison on the sealed "
            "external environment without refitting or rescaling."
        ),
    },
    "response_surface": {
        "evaluation_rows": (
            "A deterministic action-active/zero-action stratified sample from the "
            "declared evaluation split. Predicted response is T_hat(s,a)-T_hat(s,0); "
            "reference response is T_star(s,a_implemented)-T_star(s,0), holding "
            "state and contamination fixed."
        ),
        "relative_rmse": (
            "RMSE(predicted_response-reference_response) divided by "
            "max(RMS(reference_response), 1e-8)"
        ),
        "implementation_boundary": (
            "Jacobian recovery is claim-bearing only when implementation is exact. "
            "For latent partial/delayed implementation it is reported unavailable, "
            "not silently compared across different action variables."
        ),
    },
    "jacobian": {
        "method": "central finite differences of T_hat with epsilon 1e-5",
        "reference": "analytic full graph Jacobian of T_star",
        "anchors": 64,
        "anchor_sampling": (
            "Deterministic stratification over evaluation transitions and nodes; "
            "threshold nondifferentiability is flagged and omitted from sign scoring"
        ),
    },
    "replicate_declaration": {
        "prediction_only": (
            "External primitive macro NMAE below no-action with at least three of "
            "four components improved"
        ),
        "full_iec": "G0 through G6 all pass; no indeterminate gate is coerced to pass",
        "truth_positive": (
            "The scenario is structurally eligible and the model passes frozen "
            "response-surface and Jacobian recovery tolerances"
        ),
    },
    "study_level_inference": (
        "Compute paired declaration differences per scenario-cell seed. Use the "
        "frozen two-stage cluster bootstrap: resample the 64 scenario cells, then "
        "resample 30 seeds within each selected cell. Clean-regime sensitivity is "
        "the IEC pass rate among all-clean replicates that satisfy truth recovery."
    ),
}

GATE_EXECUTION_CONTRACT = {
    "G0": "Pass only for the frozen primitive ontology and dependency map.",
    "G1": "Exact implementation passes; latent partial/delayed implementation is indeterminate.",
    "G2": "Absent contamination passes; auditor-known latent contamination fails.",
    "G3": (
        "Independent primitive rank plus interpolation support passes. Bundling or "
        "extrapolation fails the component/interpolation claim. Institutional-event "
        "and node-exposure support must remain separate in real audits."
    ),
    "G4": (
        "Pass requires an exact candidate feature-schema allowlist, zero oracle-field "
        "access, deterministic permutation ledgers, and the primitive model to beat "
        "the shortcut-positive opaque/environment, component-shuffled, and action-"
        "permuted controls on development holdout."
    ),
    "G5": "Apply the frozen development prediction and semantic-specificity gate.",
    "G6": (
        "After model/scaler hashes freeze, open the external environment once and "
        "apply the frozen external gate. Environment-specific response fails shared-"
        "response transfer even if prediction is accurate."
    ),
}


@dataclass(frozen=True)
class ProtocolThresholds:
    action_support_tolerance: float = 1e-8
    relative_response_surface_rmse_max: float = 0.10
    relative_jacobian_frobenius_error_max: float = 0.15
    nonzero_jacobian_sign_agreement_min: float = 0.90
    clean_regime_sensitivity_min: float = 0.80
    paired_confidence_level: float = 0.95
    cluster_bootstrap_replicates: int = 20_000
    cluster_bootstrap_seed: int = 20260719
    action_minus_no_action_upper_bound_max: float = 0.0
    minimum_target_improvement_fraction: float = 0.75

    def validate(self) -> None:
        if self.action_support_tolerance <= 0:
            raise ValueError("action_support_tolerance must be positive")
        for name in (
            "relative_response_surface_rmse_max",
            "relative_jacobian_frobenius_error_max",
        ):
            value = getattr(self, name)
            if not 0 < value < 1:
                raise ValueError(f"{name} must be between zero and one")
        for name in (
            "nonzero_jacobian_sign_agreement_min",
            "clean_regime_sensitivity_min",
            "paired_confidence_level",
            "minimum_target_improvement_fraction",
        ):
            value = getattr(self, name)
            if not 0 < value <= 1:
                raise ValueError(f"{name} must be in (0, 1]")
        if self.cluster_bootstrap_replicates < 1_000:
            raise ValueError("cluster bootstrap requires at least 1000 replicates")


def iter_factor_cells() -> Iterator[dict[str, str]]:
    names = tuple(FACTOR_LEVELS)
    for values in product(*(FACTOR_LEVELS[name] for name in names)):
        yield dict(zip(names, values))


def cell_id(cell: dict[str, str]) -> str:
    abbreviations = {
        "independent": "ind",
        "bundled": "bun",
        "interpolation": "int",
        "extrapolation": "ext",
        "absent": "abs",
        "event_environment_correlated": "shc",
        "exact": "exa",
        "partial_delayed": "par",
        "latent": "lat",
        "shared": "shr",
        "environment_specific": "esp",
    }
    return "_".join(abbreviations[cell[name]] for name in FACTOR_LEVELS)


def primary_scenario_specs() -> tuple[ControlledScenarioSpec, ...]:
    specs: list[ControlledScenarioSpec] = []
    for cell in iter_factor_cells():
        identifier = cell_id(cell)
        for seed in PRIMARY_SEEDS:
            specs.append(
                ControlledScenarioSpec(
                    name=f"primary_{identifier}_seed_{seed}",
                    seed=seed,
                    response_family=PRIMARY_RESPONSE_FAMILY,
                    action_geometry=cell["action_geometry"],  # type: ignore[arg-type]
                    target_support=cell["target_support"],  # type: ignore[arg-type]
                    shortcut_mode=cell["shortcut_mode"],  # type: ignore[arg-type]
                    implementation_mode=cell["implementation_mode"],  # type: ignore[arg-type]
                    contamination_mode=cell["contamination_mode"],  # type: ignore[arg-type]
                    response_invariance=cell["response_invariance"],  # type: ignore[arg-type]
                    n_environments=4,
                    n_nodes=64,
                    n_steps=365,
                    state_dim=4,
                    action_dim=4,
                    noise_std=0.01,
                )
            )
    return tuple(specs)


def untouched_family_specs() -> tuple[ControlledScenarioSpec, ...]:
    clean_cell = {
        "action_geometry": "independent",
        "target_support": "interpolation",
        "shortcut_mode": "absent",
        "implementation_mode": "exact",
        "contamination_mode": "absent",
        "response_invariance": "shared",
    }
    failure_cells = {
        factor: {**clean_cell, factor: levels[1]}
        for factor, levels in FACTOR_LEVELS.items()
    }
    selected_cells = {"clean": clean_cell, **failure_cells}
    specs: list[ControlledScenarioSpec] = []
    for family in UNTOUCHED_RESPONSE_FAMILIES:
        for cell_name, cell in selected_cells.items():
            for seed in PRIMARY_SEEDS:
                specs.append(
                    ControlledScenarioSpec(
                        name=f"untouched_{family}_{cell_name}_seed_{seed}",
                        seed=seed,
                        response_family=family,  # type: ignore[arg-type]
                        action_geometry=cell["action_geometry"],  # type: ignore[arg-type]
                        target_support=cell["target_support"],  # type: ignore[arg-type]
                        shortcut_mode=cell["shortcut_mode"],  # type: ignore[arg-type]
                        implementation_mode=cell["implementation_mode"],  # type: ignore[arg-type]
                        contamination_mode=cell["contamination_mode"],  # type: ignore[arg-type]
                        response_invariance=cell["response_invariance"],  # type: ignore[arg-type]
                        n_environments=4,
                        n_nodes=64,
                        n_steps=365,
                        state_dim=4,
                        action_dim=4,
                        noise_std=0.01,
                    )
                )
    return tuple(specs)


def build_protocol_manifest() -> dict[str, Any]:
    thresholds = ProtocolThresholds()
    thresholds.validate()
    cells = list(iter_factor_cells())
    primary_specs = primary_scenario_specs()
    untouched_specs = untouched_family_specs()
    return {
        "schema": "uwm.regimeworld_iec_benchmark_protocol.v1",
        "status": "component_protocol_frozen_upstream_architecture_blocked",
        "pre_outcome_amendment": {
            "id": "T3A-2026-07-19-execution-contract",
            "reason": (
                "The initial T3 manifest named model families but did not fix the "
                "feature schema, temporal split, estimator budgets, response grid, "
                "or gate-to-algorithm mapping required for reproducible T5 execution."
            ),
            "scientific_effect": (
                "Closes researcher degrees of freedom before T4. It does not change "
                "the scenario grid, seeds, truth families, IEC thresholds, or primary "
                "study-level decision rule."
            ),
            "outcome_state_at_amendment": {
                "primary_outcomes_generated": False,
                "untouched_outcomes_generated": False,
                "candidate_models_trained": False,
            },
        },
        "architecture_boundary": (
            "UWM is intended to be the urban-domain instance built on GWM, but "
            "the current RegimeWorld generator is a standalone controlled graph "
            "simulator and is not bound to the shared GWM Geospatial Kernel. The "
            "protocol is frozen only as an IEC component design, not as an "
            "executable GWM-based UWM paper experiment."
        ),
        "upstream_dependencies": {
            "gwm_geospatial_kernel_ready": False,
            "gwm_public_scientific_benchmark_ready": False,
            "uwm_shared_kernel_binding_implemented": False,
            "uwm_shared_kernel_conformance_passed": False,
            "regimeworld_uses_shared_gwm_geospatial_kernel": False,
            "iec_component_only": True,
            "dependency_status_artifact": (
                "docs/research/"
                "UWM_GWM_KERNEL_DEPENDENCY_STATUS_2026-07-20.json"
            ),
            "paper_experiment_blocked": True,
        },
        "primary_design": {
            "response_family": PRIMARY_RESPONSE_FAMILY,
            "factor_levels": FACTOR_LEVELS,
            "cell_count": len(cells),
            "seeds": list(PRIMARY_SEEDS),
            "replicate_count": len(primary_specs),
            "scenario_shape": {
                "n_environments": 4,
                "development_environments": 3,
                "external_environments": 1,
                "n_nodes": 64,
                "n_steps": 365,
                "state_dim": 4,
                "action_dim": 4,
            },
            "cells": [
                {"cell_id": cell_id(cell), "factors": cell} for cell in cells
            ],
        },
        "untouched_external_design": {
            "response_families": list(UNTOUCHED_RESPONSE_FAMILIES),
            "cell_policy": (
                "One all-clean cell plus six one-factor-at-a-time failure cells "
                "per family; unavailable until models and thresholds freeze."
            ),
            "cells_per_family": 7,
            "seeds": list(PRIMARY_SEEDS),
            "replicate_count": len(untouched_specs),
            "single_use_primary_metric_receipt": True,
        },
        "thresholds": asdict(thresholds),
        "model_families": {
            "required": list(MODEL_VARIANTS),
            "minimum_architectures": [
                "transparent_linear_graph_transition",
                "nonlinear_graph_recurrent_transition",
            ],
            "capacity_rule": (
                "Within an architecture, matched variants share state/history/graph "
                "capacity and differ only in the declared action representation or control."
            ),
        },
        "feature_contract": FEATURE_CONTRACT,
        "temporal_split": TEMPORAL_SPLIT,
        "model_execution_contract": MODEL_EXECUTION_CONTRACT,
        "metric_execution_contract": METRIC_EXECUTION_CONTRACT,
        "gate_execution_contract": GATE_EXECUTION_CONTRACT,
        "data_views": {
            "candidate_model_view": [
                "observed state history",
                "declared intended primitive action",
                "frozen graph for graph-enabled variants",
                "permitted calendar/environment context under the variant contract",
            ],
            "control_only_view": [
                "opaque event/environment token for the opaque-token control",
                "correlated shortcut fields for the shortcut-positive control",
                "permuted or shuffled actions under frozen ledgers",
            ],
            "auditor_oracle_only_view": [
                "realized implemented action",
                "latent contamination process",
                "reference transition function T_star",
                "reference action-response surface",
                "full graph action Jacobian",
                "scenario eligibility truth",
            ],
            "prohibition": (
                "No candidate, selection routine, scaler, or certificate threshold "
                "may consume auditor_oracle_only_view fields."
            ),
        },
        "scenario_eligibility_truth": {
            "clean_regime": {
                "action_geometry": "independent",
                "target_support": "interpolation",
                "shortcut_mode": "absent",
                "implementation_mode": "exact",
                "contamination_mode": "absent",
                "response_invariance": "shared",
            },
            "factor_consequences": {
                "bundled": "G3 ineligible for primitive component-law recovery",
                "extrapolation": "G3 ineligible for interpolation claim; predictive extrapolation must be labeled",
                "event_environment_correlated": "G4 challenge; pass depends on frozen shortcut controls, not availability alone",
                "partial_delayed": "G1 indeterminate to candidates because realized implementation is withheld",
                "latent": "G2 ineligible in truth and indeterminate to candidates because contamination is withheld",
                "environment_specific": "shared-response transfer ineligible; external predictive performance remains measurable",
            },
            "eligible_clean_cell_count": 1,
            "ineligible_or_challenge_cell_count": 63,
            "label_independence": (
                "Eligibility truth is generated from scenario factors before and "
                "without candidate predictions. G4 remains a model-specific control "
                "gate rather than an automatic scenario failure."
            ),
        },
        "split_and_selection": {
            "development_only_hyperparameter_selection": True,
            "external_environment_used_for_selection": False,
            "untouched_response_families_used_for_selection": False,
            "scaler_fit_scope": "development training window only",
            "model_selection_metric": "development validation macro state-component NMAE",
            "development_holdout_used_for_selection": False,
            "unit_of_uncertainty": "scenario_cell_seed",
            "cluster_order": ["scenario_cell", "seed"],
        },
        "primary_decision_rules": {
            "validated_certificate": (
                "The cluster-bootstrap 95% upper bound for full-IEC minus "
                "prediction-only false-positive rate is below zero, and clean-"
                "regime sensitivity is at least 0.80."
            ),
            "law_recovery": (
                "Relative response-surface RMSE <= 0.10, relative Jacobian error "
                "<= 0.15, and nonzero-Jacobian sign agreement >= 0.90."
            ),
            "incremental_prediction": (
                "The paired 95% upper bound for full-minus-no-action error is below "
                "zero and at least 3 of 4 targets improve."
            ),
            "semantic_specificity": (
                "The primitive model passes incremental prediction and beats "
                "magnitude-only, opaque-token, component-shuffled, and action-"
                "permuted controls under the same paired protocol."
            ),
        },
        "integrity": {
            "primary_outcomes_generated": False,
            "untouched_outcomes_generated": False,
            "candidate_models_trained": False,
            "paper_experimenter_admitted": False,
            "auditor_oracle_fields_exposed_to_candidates": False,
            "nyc_2012_paths_rows_counts_outcomes_or_aggregates_accessed": False,
        },
    }
