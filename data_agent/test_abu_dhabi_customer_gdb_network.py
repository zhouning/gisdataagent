from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point

from data_agent.uwm.abu_dhabi_flood.customer_gdb_network import (
    CUSTOMER_GDB_NETWORK_SCHEMA,
    CustomerGdbCompilePolicy,
    CustomerGdbSwmmBatchPolicy,
    CustomerGwmStaticTensorPolicy,
    _artifact,
    _atomic_write_json,
    _facility_depth_audit,
    _require_private_output_root,
    build_customer_gwm_static_graph_contract,
    build_customer_gwm_static_tensors,
    compile_customer_facility_attachments,
    compile_customer_gdb_swmm_diagnostic_batch,
    compile_customer_gwm_input_window_shapes,
    compile_customer_gwm_static_tensors,
    compile_customer_swmm_gwm_alignment,
    compile_customer_swmm_gwm_dynamic_diagnostic,
    load_customer_gwm_input_window_shapes,
    load_customer_gwm_static_tensors,
    load_customer_swmm_gwm_alignment,
    load_customer_swmm_gwm_dynamic_diagnostic,
    select_customer_gdb_swmm_pilot_batch,
)
from data_agent.uwm.abu_dhabi_flood.network_compiler import (
    PipelineCompilePolicy,
    compile_pipeline_topology,
)
from data_agent.uwm.abu_dhabi_flood.registered_swmm_diagnostic import (
    RegisteredSwmmDiagnosticPolicy,
)


def _pipelines():
    source = gpd.GeoDataFrame(
        {
            "fid": [1, 2],
            "registered_pipeline_fid": [1, 2],
            "OBJECTID": [1, 2],
            "ASSET_DIAMETER": [300.0, 400.0],
            "INVERT_LEVEL_UP": [5.0, 4.0],
            "INVERT_LEVEL_DOWN": [4.0, 3.0],
            "Start_X": [0.0, 10.0],
            "Start_Y": [0.0, 0.0],
            "End_X": [10.0, 20.0],
            "End_Y": [0.0, 0.0],
            "StartCode": ["A", "B"],
            "EndCode": ["B", "C"],
            "ASSET_BEFORE": [None, None],
            "ASSET_AFTER": [None, None],
            "OUTFALLID": [None, "OUT"],
            "pipe_material": ["GRP", "GRP"],
            "pipeline_status": ["ACTIVE", "ACTIVE"],
        },
        geometry=[
            LineString([(0.0, 0.0), (10.0, 0.0)]),
            LineString([(10.0, 0.0), (20.0, 0.0)]),
        ],
        crs="EPSG:32640",
    )
    compiled, nodes, _ = compile_pipeline_topology(
        source,
        policy=PipelineCompilePolicy(snap_tolerance_m=0.1),
    )
    compiled["registered_pipeline_fid"] = source["registered_pipeline_fid"]
    return source, compiled, nodes


def test_multi_evidence_attachment_uses_codes_outfall_and_spatial_fallback():
    source, compiled, _ = _pipelines()
    facilities = gpd.GeoDataFrame(
        {
            "registered_facility_fid": [1, 2, 3, 4],
            "UNITID": ["U-A", "U-B", "U-C", "OUT"],
            "PointCode": ["A", "B", "C", None],
            "OUTFALL_NAME": [None, None, None, None],
            "MAINASSETNAME": [None, None, None, None],
            "facility_role": ["inlet", "inlet", "inlet", "outfall"],
        },
        geometry=[
            Point(0.0, 0.0),
            Point(10.0, 0.0),
            Point(20.0, 0.0),
            Point(20.0, 0.0),
        ],
        crs="EPSG:32640",
    )
    attachments, audit = compile_customer_facility_attachments(
        source,
        compiled,
        facilities,
    )

    assert set(attachments["facility_role"]) == {"inlet", "outfall"}
    assert audit["mapped_pipeline_endpoint_count"] == 4
    assert audit["accepted_reference_counts"]["StartCode"] == 2
    assert audit["accepted_reference_counts"]["EndCode"] == 2
    assert audit["accepted_reference_counts"]["OUTFALLID"] == 1
    assert audit["source_identifiers_persisted"] is False
    assert not {"UNITID", "PointCode", "OUTFALLID"}.intersection(attachments.columns)


