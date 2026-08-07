"""Project adapter for AI Urban Scientist skills and the GWM-based UWM instance."""

from __future__ import annotations

from typing import Any


UWM_AI_URBAN_SCIENTIST_GAP_MATRIX_SCHEMA = (
    "uwm.ai_urban_scientist_data_gap_matrix.v1"
)


UWM_AI_URBAN_SCIENTIST_GAP_ROUTES: tuple[dict[str, Any], ...] = (
    {
        "gap_id": "observed_policy_outcome_panel",
        "priority": "P0",
        "uwm_roles": ["causal_evidence_gate", "planner_validation"],
        "evidence_needed": (
            "Authoritative intervention history, timing, target, intensity, "
            "pre-state, post-state, comparison units, and observed outcomes."
        ),
        "selected_skills": [
            "document-portal-platform",
            "planetary-computer",
            "arcgis-platform",
            "ckan-platform",
        ],
        "route_type": "official_register_plus_observed_outcome_candidate",
        "route_use": (
            "Link the official Chongqing 2023 major-project register to bounded "
            "Landsat surface-temperature and reflectance observations. The route "
            "is a candidate panel design, not an admitted policy-effect dataset."
        ),
        "access_boundary": "project_geometry_and_license_review_required",
        "download_status": "sample_ready_after_geometry_freeze",
        "current_closure_status": "candidate_route_identified_gap_open",
        "candidate_evidence_routes": [
            {
                "candidate_id": "chongqing_2023_urban_renewal_register",
                "source_type": "official_project_register",
                "publisher": "Chongqing Municipal Government General Office",
                "canonical_url": (
                    "https://www.cq.gov.cn/zwgk/zfxxgkzl/fdzdgknr/zdxm/"
                    "zdxmqd/zdxm2023/csgxts/202404/t20240425_13500292.html"
                ),
                "verified_fields": [
                    "project_id",
                    "project_name",
                    "construction_scope",
                    "start_year",
                    "planned_completion_year",
                    "annual_stage",
                    "annual_target",
                    "responsible_unit",
                ],
                "evidence_status": "official_metadata_candidate",
            },
            {
                "candidate_id": "landsat_c2_l2_chongqing_intervention_outcomes",
                "source_type": "observed_remote_sensing_candidate",
                "publisher": "USGS via Microsoft Planetary Computer",
                "collection": "landsat-c2-l2",
                "verified_assets": ["red", "nir08", "lwir11", "qa_pixel"],
                "pre_period": "2020-06-01/2022-09-30",
                "post_period": "2024-06-01/2025-09-30",
                "evidence_status": "coverage_probed_not_downloaded",
            },
            {
                "candidate_id": "chicago_zoning_longitudinal_panel_v0",
                "source_type": "cross_city_longitudinal_panel_source_candidate",
                "geography": "Chicago, Illinois, United States",
                "selected_skills": [
                    "legistar-platform",
                    "socrata-platform",
                    "census-acs",
                    "us-tiger-boundaries",
                ],
                "treatment_source": "official_chicago_elms_zoning_reclassification",
                "outcome_source": "chicago_socrata_building_permits_ydr8_5enu",
                "confounder_source": "census_acs5_tract_vintages",
                "spatial_source": "census_tiger_tract_boundaries",
                "verified_treatment_fields": [
                    "matter_id",
                    "record_number",
                    "status",
                    "sub_status",
                    "introduction_date",
                    "final_action_date",
                    "address_bearing_title",
                    "attachment_urls",
                ],
                "source_contract": (
                    "benchmarks/gwm_bench_candidates/"
                    "chicago_zoning_longitudinal_panel/"
                    "source_candidate_contract.json"
                ),
                "access_boundary": (
                    "treatment_probe_passed_outcome_acs_tiger_access_blocked"
                ),
                "download_status": "probe_only",
                "evidence_status": (
                    "treatment_record_candidate_ready_panel_materialization_blocked"
                ),
                "claim_boundary": (
                    "A passed zoning record is not an observed outcome panel, causal "
                    "effect, or cross-city GWM validation."
                ),
            },
        ],
        "admission_gate": (
            "Require authoritative project IDs, temporal linkage, outcome "
            "definitions, license, provenance, and a defensible comparison design."
        ),
        "claim_impact": (
            "Blocks observed policy-outcome, causal-effect, and real-world planner "
            "superiority claims."
        ),
    },
    {
        "gap_id": "observed_mobility_or_travel_time_graph",
        "priority": "P0",
        "uwm_roles": ["mobility_graph", "service_accessibility"],
        "evidence_needed": (
            "Observed OD flows or travel times with stable spatial IDs, time "
            "coverage, mode, sampling frame, and network impedance semantics."
        ),
        "selected_skills": [
            "document-portal-platform",
            "gtfs-feed",
            "osm-geofabrik-extracts",
        ],
        "route_type": "official_reports_plus_topology_then_external_candidate",
        "route_use": (
            "Use the official annual traffic-report series for aggregate observed "
            "mobility indicators and the exact Geofabrik Chongqing extract for road "
            "topology. GTFS remains unresolved, and none of these sources is raw "
            "observed Chongqing OD flow or realized link travel time."
        ),
        "access_boundary": "external_candidate_required",
        "download_status": "probe_only",
        "current_closure_status": "open_hard_gap",
        "candidate_evidence_routes": [
            {
                "candidate_id": "chongqing_traffic_annual_report_series",
                "source_type": "official_aggregate_mobility_reports",
                "publisher": "Chongqing Municipal Government",
                "coverage_note": "Published annually since 2007; 2018 and 2022-2025 pages verified.",
                "evidence_status": "aggregate_candidate_not_raw_od",
            },
            {
                "candidate_id": "geofabrik_chongqing_osm_extract",
                "source_type": "road_topology_candidate",
                "publisher": "Geofabrik/OpenStreetMap contributors",
                "canonical_url": (
                    "https://download.geofabrik.de/asia/china/chongqing-latest.osm.pbf"
                ),
                "probe_size_bytes": 30485952,
                "evidence_status": "metadata_probed_not_downloaded",
            },
            {
                "candidate_id": "chongqing_gtfs_static",
                "source_type": "scheduled_transit_candidate",
                "evidence_status": "no_concrete_official_feed_found",
            },
        ],
        "admission_gate": (
            "Reject schedule, topology, search-index, and latent-similarity data as "
            "substitutes for observed OD or travel-time evidence."
        ),
        "claim_impact": (
            "Blocks observed mobility propagation, trip-time accessibility, and "
            "production mobility-kernel claims."
        ),
    },
    {
        "gap_id": "scene_aligned_station_air_quality",
        "priority": "P1",
        "uwm_roles": ["air_pollution_exposure", "state_dynamics_validation"],
        "evidence_needed": (
            "Station observations aligned to the declared 2024 Chongqing scene, "
            "with sensor, pollutant, unit, timestamp, provider, and coordinate metadata."
        ),
        "selected_skills": ["open-aq"],
        "route_type": "data_type_source",
        "route_use": (
            "Probe OpenAQ locations and bounded measurements before acquisition; "
            "preserve the existing zero-coverage result if the scene window is absent."
        ),
        "access_boundary": "api_key_required",
        "download_status": "probe_only",
        "current_closure_status": "historical_only_scene_gap_open",
        "admission_gate": (
            "Require non-zero scene-window coverage, unit harmonization, provider "
            "provenance, pagination completeness, and station-to-scene alignment."
        ),
        "claim_impact": (
            "Can strengthen observed state prediction but cannot support policy outcomes."
        ),
    },
    {
        "gap_id": "external_city_transition_benchmark",
        "priority": "P1",
        "uwm_roles": ["state_dynamics_validation", "generalization"],
        "evidence_needed": (
            "A second-city state/action/context/transition package harmonized to "
            "the UWM schema without test-derived mappings."
        ),
        "selected_skills": [
            "open-aq",
            "noaa-weather",
            "osm-geofabrik-extracts",
            "microsoft-building-footprints",
            "planetary-computer",
        ],
        "route_type": "multi_source_discovery",
        "route_use": (
            "Assemble comparable environmental and built-form context; no bundled "
            "source supplies observed urban intervention transitions."
        ),
        "access_boundary": "external_candidate_required_for_actions_and_outcomes",
        "download_status": "probe_only",
        "current_closure_status": "open_optional_scope_extension",
        "admission_gate": (
            "Freeze a common schema, evidence classes, spatial crosswalk, time split, "
            "license, and leave-city-out evaluation before any generalization claim."
        ),
        "claim_impact": "Blocks cross-city UWM superiority and generalization claims.",
    },
    {
        "gap_id": "remote_sensing_state_refresh",
        "priority": "P2",
        "uwm_roles": ["remote_sensing_state", "heat_exposure", "urban_form"],
        "evidence_needed": (
            "Versioned imagery or derived land-cover/temperature products covering "
            "the declared Chongqing geography and scene dates."
        ),
        "selected_skills": [
            "planetary-computer",
            "stac-platform",
            "nasa-earthdata-cmr",
        ],
        "route_type": "data_type_source",
        "route_use": (
            "Discover collections, query bounded items, inspect assets, and validate "
            "CRS, resolution, nodata, cloud/quality flags, license, and coverage."
        ),
        "access_boundary": "source_specific",
        "download_status": "sample_ready_after_probe",
        "current_closure_status": "enhancement_not_claim_closure",
        "admission_gate": (
            "Do not admit catalog or asset URLs until item coverage, product semantics, "
            "license, resolution, and reproducible processing are verified."
        ),
        "claim_impact": (
            "Improves state coverage and reproducibility but does not close policy, "
            "mobility, Kernel, or write-back evidence gaps."
        ),
    },
    {
        "gap_id": "built_form_and_service_refresh",
        "priority": "P2",
        "uwm_roles": ["urban_form", "service_accessibility"],
        "evidence_needed": (
            "Versioned building footprints, roads, POIs, and land-use features with "
            "coverage, geometry, tag, duplicate, license, and vintage audits."
        ),
        "selected_skills": [
            "osm-geofabrik-extracts",
            "microsoft-building-footprints",
        ],
        "route_type": "data_type_source",
        "route_use": (
            "Refresh public built-form and network proxies and compare them with local "
            "planning assets; do not silently replace authoritative inventories."
        ),
        "access_boundary": "none_after_source_probe",
        "download_status": "sample_ready_after_probe",
        "current_closure_status": "proxy_enhancement",
        "admission_gate": (
            "Require ODbL or source-license compliance, spatial coverage, vintage, "
            "feature completeness, geometry validity, and local crosswalk validation."
        ),
        "claim_impact": (
            "Can strengthen renderer and endpoint proxies but not observed trip time "
            "or policy-outcome claims."
        ),
    },
)


