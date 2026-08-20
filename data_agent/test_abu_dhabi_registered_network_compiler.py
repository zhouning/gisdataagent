from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, MultiLineString, Point

from data_agent.uwm.abu_dhabi_flood.network_compiler import compile_pipeline_topology
from data_agent.uwm.abu_dhabi_flood.registered_network_compiler import (
    aggregate_facility_attachments_to_nodes,
    compile_facility_attachments,
    match_public_registered_pipelines,
    standardize_registered_pipelines,
)


def test_geometry_crosswalk_merges_multilines_and_rejects_changed_shape() -> None:
    public = gpd.GeoDataFrame(
        {
            "source_object_id": [1, 2],
        },
        geometry=[
            LineString([(200000.0, 2600000.0), (200010.0, 2600000.0)]),
            LineString([(200020.0, 2600000.0), (200030.0, 2600000.0)]),
        ],
        crs="EPSG:32640",
    )
    registered = gpd.GeoDataFrame(
        {"fid": [10, 20]},
        geometry=[
            MultiLineString(
                [[(200000.0002, 2600000.0), (200010.0002, 2600000.0)]]
            ),
            MultiLineString(
                [[
                    (200020.0, 2600000.0),
                    (200025.0, 2600002.0),
                    (200030.0, 2600000.0),
                ]]
            ),
        ],
        crs="EPSG:32640",
    )
    crosswalk, audit = match_public_registered_pipelines(public, registered)

    assert list(crosswalk["public_source_object_id"]) == [1]
    assert list(crosswalk["registered_fid"]) == [10]
    assert audit["unique_endpoint_candidate_count"] == 2
    assert audit["accepted_crosswalk_count"] == 1
    assert audit["authoritative_identity_established"] is False


def test_facility_attachment_uses_unique_unitid_and_audits_orientation() -> None:
    pipelines = gpd.GeoDataFrame(
        {
            "fid": [10, 20],
            "asset_before": ["A", "DUP"],
            "asset_after": ["B", "NC"],
        },
        geometry=[
            MultiLineString([[(0.0, 0.0), (10.0, 0.0)]]),
            MultiLineString([[(20.0, 0.0), (30.0, 0.0)]]),
        ],
        crs="EPSG:32640",
    )
    facilities = gpd.GeoDataFrame(
        pd.DataFrame(
            {
                "fid": [1, 2, 3, 4],
                "unitid": ["A", "B", "DUP", "DUP"],
                "facility_role": ["inlet", "outfall", "inlet", "catchbasin"],
            }
        ),
        geometry=[Point(0.0, 0.0), Point(10.0, 0.0), Point(20.0, 0.0), Point(20.0, 0.0)],
        crs="EPSG:32640",
    )

    attachments, audit = compile_facility_attachments(pipelines, facilities)

    assert len(attachments) == 2
    assert attachments["within_0_1m"].all()
    assert audit["ambiguous_unitid_distinct_count"] == 1
    assert audit["ambiguous_reference_count"] == 1
    orientation = audit["geometry_orientation_diagnostic"]
    assert orientation["both_references_attached_pipeline_count"] == 1
    assert orientation["before_start_after_end_preferred_count"] == 1
    assert orientation["asset_field_orientation_semantics_verified"] is False


def test_registered_pipeline_standardization_and_node_facility_aggregation() -> None:
    registered = gpd.GeoDataFrame(
        {
            "fid": [10, 20],
            "unitid": ["P-10", "P-20"],
            "pipe_diameter": [300.0, 400.0],
            "invert_level_upstream": [5.0, 4.0],
            "invert_level_downstream": [4.0, 3.0],
        },
        geometry=[
            MultiLineString([[(0.0, 0.0), (10.0, 0.0)]]),
            MultiLineString([[(10.0, 0.0), (20.0, 0.0)]]),
        ],
        crs="EPSG:32640",
    )
    standardized = standardize_registered_pipelines(registered)
    pipelines, nodes, _ = compile_pipeline_topology(standardized)
    attachments = pd.DataFrame(
        {
            "registered_pipeline_fid": [10, 20, 20, 10],
            "endpoint_role": [
                "asset_after",
                "asset_before",
                "asset_after",
                "asset_before",
            ],
            "facility_role": ["inlet", "inlet", "outfall", "pump"],
            "registered_facility_fid": [1, 1, 2, 3],
            "nearest_geometry_endpoint": [
                "geometry_end",
                "geometry_start",
                "geometry_end",
                "geometry_start",
            ],
            "nearest_endpoint_distance_m": [0.0, 0.1, 0.0, 2.0],
        }
    )

    enriched_nodes, links, audit = aggregate_facility_attachments_to_nodes(
        pipelines,
        nodes,
        attachments,
    )

    assert list(pipelines["registered_pipeline_fid"]) == [10, 20]
    assert list(pipelines["source_object_id"]) == [10, 20]
    assert list(pipelines["diameter_numeric"]) == [300.0, 400.0]
    assert len(links) == 2
    shared = links[links["facility_role"].eq("inlet")].iloc[0]
    assert shared["pipeline_attachment_count"] == 2
    assert shared["registered_pipeline_count"] == 2
    assert audit["within_distance_attachment_count"] == 3
    assert audit["mapped_pipeline_endpoint_count"] == 3
    assert audit["residual_unmatched_pipeline_endpoint_count"] == 1
    assert audit["nodes_with_candidate_facility_count"] == 2
    assert audit["outside_distance_attachment_count"] == 1
    assert audit["source_target_node_labels_are_verified_hydraulic_direction"] is False
    assert enriched_nodes["candidate_surface_intake_count"].sum() == 1
    assert enriched_nodes["candidate_outfall_count"].sum() == 1
    assert not enriched_nodes["facility_semantics_admitted"].any()