def test_facility_depth_audit_detects_uniform_derived_depth():
    facilities = pd.DataFrame(
        {
            "GroundElev": [5.0, 7.5, 9.0],
            "WellBottomElev": [3.8, 6.3, 7.8],
        }
    )
    audit = _facility_depth_audit(facilities, CustomerGdbCompilePolicy())
    assert audit["exact_derived_depth_percent"] == 100.0
    assert audit["engineering_facility_bottom_elevation_admitted"] is False


def test_gwm_static_graph_contract_keeps_dynamic_training_closed():
    _, compiled, nodes = _pipelines()
    compiled["pipe_material"] = ["GRP", "GRP"]
    compiled["pipeline_status"] = ["ACTIVE", "ACTIVE"]
    nodes["candidate_surface_intake_count"] = [1, 1, 0]
    nodes["candidate_outfall_count"] = [0, 0, 1]
    nodes["candidate_pump_count"] = 0
    links = pd.DataFrame(
        {
            "facility_role": ["inlet", "outfall"],
        }
    )
    contract = build_customer_gwm_static_graph_contract(compiled, nodes, links)

    assert contract["readiness"]["static_graph_compiled"] is True
    assert contract["readiness"]["static_encoder_development_allowed"] is True
    assert contract["readiness"]["gwm_training_admitted"] is False
    assert contract["privacy"]["single_asset_or_node_details_persisted"] is False


def test_customer_outputs_are_rejected_inside_public_repository(tmp_path):
    repository = _require_private_output_root.__globals__["_repository_root"]()
    with pytest.raises(ValueError, match="outside_public_repository"):
        _require_private_output_root(repository / "private-customer-output")
    assert _require_private_output_root(tmp_path) == tmp_path.resolve()


def _multi_outfall_network():
    edge_rows = []
    node_rows = []
    facility_rows = []
    edge_id = 1
    for branch in ("a", "b"):
        node_ids = [f"{branch}{index}" for index in range(5)]
        for index, node_id in enumerate(node_ids):
            node_rows.append(
                {
                    "node_id": node_id,
                    "snap_x_m": float(index),
                    "snap_y_m": 0.0 if branch == "a" else 10.0,
                    "component_id": 1 if branch == "a" else 2,
                    "component_node_count": 5,
                    "degree": 1 if index in {0, 4} else 2,
                    "candidate_surface_intake_count": 1 if index < 4 else 0,
                    "candidate_outfall_count": 1 if index == 4 else 0,
                }
            )
            facility_rows.append(
                {
                    "node_id": node_id,
                    "facility_role": "outfall" if index == 4 else "inlet",
                    "registered_facility_fid": len(facility_rows) + 1,
                    "minimum_endpoint_distance_m": 0.0,
                    "endpoint_roles": "asset_after" if index == 4 else "asset_before",
                    "geometry_endpoints": (
                        "geometry_end" if index == 4 else "geometry_start"
                    ),
                    "evidence_level": "candidate",
                    "admitted": False,
                }
            )
        for index in range(4):
            edge_rows.append(
                {
                    "registered_pipeline_fid": edge_id,
                    "source_node_id": node_ids[index],
                    "target_node_id": node_ids[index + 1],
                    "recomputed_length_m": 10.0,
                    "diameter_numeric": 300.0,
                    "invert_up_numeric": 10.0 - index,
                    "invert_down_numeric": 9.0 - index,
                    "invert_up_plausible_candidate": True,
                    "invert_down_plausible_candidate": True,
                    "flow_direction_conflict": False,
                    "self_loop_after_snap": False,
                    "duplicate_node_pair": False,
                    "pipe_material": "GRP",
                }
            )
            edge_id += 1
    return pd.DataFrame(edge_rows), pd.DataFrame(node_rows), pd.DataFrame(facility_rows)


