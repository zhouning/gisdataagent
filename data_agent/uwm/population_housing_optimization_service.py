"""Bounded service facade for the aggregate population/housing MILP PoC."""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

from .population_housing_optimization import (
    DEFAULT_OBJECTIVE_WEIGHTS,
    DEFAULT_PORTFOLIO_PROFILES,
    POPULATION_HOUSING_INPUT_SCHEMA,
    POPULATION_HOUSING_PORTFOLIO_SCHEMA,
    add_population_housing_reference_comparison,
    solve_population_housing_portfolio,
    validate_population_housing_input,
)
from .population_housing_presentation import (
    build_population_housing_map_update,
    load_population_housing_map_context,
)

PRODUCT_FILES = (
    "population_housing_input.json",
    "input_validation.json",
    "population_housing_portfolio.json",
)

SERVICE_LIMITS = {
    "max_request_bytes": 2_000_000,
    "max_zones": 50,
    "max_population_groups": 250,
    "max_housing_options": 250,
    "max_candidate_assignments": 5_000,
    "max_profiles_per_solve": 3,
    "max_solver_time_limit_seconds": 30.0,
    "min_solver_mip_relative_gap": 0.001,
}

DEFAULT_BOUNDARY_PATH = (
    Path(__file__).resolve().parents[2]
    / "data/uwm_public_proxy/chongqing_central/admin_units/"
    "chongqing_township_admin_units.geojson"
)

INTERACTIVE_PROFILE_WEIGHTS = {
    "balanced": deepcopy(DEFAULT_PORTFOLIO_PROFILES["balanced"]),
    "fiscal": deepcopy(DEFAULT_PORTFOLIO_PROFILES["fiscal_priority"]),
    "commute": deepcopy(DEFAULT_PORTFOLIO_PROFILES["commute_priority"]),
    "resident": {
        "public_cost": 0.2,
        "resident_housing_cost": 1.0,
        "commute_cost": 0.2,
        "relocation_cost": 0.5,
        "unmet_penalty": 1.0,
    },
}

BOUNDED_RESOURCE_PERCENT_LIMITS = {
    "budget": (35.0, 125.0),
    "supply": (0.0, 125.0),
    "service": (0.0, 125.0),
    "relocation": (0.0, 20.0),
}


class PopulationHousingProductError(RuntimeError):
    """Raised when the immutable default product cannot be trusted or loaded."""


class PopulationHousingRequestLimitError(ValueError):
    """Raised when a custom solve exceeds the bounded service envelope."""

    def __init__(self, code: str, *, actual: int | float, limit: int | float):
        super().__init__(code)
        self.code = code
        self.actual = actual
        self.limit = limit

    def as_dict(self) -> dict[str, Any]:
        return {
            "error": self.code,
            "actual": self.actual,
            "limit": self.limit,
            "empirical_policy_optimality_claim": False,
        }


