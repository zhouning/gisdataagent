"""Released deterministic algorithms allowed in production GIS workflow DAGs."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .gis_algorithm_registry import (
    DEFAULT_GIS_ALGORITHM_REGISTRY,
    GISAnalysisOperation,
)
from .platform_contracts import Sha256, canonical_json_fingerprint


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GISWorkflowOperation(StrEnum):
    INTERSECTION = "intersection"
    BUFFER = "buffer"
    SPATIAL_FILTER = "spatial_filter"
    AREA_FILTER = "area_filter"
    SPATIAL_GROUP_BY = "spatial_group_by"
    LAND_USE_SPATIAL_GROUP_BY = "land_use_spatial_group_by"


class GISWorkflowAlgorithmSpec(_FrozenContract):
    schema_id: Literal["gda.gis_workflow_algorithm_spec.v1"] = (
        "gda.gis_workflow_algorithm_spec.v1"
    )
    operation: GISWorkflowOperation
    algorithm_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    algorithm_version: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    engine: Literal["postgis"] = "postgis"
    deterministic: Literal[True] = True
    read_only: Literal[True] = True
    spec_fingerprint: Sha256

    @model_validator(mode="after")
    def _exact_release(self) -> GISWorkflowAlgorithmSpec:
        expected = canonical_json_fingerprint(
            self.model_dump(mode="json", exclude={"spec_fingerprint"})
        )
        if self.spec_fingerprint != expected:
            raise ValueError("GIS workflow algorithm fingerprint is invalid")
        return self

    @classmethod
    def release(cls, **values: object) -> GISWorkflowAlgorithmSpec:
        provisional = cls.model_construct(**values, spec_fingerprint="0" * 64)
        fingerprint = canonical_json_fingerprint(
            provisional.model_dump(mode="json", exclude={"spec_fingerprint"})
        )
        return cls(**values, spec_fingerprint=fingerprint)


class GISWorkflowAlgorithmRegistry:
    def __init__(self, specs: Iterable[GISWorkflowAlgorithmSpec]):
        releases = tuple(specs)
        by_operation = {spec.operation: spec for spec in releases}
        if len(by_operation) != len(releases):
            raise ValueError("duplicate GIS workflow algorithm operation")
        if set(by_operation) != set(GISWorkflowOperation):
            raise ValueError("each GIS workflow operation requires one release")
        self._by_operation = by_operation
        self._releases = tuple(by_operation[operation] for operation in GISWorkflowOperation)
        self.fingerprint = canonical_json_fingerprint(
            [spec.model_dump(mode="json") for spec in self._releases]
        )

    def resolve(self, operation: GISWorkflowOperation | str) -> GISWorkflowAlgorithmSpec:
        try:
            normalized = GISWorkflowOperation(operation)
        except ValueError as exc:
            raise ValueError("GIS workflow operation is not registered") from exc
        return self._by_operation[normalized]

    def require_binding(
        self,
        *,
        operation: GISWorkflowOperation | str,
        algorithm_id: str,
        algorithm_version: str,
        spec_fingerprint: str,
    ) -> GISWorkflowAlgorithmSpec:
        spec = self.resolve(operation)
        if (
            spec.algorithm_id != algorithm_id
            or spec.algorithm_version != algorithm_version
            or spec.spec_fingerprint != spec_fingerprint
        ):
            raise ValueError("workflow step is not bound to its registered release")
        return spec

    @property
    def operations(self) -> tuple[GISWorkflowOperation, ...]:
        return tuple(spec.operation for spec in self._releases)

    @property
    def algorithms(self) -> tuple[GISWorkflowAlgorithmSpec, ...]:
        return self._releases


def _standalone_release(
    workflow_operation: GISWorkflowOperation,
    analysis_operation: GISAnalysisOperation,
) -> GISWorkflowAlgorithmSpec:
    release = DEFAULT_GIS_ALGORITHM_REGISTRY.resolve(analysis_operation)
    return GISWorkflowAlgorithmSpec.release(
        operation=workflow_operation,
        algorithm_id=release.algorithm_id,
        algorithm_version=release.algorithm_version,
    )


DEFAULT_GIS_WORKFLOW_ALGORITHM_REGISTRY = GISWorkflowAlgorithmRegistry(
    (
        _standalone_release(
            GISWorkflowOperation.INTERSECTION,
            GISAnalysisOperation.INTERSECTION,
        ),
        _standalone_release(
            GISWorkflowOperation.BUFFER,
            GISAnalysisOperation.BUFFER,
        ),
        GISWorkflowAlgorithmSpec.release(
            operation=GISWorkflowOperation.SPATIAL_FILTER,
            algorithm_id="postgis.st_intersects_filter",
            algorithm_version="gda.postgis-workflow.v1",
        ),
        GISWorkflowAlgorithmSpec.release(
            operation=GISWorkflowOperation.AREA_FILTER,
            algorithm_id="postgis.st_area_filter_geography",
            algorithm_version="gda.postgis-workflow.v1",
        ),
        GISWorkflowAlgorithmSpec.release(
            operation=GISWorkflowOperation.SPATIAL_GROUP_BY,
            algorithm_id="postgis.spatial_admin_area_aggregate",
            algorithm_version="gda.postgis-workflow.v1",
        ),
        GISWorkflowAlgorithmSpec.release(
            operation=GISWorkflowOperation.LAND_USE_SPATIAL_GROUP_BY,
            algorithm_id="postgis.spatial_land_use_area_aggregate",
            algorithm_version="gda.postgis-workflow.v1",
        ),
    )
)


__all__ = [
    "DEFAULT_GIS_WORKFLOW_ALGORITHM_REGISTRY",
    "GISWorkflowAlgorithmRegistry",
    "GISWorkflowAlgorithmSpec",
    "GISWorkflowOperation",
]
