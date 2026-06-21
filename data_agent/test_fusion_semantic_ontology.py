"""Tests for MMFE semantic ontology packages."""

import json
import tempfile
import unittest
from pathlib import Path


MANIFEST_PATH = Path("data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion/twm_mmfe_semantic_product.json")


class TestFusionSemanticOntology(unittest.TestCase):
    def test_build_semantic_ontology_package_from_twm_semantic_product(self):
        from data_agent.fusion.semantic_ontology import (
            SEMANTIC_ONTOLOGY_SCHEMA,
            build_semantic_ontology_package,
            validate_semantic_ontology_package,
        )

        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        bundle = manifest["mmfe_bundle"]
        ontology = build_semantic_ontology_package(
            manifest,
            field_semantics=bundle["field_semantics"],
            value_domain_audits=bundle["value_domain_audits"],
            standard_sources=bundle["standard_source_registry"]["entries"],
            semantic_relations=bundle["semantic_relations"],
            state_input=json.loads(
                Path("data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion/twm_state_input.json").read_text(encoding="utf-8")
            ),
            timestamp="2026-06-17T00:00:00+00:00",
        )

        validation = validate_semantic_ontology_package(ontology)
        self.assertEqual(ontology["schema"], SEMANTIC_ONTOLOGY_SCHEMA)
        self.assertTrue(validation["valid"], validation["errors"])
        self.assertEqual(ontology["source_product"]["product_id"], "sfp-twm-dc2a707aabda0c01")
        self.assertGreater(ontology["summary"]["field_count"], 100)
        self.assertGreater(ontology["summary"]["value_domain_count"], 0)
        self.assertGreater(ontology["summary"]["standard_source_count"], 0)
        self.assertGreater(ontology["summary"]["relationship_count"], 0)
        self.assertEqual(ontology["semantic_stack"]["standard_platform"]["role"], "authority_source")
        self.assertEqual(ontology["semantic_stack"]["twm"]["role"], "world_model_consumer")
        self.assertEqual(
            ontology["governance_contract"]["authority_chain"],
            [
                "standard_platform_release",
                "ontology_package",
                "semantic_layer_registration",
                "mmfe_semantic_product",
                "twm_state_input",
            ],
        )
        self.assertGreater(len(ontology["governance_contract"]["standard_versions"]), 0)
        self.assertEqual(
            ontology["consumption_contract"]["primary_consumer"],
            "territory_world_model",
        )
        self.assertGreater(len(ontology["consumption_contract"]["runtime_bindings"]), 0)
        self.assertGreater(
            ontology["summary"]["governed_field_count"],
            0,
        )
        self.assertEqual(
            ontology["summary"]["runtime_binding_count"],
            len(ontology["consumption_contract"]["runtime_bindings"]),
        )

        field_ids = {item["id"] for item in ontology["concepts"]["fields"]}
        self.assertIn("field:parcel_current.DLBM", field_ids)
        relation_types = {item["relation_type"] for item in ontology["concepts"]["relation_types"]}
        self.assertIn("project_overlaps_parcel", relation_types)
        self.assertIn("annual_change_of_parcel", relation_types)

        dlbm = next(item for item in ontology["concepts"]["fields"] if item["id"] == "field:parcel_current.DLBM")
        self.assertEqual(dlbm["value_domain"], "gb_t_21010_2017_land_use_code")
        self.assertIn("standard_source:gb-t-21010-2017", dlbm["standard_source_ids"])
        self.assertEqual(
            dlbm["governance_provenance"]["standard_id"],
            "NR_ONE_MAP_TWM_CORE_2026",
        )
        self.assertIn(
            "standard_reference",
            dlbm["governance_provenance"]["evidence_types"],
        )

    def test_write_semantic_ontology_package_and_validate_required_fields(self):
        from data_agent.fusion.semantic_ontology import (
            build_semantic_ontology_package,
            validate_semantic_ontology_package,
            write_semantic_ontology_package,
        )

        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        ontology = build_semantic_ontology_package(manifest)

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "mmfe_semantic_ontology.json"
            written = write_semantic_ontology_package(ontology, out_path)
            payload = json.loads(Path(written).read_text(encoding="utf-8"))

        self.assertEqual(payload["schema"], ontology["schema"])
        self.assertTrue(validate_semantic_ontology_package(payload)["valid"])

    def test_semantic_ontology_api_is_exported_through_fusion_proxy(self):
        from data_agent import fusion_engine

        self.assertEqual(fusion_engine.SEMANTIC_ONTOLOGY_SCHEMA, "mmfe.semantic_ontology.v1")


if __name__ == "__main__":
    unittest.main()