class PopulationHousingOptimizationService:
    """Load a verified snapshot and execute explicitly bounded aggregate solves."""

    def __init__(self, root: Path, *, boundary_path: Path | None = None):
        self.root = Path(root)
        self.boundary_path = Path(boundary_path or DEFAULT_BOUNDARY_PATH)
        self._map_context: dict[str, Any] | None = None
        self._manifest = self._read_json(self.root / "snapshot_manifest.json")
        self._verify_snapshot_files()
        self._input = self._read_json(self.root / "population_housing_input.json")
        self._stored_validation = self._read_json(self.root / "input_validation.json")
        self._portfolio = self._read_json(
            self.root / "population_housing_portfolio.json"
        )
        self._verify_contracts()
        self._portfolio = add_population_housing_reference_comparison(self._portfolio)

    def catalog(self) -> dict[str, Any]:
        validation = validate_population_housing_input(self._input)
        source_summary = deepcopy(self._input.get("source_summary") or {})
        profiles = [
            {
                "profile_id": row.get("profile_id"),
                "status": row.get("status"),
                "objective_weights": result.get("objective_weights"),
            }
            for row, result in zip(
                self._portfolio.get("comparison") or [],
                self._portfolio.get("results") or [],
                strict=False,
            )
        ]
        return {
            "schema": "uwm.population_housing_optimization.catalog.v1",
            "ready": True,
            "product": {
                "root": str(self.root),
                "scenario_id": self._input.get("scenario_id"),
                "created_at": self._manifest.get("created_at"),
                "snapshot_hashes_verified": True,
                "input_schema": self._input.get("schema"),
                "portfolio_schema": self._portfolio.get("schema"),
                "display": deepcopy(self._input.get("display") or {}),
            },
            "scope": {
                **validation["counts"],
                **source_summary,
                "cost_unit": self._input.get("cost_unit"),
            },
            "profiles": profiles,
            "operations": {
                "default_input": "GET /api/uwm/population-housing/default-input",
                "default_portfolio": (
                    "GET /api/uwm/population-housing/default-portfolio"
                ),
                "validate": "POST /api/uwm/population-housing/validate",
                "solve": "POST /api/uwm/population-housing/solve",
                "map_context": "GET /api/uwm/population-housing/map-context",
                "solve_contract": {
                    "input": "population-housing input object",
                    "use_default_input": "true may replace input",
                    "profiles": (
                        "optional profile-id list or profile-id to weight-object mapping"
                    ),
                },
            },
            "service_limits": deepcopy(SERVICE_LIMITS),
            "data_readiness": {
                "usable_for": "aggregate_proxy_optimization_poc",
                "not_usable_for": "policy_or_person_level_housing_assignment",
                "synthetic_flags": deepcopy(self._input.get("synthetic_flags") or []),
                "status_quo_baseline_available": False,
                "status_quo_baseline_blocker": (
                    "observed_current_group_to_housing_occupancy_is_not_available"
                ),
            },
            "claim_boundary": deepcopy(self._portfolio.get("claim_boundary") or {}),
            "empirical_policy_optimality_claim": False,
        }

    def default_input(self) -> dict[str, Any]:
        return deepcopy(self._input)

    def default_portfolio(self) -> dict[str, Any]:
        return deepcopy(self._portfolio)

    def map_context(self) -> dict[str, Any]:
        if self._map_context is None:
            self._map_context = load_population_housing_map_context(
                self._input,
                self.boundary_path,
            )
        return deepcopy(self._map_context)

    def map_update(
        self,
        result: dict[str, Any],
        *,
        title: str = "人口与住房空间配置",
        profile_label: str = "当前方案",
        focus_assignment: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return build_population_housing_map_update(
            self.map_context(),
            result,
            title=title,
            profile_label=profile_label,
            focus_assignment=focus_assignment,
        )

    def solve_bounded_scenario(
        self,
        *,
        profile_id: str,
        resources: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        """Solve from the verified snapshot using only bounded chat/UI controls."""
        if profile_id not in INTERACTIVE_PROFILE_WEIGHTS:
            raise ValueError("unknown interactive profile")
        if not isinstance(resources, dict):
            raise ValueError("resources object required")

        normalized: dict[str, float] = {}
        for name, (minimum, maximum) in BOUNDED_RESOURCE_PERCENT_LIMITS.items():
            value = resources.get(name, 20.0 if name == "relocation" else 100.0)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise ValueError(f"resource percentage must be numeric::{name}")
            number = float(value)
            if number < minimum or number > maximum:
                raise ValueError(
                    f"resource percentage outside bounded range::{name}::{minimum}::{maximum}"
                )
            normalized[name] = number

        scenario = deepcopy(self._input)
        scenario["scenario_id"] = "bounded-interactive-population-housing"
        scenario["parameters"]["total_public_budget"] = round(
            float(self._input["parameters"]["total_public_budget"])
            * normalized["budget"]
            / 100,
            6,
        )
        scenario["parameters"]["max_relocated_households_share"] = (
            normalized["relocation"] / 100
        )
        for option, source in zip(
            scenario.get("housing_options") or [],
            self._input.get("housing_options") or [],
            strict=True,
        ):
            option["max_new_units"] = max(
                0,
                round(float(source["max_new_units"]) * normalized["supply"] / 100),
            )
        for zone, source in zip(
            scenario.get("zones") or [],
            self._input.get("zones") or [],
            strict=True,
        ):
            zone["max_service_expansion"] = round(
                float(source["max_service_expansion"])
                * normalized["service"]
                / 100,
                6,
            )

        portfolio = self.solve(
            {
                "input": scenario,
                "profiles": {
                    profile_id: deepcopy(INTERACTIVE_PROFILE_WEIGHTS[profile_id])
                },
            },
            actor=actor,
        )
        portfolio["bounded_scenario"] = {
            "profile_id": profile_id,
            "resources_percent": normalized,
            "input_transport": "verified_snapshot_plus_bounded_parameters",
            "confirmation_required_for_chat": True,
        }
        return portfolio

    def validate(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._enforce_model_limits(payload)
        validation = validate_population_housing_input(payload)
        return {
            **validation,
            "within_service_limits": True,
            "service_limits": deepcopy(SERVICE_LIMITS),
            "empirical_policy_optimality_claim": False,
        }

    def solve(self, request: dict[str, Any], *, actor: str) -> dict[str, Any]:
        input_payload, input_source = self._resolve_input(request)
        self._enforce_model_limits(input_payload)
        validation = validate_population_housing_input(input_payload)
        if not validation["valid"]:
            raise ValueError(
                "invalid population-housing input: " + "; ".join(validation["errors"])
            )

        scenario = deepcopy(input_payload)
        parameters = scenario.setdefault("parameters", {})
        requested_time_limit = float(
            parameters.get(
                "solver_time_limit_seconds",
                SERVICE_LIMITS["max_solver_time_limit_seconds"],
            )
        )
        requested_mip_gap = float(parameters.get("solver_mip_relative_gap", 0.001))
        parameters["solver_time_limit_seconds"] = min(
            requested_time_limit,
            float(SERVICE_LIMITS["max_solver_time_limit_seconds"]),
        )
        parameters["solver_mip_relative_gap"] = max(
            requested_mip_gap,
            float(SERVICE_LIMITS["min_solver_mip_relative_gap"]),
        )
        parameters["solver_log"] = False
        profiles = self._resolve_profiles(request.get("profiles"))
        portfolio = solve_population_housing_portfolio(scenario, profiles=profiles)
        portfolio["execution"] = {
            "actor": str(actor),
            "input_source": input_source,
            "requested_solver_time_limit_seconds": requested_time_limit,
            "effective_solver_time_limit_seconds": parameters[
                "solver_time_limit_seconds"
            ],
            "requested_solver_mip_relative_gap": requested_mip_gap,
            "effective_solver_mip_relative_gap": parameters[
                "solver_mip_relative_gap"
            ],
            "profile_ids": list(profiles),
            "persisted": False,
        }
        portfolio["service_limits"] = deepcopy(SERVICE_LIMITS)
        portfolio["empirical_policy_optimality_claim"] = False
        return portfolio

    def _resolve_input(
        self, request: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        if not isinstance(request, dict):
            raise ValueError("Request object required")
        has_input = "input" in request
        use_default = request.get("use_default_input", False)
        if not isinstance(use_default, bool):
            raise ValueError("use_default_input must be boolean")
        if has_input and use_default:
            raise ValueError("provide input or use_default_input, not both")
        if use_default:
            return deepcopy(self._input), "verified_default_snapshot"
        payload = request.get("input")
        if not isinstance(payload, dict):
            raise ValueError("input object required")
        return deepcopy(payload), "custom_request"

    @staticmethod
    def _resolve_profiles(value: Any) -> dict[str, dict[str, float]]:
        if value is None:
            return deepcopy(DEFAULT_PORTFOLIO_PROFILES)
        if isinstance(value, list):
            if not value:
                raise ValueError("profiles must not be empty")
            if any(not isinstance(name, str) for name in value):
                raise ValueError("profile ids must be strings")
            if len(set(value)) != len(value):
                raise ValueError("profile ids must not contain duplicates")
            unknown = [name for name in value if name not in DEFAULT_PORTFOLIO_PROFILES]
            if unknown:
                raise ValueError("unknown default profiles: " + ",".join(map(str, unknown)))
            profiles = {
                str(name): deepcopy(DEFAULT_PORTFOLIO_PROFILES[str(name)])
                for name in value
            }
        elif isinstance(value, dict):
            if not value:
                raise ValueError("profiles must not be empty")
            profiles = {}
            for profile_id, weights in value.items():
                if not isinstance(profile_id, str) or not profile_id.strip():
                    raise ValueError("profile ids must be non-empty strings")
                if len(profile_id) > 64:
                    raise ValueError("profile ids must be at most 64 characters")
                if not isinstance(weights, dict):
                    raise ValueError(f"profile {profile_id} weights must be an object")
                unknown_weights = sorted(set(weights) - set(DEFAULT_OBJECTIVE_WEIGHTS))
                if unknown_weights:
                    raise ValueError(
                        f"profile {profile_id} has unknown weights: "
                        + ",".join(unknown_weights)
                    )
                merged = dict(DEFAULT_OBJECTIVE_WEIGHTS)
                merged.update(weights)
                if any(
                    isinstance(weight, bool)
                    or not isinstance(weight, (int, float))
                    or not math.isfinite(float(weight))
                    or float(weight) < 0
                    for weight in merged.values()
                ):
                    raise ValueError(
                        f"profile {profile_id} weights must be finite nonnegative numbers"
                    )
                if not any(float(weight) > 0 for weight in merged.values()):
                    raise ValueError(f"profile {profile_id} must include a positive weight")
                profiles[profile_id] = {name: float(weight) for name, weight in merged.items()}
        else:
            raise ValueError("profiles must be a list or object")

        limit = int(SERVICE_LIMITS["max_profiles_per_solve"])
        if len(profiles) > limit:
            raise PopulationHousingRequestLimitError(
                "profile_count_exceeds_service_limit",
                actual=len(profiles),
                limit=limit,
            )
        return profiles

    @staticmethod
    def _enforce_model_limits(payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            raise ValueError("population-housing input object required")
        fields = (
            ("zones", "max_zones"),
            ("population_groups", "max_population_groups"),
            ("housing_options", "max_housing_options"),
            ("candidate_assignments", "max_candidate_assignments"),
        )
        for field, limit_name in fields:
            rows = payload.get(field)
            if not isinstance(rows, list):
                continue
            limit = int(SERVICE_LIMITS[limit_name])
            if len(rows) > limit:
                raise PopulationHousingRequestLimitError(
                    f"{field}_exceeds_service_limit",
                    actual=len(rows),
                    limit=limit,
                )

    def _verify_snapshot_files(self) -> None:
        if self._manifest.get("schema") != (
            "uwm.population_housing_optimization.snapshot_manifest.v1"
        ):
            raise PopulationHousingProductError("snapshot_manifest_schema_mismatch")
        records = self._manifest.get("files")
        if not isinstance(records, list):
            raise PopulationHousingProductError("snapshot_manifest_files_missing")
        by_name: dict[str, dict[str, Any]] = {}
        for record in records:
            if not isinstance(record, dict):
                raise PopulationHousingProductError("snapshot_manifest_record_invalid")
            name = Path(str(record.get("path") or "")).name
            if not name or name in by_name:
                raise PopulationHousingProductError("snapshot_manifest_file_identity_invalid")
            by_name[name] = record

        for filename in PRODUCT_FILES:
            record = by_name.get(filename)
            if record is None:
                raise PopulationHousingProductError(
                    f"snapshot_manifest_record_missing::{filename}"
                )
            path = self.root / filename
            try:
                data = path.read_bytes()
            except OSError as error:
                raise PopulationHousingProductError(
                    f"snapshot_file_unavailable::{filename}"
                ) from error
            if len(data) != record.get("bytes"):
                raise PopulationHousingProductError(
                    f"snapshot_file_size_mismatch::{filename}"
                )
            digest = hashlib.sha256(data).hexdigest()
            if digest != record.get("sha256"):
                raise PopulationHousingProductError(
                    f"snapshot_file_hash_mismatch::{filename}"
                )

    def _verify_contracts(self) -> None:
        if self._input.get("schema") != POPULATION_HOUSING_INPUT_SCHEMA:
            raise PopulationHousingProductError("snapshot_input_schema_mismatch")
        validation = validate_population_housing_input(self._input)
        if not validation["valid"]:
            raise PopulationHousingProductError("snapshot_input_validation_failed")
        if not self._stored_validation.get("valid"):
            raise PopulationHousingProductError("stored_input_validation_not_valid")
        if self._stored_validation.get("counts") != validation.get("counts"):
            raise PopulationHousingProductError("stored_input_validation_counts_mismatch")
        if self._portfolio.get("schema") != POPULATION_HOUSING_PORTFOLIO_SCHEMA:
            raise PopulationHousingProductError("snapshot_portfolio_schema_mismatch")
        if self._portfolio.get("input_digest") != self._input_digest(self._input):
            raise PopulationHousingProductError("snapshot_portfolio_input_digest_mismatch")
        results = self._portfolio.get("results")
        if not isinstance(results, list):
            raise PopulationHousingProductError("snapshot_portfolio_results_invalid")
        if self._portfolio.get("profile_count") != len(results):
            raise PopulationHousingProductError("snapshot_portfolio_profile_count_mismatch")
        comparison = self._portfolio.get("comparison")
        if not isinstance(comparison, list) or len(comparison) != len(results):
            raise PopulationHousingProductError("snapshot_portfolio_comparison_mismatch")
        if any(not isinstance(row, dict) for row in comparison + results):
            raise PopulationHousingProductError("snapshot_portfolio_rows_invalid")
        comparison_ids = [row.get("profile_id") for row in comparison]
        result_ids = [row.get("profile_id") for row in results]
        if comparison_ids != result_ids or len(set(result_ids)) != len(result_ids):
            raise PopulationHousingProductError("snapshot_portfolio_profile_identity_mismatch")
        if any(
            row.get("empirical_policy_optimality_claim") is not False
            for row in results
        ):
            raise PopulationHousingProductError("result_claim_boundary_invalid")
        if self._manifest.get("empirical_policy_optimality_claim") is not False:
            raise PopulationHousingProductError("snapshot_claim_boundary_invalid")
        if self._portfolio.get("empirical_policy_optimality_claim") is not False:
            raise PopulationHousingProductError("portfolio_claim_boundary_invalid")

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise PopulationHousingProductError(
                f"product_json_unavailable::{path.name}"
            ) from error
        if not isinstance(payload, dict):
            raise PopulationHousingProductError(f"product_json_not_object::{path.name}")
        return payload

    @staticmethod
    def _input_digest(payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


__all__ = [
    "BOUNDED_RESOURCE_PERCENT_LIMITS",
    "DEFAULT_BOUNDARY_PATH",
    "INTERACTIVE_PROFILE_WEIGHTS",
    "PopulationHousingOptimizationService",
    "PopulationHousingProductError",
    "PopulationHousingRequestLimitError",
    "SERVICE_LIMITS",
]
