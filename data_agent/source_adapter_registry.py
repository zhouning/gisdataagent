"""Declarative, fail-closed contracts for governed source ingestion."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from data_agent.standards_platform.application.acceptance import sha256_file

_SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class SourceKind(StrEnum):
    VECTOR = "vector"
    RASTER = "raster"
    TABULAR = "tabular"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AdapterOperationRef(_FrozenModel):
    """Versioned reference to executable profiling or transform code."""

    adapter_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,127}$")
    version: str

    @model_validator(mode="after")
    def _valid_version(self) -> AdapterOperationRef:
        if not _SEMVER_RE.fullmatch(self.version):
            raise ValueError("adapter operation version must be semantic x.y.z")
        return self


class BundleMemberRule(_FrozenModel):
    """One explicitly governed member of a logical source bundle."""

    role: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,63}$")
    path_mode: Literal["primary", "replace_extension", "append_to_name"]
    suffix: str = ""
    required: bool = False

    @model_validator(mode="after")
    def _valid_path_rule(self) -> BundleMemberRule:
        if self.path_mode == "primary":
            if self.suffix:
                raise ValueError("primary bundle member cannot define a suffix")
            if not self.required:
                raise ValueError("primary bundle member must be required")
        elif not self.suffix.startswith("."):
            raise ValueError("companion member suffix must start with '.'")
        return self


class BundlePolicy(_FrozenModel):
    policy_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,127}$")
    version: str
    members: tuple[BundleMemberRule, ...]
    reject_unlisted_same_stem_members: bool = True

    @model_validator(mode="after")
    def _valid_policy(self) -> BundlePolicy:
        if not _SEMVER_RE.fullmatch(self.version):
            raise ValueError("bundle policy version must be semantic x.y.z")
        primary_count = sum(rule.path_mode == "primary" for rule in self.members)
        if primary_count != 1:
            raise ValueError("bundle policy must define exactly one primary member")
        roles = [rule.role for rule in self.members]
        if len(roles) != len(set(roles)):
            raise ValueError("bundle member roles must be unique")
        paths = [(rule.path_mode, rule.suffix.casefold()) for rule in self.members]
        if len(paths) != len(set(paths)):
            raise ValueError("bundle member paths must be unique")
        return self


class PromotionPolicy(_FrozenModel):
    eligible: bool = False
    required_decisions: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()


class SourceAdapterDefinition(_FrozenModel):
    """Versioned declaration that controls one governed source shape."""

    adapter_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,127}$")
    version: str
    source_kind: SourceKind
    extensions: tuple[str, ...]
    drivers: tuple[str, ...]
    bundle_policy: BundlePolicy
    profiler: AdapterOperationRef
    transform: AdapterOperationRef
    logical_target_stage: Literal["ods", "dwd", "dws", "ads"]
    classification: Literal["public", "internal", "confidential", "restricted"]
    required_evidence: tuple[str, ...]
    required_checks: tuple[str, ...]
    promotion_policy: PromotionPolicy

    @model_validator(mode="after")
    def _valid_adapter(self) -> SourceAdapterDefinition:
        if not _SEMVER_RE.fullmatch(self.version):
            raise ValueError("source adapter version must be semantic x.y.z")
        if not self.extensions:
            raise ValueError("source adapter must declare at least one extension")
        if any(
            not extension.startswith(".") or extension != extension.casefold()
            for extension in self.extensions
        ):
            raise ValueError("source extensions must be lowercase and start with '.'")
        if len(self.extensions) != len(set(self.extensions)):
            raise ValueError("source extensions must be unique")
        if not self.drivers or len(self.drivers) != len(set(self.drivers)):
            raise ValueError("source drivers must be non-empty and unique")
        if not self.required_evidence or not self.required_checks:
            raise ValueError("source adapter must declare evidence and checks")
        if self.classification == "restricted" and self.promotion_policy.eligible:
            raise ValueError("restricted source cannot be directly promotion eligible")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json"))

    def reference(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "version": self.version,
            "fingerprint": self.fingerprint,
            "source_kind": self.source_kind.value,
            "profiler": self.profiler.model_dump(mode="json"),
            "transform": self.transform.model_dump(mode="json"),
            "bundle_policy": {
                "policy_id": self.bundle_policy.policy_id,
                "version": self.bundle_policy.version,
            },
            "logical_target_stage": self.logical_target_stage,
            "classification": self.classification,
            "required_evidence": list(self.required_evidence),
            "required_checks": list(self.required_checks),
            "promotion_policy": self.promotion_policy.model_dump(mode="json"),
        }


SHAPEFILE_BUNDLE_POLICY = BundlePolicy(
    policy_id="esri-shapefile-bundle",
    version="1.0.0",
    members=(
        BundleMemberRule(role="geometry", path_mode="primary", required=True),
        BundleMemberRule(
            role="shape-index",
            path_mode="replace_extension",
            suffix=".shx",
            required=True,
        ),
        BundleMemberRule(
            role="attributes",
            path_mode="replace_extension",
            suffix=".dbf",
            required=True,
        ),
        BundleMemberRule(
            role="projection", path_mode="replace_extension", suffix=".prj"
        ),
        BundleMemberRule(
            role="encoding", path_mode="replace_extension", suffix=".cpg"
        ),
        BundleMemberRule(
            role="spatial-index-sbn",
            path_mode="replace_extension",
            suffix=".sbn",
        ),
        BundleMemberRule(
            role="spatial-index-sbx",
            path_mode="replace_extension",
            suffix=".sbx",
        ),
        BundleMemberRule(
            role="spatial-index-qix",
            path_mode="replace_extension",
            suffix=".qix",
        ),
        BundleMemberRule(
            role="spatial-index-fix",
            path_mode="replace_extension",
            suffix=".fix",
        ),
        BundleMemberRule(
            role="metadata",
            path_mode="append_to_name",
            suffix=".xml",
        ),
    ),
)

GEOTIFF_DEM_BUNDLE_POLICY = BundlePolicy(
    policy_id="geotiff-dem-sidecar-bundle",
    version="1.0.0",
    members=(
        BundleMemberRule(role="raster", path_mode="primary", required=True),
        BundleMemberRule(
            role="world-file", path_mode="replace_extension", suffix=".tfw"
        ),
        BundleMemberRule(
            role="gdal-auxiliary", path_mode="append_to_name", suffix=".aux.xml"
        ),
        BundleMemberRule(
            role="external-overviews", path_mode="append_to_name", suffix=".ovr"
        ),
        BundleMemberRule(
            role="value-table-encoding",
            path_mode="append_to_name",
            suffix=".vat.cpg",
        ),
        BundleMemberRule(
            role="value-table",
            path_mode="append_to_name",
            suffix=".vat.dbf",
        ),
        BundleMemberRule(
            role="metadata", path_mode="append_to_name", suffix=".xml"
        ),
    ),
)

CENTRAL_BUILDINGS_SOURCE_ADAPTER = SourceAdapterDefinition(
    adapter_id="chongqing-central-buildings-shapefile",
    version="1.0.0",
    source_kind=SourceKind.VECTOR,
    extensions=(".shp",),
    drivers=("ESRI Shapefile",),
    bundle_policy=SHAPEFILE_BUNDLE_POLICY,
    profiler=AdapterOperationRef(
        adapter_id="central-buildings-full-scan", version="1.0.0"
    ),
    transform=AdapterOperationRef(
        adapter_id="central-buildings-multipolygon-geojson", version="1.0.0"
    ),
    logical_target_stage="ods",
    classification="restricted",
    required_evidence=(
        "sealed_source_bundle",
        "full_feature_scan",
        "immutable_snapshot_readback",
        "defect_ledger",
    ),
    required_checks=(
        "feature_count_conservation",
        "source_fid_uniqueness",
        "geometry_defects_recorded",
        "physical_sha256_verified",
    ),
    promotion_policy=PromotionPolicy(
        blockers=("license_unconfirmed", "standard_mapping_unapproved")
    ),
)

CHONGQING_DEM_SOURCE_ADAPTER = SourceAdapterDefinition(
    adapter_id="chongqing-aster-gdem-geotiff",
    version="1.0.0",
    source_kind=SourceKind.RASTER,
    extensions=(".tif", ".tiff"),
    drivers=("GTiff",),
    bundle_policy=GEOTIFF_DEM_BUNDLE_POLICY,
    profiler=AdapterOperationRef(adapter_id="rasterio-full-pixel-scan", version="1.0.0"),
    transform=AdapterOperationRef(adapter_id="byte-preserving-raster-snapshot", version="1.0.0"),
    logical_target_stage="ods",
    classification="restricted",
    required_evidence=(
        "sealed_source_bundle",
        "full_pixel_scan",
        "immutable_bundle_readback",
        "raster_grid_profile",
    ),
    required_checks=(
        "driver_allowed",
        "crs_present",
        "pixel_accounting_exact",
        "physical_sha256_verified",
    ),
    promotion_policy=PromotionPolicy(
        blockers=(
            "license_unconfirmed",
            "cog_conformance_not_evaluated",
            "standard_mapping_unapproved",
        )
    ),
)

SOURCE_ADAPTERS = {
    adapter.adapter_id: adapter
    for adapter in (CENTRAL_BUILDINGS_SOURCE_ADAPTER, CHONGQING_DEM_SOURCE_ADAPTER)
}


def resolve_source_adapter(
    adapter_id: str,
    source_path: Path,
    *,
    observed_driver: str | None = None,
) -> SourceAdapterDefinition:
    """Resolve an adapter and reject undeclared source shapes."""

    try:
        adapter = SOURCE_ADAPTERS[adapter_id]
    except KeyError as exc:
        raise ValueError(f"unknown source adapter: {adapter_id}") from exc
    extension = source_path.suffix.casefold()
    if extension not in adapter.extensions:
        raise ValueError(
            f"adapter {adapter_id} does not allow source extension {extension!r}"
        )
    if observed_driver is not None and observed_driver not in adapter.drivers:
        raise ValueError(
            f"adapter {adapter_id} does not allow source driver {observed_driver!r}"
        )
    return adapter


def sealed_bundle_identity(
    source_path: Path,
    adapter: SourceAdapterDefinition,
) -> dict[str, Any]:
    """Hash every declared bundle member and reject ambiguous companions."""

    source = source_path.resolve(strict=True)
    if not source.is_file():
        raise FileNotFoundError(source)
    resolve_source_adapter(adapter.adapter_id, source)

    resolved: list[tuple[BundleMemberRule, Path]] = []
    for rule in adapter.bundle_policy.members:
        member = _member_path(source, rule)
        if member.is_file():
            resolved.append((rule, member))
        elif rule.required:
            raise FileNotFoundError(
                f"required bundle member {rule.role!r} is missing: {member}"
            )

    governed_paths = {path.resolve() for _, path in resolved}
    if adapter.bundle_policy.reject_unlisted_same_stem_members:
        unlisted = sorted(
            candidate.name
            for candidate in source.parent.glob(f"{source.stem}*")
            if candidate.is_file() and candidate.resolve() not in governed_paths
        )
        if unlisted:
            raise ValueError(f"unlisted same-stem bundle members: {unlisted}")

    members = [
        {
            "name": path.name,
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for _, path in resolved
    ]
    bundle_sha256 = (
        members[0]["sha256"] if len(members) == 1 else _canonical_sha256(members)
    )
    return {
        "bundle_sha256": bundle_sha256,
        "size_bytes": sum(member["size_bytes"] for member in members),
        "members": members,
        "member_roles": [rule.role for rule, _ in resolved],
        "bundle_policy_id": adapter.bundle_policy.policy_id,
        "bundle_policy_version": adapter.bundle_policy.version,
    }


def bundle_member_paths(
    source_path: Path,
    adapter: SourceAdapterDefinition,
) -> tuple[Path, ...]:
    """Return members in the same governed order used by bundle identity."""

    identity = sealed_bundle_identity(source_path, adapter)
    return tuple(source_path.parent / member["name"] for member in identity["members"])


def _member_path(source: Path, rule: BundleMemberRule) -> Path:
    if rule.path_mode == "primary":
        return source
    if rule.path_mode == "replace_extension":
        return source.with_suffix(rule.suffix)
    return source.with_name(f"{source.name}{rule.suffix}")


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
