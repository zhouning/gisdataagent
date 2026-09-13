from pathlib import Path

from data_agent.uwm.fitted_gap_filling import (
    build_fitted_gap_filling_mmfe_state_input,
    build_population_downscaling_proxy,
    build_unicom_latent_mobility_graph,
    write_fitted_gap_filling_snapshot,
)


def test_population_downscaling_preserves_district_totals_and_records_weight_basis():
    ghsl_rows = [
        {
            "admin_unit_id": "a-1",
            "county": "Alpha",
            "township": "A1",
            "population_proxy_sum": "30",
            "built_surface_proxy_sum": "0",
        },
        {
            "admin_unit_id": "a-2",
            "county": "Alpha",
            "township": "A2",
            "population_proxy_sum": "10",
            "built_surface_proxy_sum": "0",
        },
        {
            "admin_unit_id": "b-1",
            "county": "Beta",
            "township": "B1",
            "population_proxy_sum": "0",
            "built_surface_proxy_sum": "2",
        },
        {
            "admin_unit_id": "b-2",
            "county": "Beta",
            "township": "B2",
            "population_proxy_sum": "0",
            "built_surface_proxy_sum": "3",
        },
        {
            "admin_unit_id": "c-1",
            "county": "Gamma",
            "township": "C1",
            "population_proxy_sum": "0",
            "built_surface_proxy_sum": "0",
        },
        {
            "admin_unit_id": "c-2",
            "county": "Gamma",
            "township": "C2",
            "population_proxy_sum": "0",
            "built_surface_proxy_sum": "0",
        },
    ]
    district_rows = [
        {"admin_code": "500101", "district_name": "Alpha", "resident_population_10k": "1.0"},
        {"admin_code": "500102", "district_name": "Beta", "resident_population_10k": "0.5"},
        {"admin_code": "500103", "district_name": "Gamma", "resident_population_10k": "0.3"},
    ]

    proxy = build_population_downscaling_proxy(
        ghsl_rows=ghsl_rows,
        district_rows=district_rows,
        source_ref="unit-test",
        created_at="2026-07-05T00:00:00+08:00",
    )

    assert proxy["schema"] == "uwm.population_downscaling_fitted_proxy.v1"
    assert proxy["synthetic_flags"] == [
        {"dataset_id": "uwm_fitted_admin_population_downscaling_2021", "status": "fitted_proxy"}
    ]
    assert proxy["empirical_superiority_claim"] is False
    assert proxy["summary"]["district_resident_population_input_sum"] == 18000.0
    assert proxy["summary"]["admin_downscaled_population_sum"] == 18000.0
    assert proxy["summary"]["district_total_absolute_error"] == 0.0

    rows_by_id = {row["admin_unit_id"]: row for row in proxy["admin_rows"]}
    assert rows_by_id["a-1"]["downscaled_population"] == 7500.0
    assert rows_by_id["a-2"]["downscaled_population"] == 2500.0
    assert rows_by_id["a-1"]["allocation_basis"] == "ghsl_population_proxy_sum"
    assert rows_by_id["b-1"]["downscaled_population"] == 2000.0
    assert rows_by_id["b-2"]["downscaled_population"] == 3000.0
    assert rows_by_id["b-1"]["allocation_basis"] == "ghsl_built_surface_proxy_sum_fallback"
    assert rows_by_id["c-1"]["downscaled_population"] == 1500.0
    assert rows_by_id["c-2"]["downscaled_population"] == 1500.0
    assert rows_by_id["c-1"]["allocation_basis"] == "equal_weight_fallback"


def test_population_downscaling_keeps_unmatched_districts_as_explicit_district_fallback_rows():
    proxy = build_population_downscaling_proxy(
        ghsl_rows=[
            {
                "admin_unit_id": "a-1",
                "county": "Alpha",
                "township": "A1",
                "population_proxy_sum": "1",
                "built_surface_proxy_sum": "0",
            }
        ],
        district_rows=[
            {"admin_code": "500101", "district_name": "Alpha", "resident_population_10k": "1.0"},
            {"admin_code": "500102", "district_name": "Delta", "resident_population_10k": "0.2"},
        ],
        source_ref="unit-test",
        created_at="2026-07-05T00:00:00+08:00",
    )

    rows_by_id = {row["admin_unit_id"]: row for row in proxy["admin_rows"]}
    assert proxy["summary"]["district_resident_population_input_sum"] == 12000.0
    assert proxy["summary"]["admin_downscaled_population_sum"] == 12000.0
    assert proxy["summary"]["district_total_absolute_error"] == 0.0
    assert rows_by_id["500102|Delta|district_fallback"]["downscaled_population"] == 2000.0
    assert rows_by_id["500102|Delta|district_fallback"]["allocation_basis"] == "district_total_no_ghsl_admin_rows_fallback"
    assert rows_by_id["500102|Delta|district_fallback"]["geometry_level"] == "district_without_township_geometry"
    assert "unmatched_district_kept_as_district_level_fallback" in proxy["limitations"]


