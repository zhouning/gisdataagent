"""Compile registered Makani geometry and facility crosswalk candidates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .network_compiler import PipelineCompilePolicy, compile_pipeline_topology
from .registered_makani_acquisition import LAYER_SPECS
from .smartmakani_acquisition import TARGET_CRS, canonical_json_bytes

REGISTERED_CROSSWALK_SCHEMA = "gwm.abu_dhabi_flood.registered_crosswalk_audit.v1"
REGISTERED_NETWORK_SCHEMA = "gwm.abu_dhabi_flood.registered_network_candidate.v1"
REGISTERED_NETWORK_AUDIT_SCHEMA = (
    "gwm.abu_dhabi_flood.registered_network_candidate_audit.v1"
)
_REFERENCE_SENTINELS = frozenset(
    {
        "NC",
        "N/C",
        "N.A",
        "N/A",
        "NA",
        "NONE",
        "NULL",
        "UNKNOWN",
        "NOT CONNECTED",
        "NOT APPLICABLE",
        "0",
        "-",
        "NIL",
    }
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(canonical_json_bytes(payload))
    temporary.replace(path)


def _atomic_write_parquet(path: Path, frame: Any) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)
    return {
        "path": path.name,
        "record_count": len(frame),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _path_label(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _normalize_identifier(values: Any) -> Any:
    normalized = values.astype("string").str.strip().str.upper()
    return normalized.mask(normalized.eq(""))


def _require_columns(frame: Any, names: set[str], *, contract: str) -> None:
    missing = sorted(names.difference(frame.columns))
    if missing:
        raise ValueError(f"{contract}_missing_columns:{','.join(missing)}")


def standardize_registered_pipelines(pipelines: Any) -> Any:
    """Map the minimized registered schema to the shared topology compiler."""

    import geopandas as gpd

    _require_columns(
        pipelines,
        {
            "fid",
            "pipe_diameter",
            "invert_level_upstream",
            "invert_level_downstream",
        },
        contract="registered_pipeline",
    )
    if pipelines.crs is None:
        raise ValueError("registered_pipeline_crs_required")
    frame = pipelines.to_crs(TARGET_CRS).copy().reset_index(drop=True)
    if frame.geometry.name != "geometry":
        frame = frame.rename_geometry("geometry")
    frame["registered_pipeline_fid"] = frame["fid"]
    frame["OBJECTID"] = frame["fid"]
    frame["ASSET_DIAMETER"] = frame["pipe_diameter"]
    frame["INVERT_LEVEL_UP"] = frame["invert_level_upstream"]
    frame["INVERT_LEVEL_DOWN"] = frame["invert_level_downstream"]
    return gpd.GeoDataFrame(frame, geometry="geometry", crs=TARGET_CRS)


def aggregate_facility_attachments_to_nodes(
    pipelines: Any,
    nodes: Any,
    attachments: Any,
    *,
    maximum_distance_m: float = 1.0,
) -> tuple[Any, Any, dict[str, Any]]:
    """Attach candidate facilities to snapped geometry endpoint nodes."""

    import geopandas as gpd
    import numpy as np
    import pandas as pd

    if maximum_distance_m <= 0:
        raise ValueError("facility_attachment_distance_m_must_be_positive")
    _require_columns(
        pipelines,
        {
            "registered_pipeline_fid",
            "source_node_id",
            "target_node_id",
            "geometry_supported",
        },
        contract="compiled_registered_pipeline",
    )
    _require_columns(
        attachments,
        {
            "registered_pipeline_fid",
            "endpoint_role",
            "facility_role",
            "registered_facility_fid",
            "nearest_geometry_endpoint",
            "nearest_endpoint_distance_m",
        },
        contract="registered_facility_attachment",
    )
    if pipelines["registered_pipeline_fid"].duplicated().any():
        raise ValueError("registered_pipeline_fid_not_unique")

    endpoint_map = pipelines[
        [
            "registered_pipeline_fid",
            "source_node_id",
            "target_node_id",
            "geometry_supported",
        ]
    ]
    candidates = attachments[
        attachments["nearest_endpoint_distance_m"].le(maximum_distance_m)
    ].copy()
    candidates = candidates.merge(
        endpoint_map,
        on="registered_pipeline_fid",
        how="left",
        validate="many_to_one",
        indicator=True,
    )
    valid_endpoint = candidates["nearest_geometry_endpoint"].isin(
        ["geometry_start", "geometry_end"]
    )
    candidates["node_id"] = np.select(
        [
            candidates["nearest_geometry_endpoint"].eq("geometry_start"),
            candidates["nearest_geometry_endpoint"].eq("geometry_end"),
        ],
        [candidates["source_node_id"], candidates["target_node_id"]],
        default=None,
    )
    mapped = candidates[
        candidates["_merge"].eq("both")
        & candidates["geometry_supported"].fillna(False)
        & valid_endpoint
        & candidates["node_id"].notna()
    ].copy()

    def joined(values: Any) -> str:
        return "|".join(sorted({str(value) for value in values if pd.notna(value)}))

    links = (
        mapped.groupby(
            ["node_id", "facility_role", "registered_facility_fid"],
            as_index=False,
            sort=True,
        )
        .agg(
            pipeline_attachment_count=("registered_pipeline_fid", "size"),
            registered_pipeline_count=("registered_pipeline_fid", "nunique"),
            minimum_endpoint_distance_m=("nearest_endpoint_distance_m", "min"),
            endpoint_roles=("endpoint_role", joined),
            geometry_endpoints=("nearest_geometry_endpoint", joined),
        )
        .sort_values(["node_id", "facility_role", "registered_facility_fid"])
        .reset_index(drop=True)
    )
    links["match_method"] = "unitid_exact_unique_then_endpoint_within_1m"
    links["evidence_level"] = "candidate"
    links["admitted"] = False

    attachment_counts = mapped.groupby("node_id").size().rename(
        "candidate_facility_attachment_count"
    )
    facility_counts = links.groupby("node_id").size().rename(
        "candidate_facility_count"
    )
    facility_roles = links.groupby("node_id")["facility_role"].agg(joined).rename(
        "candidate_facility_roles"
    )
    role_sets = {
        "candidate_surface_intake_count": {"inlet", "catchbasin"},
        "candidate_outfall_count": {"outfall"},
        "candidate_pump_count": {"pump", "pumping_station_structure"},
    }
    summaries = [attachment_counts, facility_counts, facility_roles]
    for column, roles in role_sets.items():
        summaries.append(
            links[links["facility_role"].isin(roles)]
            .groupby("node_id")
            .size()
            .rename(column)
        )
    node_summary = pd.concat(summaries, axis=1).reset_index()
    enriched_nodes = nodes.merge(node_summary, on="node_id", how="left")
    count_columns = [
        "candidate_facility_attachment_count",
        "candidate_facility_count",
        *role_sets,
    ]
    for column in count_columns:
        enriched_nodes[column] = enriched_nodes[column].fillna(0).astype("int64")
    enriched_nodes["candidate_facility_roles"] = enriched_nodes[
        "candidate_facility_roles"
    ].fillna("")
    enriched_nodes["has_candidate_facility"] = enriched_nodes[
        "candidate_facility_count"
    ].gt(0)
    enriched_nodes["facility_semantics_admitted"] = False
    enriched_nodes = gpd.GeoDataFrame(
        enriched_nodes,
        geometry=nodes.geometry.name,
        crs=nodes.crs,
    )

    mapped_endpoint_count = len(
        mapped[
            ["registered_pipeline_fid", "nearest_geometry_endpoint"]
        ].drop_duplicates()
    )
    supported_endpoint_count = int(pipelines["geometry_supported"].sum()) * 2
    role_counts = []
    for role, group in mapped.groupby("facility_role", sort=True):
        role_links = links[links["facility_role"].eq(role)]
        role_counts.append(
            {
                "facility_role": role,
                "attachment_count": len(group),
                "node_facility_candidate_count": len(role_links),
                "distinct_facility_count": int(
                    role_links["registered_facility_fid"].nunique()
                ),
                "node_count": int(role_links["node_id"].nunique()),
            }
        )
    audit = {
        "input_attachment_count": len(attachments),
        "within_distance_attachment_count": len(candidates),
        "outside_distance_attachment_count": len(attachments) - len(candidates),
        "maximum_distance_m": maximum_distance_m,
        "mapped_attachment_count": len(mapped),
        "unmapped_attachment_count": len(candidates) - len(mapped),
        "mapped_pipeline_endpoint_count": mapped_endpoint_count,
        "supported_pipeline_endpoint_count": supported_endpoint_count,
        "mapped_pipeline_endpoint_percent": round(
            mapped_endpoint_count / supported_endpoint_count * 100.0
            if supported_endpoint_count
            else 0.0,
            6,
        ),
        "residual_unmatched_pipeline_endpoint_count": (
            supported_endpoint_count - mapped_endpoint_count
        ),
        "node_facility_candidate_count": len(links),
        "distinct_facility_count": len(
            links[["facility_role", "registered_facility_fid"]].drop_duplicates()
        ),
        "nodes_with_candidate_facility_count": int(
            enriched_nodes["has_candidate_facility"].sum()
        ),
        "nodes_with_surface_intake_candidate_count": int(
            enriched_nodes["candidate_surface_intake_count"].gt(0).sum()
        ),
        "nodes_with_outfall_candidate_count": int(
            enriched_nodes["candidate_outfall_count"].gt(0).sum()
        ),
        "nodes_with_pump_candidate_count": int(
            enriched_nodes["candidate_pump_count"].gt(0).sum()
        ),
        "matches_by_role": role_counts,
        "facility_identity_key": ["facility_role", "registered_facility_fid"],
        "source_target_node_labels_are_geometry_orientation_only": True,
        "source_target_node_labels_are_verified_hydraulic_direction": False,
        "outfall_or_pump_connectivity_authoritative": False,
        "nodes_are_surface_patches": False,
        "admitted": False,
    }
    return enriched_nodes, links, audit


def _valid_reference(values: Any) -> Any:
    normalized = _normalize_identifier(values)
    return normalized.mask(normalized.isin(_REFERENCE_SENTINELS))


def _summary(values: Any) -> dict[str, float | int | None]:
    import numpy as np

    array = np.asarray(values, dtype="float64")
    array = array[np.isfinite(array)]
    if not len(array):
        return {
            "count": 0,
            "minimum": None,
            "median": None,
            "p95": None,
            "p99": None,
            "maximum": None,
        }
    return {
        "count": int(len(array)),
        "minimum": float(array.min()),
        "median": float(np.median(array)),
        "p95": float(np.quantile(array, 0.95)),
        "p99": float(np.quantile(array, 0.99)),
        "maximum": float(array.max()),
    }


def _endpoint_keys(geometries: Any, tolerance_m: float) -> tuple[Any, Any]:
    import numpy as np
    import pandas as pd
    import shapely

    merged = shapely.line_merge(geometries)
    valid = shapely.get_type_id(merged) == 1
    keys: list[tuple[int, int, int, int] | None] = [None] * len(merged)
    valid_indexes = np.flatnonzero(valid)
    if len(valid_indexes):
        selected = merged[valid_indexes]
        starts = shapely.get_point(selected, 0)
        ends = shapely.get_point(selected, -1)
        sx = np.rint(shapely.get_x(starts) / tolerance_m).astype("int64")
        sy = np.rint(shapely.get_y(starts) / tolerance_m).astype("int64")
        ex = np.rint(shapely.get_x(ends) / tolerance_m).astype("int64")
        ey = np.rint(shapely.get_y(ends) / tolerance_m).astype("int64")
        swap = (sx > ex) | ((sx == ex) & (sy > ey))
        first_x = np.where(swap, ex, sx)
        first_y = np.where(swap, ey, sy)
        second_x = np.where(swap, sx, ex)
        second_y = np.where(swap, sy, ey)
        for offset, index in enumerate(valid_indexes):
            keys[int(index)] = (
                int(first_x[offset]),
                int(first_y[offset]),
                int(second_x[offset]),
                int(second_y[offset]),
            )
    return pd.Series(keys, dtype="object"), merged


def match_public_registered_pipelines(
    public_pipelines: Any,
    registered_pipelines: Any,
    *,
    endpoint_grid_m: float = 0.1,
    maximum_endpoint_error_m: float = 0.25,
    maximum_hausdorff_m: float = 0.5,
    maximum_relative_length_delta: float = 0.01,
) -> tuple[Any, dict[str, Any]]:
    """Return unique geometry matches that pass strict shape checks."""

    import numpy as np
    import pandas as pd
    import shapely

    public_keys, public_lines = _endpoint_keys(
        public_pipelines.geometry.array,
        endpoint_grid_m,
    )
    registered_keys, registered_lines = _endpoint_keys(
        registered_pipelines.geometry.array,
        endpoint_grid_m,
    )
    public_counts = public_keys.dropna().value_counts()
    registered_counts = registered_keys.dropna().value_counts()
    unique_keys = set(public_counts[public_counts.eq(1)].index).intersection(
        registered_counts[registered_counts.eq(1)].index
    )
    public_index = pd.DataFrame(
        {"endpoint_key": public_keys, "public_row_index": np.arange(len(public_keys))}
    )
    registered_index = pd.DataFrame(
        {
            "endpoint_key": registered_keys,
            "registered_row_index": np.arange(len(registered_keys)),
        }
    )
    public_index = public_index[
        public_index["endpoint_key"].map(lambda value: value in unique_keys)
    ]
    registered_index = registered_index[
        registered_index["endpoint_key"].map(lambda value: value in unique_keys)
    ]
    candidates = public_index.merge(
        registered_index,
        on="endpoint_key",
        validate="one_to_one",
    )
    public_rows = candidates["public_row_index"].to_numpy(dtype="int64")
    registered_rows = candidates["registered_row_index"].to_numpy(dtype="int64")
    public_geometry = shapely.force_2d(public_lines[public_rows])
    registered_geometry = shapely.force_2d(registered_lines[registered_rows])
    public_start = shapely.get_point(public_geometry, 0)
    public_end = shapely.get_point(public_geometry, -1)
    registered_start = shapely.get_point(registered_geometry, 0)
    registered_end = shapely.get_point(registered_geometry, -1)
    direct = np.maximum(
        shapely.distance(public_start, registered_start),
        shapely.distance(public_end, registered_end),
    )
    reverse = np.maximum(
        shapely.distance(public_start, registered_end),
        shapely.distance(public_end, registered_start),
    )
    endpoint_error = np.minimum(direct, reverse)
    hausdorff = shapely.hausdorff_distance(public_geometry, registered_geometry)
    public_length = shapely.length(public_geometry)
    registered_length = shapely.length(registered_geometry)
    relative_length_delta = np.abs(public_length - registered_length) / np.maximum(
        np.maximum(public_length, registered_length),
        0.01,
    )
    accepted = (
        (endpoint_error <= maximum_endpoint_error_m)
        & (hausdorff <= maximum_hausdorff_m)
        & (relative_length_delta <= maximum_relative_length_delta)
    )
    crosswalk = pd.DataFrame(
        {
            "public_source_object_id": public_pipelines.iloc[public_rows][
                "source_object_id"
            ].to_numpy(),
            "registered_fid": registered_pipelines.iloc[registered_rows][
                "fid"
            ].to_numpy(),
            "endpoint_error_m": endpoint_error,
            "hausdorff_distance_m": hausdorff,
            "relative_length_delta": relative_length_delta,
            "orientation_reversed": reverse < direct,
            "match_method": "unique_endpoint_grid_0_1m_shape_validated",
            "evidence_level": "candidate_high",
            "admitted": False,
        }
    ).loc[accepted]
    crosswalk = crosswalk.sort_values(
        ["public_source_object_id", "registered_fid"]
    ).reset_index(drop=True)
    audit = {
        "public_pipeline_count": len(public_pipelines),
        "registered_pipeline_count": len(registered_pipelines),
        "registered_line_merge_supported_count": int(
            (shapely.get_type_id(registered_lines) == 1).sum()
        ),
        "unique_endpoint_candidate_count": len(candidates),
        "accepted_crosswalk_count": len(crosswalk),
        "public_coverage_percent": round(
            len(crosswalk) / len(public_pipelines) * 100.0, 6
        ),
        "registered_coverage_percent": round(
            len(crosswalk) / len(registered_pipelines) * 100.0, 6
        ),
        "endpoint_error_m": _summary(endpoint_error),
        "hausdorff_distance_m": _summary(hausdorff),
        "relative_length_delta": _summary(relative_length_delta),
        "policy": {
            "endpoint_grid_m": endpoint_grid_m,
            "maximum_endpoint_error_m": maximum_endpoint_error_m,
            "maximum_hausdorff_m": maximum_hausdorff_m,
            "maximum_relative_length_delta": maximum_relative_length_delta,
            "unique_in_each_snapshot_required": True,
        },
        "authoritative_identity_established": False,
    }
    return crosswalk, audit


def identifier_crosswalk_audit(
    public_pipelines: Any,
    registered_pipelines: Any,
) -> list[dict[str, Any]]:
    rows = []
    for registered_field in ("unitid", "uid"):
        registered = _normalize_identifier(registered_pipelines[registered_field])
        registered_values = set(registered.dropna())
        for public_field in ("UNIQUE_ID", "Asset_ID", "HYDROID", "O_ID"):
            public = _normalize_identifier(public_pipelines[public_field])
            public_values = set(public.dropna())
            rows.append(
                {
                    "registered_field": registered_field,
                    "public_field": public_field,
                    "registered_present_count": int(registered.notna().sum()),
                    "registered_distinct_count": len(registered_values),
                    "public_present_count": int(public.notna().sum()),
                    "public_distinct_count": len(public_values),
                    "shared_distinct_count": len(
                        registered_values.intersection(public_values)
                    ),
                    "registered_matching_row_count": int(
                        registered.isin(public_values).sum()
                    ),
                    "public_matching_row_count": int(
                        public.isin(registered_values).sum()
                    ),
                }
            )
    return rows


def compile_facility_attachments(
    registered_pipelines: Any,
    facilities: Any,
) -> tuple[Any, dict[str, Any]]:
    """Attach pipeline reference fields to globally unique facility unit IDs."""

    import numpy as np
    import pandas as pd
    import shapely

    facility_frame = facilities.copy().reset_index(drop=True)
    facility_frame["identifier_norm"] = _normalize_identifier(
        facility_frame["unitid"]
    )
    identifier_counts = facility_frame["identifier_norm"].dropna().value_counts()
    ambiguous_ids = set(identifier_counts[identifier_counts.gt(1)].index)
    unique_facilities = facility_frame[
        facility_frame["identifier_norm"].notna()
        & ~facility_frame["identifier_norm"].isin(ambiguous_ids)
    ][["identifier_norm", "facility_role", "fid", "geometry"]].rename(
        columns={"fid": "registered_facility_fid", "geometry": "facility_geometry"}
    )

    reference_parts = []
    for endpoint_role in ("asset_before", "asset_after"):
        reference_parts.append(
            pd.DataFrame(
                {
                    "pipeline_row_index": np.arange(len(registered_pipelines)),
                    "registered_pipeline_fid": registered_pipelines["fid"].to_numpy(),
                    "endpoint_role": endpoint_role,
                    "identifier_norm": _valid_reference(
                        registered_pipelines[endpoint_role]
                    ),
                }
            )
        )
    references = pd.concat(reference_parts, ignore_index=True)
    references = references[references["identifier_norm"].notna()].copy()
    ambiguous_reference_count = int(
        references["identifier_norm"].isin(ambiguous_ids).sum()
    )
    matches = references.merge(
        unique_facilities,
        on="identifier_norm",
        how="inner",
        validate="many_to_one",
    )
    merged_lines = shapely.line_merge(registered_pipelines.geometry.array)
    pipeline_rows = matches["pipeline_row_index"].to_numpy(dtype="int64")
    lines = merged_lines[pipeline_rows]
    supported = shapely.get_type_id(lines) == 1
    matches = matches.loc[supported].reset_index(drop=True)
    lines = lines[supported]
    start_points = shapely.get_point(lines, 0)
    end_points = shapely.get_point(lines, -1)
    facility_geometry = np.asarray(matches["facility_geometry"], dtype="object")
    distance_start = shapely.distance(start_points, facility_geometry)
    distance_end = shapely.distance(end_points, facility_geometry)
    nearest_is_start = distance_start <= distance_end
    nearest_distance = np.minimum(distance_start, distance_end)
    attachments = pd.DataFrame(
        {
            "registered_pipeline_fid": matches["registered_pipeline_fid"],
            "endpoint_role": matches["endpoint_role"],
            "facility_role": matches["facility_role"],
            "registered_facility_fid": matches["registered_facility_fid"],
            "identifier_match_method": "unitid_exact_unique_across_downloaded_facilities",
            "distance_to_geometry_start_m": distance_start,
            "distance_to_geometry_end_m": distance_end,
            "nearest_geometry_endpoint": np.where(
                nearest_is_start,
                "geometry_start",
                "geometry_end",
            ),
            "nearest_endpoint_distance_m": nearest_distance,
            "within_0_1m": nearest_distance <= 0.1,
            "within_1m": nearest_distance <= 1.0,
            "within_5m": nearest_distance <= 5.0,
            "evidence_level": "candidate",
            "admitted": False,
        }
    ).sort_values(
        ["registered_pipeline_fid", "endpoint_role", "facility_role"]
    ).reset_index(drop=True)

    role_counts = []
    for (endpoint_role, facility_role), group in attachments.groupby(
        ["endpoint_role", "facility_role"],
        sort=True,
    ):
        role_counts.append(
            {
                "endpoint_role": endpoint_role,
                "facility_role": facility_role,
                "match_count": len(group),
                "within_1m_count": int(group["within_1m"].sum()),
                "within_5m_count": int(group["within_5m"].sum()),
            }
        )

    before = attachments[attachments["endpoint_role"].eq("asset_before")][
        [
            "registered_pipeline_fid",
            "distance_to_geometry_start_m",
            "distance_to_geometry_end_m",
        ]
    ].rename(
        columns={
            "distance_to_geometry_start_m": "before_start_m",
            "distance_to_geometry_end_m": "before_end_m",
        }
    )
    after = attachments[attachments["endpoint_role"].eq("asset_after")][
        [
            "registered_pipeline_fid",
            "distance_to_geometry_start_m",
            "distance_to_geometry_end_m",
        ]
    ].rename(
        columns={
            "distance_to_geometry_start_m": "after_start_m",
            "distance_to_geometry_end_m": "after_end_m",
        }
    )
    paired = before.merge(after, on="registered_pipeline_fid", validate="one_to_one")
    direct_orientation = paired["before_start_m"] + paired["after_end_m"]
    reverse_orientation = paired["before_end_m"] + paired["after_start_m"]
    audit = {
        "pipeline_count": len(registered_pipelines),
        "facility_count": len(facility_frame),
        "facility_unitid_present_count": int(
            facility_frame["identifier_norm"].notna().sum()
        ),
        "ambiguous_unitid_distinct_count": len(ambiguous_ids),
        "ambiguous_reference_count": ambiguous_reference_count,
        "valid_reference_count": len(references),
        "attachment_count": len(attachments),
        "attachment_percent_of_valid_references": round(
            len(attachments) / len(references) * 100.0 if len(references) else 0.0,
            6,
        ),
        "nearest_endpoint_distance_m": _summary(nearest_distance),
        "within_0_1m_count": int(attachments["within_0_1m"].sum()),
        "within_1m_count": int(attachments["within_1m"].sum()),
        "within_5m_count": int(attachments["within_5m"].sum()),
        "matches_by_role": role_counts,
        "geometry_orientation_diagnostic": {
            "both_references_attached_pipeline_count": len(paired),
            "before_start_after_end_preferred_count": int(
                (direct_orientation < reverse_orientation).sum()
            ),
            "before_end_after_start_preferred_count": int(
                (reverse_orientation < direct_orientation).sum()
            ),
            "tied_count": int(
                np.isclose(direct_orientation, reverse_orientation, atol=1e-9).sum()
            ),
            "asset_field_orientation_semantics_verified": False,
        },
        "authoritative_connectivity_established": False,
    }
    return attachments, audit


def _load_registered_layer(snapshot_root: Path, table_name: str) -> Any:
    import geopandas as gpd
    import pandas as pd

    layer_root = snapshot_root / table_name
    manifest = json.loads((layer_root / "manifest.json").read_text(encoding="utf-8"))
    frames = []
    for page in manifest["pages"]:
        path = layer_root / page["path"]
        if _sha256_file(path) != page["sha256"]:
            raise ValueError(f"registered_page_checksum_mismatch:{table_name}")
        frames.append(gpd.read_parquet(path))
    if not frames:
        return gpd.GeoDataFrame(columns=manifest["fields"], geometry="geom", crs=TARGET_CRS)
    frame = gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True),
        geometry="geom",
        crs=frames[0].crs,
    )
    if len(frame) != manifest["record_count"]:
        raise ValueError(f"registered_layer_count_mismatch:{table_name}")
    return frame


def compile_registered_network_crosswalks(
    dataset_root: Path,
    *,
    output_root: Path | None = None,
) -> dict[str, Any]:
    """Compile and persist cross-source and pipeline-facility candidates."""

    import geopandas as gpd
    import pandas as pd

    pointer_path = dataset_root / "online/makani_registered/latest_snapshot.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    snapshot_root = dataset_root / pointer["path"]
    snapshot_path = snapshot_root / "snapshot.json"
    if _sha256_file(snapshot_path) != pointer["snapshot_sha256"]:
        raise ValueError("registered_snapshot_checksum_mismatch")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

    registered = _load_registered_layer(snapshot_root, "st_pipeline").rename_geometry(
        "geometry"
    )
    public_path = (
        dataset_root
        / "derived/smartmakani/abu_dhabi_stormwater_pipelines.parquet"
    )
    public = gpd.read_parquet(public_path)[
        [
            "source_object_id",
            "UNIQUE_ID",
            "Asset_ID",
            "HYDROID",
            "O_ID",
            "geometry",
        ]
    ]
    identifier_audit = identifier_crosswalk_audit(public, registered)
    pipeline_crosswalk, pipeline_audit = match_public_registered_pipelines(
        public,
        registered,
    )

    facility_frames = []
    for spec in LAYER_SPECS:
        if spec.table_name == "st_pipeline":
            continue
        frame = _load_registered_layer(snapshot_root, spec.table_name)
        facility_frames.append(
            gpd.GeoDataFrame(
                {
                    "fid": frame["fid"],
                    "unitid": frame["unitid"],
                    "facility_role": spec.role,
                    "geometry": frame.geometry,
                },
                geometry="geometry",
                crs=frame.crs,
            )
        )
    facilities = gpd.GeoDataFrame(
        pd.concat(facility_frames, ignore_index=True),
        geometry="geometry",
        crs=TARGET_CRS,
    )
    attachments, attachment_audit = compile_facility_attachments(
        registered,
        facilities,
    )

    destination = output_root or dataset_root / "derived/makani_registered"
    pipeline_output = destination / "smartmakani_registered_pipeline_crosswalk.parquet"
    attachment_output = destination / "registered_pipeline_facility_attachments.parquet"
    pipeline_artifact = _atomic_write_parquet(pipeline_output, pipeline_crosswalk)
    attachment_artifact = _atomic_write_parquet(attachment_output, attachments)
    audit = {
        "schema": REGISTERED_CROSSWALK_SCHEMA,
        "registered_snapshot_id": snapshot["snapshot_id"],
        "registered_snapshot_sha256": pointer["snapshot_sha256"],
        "public_pipeline_artifact": {
            "path": str(public_path.relative_to(dataset_root)),
            "sha256": _sha256_file(public_path),
        },
        "identifier_crosswalk": {
            "candidate_pairs": identifier_audit,
            "any_explicit_identifier_match": any(
                item["shared_distinct_count"] > 0 for item in identifier_audit
            ),
        },
        "geometry_crosswalk": pipeline_audit,
        "facility_attachments": attachment_audit,
        "artifacts": {
            "pipeline_crosswalk": pipeline_artifact,
            "facility_attachments": attachment_artifact,
        },
        "admission": {
            "admitted": False,
            "operator_admitted": False,
            "calibration_admitted": False,
            "flood_network_contract_compiled": False,
        },
        "claim_boundary": [
            "geometry_crosswalk_is_candidate_identity_not_authoritative_asset_equivalence",
            "unitid_attachment_requires_spatial_and_engineering_validation",
            "asset_before_and_asset_after_orientation_semantics_are_not_declared_foreign_keys",
            "pipeline_and_facility_nodes_are_not_surface_catchments",
        ],
    }
    audit_path = destination / "registered_network_crosswalk_audit.json"
    _atomic_write_json(audit_path, audit)
    return audit


def compile_registered_network_candidate(
    dataset_root: Path,
    *,
    output_root: Path | None = None,
    policy: PipelineCompilePolicy | None = None,
) -> dict[str, Any]:
    """Compile registered pipelines and candidate facility-to-node semantics."""

    import pandas as pd

    root = dataset_root.resolve()
    pointer_path = root / "online/makani_registered/latest_snapshot.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    snapshot_root = root / pointer["path"]
    snapshot_path = snapshot_root / "snapshot.json"
    if _sha256_file(snapshot_path) != pointer["snapshot_sha256"]:
        raise ValueError("registered_snapshot_checksum_mismatch")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

    crosswalk_root = (output_root or root / "derived/makani_registered").resolve()
    crosswalk_audit_path = crosswalk_root / "registered_network_crosswalk_audit.json"
    crosswalk_audit = json.loads(crosswalk_audit_path.read_text(encoding="utf-8"))
    if crosswalk_audit["registered_snapshot_id"] != snapshot["snapshot_id"]:
        raise ValueError("registered_crosswalk_snapshot_mismatch")
    attachment_metadata = crosswalk_audit["artifacts"]["facility_attachments"]
    attachment_path = crosswalk_root / attachment_metadata["path"]
    if _sha256_file(attachment_path) != attachment_metadata["sha256"]:
        raise ValueError("registered_facility_attachment_checksum_mismatch")
    attachments = pd.read_parquet(attachment_path)
    if len(attachments) != attachment_metadata["record_count"]:
        raise ValueError("registered_facility_attachment_count_mismatch")

    registered = _load_registered_layer(snapshot_root, "st_pipeline")
    standardized = standardize_registered_pipelines(registered)
    active_policy = policy or PipelineCompilePolicy(snap_tolerance_m=1.0)
    pipelines, nodes, topology_audit = compile_pipeline_topology(
        standardized,
        policy=active_policy,
    )
    nodes, facility_links, facility_audit = aggregate_facility_attachments_to_nodes(
        pipelines,
        nodes,
        attachments,
        maximum_distance_m=1.0,
    )

    destination = crosswalk_root
    pipeline_path = destination / "registered_stormwater_pipelines.parquet"
    node_path = destination / "registered_stormwater_nodes.parquet"
    facility_path = destination / "registered_node_facility_candidates.parquet"
    outputs = {
        "pipelines_geoparquet": _atomic_write_parquet(pipeline_path, pipelines),
        "nodes_geoparquet": _atomic_write_parquet(node_path, nodes),
        "node_facility_candidates_parquet": _atomic_write_parquet(
            facility_path,
            facility_links,
        ),
    }
    for artifact, path in zip(
        outputs.values(),
        (pipeline_path, node_path, facility_path),
        strict=True,
    ):
        artifact["path"] = _path_label(path, root)

    topology_audit["admission"]["flood_network_blocker"] = (
        "residual unmatched pipeline endpoints; unverified outfall and pump connectivity; "
        "missing catchment and surface-patch bindings; unverified engineering units and "
        "vertical datum; missing event operations and observations"
    )
    audit = {
        "schema": REGISTERED_NETWORK_AUDIT_SCHEMA,
        "registered_snapshot_id": snapshot["snapshot_id"],
        "registered_snapshot_sha256": pointer["snapshot_sha256"],
        "crosswalk_audit": {
            "path": _path_label(crosswalk_audit_path, root),
            "sha256": _sha256_file(crosswalk_audit_path),
        },
        "topology": topology_audit,
        "facility_semantics": facility_audit,
        "outputs": outputs,
        "admission": {
            "admitted": False,
            "operator_admitted": False,
            "calibration_admitted": False,
            "flood_network_contract_compiled": False,
            "k0_opened": False,
        },
        "claim_boundary": [
            "source_and_target_nodes_follow_geometry_orientation_not_verified_flow_direction",
            "facility_links_are_candidate_relationships_not_authoritative_connectivity",
            "outfall_and_pump_relationships_remain_unverified",
            "pipeline_nodes_are_not_surface_patches_or_catchments",
            "candidate_network_is_not_a_calibrated_hydraulic_graph_or_city_scale_predictor",
        ],
    }
    audit_path = destination / "registered_network_candidate_audit.json"
    _atomic_write_json(audit_path, audit)
    manifest = {
        "schema": REGISTERED_NETWORK_SCHEMA,
        "network_id": "abu-dhabi-registered-makani-stormwater-candidate-v1",
        "crs": TARGET_CRS,
        "registered_snapshot_id": snapshot["snapshot_id"],
        "registered_snapshot_sha256": pointer["snapshot_sha256"],
        "pipeline_count": len(pipelines),
        "node_count": len(nodes),
        "node_facility_candidate_count": len(facility_links),
        "outputs": outputs,
        "audit": {
            "path": _path_label(audit_path, root),
            "sha256": _sha256_file(audit_path),
        },
        "evidence_level": "candidate",
        "admitted": False,
        "diagnostic_only": True,
        "flood_network_contract_compiled": False,
        "claim_boundary": (
            "Facility-enhanced registered topology candidate; not an authoritative or "
            "calibrated hydraulic network and not a city-scale flood predictor."
        ),
    }
    manifest_path = destination / "registered_network_candidate_manifest.json"
    _atomic_write_json(manifest_path, manifest)
    return manifest
