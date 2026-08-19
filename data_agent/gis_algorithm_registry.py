"""Versioned release registry for deterministic GIS analysis algorithms."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .platform_contracts import Sha256, canonical_json_fingerprint


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GISAnalysisOperation(StrEnum):
    BUFFER = "buffer"
    CLIP = "clip"
    INTERSECTION = "intersection"


class GISAlgorithmLifecycle(StrEnum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class GISAlgorithmParameterSpec(_FrozenContract):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    value_type: Literal["number"]
    required: bool
    unit: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,31}$")
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def _valid_range(self) -> GISAlgorithmParameterSpec:
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum >= self.maximum
        ):
            raise ValueError("GIS algorithm parameter range is invalid")
        return self


class GISAlgorithmBudgetCeiling(_FrozenContract):
    max_features: int = Field(ge=1, le=100_000)
    max_output_bytes: int = Field(ge=1_024, le=10_000_000_000)
    max_duration_ms: int = Field(ge=100, le=1_795_000)


class GISAlgorithmSpec(_FrozenContract):
    schema_id: Literal["gda.gis_algorithm_spec.v1"] = "gda.gis_algorithm_spec.v1"
    algorithm_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    algorithm_version: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    operation: GISAnalysisOperation
    title: str = Field(min_length=1, max_length=128)
    engine: Literal["postgis"] = "postgis"
    implementation_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    input_roles: tuple[Literal["input", "overlay"], ...]
    parameters: tuple[GISAlgorithmParameterSpec, ...] = ()
    budget_ceiling: GISAlgorithmBudgetCeiling
    deterministic: Literal[True] = True
    read_only: Literal[True] = True
    execution_mode: Literal["asynchronous"] = "asynchronous"
    output_media_type: Literal["application/geo+json"] = "application/geo+json"
    output_semantic_type: Literal["gda.gis_analysis_result.v1"] = (
        "gda.gis_analysis_result.v1"
    )
    lifecycle: GISAlgorithmLifecycle = GISAlgorithmLifecycle.ACTIVE
    is_default: bool = False
    released_at: datetime
    spec_fingerprint: Sha256

    @model_validator(mode="after")
    def _exact_release(self) -> GISAlgorithmSpec:
        if self.released_at.tzinfo is None or self.released_at.utcoffset() is None:
            raise ValueError("GIS algorithm release time must be timezone-aware")
        if not self.input_roles or self.input_roles[0] != "input":
            raise ValueError("GIS algorithm input roles must start with input")
        if len(set(self.input_roles)) != len(self.input_roles):
            raise ValueError("GIS algorithm input roles must be unique")
        names = tuple(parameter.name for parameter in self.parameters)
        if len(set(names)) != len(names):
            raise ValueError("GIS algorithm parameters must be unique")
        expected = canonical_json_fingerprint(
            self.model_dump(mode="json", exclude={"spec_fingerprint"})
        )
        if self.spec_fingerprint != expected:
            raise ValueError("GIS algorithm specification fingerprint is invalid")
        if self.lifecycle is not GISAlgorithmLifecycle.ACTIVE and self.is_default:
            raise ValueError("only an active GIS algorithm can be the default")
        return self

    @classmethod
    def release(cls, **values: object) -> GISAlgorithmSpec:
        normalized = dict(values)
        released_at = normalized.get("released_at")
        if isinstance(released_at, datetime):
            if released_at.tzinfo is None or released_at.utcoffset() is None:
                raise GISAlgorithmRegistryError(
                    "GIS algorithm release time must be timezone-aware"
                )
            normalized["released_at"] = released_at.astimezone(UTC)
        provisional = cls.model_construct(**normalized, spec_fingerprint="0" * 64)
        fingerprint = canonical_json_fingerprint(
            provisional.model_dump(mode="json", exclude={"spec_fingerprint"})
        )
        return cls(**normalized, spec_fingerprint=fingerprint)

    @property
    def required_parameter_names(self) -> tuple[str, ...]:
        return tuple(parameter.name for parameter in self.parameters if parameter.required)


class GISAlgorithmCatalog(_FrozenContract):
    schema_id: Literal["gda.gis_algorithm_catalog.v1"] = (
        "gda.gis_algorithm_catalog.v1"
    )
    registry_fingerprint: Sha256
    algorithms: tuple[GISAlgorithmSpec, ...]


class GISAlgorithmRegistryError(ValueError):
    """The requested algorithm release is absent or not admissible."""


class GISAlgorithmRegistry:
    """Immutable index of released implementations available to plans and workers."""

    def __init__(self, specs: Iterable[GISAlgorithmSpec]):
        releases = tuple(specs)
        if not releases:
            raise GISAlgorithmRegistryError("GIS algorithm registry cannot be empty")
        by_release: dict[tuple[str, str], GISAlgorithmSpec] = {}
        defaults: dict[GISAnalysisOperation, GISAlgorithmSpec] = {}
        for spec in releases:
            key = (spec.algorithm_id, spec.algorithm_version)
            if key in by_release:
                raise GISAlgorithmRegistryError("duplicate GIS algorithm release")
            by_release[key] = spec
            if spec.is_default:
                if spec.operation in defaults:
                    raise GISAlgorithmRegistryError(
                        "GIS operation has more than one default algorithm"
                    )
                defaults[spec.operation] = spec
        active_operations = {
            spec.operation
            for spec in releases
            if spec.lifecycle is GISAlgorithmLifecycle.ACTIVE
        }
        if active_operations != set(defaults):
            raise GISAlgorithmRegistryError(
                "each active GIS operation requires exactly one default algorithm"
            )
        self._releases = tuple(
            sorted(
                releases,
                key=lambda item: (
                    item.operation.value,
                    item.algorithm_id,
                    item.algorithm_version,
                ),
            )
        )
        self._by_release = by_release
        self._defaults = defaults
        self._fingerprint = canonical_json_fingerprint(
            [spec.model_dump(mode="json") for spec in self._releases]
        )

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    def catalog(self, *, include_retired: bool = False) -> GISAlgorithmCatalog:
        algorithms = tuple(
            spec
            for spec in self._releases
            if include_retired or spec.lifecycle is not GISAlgorithmLifecycle.RETIRED
        )
        return GISAlgorithmCatalog(
            registry_fingerprint=self._fingerprint,
            algorithms=algorithms,
        )

    def resolve(
        self,
        operation: GISAnalysisOperation,
        *,
        algorithm_id: str | None = None,
        algorithm_version: str | None = None,
    ) -> GISAlgorithmSpec:
        if (algorithm_id is None) != (algorithm_version is None):
            raise GISAlgorithmRegistryError(
                "GIS algorithm id and version must be selected together"
            )
        if algorithm_id is None:
            spec = self._defaults.get(operation)
        else:
            spec = self._by_release.get((algorithm_id, algorithm_version or ""))
        if spec is None or spec.operation is not operation:
            raise GISAlgorithmRegistryError(
                "GIS algorithm release is not registered for this operation"
            )
        if spec.lifecycle is not GISAlgorithmLifecycle.ACTIVE:
            raise GISAlgorithmRegistryError("GIS algorithm release is not active")
        return spec

    def require_plan_binding(
        self,
        *,
        operation: GISAnalysisOperation,
        algorithm_id: str,
        algorithm_version: str,
        spec_fingerprint: str,
        engine: str,
    ) -> GISAlgorithmSpec:
        spec = self._by_release.get((algorithm_id, algorithm_version))
        if (
            spec is None
            or spec.operation is not operation
            or spec.engine != engine
            or spec.spec_fingerprint != spec_fingerprint
        ):
            raise GISAlgorithmRegistryError(
                "GIS plan is not bound to an exact registered algorithm release"
            )
        return spec


_RELEASED_AT = datetime(2026, 8, 13, tzinfo=UTC)
_DEFAULT_BUDGET = GISAlgorithmBudgetCeiling(
    max_features=100_000,
    max_output_bytes=10_000_000_000,
    max_duration_ms=1_795_000,
)

DEFAULT_GIS_ALGORITHM_REGISTRY = GISAlgorithmRegistry(
    (
        GISAlgorithmSpec.release(
            algorithm_id="postgis.st_buffer_geography",
            algorithm_version="gda.postgis-spatial-analysis.v1",
            operation=GISAnalysisOperation.BUFFER,
            title="Geodesic buffer",
            implementation_key="postgis.buffer_geography.v1",
            input_roles=("input",),
            parameters=(
                GISAlgorithmParameterSpec(
                    name="distance_meters",
                    value_type="number",
                    required=True,
                    unit="meter",
                    minimum=0,
                    maximum=1_000_000,
                ),
            ),
            budget_ceiling=_DEFAULT_BUDGET,
            is_default=True,
            released_at=_RELEASED_AT,
        ),
        GISAlgorithmSpec.release(
            algorithm_id="postgis.st_clip",
            algorithm_version="gda.postgis-spatial-analysis.v1",
            operation=GISAnalysisOperation.CLIP,
            title="Vector clip",
            implementation_key="postgis.clip.v1",
            input_roles=("input", "overlay"),
            budget_ceiling=_DEFAULT_BUDGET,
            is_default=True,
            released_at=_RELEASED_AT,
        ),
        GISAlgorithmSpec.release(
            algorithm_id="postgis.st_intersection",
            algorithm_version="gda.postgis-spatial-analysis.v1",
            operation=GISAnalysisOperation.INTERSECTION,
            title="Pairwise vector intersection",
            implementation_key="postgis.intersection.v1",
            input_roles=("input", "overlay"),
            budget_ceiling=_DEFAULT_BUDGET,
            is_default=True,
            released_at=_RELEASED_AT,
        ),
    )
)


__all__ = [
    "DEFAULT_GIS_ALGORITHM_REGISTRY",
    "GISAlgorithmBudgetCeiling",
    "GISAlgorithmCatalog",
    "GISAlgorithmLifecycle",
    "GISAlgorithmParameterSpec",
    "GISAlgorithmRegistry",
    "GISAlgorithmRegistryError",
    "GISAlgorithmSpec",
    "GISAnalysisOperation",
]