def test_unicom_latent_mobility_graph_aggregates_duplicate_edges_and_flags_missing_geometry():
    records = [
        {"home_grid_id": "1", "work_grid_id": "2", "home_work_same": "0", "expanded_population": "10"},
        {"home_grid_id": "1", "work_grid_id": "2", "home_work_same": "0", "expanded_population": "5"},
        {"home_grid_id": "1", "work_grid_id": "0", "home_work_same": "0", "expanded_population": "2"},
        {"home_grid_id": "2", "work_grid_id": "2", "home_work_same": "1", "expanded_population": "3"},
    ]

    graph = build_unicom_latent_mobility_graph(
        records=records,
        source_ref="unit-test",
        created_at="2026-07-05T00:00:00+08:00",
    )

    assert graph["schema"] == "uwm.unicom_latent_mobility_graph.v1"
    assert graph["synthetic_flags"] == [
        {"dataset_id": "uwm_unicom_latent_mobility_graph_2023", "status": "fitted_proxy"}
    ]
    assert graph["record_counts"]["raw_rows"] == 4
    assert graph["record_counts"]["directed_edges"] == 3
    assert graph["summary"]["total_expanded_population"] == 20.0
    assert graph["summary"]["self_loop_expanded_population"] == 3.0
    assert graph["summary"]["unknown_or_external_work_grid_expanded_population"] == 2.0
    assert "grid_geometry_dictionary_missing" in graph["limitations"]

    edge_by_pair = {(edge["home_grid_id"], edge["work_grid_id"]): edge for edge in graph["edges"]}
    assert edge_by_pair[("1", "2")]["expanded_population"] == 15.0
    assert edge_by_pair[("1", "2")]["raw_row_count"] == 2
    assert edge_by_pair[("1", "0")]["is_unknown_or_external_work_grid"] is True

    node_by_id = {node["grid_id"]: node for node in graph["nodes"]}
    assert node_by_id["1"]["out_weight"] == 17.0
    assert node_by_id["2"]["in_weight"] == 18.0
    assert node_by_id["0"]["is_unknown_or_external_work_grid"] is True


def test_fitted_gap_filling_mmfe_state_input_marks_fitted_proxy_as_non_production_source():
    population_proxy = build_population_downscaling_proxy(
        ghsl_rows=[
            {
                "admin_unit_id": "a-1",
                "county": "Alpha",
                "township": "A1",
                "population_proxy_sum": "1",
                "built_surface_proxy_sum": "0",
            }
        ],
        district_rows=[{"district_name": "Alpha", "resident_population_10k": "1"}],
        source_ref="unit-test",
        created_at="2026-07-05T00:00:00+08:00",
    )
    mobility_graph = build_unicom_latent_mobility_graph(
        records=[{"home_grid_id": "1", "work_grid_id": "2", "expanded_population": "4"}],
        source_ref="unit-test",
        created_at="2026-07-05T00:00:00+08:00",
    )

    state_input = build_fitted_gap_filling_mmfe_state_input(
        population_proxy=population_proxy,
        mobility_graph=mobility_graph,
        timestamp="2026-07-05T00:00:00+08:00",
    )

    assert state_input["state_components"]["population_vulnerability"]["role_count"] == 1
    assert state_input["state_components"]["mobility_activity"]["role_count"] == 1
    assert state_input["production_policy"]["contains_synthetic_sources"] is True
    assert state_input["production_policy"]["authoritative_data_required_for_production"] is True
    assert "fitted proxies cannot support empirical superiority claims" in " ".join(
        state_input["warnings"]
    )


def test_write_fitted_gap_filling_snapshot_persists_expected_files(tmp_path: Path):
    manifest = write_fitted_gap_filling_snapshot(
        output_dir=tmp_path,
        ghsl_rows=[
            {
                "admin_unit_id": "a-1",
                "county": "Alpha",
                "township": "A1",
                "population_proxy_sum": "1",
                "built_surface_proxy_sum": "0",
            }
        ],
        district_rows=[{"district_name": "Alpha", "resident_population_10k": "1"}],
        unicom_records=[{"home_grid_id": "1", "work_grid_id": "2", "expanded_population": "4"}],
        source_ref="unit-test",
        created_at="2026-07-05T00:00:00+08:00",
    )

    assert manifest["schema"] == "uwm.fitted_gap_filling_snapshot_manifest.v1"
    assert manifest["empirical_superiority_claim"] is False
    assert (tmp_path / "population_downscaling_proxy.json").exists()
    assert (tmp_path / "population_downscaling_admin_rows.csv").exists()
    assert (tmp_path / "unicom_latent_mobility_graph.json").exists()
    assert (tmp_path / "unicom_latent_mobility_edges.csv").exists()
    assert (tmp_path / "mmfe_uwm_state_input_fitted_gap_filling.json").exists()
    assert (tmp_path / "snapshot_manifest.json").exists()