def test_swmm_pilot_batch_selects_two_disjoint_outfalls():
    pipelines, nodes, facilities = _multi_outfall_network()
    selections, audit = select_customer_gdb_swmm_pilot_batch(
        pipelines,
        nodes,
        facilities,
        selection_policy=RegisteredSwmmDiagnosticPolicy(
            maximum_edges=4,
            maximum_upstream_hops=4,
            minimum_edges=4,
        ),
        batch_policy=CustomerGdbSwmmBatchPolicy(
            maximum_pilots=2,
            maximum_candidate_attempts=2,
            maximum_edge_overlap_fraction=0.0,
        ),
    )

    assert len(selections) == 2
    assert audit["selected_pilot_count"] == 2
    assert audit["maximum_selected_edge_overlap_fraction"] == 0.0
    assert audit["source_asset_identifiers_persisted"] is False


def _write_private_network_fixture(tmp_path):
    source, pipelines, nodes = _pipelines()
    del source
    pipelines["pipe_material"] = ["GRP", "GRP"]
    pipelines["pipeline_status"] = ["ACTIVE", "ACTIVE"]
    nodes["candidate_surface_intake_count"] = [1, 1, 0]
    nodes["candidate_outfall_count"] = [0, 0, 1]
    nodes["candidate_pump_count"] = 0
    nodes["candidate_facility_count"] = [1, 1, 1]
    nodes["candidate_facility_roles"] = ["inlet", "inlet", "outfall"]
    links = pd.DataFrame(
        {
            "node_id": [nodes.iloc[0]["node_id"], nodes.iloc[-1]["node_id"]],
            "facility_role": ["inlet", "outfall"],
            "registered_facility_fid": [1, 2],
            "minimum_endpoint_distance_m": [0.0, 0.0],
            "endpoint_roles": ["asset_before", "asset_after"],
            "geometry_endpoints": ["geometry_start", "geometry_end"],
            "match_method": ["test", "test"],
            "evidence_level": ["candidate", "candidate"],
            "admitted": [False, False],
        }
    )
    root = tmp_path / "private_customer"
    root.mkdir()
    pipeline_path = root / "customer_stormwater_pipelines.private.parquet"
    node_path = root / "customer_stormwater_nodes.private.parquet"
    link_path = root / "customer_node_facilities.private.parquet"
    pipelines.to_parquet(pipeline_path, index=False)
    nodes.to_parquet(node_path, index=False)
    links.to_parquet(link_path, index=False)
    manifest = {
        "schema": CUSTOMER_GDB_NETWORK_SCHEMA,
        "diagnostic_only": True,
        "admitted": False,
        "claim_boundary": ["synthetic_test_fixture"],
        "outputs": {
            "pipelines_private_geoparquet": _artifact(
                pipeline_path, root, record_count=len(pipelines)
            ),
            "nodes_private_geoparquet": _artifact(
                node_path, root, record_count=len(nodes)
            ),
            "node_facilities_private_parquet": _artifact(
                link_path, root, record_count=len(links)
            ),
        },
    }
    _atomic_write_json(root / "customer_gdb_network_private_manifest.json", manifest)
    return root


def test_gwm_static_tensor_builder_uses_id_free_arrays_and_keeps_training_closed(
    tmp_path,
):
    root = _write_private_network_fixture(tmp_path)
    manifest = compile_customer_gwm_static_tensors(
        root,
        policy=CustomerGwmStaticTensorPolicy(maximum_nodes_per_partition=128),
    )
    arrays, inventory, loaded_manifest = load_customer_gwm_static_tensors(root)

    assert arrays["edge_index"].shape == (2, 2)
    assert arrays["node_features"].shape == (3, 8)
    assert arrays["edge_features"].shape == (2, 13)
    assert not any("id" in name for name in arrays)
    assert np.isfinite(arrays["node_features"]).all()
    assert len(inventory) == manifest["feature_contract"]["partition_count"]
    assert loaded_manifest["readiness"]["static_encoder_development_allowed"] is True
    assert loaded_manifest["readiness"]["gwm_training_admitted"] is False
    assert loaded_manifest["privacy"]["source_asset_identifiers_persisted"] is False
    serialized = json.dumps(loaded_manifest, ensure_ascii=True)
    assert "/Users/" not in serialized