def build_uwm_ai_urban_scientist_gap_matrix() -> dict[str, Any]:
    """Map current UWM evidence gaps to bounded AI Urban Scientist routes."""

    routes = [dict(route) for route in UWM_AI_URBAN_SCIENTIST_GAP_ROUTES]
    return {
        "schema": UWM_AI_URBAN_SCIENTIST_GAP_MATRIX_SCHEMA,
        "scope": "uwm_data_foundation_and_paper_evidence",
        "architecture_context": {
            "gwm_role": (
                "Upper-level Geospatial World Model paradigm and shared contract for "
                "state, action, transition, spatial relations, uncertainty, write-back, "
                "replanning, evidence, and claim boundaries."
            ),
            "uwm_role": (
                "Urban-domain GWM instance that specializes the shared contract with "
                "urban ontology, data roles, states, actions, dynamics, outcomes, and "
                "evaluation tasks."
            ),
            "inheritance_contract": [
                "updatable_world_state",
                "action_conditioned_transition",
                "dynamic_geospatial_relations",
                "state_write_back",
                "replanning_in_updated_state",
                "multi_step_error_and_uncertainty",
                "evidence_and_claim_boundary",
            ],
            "urban_specialization": [
                "urban_object_and_state_ontology",
                "urban_intervention_action_taxonomy",
                "urban_spatial_relation_semantics",
                "urban_transition_and_outcome_measurement",
                "urban_policy_and_planning_evaluation",
            ],
            "current_implementation_state": {
                "gwm_paradigm_present": True,
                "twm_and_uwm_domain_instances_present": True,
                "shared_platform_runtime_kernel_extracted": False,
                "rule_based_kernel_is_only_a_baseline": True,
                "status_rule": (
                    "Do not describe the current repository as having a fully extracted "
                    "platform-level shared GWM Runtime Kernel."
                ),
            },
            "paper_claim_boundary": {
                "uwm_success_proves_general_gwm": False,
                "single_city_proves_general_gwm": False,
                "bundle_completeness_proves_world_model_validity": False,
                "allowed_architecture_claim": (
                    "A passing contract-conformance audit can support the feasibility "
                    "of this urban-domain instantiation, not general GWM validity."
                ),
                "failure_attribution_rule": (
                    "Use contract and specialization ablations to distinguish a shared "
                    "GWM-interface failure from an urban ontology, data, transition, or "
                    "evaluation failure."
                ),
            },
            "skill_bundle_role": (
                "AI Urban Scientist skills support source discovery, bounded acquisition, "
                "data governance, experiment planning, and paper production for UWM; "
                "they are not the GWM or UWM model architecture."
            ),
        },
        "bundle_contract": {
            "selected_skill_count": 25,
            "platform_skill_count": 9,
            "concrete_source_skill_count": 16,
            "full_native_universe_count": 144,
            "router_is_dataset_evidence": False,
            "homepage_is_validated_dataset": False,
            "no_silent_substitution": True,
        },
        "routes": routes,
        "priority_counts": {
            priority: sum(route["priority"] == priority for route in routes)
            for priority in ("P0", "P1", "P2")
        },
        "hard_gaps_closed_by_bundle": [],
        "hard_gaps_still_open": [
            "observed_policy_outcome_panel",
            "observed_mobility_or_travel_time_graph",
        ],
        "claim_boundary": {
            "observed_policy_outcome_superiority": False,
            "causal_effect_of_urban_intervention": False,
            "observed_mobility_propagation": False,
            "cross_city_world_model_superiority": False,
            "rule": (
                "Skill routing and successful download improve the evidence inventory "
                "only after UWM manifest, license, lineage, MMFE alignment, quality, "
                "split, and claim gates pass."
            ),
        },
    }
