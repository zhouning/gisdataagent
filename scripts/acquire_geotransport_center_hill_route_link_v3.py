#!/usr/bin/env python3
"""Verify NOAA NWM v3 parameters and compile a Center Hill RouteLink subset."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
from typing import Any, Iterator, Mapping

import h5py
import numpy as np
from scipy.io import netcdf_file


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = (
    REPO_ROOT
    / "data/geotransport_v0_1/route_link_public_audit/acquisition_plan.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "data/geotransport_v0_1/route_link_nwm_v3_center_hill"
)
DEFAULT_ARCHIVE = Path("/private/tmp/nwm_parameter_files_v3_prefix.tar.gz")
DEFAULT_README = Path("/private/tmp/README.v3.0.txt")
SCHEMA = "gwm.geotransport.center_hill_route_link_v3_acquisition.v1"
ARCHIVE_URL = (
    "https://www.nohrsc.noaa.gov/owp_files/nwm/nwm_parameters/"
    "NWM_parameter_files_v3.0.tar.gz"
)
README_URL = (
    "https://www.nohrsc.noaa.gov/owp_files/nwm/nwm_parameters/README.v3.0.txt"
)
ARCHIVE_SIZE_BYTES = 4_678_832_855
ARCHIVE_ETAG = '"116e152d7-605cc9d2317f0"'
ARCHIVE_LAST_MODIFIED = "Wed, 20 Sep 2023 16:10:28 GMT"
MAXIMUM_ARCHIVE_BYTES = 4_700_000_000
SUBSET_NAME = "RouteLink_CONUS_NWMv3_CenterHill.nc"
REQUIRED_FIELDS = (
    "link",
    "to",
    "Length",
    "BtmWdth",
    "TopWdth",
    "TopWdthCC",
    "ChSlp",
    "So",
    "n",
    "nCC",
)
OPTIONAL_FIELDS = (
    "feature_id",
    "MusK",
    "MusX",
    "Qi",
    "alt",
    "lat",
    "lon",
    "order",
    "NHDWaterbodyComID",
)
POSITIVE_PARAMETER_FIELDS = (
    "Length",
    "BtmWdth",
    "TopWdth",
    "TopWdthCC",
    "ChSlp",
    "So",
    "n",
    "nCC",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--readme", type=Path, default=DEFAULT_README)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--delete-archive-after-success",
        action="store_true",
        help="Delete the verified multi-gigabyte source archive after outputs exist.",
    )
    return parser.parse_args()


def acquire(
    *,
    archive_path: Path = DEFAULT_ARCHIVE,
    readme_path: Path = DEFAULT_README,
    plan_path: Path = DEFAULT_PLAN,
    output_root: Path = DEFAULT_OUTPUT,
    delete_archive_after_success: bool = False,
) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    plan_body = plan_path.read_bytes()
    plan = json.loads(plan_body)
    requested_ids, active_ids = _feature_ids(plan)
    readme_body = readme_path.read_bytes()
    _validate_readme(readme_body)

    archive_stat = archive_path.stat()
    if archive_stat.st_size > MAXIMUM_ARCHIVE_BYTES:
        raise ValueError("nwm_v3_parameter_archive_exceeds_maximum_size")
    if archive_stat.st_size != ARCHIVE_SIZE_BYTES:
        raise ValueError(
            "nwm_v3_parameter_archive_size_mismatch:"
            f"expected={ARCHIVE_SIZE_BYTES}:actual={archive_stat.st_size}"
        )
    archive_sha256 = _sha256_path(archive_path)

    output_root.mkdir(parents=True, exist_ok=True)
    readme_output = output_root / "README.v3.0.txt"
    readme_output.write_bytes(readme_body)
    with tempfile.TemporaryDirectory(prefix="gwm-nwm-v3-route-link-") as tmp:
        member_path, member_size, source_path = _extract_route_link_member(
            archive_path, Path(tmp)
        )
        member_sha256 = _sha256_path(source_path)
        with _route_link_reader(source_path) as reader:
            audit, subset_values, variable_attributes = _audit_and_select(
                reader,
                requested_ids=requested_ids,
                active_ids=active_ids,
            )
            source_global_attributes = reader.global_attributes()
            source_format = reader.container_format

        subset_path = output_root / SUBSET_NAME
        generated_at = datetime.now(timezone.utc)
        _write_subset(
            subset_path,
            subset_values=subset_values,
            variable_attributes=variable_attributes,
            source_global_attributes=source_global_attributes,
            source_member_path=member_path,
            source_member_sha256=member_sha256,
            source_archive_sha256=archive_sha256,
            generated_at=generated_at,
        )
        subset_body = subset_path.read_bytes()
        subset_audit = _audit_subset(
            subset_path,
            expected_feature_ids=tuple(audit["covered_requested_feature_ids"]),
        )

    manifest = {
        "schema": SCHEMA,
        "status": "pass",
        "retrieved_and_compiled_at": generated_at.isoformat(),
        "processing_started_at": started_at.isoformat(),
        "source": {
            "publisher": "NOAA National Water Center / Office of Water Prediction",
            "parameter_release": "NWM v3.0",
            "archive_url": ARCHIVE_URL,
            "readme_url": README_URL,
            "etag": ARCHIVE_ETAG,
            "last_modified": ARCHIVE_LAST_MODIFIED,
            "content_length_bytes": ARCHIVE_SIZE_BYTES,
            "archive_sha256": archive_sha256,
            "archive_local_path_retained": not delete_archive_after_success,
            "archive_local_path": (
                archive_path.as_posix() if not delete_archive_after_success else None
            ),
            "readme": _artifact(readme_output, readme_body),
            "readme_sha256": hashlib.sha256(readme_body).hexdigest(),
            "route_link_member_path": member_path,
            "route_link_member_size_bytes": member_size,
            "route_link_member_sha256": member_sha256,
            "route_link_container_format": source_format,
            "source_global_attributes": source_global_attributes,
        },
        "input_identity": {
            "center_hill_plan": _artifact(plan_path, plan_body),
            "requested_feature_ids": list(requested_ids),
            "active_feature_ids": list(active_ids),
        },
        "source_route_link_audit": audit,
        "subset": {
            **_artifact(subset_path, subset_body),
            "container_format": "netcdf3_64bit_offset",
            "audit": subset_audit,
        },
        "adjudication": {
            "official_nwm_v3_parameter_source": True,
            "all_required_parameter_fields_present": audit[
                "all_required_parameter_fields_present"
            ],
            "center_hill_requested_feature_coverage": (
                f"{audit['requested_feature_coverage_count']}/"
                f"{len(requested_ids)}"
            ),
            "center_hill_active_feature_coverage": (
                f"{audit['active_feature_coverage_count']}/{len(active_ids)}"
            ),
            "center_hill_active_feature_coverage_complete": True,
            "center_hill_route_link_parameter_development_admitted": True,
            "retrospective_parameter_identity_verified": False,
            "retrospective_identity_reason": (
                "the official NWM v3 parameter distribution and Center Hill feature "
                "axis are verified; byte identity to the separate retrospective "
                "production domain has not been established"
            ),
        },
        "claim_boundary": {
            "public_data_acquired_without_user_supplied_data": True,
            "center_hill_route_link_parameters_available": True,
            "center_hill_initial_hydraulic_state_available": False,
            "center_hill_real_forcing_support_validated": False,
            "center_hill_transition_execution_admitted": False,
            "new_frozen_evaluation_window_required": True,
            "benchmark_validated": False,
            "geospatial_kernel_validated": False,
        },
    }
    manifest_path = output_root / "acquisition_manifest.json"
    _write_json(manifest_path, manifest)
    if delete_archive_after_success:
        archive_path.unlink()
    return manifest


class _RouteLinkReader:
    container_format: str

    def variable_names(self) -> tuple[str, ...]:
        raise NotImplementedError

    def shape(self, name: str) -> tuple[int, ...]:
        raise NotImplementedError

    def dtype(self, name: str) -> np.dtype[Any]:
        raise NotImplementedError

    def values(self, name: str) -> np.ndarray:
        raise NotImplementedError

    def selected(self, name: str, indices: tuple[int, ...]) -> np.ndarray:
        raise NotImplementedError

    def variable_attributes(self, name: str) -> dict[str, Any]:
        raise NotImplementedError

    def global_attributes(self) -> dict[str, Any]:
        raise NotImplementedError


class _Hdf5RouteLinkReader(_RouteLinkReader):
    container_format = "netcdf4_hdf5"

    def __init__(self, path: Path) -> None:
        self.dataset = h5py.File(path, "r")

    def close(self) -> None:
        self.dataset.close()

    def variable_names(self) -> tuple[str, ...]:
        return tuple(
            str(name)
            for name, value in self.dataset.items()
            if isinstance(value, h5py.Dataset)
        )

    def shape(self, name: str) -> tuple[int, ...]:
        return tuple(int(value) for value in self.dataset[name].shape)

    def dtype(self, name: str) -> np.dtype[Any]:
        return np.dtype(self.dataset[name].dtype)

    def values(self, name: str) -> np.ndarray:
        return np.asarray(self.dataset[name][...]).copy()

    def selected(self, name: str, indices: tuple[int, ...]) -> np.ndarray:
        dataset = self.dataset[name]
        if len(dataset.shape) != 1:
            raise ValueError("nwm_v3_route_link_subset_requires_1d_variable")
        ordered = sorted(enumerate(indices), key=lambda item: item[1])
        selected = np.asarray(dataset[[index for _, index in ordered]])
        inverse = np.empty(len(ordered), dtype=np.int64)
        for sorted_position, (original_position, _) in enumerate(ordered):
            inverse[original_position] = sorted_position
        return selected[inverse].copy()

    def variable_attributes(self, name: str) -> dict[str, Any]:
        return _normalise_attributes(self.dataset[name].attrs)

    def global_attributes(self) -> dict[str, Any]:
        return _normalise_attributes(self.dataset.attrs)


class _Netcdf3RouteLinkReader(_RouteLinkReader):
    container_format = "netcdf3"

    def __init__(self, path: Path) -> None:
        self.dataset = netcdf_file(path, "r", mmap=True)

    def close(self) -> None:
        self.dataset.close()

    def variable_names(self) -> tuple[str, ...]:
        return tuple(str(name) for name in self.dataset.variables)

    def shape(self, name: str) -> tuple[int, ...]:
        return tuple(int(value) for value in self.dataset.variables[name].shape)

    def dtype(self, name: str) -> np.dtype[Any]:
        return np.dtype(self.dataset.variables[name].data.dtype)

    def values(self, name: str) -> np.ndarray:
        return np.asarray(self.dataset.variables[name][:]).copy()

    def selected(self, name: str, indices: tuple[int, ...]) -> np.ndarray:
        values = np.asarray(self.dataset.variables[name][:])
        return np.asarray(values[list(indices)]).copy()

    def variable_attributes(self, name: str) -> dict[str, Any]:
        return _normalise_attributes(self.dataset.variables[name]._attributes)

    def global_attributes(self) -> dict[str, Any]:
        return _normalise_attributes(self.dataset._attributes)


@contextmanager
def _route_link_reader(path: Path) -> Iterator[_RouteLinkReader]:
    reader: _RouteLinkReader
    if h5py.is_hdf5(path):
        reader = _Hdf5RouteLinkReader(path)
    else:
        reader = _Netcdf3RouteLinkReader(path)
    try:
        yield reader
    finally:
        reader.close()  # type: ignore[attr-defined]


def _audit_and_select(
    reader: _RouteLinkReader,
    *,
    requested_ids: tuple[int, ...],
    active_ids: tuple[int, ...],
) -> tuple[dict[str, Any], dict[str, np.ndarray], dict[str, dict[str, Any]]]:
    names = set(reader.variable_names())
    missing = [name for name in REQUIRED_FIELDS if name not in names]
    if missing:
        raise ValueError(
            "nwm_v3_route_link_required_fields_missing:" + ",".join(missing)
        )
    link_values = np.asarray(reader.values("link"), dtype=np.int64).reshape(-1)
    if link_values.size != np.unique(link_values).size:
        raise ValueError("nwm_v3_route_link_feature_axis_not_unique")
    source_index = {int(value): index for index, value in enumerate(link_values)}
    covered_requested = tuple(value for value in requested_ids if value in source_index)
    covered_active = tuple(value for value in active_ids if value in source_index)
    missing_active = tuple(value for value in active_ids if value not in source_index)
    if missing_active:
        raise ValueError(
            "nwm_v3_route_link_center_hill_active_features_missing:"
            + ",".join(str(value) for value in missing_active)
        )
    selected_ids = covered_requested
    indices = tuple(source_index[value] for value in selected_ids)
    subset_values: dict[str, np.ndarray] = {}
    variable_attributes: dict[str, dict[str, Any]] = {}
    field_audit: dict[str, dict[str, Any]] = {}
    for name in REQUIRED_FIELDS + OPTIONAL_FIELDS:
        if name not in names:
            continue
        shape = reader.shape(name)
        if shape != (link_values.size,):
            if name in REQUIRED_FIELDS:
                raise ValueError(
                    f"nwm_v3_route_link_required_field_axis_mismatch:{name}:{shape}"
                )
            continue
        values = reader.selected(name, indices)
        if values.dtype.kind not in "biuf":
            if name in REQUIRED_FIELDS:
                raise ValueError(
                    f"nwm_v3_route_link_required_field_not_numeric:{name}"
                )
            continue
        numeric = values.astype(float)
        if not np.isfinite(numeric).all():
            raise ValueError(f"nwm_v3_route_link_selected_values_nonfinite:{name}")
        if name in POSITIVE_PARAMETER_FIELDS and bool((numeric <= 0.0).any()):
            raise ValueError(f"nwm_v3_route_link_selected_parameter_not_positive:{name}")
        subset_values[name] = values
        variable_attributes[name] = reader.variable_attributes(name)
        field_audit[name] = {
            "source_dtype": str(reader.dtype(name)),
            "source_shape": list(shape),
            "subset_dtype": str(values.dtype),
            "subset_value_count": int(values.size),
            "minimum": float(numeric.min()),
            "maximum": float(numeric.max()),
            "all_finite": True,
        }
    selected_links = tuple(int(value) for value in subset_values["link"])
    if selected_links != selected_ids:
        raise RuntimeError("nwm_v3_route_link_subset_feature_order_mismatch")
    selected_to = {
        int(link): int(to)
        for link, to in zip(
            subset_values["link"], subset_values["to"], strict=True
        )
    }
    active_topology_pairs = [
        {
            "upstream": upstream,
            "declared_downstream": selected_to[upstream],
            "expected_downstream": downstream,
            "matches": selected_to[upstream] == downstream,
        }
        for upstream, downstream in zip(active_ids[:-1], active_ids[1:], strict=True)
    ]
    if not all(item["matches"] for item in active_topology_pairs):
        raise ValueError("nwm_v3_route_link_center_hill_active_topology_mismatch")
    return (
        {
            "source_feature_count": int(link_values.size),
            "source_unique_feature_count": int(np.unique(link_values).size),
            "source_variable_names": sorted(names),
            "required_parameter_fields": list(REQUIRED_FIELDS),
            "required_parameter_fields_missing": missing,
            "all_required_parameter_fields_present": not missing,
            "optional_fields_present": [
                name for name in OPTIONAL_FIELDS if name in subset_values
            ],
            "requested_feature_count": len(requested_ids),
            "requested_feature_coverage_count": len(covered_requested),
            "covered_requested_feature_ids": list(covered_requested),
            "missing_requested_feature_ids": [
                value for value in requested_ids if value not in source_index
            ],
            "active_feature_count": len(active_ids),
            "active_feature_coverage_count": len(covered_active),
            "covered_active_feature_ids": list(covered_active),
            "missing_active_feature_ids": list(missing_active),
            "active_topology_pairs": active_topology_pairs,
            "active_topology_consecutive": True,
            "selected_field_audit": field_audit,
            "no_default_parameter_substitution": True,
        },
        subset_values,
        variable_attributes,
    )


def _write_subset(
    path: Path,
    *,
    subset_values: Mapping[str, np.ndarray],
    variable_attributes: Mapping[str, Mapping[str, Any]],
    source_global_attributes: Mapping[str, Any],
    source_member_path: str,
    source_member_sha256: str,
    source_archive_sha256: str,
    generated_at: datetime,
    history_subject: str = "Center Hill feature subset",
    subset_semantics: str = "selected source rows in requested path order",
) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    feature_count = int(len(subset_values["link"]))
    with netcdf_file(temporary, "w", version=2) as dataset:
        dataset.createDimension("feature", feature_count)
        dataset.history = (
            f"{generated_at.isoformat()} {history_subject} compiled by "
            "gisdataagent; no parameter substitution"
        )
        dataset.source_archive_url = ARCHIVE_URL
        dataset.source_archive_sha256 = source_archive_sha256
        dataset.source_member_path = source_member_path
        dataset.source_member_sha256 = source_member_sha256
        dataset.parameter_release = "NWM v3.0"
        dataset.subset_semantics = subset_semantics
        dataset.source_global_attributes_json = json.dumps(
            source_global_attributes, ensure_ascii=True, sort_keys=True
        )
        for name, values in subset_values.items():
            encoded, typecode = _netcdf3_values(values, name=name)
            variable = dataset.createVariable(name, typecode, ("feature",))
            variable[:] = encoded
            for key, value in variable_attributes.get(name, {}).items():
                if key.startswith("_"):
                    continue
                encoded_attribute = _netcdf_attribute(value)
                if encoded_attribute is not None:
                    setattr(variable, key, encoded_attribute)
    temporary.replace(path)


def _audit_subset(
    path: Path, *, expected_feature_ids: tuple[int, ...]
) -> dict[str, Any]:
    with _route_link_reader(path) as reader:
        names = set(reader.variable_names())
        links = tuple(int(value) for value in reader.values("link").reshape(-1))
        missing = [name for name in REQUIRED_FIELDS if name not in names]
        if links != expected_feature_ids or missing:
            raise RuntimeError("nwm_v3_route_link_written_subset_audit_failed")
        return {
            "feature_count": len(links),
            "feature_ids": list(links),
            "variable_names": sorted(names),
            "required_parameter_fields_missing": missing,
            "all_required_parameter_fields_present": True,
            "feature_axis_matches_requested_covered_order": True,
        }


def _extract_route_link_member(
    archive_path: Path, temporary_root: Path
) -> tuple[str, int, Path]:
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as archive:
        candidates = []
        for member in archive:
            member_path = PurePosixPath(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ValueError("nwm_v3_parameter_archive_unsafe_member_path")
            if member_path.name == "RouteLink_CONUS.nc":
                candidates.append(member)
        if len(candidates) != 1:
            raise ValueError(
                "nwm_v3_parameter_archive_route_link_member_count_mismatch:"
                f"{len(candidates)}"
            )
        member = candidates[0]
        if not member.isfile() or member.size <= 0:
            raise ValueError("nwm_v3_parameter_archive_route_link_member_invalid")
        source = archive.extractfile(member)
        if source is None:
            raise RuntimeError("nwm_v3_parameter_archive_route_link_open_failed")
        output = temporary_root / "RouteLink_CONUS.nc"
        with source, output.open("wb") as destination:
            shutil.copyfileobj(source, destination, length=1024 * 1024)
        if output.stat().st_size != member.size:
            raise RuntimeError("nwm_v3_parameter_route_link_extraction_size_mismatch")
        return member.name, int(member.size), output


def _feature_ids(plan: Mapping[str, Any]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    if plan.get("schema") != "gwm.geotransport.public_route_link_audit.v1":
        raise ValueError("nwm_v3_center_hill_feature_plan_invalid")
    requested = tuple(int(value) for value in plan["center_hill_feature_ids"])
    active = tuple(int(value) for value in plan["center_hill_active_feature_ids"])
    if (
        not requested
        or not active
        or len(requested) != len(set(requested))
        or len(active) != len(set(active))
        or not set(active).issubset(requested)
    ):
        raise ValueError("nwm_v3_center_hill_feature_plan_axis_invalid")
    return requested, active


def _validate_readme(body: bytes) -> None:
    text = body.decode("utf-8", errors="replace")
    required = ("NWM V3.0", "RouteLink_DOMAIN.nc")
    if any(value.casefold() not in text.casefold() for value in required):
        raise ValueError("nwm_v3_parameter_readme_identity_mismatch")


def _normalise_attributes(attributes: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): _normalise_value(value)
        for key, value in attributes.items()
        if not str(key).startswith("_")
    }


def _normalise_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.generic):
        return _normalise_value(value.item())
    if isinstance(value, np.ndarray):
        return [_normalise_value(item) for item in value.tolist()]
    if isinstance(value, (list, tuple)):
        return [_normalise_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _netcdf3_values(
    values: np.ndarray, *, name: str
) -> tuple[np.ndarray, str]:
    array = np.asarray(values)
    if array.dtype.kind in "biu":
        numeric = array.astype(np.int64)
        info = np.iinfo(np.int32)
        if bool((numeric < info.min).any()) or bool((numeric > info.max).any()):
            raise ValueError(f"nwm_v3_route_link_integer_outside_netcdf3_range:{name}")
        return numeric.astype(np.int32), "i"
    if array.dtype.kind == "f":
        if array.dtype.itemsize <= 4:
            return array.astype(np.float32), "f"
        return array.astype(np.float64), "d"
    raise ValueError(f"nwm_v3_route_link_unsupported_subset_dtype:{name}")


def _netcdf_attribute(value: Any) -> str | int | float | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (str, int, float)):
        return value
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=True, sort_keys=True)
    return None


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        display = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        display = resolved.as_posix()
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    manifest = acquire(
        archive_path=args.archive,
        readme_path=args.readme,
        plan_path=args.plan,
        output_root=args.output,
        delete_archive_after_success=args.delete_archive_after_success,
    )
    print(args.output / "acquisition_manifest.json")
    print(
        "center_hill_active_feature_coverage="
        + manifest["adjudication"]["center_hill_active_feature_coverage"]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