def test_gwm_static_tensor_loader_rejects_hash_mismatch(tmp_path):
    root = _write_private_network_fixture(tmp_path)
    manifest = compile_customer_gwm_static_tensors(
        root,
        policy=CustomerGwmStaticTensorPolicy(maximum_nodes_per_partition=128),
    )
    tensor_path = root / manifest["outputs"]["static_tensors_private_npz"]["path"]
    with tensor_path.open("ab") as handle:
        handle.write(b"tampered")

    with pytest.raises(ValueError, match="artifact_integrity_failed"):
        load_customer_gwm_static_tensors(root)


def test_swmm_batch_compile_receipt_is_aggregate_and_path_free(tmp_path):
    root = _write_private_network_fixture(tmp_path)
    receipt = compile_customer_gdb_swmm_diagnostic_batch(
        root,
        hourly_precipitation_mm=(0.0,) * 72,
        forcing_descriptor={
            "source_id": "synthetic_test",
            "model_label": "Synthetic",
            "evidence_class": "synthetic_test_only",
        },
        selection_policy=RegisteredSwmmDiagnosticPolicy(
            maximum_edges=2,
            maximum_upstream_hops=2,
            minimum_edges=2,
        ),
        batch_policy=CustomerGdbSwmmBatchPolicy(
            maximum_pilots=1,
            maximum_candidate_attempts=1,
            maximum_edge_overlap_fraction=0.0,
        ),
    )
    serialized = json.dumps(receipt, ensure_ascii=True)

    assert receipt["selection"]["selected_pilot_count"] == 1
    assert receipt["pilots"][0]["selection"]["selected_pipeline_count"] == 2
    assert receipt["admission"]["traditional_model_admitted"] is False
    assert receipt["admission"]["gwm_training_admitted"] is False
    assert str(tmp_path) not in serialized
    assert "registered_pipeline_fid" not in serialized
    assert "root_node_id" not in serialized

    compile_customer_gwm_static_tensors(
        root,
        policy=CustomerGwmStaticTensorPolicy(maximum_nodes_per_partition=128),
    )
    alignment_manifest = compile_customer_swmm_gwm_alignment(root)
    alignment, loaded_alignment_manifest = load_customer_swmm_gwm_alignment(root)
    assert alignment["pilot_node_offsets"].tolist() == [0, 3]
    assert alignment["pilot_edge_offsets"].tolist() == [0, 2]
    assert alignment["pilot_outfall_node_indices"].shape == (1,)
    assert alignment_manifest["readiness"][
        "static_solver_graph_index_alignment_compiled"
    ] is True
    assert loaded_alignment_manifest["readiness"]["gwm_training_admitted"] is False
    alignment_serialized = json.dumps(loaded_alignment_manifest, ensure_ascii=True)
    assert str(tmp_path) not in alignment_serialized
    assert "registered_pipeline_fid" not in alignment_serialized


def test_static_tensor_builder_rejects_missing_edge_endpoint():
    _, pipelines, nodes = _pipelines()
    pipelines["pipe_material"] = "GRP"
    pipelines["pipeline_status"] = "ACTIVE"
    pipelines.loc[0, "source_node_id"] = "missing"
    nodes["candidate_surface_intake_count"] = 0
    nodes["candidate_outfall_count"] = 0
    nodes["candidate_pump_count"] = 0
    nodes["candidate_facility_count"] = 0

    with pytest.raises(ValueError, match="edge_endpoint_missing"):
        build_customer_gwm_static_tensors(pipelines, nodes)


