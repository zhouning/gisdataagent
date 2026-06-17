"""Regression tests for the TWM validation dataset MMFE semantic bundle."""

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


DATA_DIR = Path("data_agent/test_data/twm_bishan_demo")
SCRIPT = Path("scripts/build_twm_mmfe_semantic_bundle.py")


class TestTwmMmfeSemanticBundle(unittest.TestCase):
    def test_builds_field_level_semantic_bundle_for_twm_dataset(self):
        self.assertTrue(DATA_DIR.exists(), f"missing fixture: {DATA_DIR}")
        self.assertTrue(SCRIPT.exists(), f"missing script: {SCRIPT}")

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "mmfe_semantic_fusion"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--data-dir",
                    str(DATA_DIR),
                    "--out-dir",
                    str(out_dir),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            summary = json.loads(result.stdout)

            self.assertEqual(summary["status"], "ok")
            self.assertEqual(summary["layer_count"], 9)
            self.assertGreater(summary["field_semantic_count"], 200)
            for key in [
                "business_view",
                "field_semantics",
                "value_domain_audit",
                "standard_sources",
                "standard_source_ingestion_plan",
                "production_readiness",
                "semantic_relations",
                "twm_input_contract",
                "twm_state_input",
                "knowledge_graph",
                "semantic_trace_cards",
                "semantic_ontology",
                "semantic_diagnostic",
                "semantic_product",
                "vector_spec",
                "publish_plan",
                "stac_item",
            ]:
                self.assertTrue(Path(summary[key]).exists(), key)

            business_rows = _read_csv(Path(summary["business_view"]))
            self.assertEqual(business_rows[0]["recommended_twm_input"], "semantic_fusion_product")
            self.assertEqual(business_rows[0]["standard_role_count"], "8")
            self.assertEqual(business_rows[0]["semantic_relation_count"], "728")

            field_rows = _read_csv(Path(summary["field_semantics"]))
            parcel_land_use = _find_row(field_rows, layer_role="parcel_current", field_name="DLBM")
            self.assertEqual(parcel_land_use["field_alias_zh"], "地类编码")
            self.assertEqual(parcel_land_use["standard_field"], "DLBM")
            self.assertEqual(parcel_land_use["standard_role"], "parcel_current")
            self.assertEqual(parcel_land_use["contract_requirement"], "required")
            self.assertEqual(parcel_land_use["twm_semantic_key"], "land_use_code")
            self.assertEqual(parcel_land_use["match_type"], "standard_field_catalog")
            self.assertEqual(parcel_land_use["alignment_decision"], "accept")
            self.assertEqual(parcel_land_use["requires_review"], "False")
            self.assertEqual(parcel_land_use["value_domain"], "gb_t_21010_2017_land_use_code")
            self.assertEqual(parcel_land_use["value_domain_status"], "loaded")
            parcel_evidence = json.loads(parcel_land_use["evidence_json"])
            self.assertIn("value_domain", {item["type"] for item in parcel_evidence})
            self.assertIn("standard_reference", {item["type"] for item in parcel_evidence})

            audit_rows = _read_csv(Path(summary["value_domain_audit"]))
            self.assertEqual(summary["value_domain_audit_count"], 6)
            parcel_domain_audit = _find_row(
                audit_rows,
                layer_role="parcel_current",
                field_name="DLBM",
            )
            self.assertEqual(parcel_domain_audit["domain"], "gb_t_21010_2017_land_use_code")
            self.assertEqual(parcel_domain_audit["domain_status"], "loaded")
            self.assertEqual(parcel_domain_audit["audit_status"], "valid")
            self.assertEqual(parcel_domain_audit["total_count"], "4900")
            self.assertEqual(parcel_domain_audit["valid_count"], "4900")
            self.assertEqual(parcel_domain_audit["unknown_count"], "0")
            self.assertEqual(parcel_domain_audit["coverage"], "1.0")
            observed_values = json.loads(parcel_domain_audit["observed_values_json"])
            self.assertIn("203", {item["code"] for item in observed_values})

            standard_source_rows = _read_csv(Path(summary["standard_sources"]))
            self.assertEqual(summary["standard_source_count"], 7)
            gbt21010 = _find_row(
                standard_source_rows,
                standard_identifier="GB/T 21010-2017",
            )
            self.assertEqual(gbt21010["title_zh"], "土地利用现状分类")
            self.assertEqual(gbt21010["retrieval_status"], "official_fulltext_available")
            self.assertEqual(gbt21010["access_mode"], "online_preview_and_download")
            self.assertIn("openstd.samr.gov.cn", gbt21010["official_url"])
            self.assertEqual(gbt21010["can_download"], "True")
            local_material = _find_row(
                standard_source_rows,
                standard_identifier="NR-ONE-MAP-DB-ARCH-02-SURVEY-MONITORING",
            )
            self.assertEqual(local_material["retrieval_status"], "local_expert_material_available")
            self.assertEqual(local_material["not_for_production_gap"], "True")

            standard_ingestion = json.loads(Path(summary["standard_source_ingestion_plan"]).read_text(encoding="utf-8"))
            self.assertEqual(standard_ingestion["schema"], "mmfe.standard_source_ingestion_plan.v1")
            self.assertFalse(standard_ingestion["summary"]["ready"])
            self.assertEqual(
                summary["standard_source_ingestion_ready"],
                standard_ingestion["summary"]["ready"],
            )
            self.assertEqual(
                summary["standard_source_ingestion_blocked_task_count"],
                standard_ingestion["summary"]["blocked_task_count"],
            )

            project_area = _find_row(field_rows, layer_role="synthetic_projects", field_name="YDMJ")
            self.assertEqual(project_area["contract_requirement"], "required")
            self.assertEqual(project_area["twm_semantic_key"], "area_m2")
            self.assertEqual(project_area["alignment_decision"], "accept")
            self.assertIn("twm_binding", {item["type"] for item in json.loads(project_area["evidence_json"])})

            pbf_area = _find_row(field_rows, layer_role="synthetic_pbf", field_name="YJJBNTMJ")
            self.assertEqual(pbf_area["standard_role"], "pbf")
            self.assertEqual(pbf_area["field_alias_zh"], "永久基本农田面积")
            self.assertEqual(pbf_area["twm_semantic_key"], "area_m2")

            rs_uri = _find_row(field_rows, layer_role="synthetic_remote_sensing_tiles", field_name="raster_uri")
            self.assertEqual(rs_uri["match_type"], "standard_field_catalog")
            self.assertEqual(rs_uri["contract_requirement"], "observed")
            self.assertEqual(rs_uri["alignment_decision"], "review")
            self.assertEqual(rs_uri["requires_review"], "True")

            relation_rows = _read_csv(Path(summary["semantic_relations"]))
            self.assertEqual(len(relation_rows), 728)
            pbf_rel = _find_row(
                relation_rows,
                semantic_relation_type="project_overlaps_permanent_basic_farmland",
            )
            self.assertEqual(pbf_rel["predicate_zh"], "触碰永久基本农田")
            self.assertEqual(pbf_rel["twm_usage"], "hard_constraint_pbf_overlap")
            self.assertEqual(pbf_rel["objective_id"], "pbf_overlap_m2")
            self.assertEqual(pbf_rel["rule_id"], "TWM-FARM-001")
            self.assertEqual(pbf_rel["requires_rule_review"], "True")

            rs_rel = _find_row(
                relation_rows,
                semantic_relation_type="project_observed_by_remote_sensing_tile",
            )
            self.assertEqual(rs_rel["evidence_type"], "remote_sensing_coverage")
            self.assertEqual(rs_rel["twm_usage"], "multimodal_observation_evidence")

            change_rel = _find_row(
                relation_rows,
                semantic_relation_type="annual_change_of_parcel",
            )
            self.assertEqual(change_rel["semantic_strength"], "strong")

            contract = json.loads(Path(summary["twm_input_contract"]).read_text(encoding="utf-8"))
            self.assertEqual(contract["recommended_twm_input"], "semantic_fusion_product")
            self.assertEqual(contract["raw_data_usage"], "source_of_truth_geometry_and_attributes")
            self.assertEqual(contract["state_builder_policy"], "load_semantic_product_then_dereference_raw_sources")
            parcel_binding = _find_binding(contract["role_bindings"], "parcel_current")
            self.assertEqual(parcel_binding["twm_binding"]["land_use_code"], "DLBM")
            self.assertEqual(parcel_binding["twm_binding"]["area_m2"], "TBMJ")
            self.assertIn("pbf_overlap_m2", contract["state_builder_inputs"]["hard_constraint_objectives"])
            self.assertEqual(contract["state_builder_inputs"]["semantic_relation_count"], 728)
            self.assertIn(
                "project_overlaps_permanent_basic_farmland",
                contract["state_builder_inputs"]["semantic_relation_types"],
            )

            state_input = json.loads(Path(summary["twm_state_input"]).read_text(encoding="utf-8"))
            self.assertTrue(summary["twm_state_input_valid"])
            self.assertEqual(state_input["schema"], "mmfe.twm_state_input.v1")
            self.assertEqual(state_input["semantic_relation_summary"]["total_relation_count"], 728)
            self.assertEqual(state_input["state_components"]["hard_constraints"]["relation_count"], 67)
            self.assertIn("pbf_overlap_m2", state_input["state_components"]["hard_constraints"]["objective_ids"])
            self.assertIn("eco_overlap_m2", state_input["state_components"]["hard_constraints"]["objective_ids"])
            self.assertEqual(state_input["state_components"]["remote_sensing_evidence"]["relation_count"], 71)
            self.assertEqual(state_input["state_components"]["dynamic_transitions"]["relation_count"], 78)
            self.assertTrue(state_input["production_policy"]["not_for_production"])
            self.assertEqual(state_input["standard_readiness"]["missing_value_domains"], {})
            self.assertEqual(state_input["standard_readiness"]["value_domain_audit"]["audit_count"], 6)
            self.assertEqual(state_input["standard_readiness"]["value_domain_audit"]["requires_review_count"], 0)
            self.assertEqual(state_input["standard_readiness"]["standard_sources"]["source_count"], 7)
            self.assertEqual(state_input["standard_readiness"]["standard_sources"]["official_verified_count"], 1)
            self.assertEqual(state_input["standard_readiness"]["standard_sources"]["pending_official_source_count"], 6)

            graph = json.loads(Path(summary["knowledge_graph"]).read_text(encoding="utf-8"))
            self.assertEqual(graph["schema"], "mmfe.semantic_graph.v1")
            self.assertGreater(graph["node_count"], 100)
            self.assertGreater(graph["edge_count"], 200)
            node_by_id = {node["id"]: node for node in graph["nodes"]}
            edge_keys = {(edge["source"], edge["target"], edge["relationship"]) for edge in graph["edges"]}
            self.assertIn(("layer:synthetic_pbf", "role:pbf", "binds_to_standard_role"), edge_keys)
            self.assertIn(("objective:pbf_overlap_m2", "layer:synthetic_pbf", "uses_constraint_layer"), edge_keys)
            self.assertEqual(
                node_by_id["standard_source:gb-t-21010-2017"]["properties"]["retrieval_status"],
                "official_fulltext_available",
            )
            self.assertIn("value_domain:gb_t_21010_2017_land_use_code", node_by_id)
            self.assertIn(
                (
                    "value_domain:gb_t_21010_2017_land_use_code",
                    "standard_source:gb-t-21010-2017",
                    "grounded_by_standard_source",
                ),
                edge_keys,
            )
            self.assertIn(
                (
                    "field:parcel_current.DLBM",
                    "value_domain:gb_t_21010_2017_land_use_code",
                    "uses_value_domain",
                ),
                edge_keys,
            )
            self.assertIn(
                (
                    "role:parcel_current",
                    "standard_source:gb-t-21010-2017",
                    "supported_by_standard_source",
                ),
                edge_keys,
            )
            self.assertTrue(any(node["type"] == "semantic_relation" for node in graph["nodes"]))
            self.assertTrue(
                any(edge["relationship"] == "project_overlaps_permanent_basic_farmland" for edge in graph["edges"])
            )

            trace_cards = json.loads(Path(summary["semantic_trace_cards"]).read_text(encoding="utf-8"))
            self.assertEqual(trace_cards["schema"], "mmfe.semantic_graph_trace.v1")
            self.assertEqual(summary["semantic_trace_card_count"], 14)
            self.assertEqual(trace_cards["trace_card_count"], 14)
            dlbm_trace = _find_trace_card(trace_cards["cards"], "field:parcel_current.DLBM")
            self.assertIn("地类编码", dlbm_trace["summary_zh"])
            self.assertTrue(
                any(
                    path["nodes"][-1]["id"] == "standard_source:gb-t-21010-2017"
                    for path in dlbm_trace["standard_source_paths"]
                )
            )

            ontology = json.loads(Path(summary["semantic_ontology"]).read_text(encoding="utf-8"))
            self.assertTrue(summary["semantic_ontology_valid"])
            self.assertEqual(ontology["schema"], "mmfe.semantic_ontology.v1")
            self.assertEqual(ontology["summary"]["standard_role_count"], 9)
            self.assertEqual(ontology["summary"]["object_type_count"], 6)
            self.assertEqual(ontology["summary"]["field_count"], 274)
            self.assertEqual(ontology["summary"]["semantic_key_count"], 14)
            self.assertEqual(ontology["summary"]["value_domain_count"], 6)
            self.assertEqual(ontology["summary"]["relation_type_count"], 7)
            self.assertEqual(ontology["summary"]["rule_count"], 7)
            self.assertEqual(ontology["summary"]["optimization_objective_count"], 13)
            self.assertEqual(
                summary["semantic_ontology_relationship_count"],
                ontology["summary"]["relationship_count"],
            )
            ontology_fields = {item["id"]: item for item in ontology["concepts"]["fields"]}
            self.assertEqual(
                ontology_fields["field:parcel_current.DLBM"]["value_domain"],
                "gb_t_21010_2017_land_use_code",
            )
            relation_type_ids = {item["relation_type"] for item in ontology["concepts"]["relation_types"]}
            self.assertIn("project_overlaps_permanent_basic_farmland", relation_type_ids)

            diagnostic = json.loads(Path(summary["semantic_diagnostic"]).read_text(encoding="utf-8"))
            self.assertEqual(diagnostic["schema"], "mmfe.semantic_product_diagnostic.v1")
            self.assertEqual(summary["semantic_diagnostic_status"], "validation_ready_with_production_gaps")
            self.assertTrue(summary["semantic_diagnostic_validation_ready"])
            self.assertFalse(summary["semantic_diagnostic_production_ready"])
            self.assertTrue(diagnostic["summary"]["validation_ready"])
            self.assertFalse(diagnostic["summary"]["production_ready"])
            self.assertEqual(diagnostic["capabilities"]["semantic_relation_count"], 728)
            self.assertEqual(diagnostic["capabilities"]["objective_count"], 13)
            self.assertEqual(diagnostic["capabilities"]["trace_card_count"], 14)
            self.assertTrue(
                any(gap["check_id"] == "production_authority" for gap in diagnostic["top_gaps"])
            )
            self.assertTrue(
                any(gap["check_id"] == "standard_source_ingestion" for gap in diagnostic["top_gaps"])
            )
            self.assertTrue(
                any(gap["check_id"] == "production_metadata_contract" for gap in diagnostic["top_gaps"])
            )

            production_readiness = json.loads(Path(summary["production_readiness"]).read_text(encoding="utf-8"))
            self.assertEqual(production_readiness["schema"], "mmfe.production_readiness.v1")
            self.assertFalse(production_readiness["summary"]["production_metadata_ready"])
            self.assertEqual(production_readiness["summary"]["source_count"], 17)
            self.assertEqual(production_readiness["summary"]["blocked_source_count"], 17)
            self.assertEqual(
                sum(1 for source in production_readiness["sources"] if source["role"] == "standard_source"),
                7,
            )
            self.assertTrue(
                any(
                    source["source_id"] == "standard-source:GB/T 21010-2017"
                    for source in production_readiness["sources"]
                )
            )
            self.assertEqual(
                summary["production_readiness_ready"],
                production_readiness["summary"]["production_metadata_ready"],
            )
            self.assertEqual(
                summary["production_readiness_blocked_source_count"],
                production_readiness["summary"]["blocked_source_count"],
            )

            product = json.loads(Path(summary["semantic_product"]).read_text(encoding="utf-8"))
            self.assertEqual(product["product_type"], "semantic_fusion_product")
            self.assertEqual(
                Path(product["business_outputs"]["twm_state_input"]).name,
                "twm_state_input.json",
            )
            self.assertEqual(
                Path(product["business_outputs"]["semantic_diagnostic"]).name,
                "twm_mmfe_semantic_diagnostic.json",
            )
            self.assertEqual(
                Path(product["business_outputs"]["production_readiness"]).name,
                "twm_mmfe_production_readiness.json",
            )
            self.assertEqual(
                Path(product["business_outputs"]["standard_source_ingestion_plan"]).name,
                "twm_mmfe_standard_source_ingestion_plan.json",
            )
            self.assertEqual(
                Path(product["business_outputs"]["semantic_ontology"]).name,
                "twm_mmfe_semantic_ontology.json",
            )
            self.assertEqual(
                product["mmfe_bundle"]["semantic_ontology_summary"]["relationship_count"],
                ontology["summary"]["relationship_count"],
            )
            self.assertEqual(
                product["mmfe_bundle"]["semantic_diagnostic_summary"]["status"],
                "validation_ready_with_production_gaps",
            )
            self.assertEqual(product["mmfe_bundle"]["standard_summary"]["role_contract_count"], 9)
            self.assertGreater(product["mmfe_bundle"]["standard_summary"]["alias_count"], 100)
            self.assertEqual(product["mmfe_bundle"]["standard_summary"]["standard_source_count"], 7)
            self.assertEqual(product["mmfe_bundle"]["standard_summary"]["official_verified_source_count"], 1)
            self.assertEqual(product["mmfe_bundle"]["standard_summary"]["pending_official_source_count"], 6)
            self.assertEqual(product["mmfe_bundle"]["standard_source_registry"]["summary"]["source_count"], 7)
            self.assertFalse(product["mmfe_bundle"]["production_readiness"]["summary"]["production_metadata_ready"])
            self.assertFalse(product["mmfe_bundle"]["standard_source_ingestion_plan"]["summary"]["ready"])
            self.assertEqual(
                product["mmfe_bundle"]["standard_source_registry"]["summary"][
                    "retrieval_status_distribution"
                ],
                {"local_expert_material_available": 6, "official_fulltext_available": 1},
            )
            self.assertEqual(product["mmfe_bundle"]["alignment_summary"]["decisions"]["accept"], 120)
            self.assertEqual(product["mmfe_bundle"]["alignment_summary"]["decisions"]["review"], 154)
            self.assertEqual(product["mmfe_bundle"]["alignment_summary"]["review_required"], 154)
            self.assertEqual(product["mmfe_bundle"]["alignment_summary"]["missing_value_domains"], {})
            self.assertEqual(
                product["mmfe_bundle"]["alignment_summary"]["loaded_value_domains"][
                    "gb_t_21010_2017_land_use_code"
                ],
                1,
            )
            self.assertEqual(product["mmfe_bundle"]["value_domain_audit_summary"]["audit_count"], 6)
            self.assertEqual(product["mmfe_bundle"]["value_domain_audit_summary"]["requires_review_count"], 0)
            self.assertEqual(product["mmfe_bundle"]["semantic_relation_summary"]["semantic_relation_count"], 728)
            self.assertEqual(product["mmfe_bundle"]["semantic_trace_cards"]["trace_card_count"], 14)
            self.assertEqual(
                product["mmfe_bundle"]["semantic_relation_summary"]["relation_type_distribution"][
                    "project_overlaps_parcel"
                ],
                354,
            )
            self.assertEqual(len(product["ai_metadata"]["chunks"]), summary["chunk_count"])
            self.assertTrue(
                any(chunk["chunk_id"] == "fusion:field-semantics" for chunk in product["ai_metadata"]["chunks"])
            )
            self.assertTrue(
                any(chunk["chunk_id"] == "fusion:semantic-relations" for chunk in product["ai_metadata"]["chunks"])
            )
            self.assertTrue(
                any(chunk["chunk_id"] == "fusion:value-domain-audit" for chunk in product["ai_metadata"]["chunks"])
            )
            self.assertTrue(
                any(chunk["chunk_id"] == "fusion:standard-sources" for chunk in product["ai_metadata"]["chunks"])
            )
            self.assertTrue(
                any(
                    mapping.get("alignment_score", {}).get("decision") == "accept"
                    and mapping.get("source_field") == "parcel_current.DLBM"
                    for mapping in product["semantic_mappings"]
                )
            )

            stac_item = json.loads(Path(summary["stac_item"]).read_text(encoding="utf-8"))
            self.assertIn("semantic_diagnostic", stac_item["assets"])
            self.assertIn("semantic_ontology", stac_item["assets"])
            self.assertIn("standard_source_ingestion_plan", stac_item["assets"])
            self.assertIn("production_readiness", stac_item["assets"])
            self.assertEqual(
                stac_item["assets"]["semantic_ontology"]["roles"],
                ["metadata", "semantic-ontology"],
            )
            self.assertEqual(
                stac_item["assets"]["production_readiness"]["roles"],
                ["metadata", "production-readiness"],
            )
            self.assertEqual(
                stac_item["assets"]["standard_source_ingestion_plan"]["roles"],
                ["metadata", "standard-source-ingestion-plan"],
            )
            self.assertEqual(
                stac_item["assets"]["semantic_diagnostic"]["roles"],
                ["metadata", "semantic-diagnostic"],
            )

            readme_text = (Path(summary["out_dir"]) / "README.md").read_text(encoding="utf-8")
            self.assertIn("twm_mmfe_standard_source_ingestion_plan.json", readme_text)
            self.assertIn("twm_mmfe_production_readiness.json", readme_text)
            self.assertIn("twm_mmfe_semantic_ontology.json", readme_text)
            self.assertIn("twm_mmfe_semantic_diagnostic.json", readme_text)
            self.assertIn("Production metadata ready: False", readme_text)
            self.assertIn("Standard source ingestion ready: False", readme_text)
            self.assertIn("Semantic ontology relationships:", readme_text)
            self.assertIn("Semantic diagnostic status: validation_ready_with_production_gaps", readme_text)


def _read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _find_row(rows: list[dict], **criteria) -> dict:
    for row in rows:
        if all(row.get(key) == value for key, value in criteria.items()):
            return row
    raise AssertionError(f"row not found: {criteria}")


def _find_binding(bindings: list[dict], role: str) -> dict:
    for binding in bindings:
        if binding.get("role") == role:
            return binding
    raise AssertionError(f"binding not found: {role}")


def _find_trace_card(cards: list[dict], node_id: str) -> dict:
    for card in cards:
        if (card.get("node") or {}).get("id") == node_id:
            return card
    raise AssertionError(f"trace card not found: {node_id}")


if __name__ == "__main__":
    unittest.main()