def test_official_swmm_saved_api_materializes_gwm_aligned_dynamic_states(tmp_path):
    repository = Path(__file__).resolve().parents[1]
    library = repository / "external_models/swmm-5.2.4/build-local/lib/libswmm5.dylib"
    if not library.is_file():
        pytest.skip("EPA SWMM shared library not built")
    root = _write_private_network_fixture(tmp_path)
    compile_customer_gdb_swmm_diagnostic_batch(
        root,
        hourly_precipitation_mm=(0.0,) * 72,
        forcing_descriptor={
            "source_id": "synthetic_test",
            "model_label": "Synthetic",
            "evidence_class": "synthetic_test_only",
        },
        selection_policy=RegisteredSwmmDiagnosticPolicy(
            maximum_edges=2,
            maximum_upstream_hops=2,
            minimum_edges=2,
        ),
        batch_policy=CustomerGdbSwmmBatchPolicy(
            maximum_pilots=1,
            maximum_candidate_attempts=1,
            maximum_edge_overlap_fraction=0.0,
        ),
    )
    compile_customer_gwm_static_tensors(
        root,
        policy=CustomerGwmStaticTensorPolicy(maximum_nodes_per_partition=128),
    )
    compile_customer_swmm_gwm_alignment(root)
    manifest = compile_customer_swmm_gwm_dynamic_diagnostic(
        root,
        library_path=library,
    )
    arrays, loaded = load_customer_swmm_gwm_dynamic_diagnostic(root)

    assert arrays["pilot_01_elapsed_seconds"].shape == (312,)
    assert arrays["pilot_01_node_state"].shape == (312, 3, 6)
    assert arrays["pilot_01_edge_state"].shape == (312, 2, 4)
    assert arrays["pilot_01_elapsed_seconds"][0] == 900
    assert np.isfinite(arrays["pilot_01_node_state"]).all()
    assert manifest["readiness"]["diagnostic_dynamic_state_interface_materialized"] is True
    assert loaded["readiness"]["gwm_training_admitted"] is False
    serialized = json.dumps(loaded, ensure_ascii=True)
    assert str(tmp_path) not in serialized
    assert "registered_pipeline_fid" not in serialized


def test_gwm_window_shapes_preserve_dynamic_contract_without_admitting_training(tmp_path):
    repository = Path(__file__).resolve().parents[1]
    library = repository / "external_models/swmm-5.2.4/build-local/lib/libswmm5.dylib"
    if not library.is_file():
        pytest.skip("EPA SWMM shared library not built")
    root = _write_private_network_fixture(tmp_path)
    compile_customer_gdb_swmm_diagnostic_batch(
        root,
        hourly_precipitation_mm=(0.0,) * 72,
        forcing_descriptor={
            "source_id": "synthetic_test",
            "model_label": "Synthetic",
            "evidence_class": "synthetic_test_only",
        },
        selection_policy=RegisteredSwmmDiagnosticPolicy(
            maximum_edges=2,
            maximum_upstream_hops=2,
            minimum_edges=2,
        ),
        batch_policy=CustomerGdbSwmmBatchPolicy(
            maximum_pilots=1,
            maximum_candidate_attempts=1,
            maximum_edge_overlap_fraction=0.0,
        ),
    )
    compile_customer_gwm_static_tensors(
        root,
        policy=CustomerGwmStaticTensorPolicy(maximum_nodes_per_partition=128),
    )
    compile_customer_swmm_gwm_alignment(root)
    compile_customer_swmm_gwm_dynamic_diagnostic(root, library_path=library)
    manifest = compile_customer_gwm_input_window_shapes(
        root,
        input_steps=12,
        target_steps=6,
        stride_steps=6,
    )
    arrays, loaded = load_customer_gwm_input_window_shapes(root)

    assert manifest["total_window_count"] == 50
    assert arrays["pilot_01_node_static_features"].shape == (50, 18, 3, 8)
    assert arrays["pilot_01_edge_static_features"].shape == (50, 18, 2, 13)
    assert arrays["pilot_01_node_state_values"].shape == (50, 18, 3, 6)
    assert arrays["pilot_01_edge_state_values"].shape == (50, 18, 2, 4)
    assert arrays["pilot_01_node_state_valid_mask"].dtype == np.bool_
    assert arrays["pilot_01_timestamps_seconds"].shape == (50, 18)
    assert loaded["readiness"]["diagnostic_target_values_present"] is True
    assert loaded["readiness"]["authoritative_target_values_present"] is False
    assert loaded["readiness"]["gwm_training_admitted"] is False
    serialized = json.dumps(loaded, ensure_ascii=True)
    assert str(tmp_path) not in serialized
    assert "registered_pipeline_fid" not in serialized
