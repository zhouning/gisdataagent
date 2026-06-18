"""Tests for MMFE semantic product readiness diagnostics."""

import json
import unittest
from pathlib import Path


MMFE_DIR = Path("data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion")


class TestSemanticProductDiagnostics(unittest.TestCase):
    def test_diagnoses_twm_product_as_validation_ready_with_production_gaps(self):
        from data_agent import fusion_engine

        inputs = fusion_engine.load_semantic_product_okf_inputs(MMFE_DIR)
        diagnostic = fusion_engine.diagnose_semantic_product_readiness(
            inputs["manifest"],
            value_domain_audits=inputs["value_domain_audits"],
            standard_sources=inputs["standard_sources"],
            semantic_relations=inputs["semantic_relations"],
            state_input=inputs["state_input"],
            semantic_graph=inputs["semantic_graph"],
            semantic_trace_cards=inputs["semantic_trace_cards"],
            timestamp="2026-06-17T00:00:00+00:00",
        )
        validation = fusion_engine.validate_semantic_product_diagnostic(diagnostic)

        self.assertTrue(validation["valid"], validation["errors"])
        self.assertEqual(diagnostic["schema"], "mmfe.semantic_product_diagnostic.v1")
        self.assertEqual(diagnostic["product_id"], inputs["manifest"]["product_id"])
        self.assertTrue(diagnostic["summary"]["validation_ready"])
        self.assertFalse(diagnostic["summary"]["production_ready"])
        self.assertEqual(
            diagnostic["summary"]["status"],
            "validation_ready_with_production_gaps",
        )
        self.assertEqual(diagnostic["capabilities"]["semantic_relation_count"], 728)
        self.assertEqual(diagnostic["capabilities"]["objective_count"], 13)
        self.assertEqual(diagnostic["capabilities"]["trace_card_count"], 14)

        checks = {item["check_id"]: item for item in diagnostic["checks"]}
        self.assertEqual(checks["value_domain_audit"]["status"], "pass")
        self.assertEqual(checks["semantic_graph"]["status"], "pass")
        self.assertEqual(checks["multi_objective_interface"]["status"], "pass")
        self.assertEqual(checks["production_authority"]["status"], "warn")
        self.assertEqual(checks["production_metadata_contract"]["status"], "warn")
        self.assertTrue(checks["production_metadata_contract"]["evidence"]["contract_present"])
        self.assertEqual(checks["production_metadata_contract"]["evidence"]["source_count"], 7)
        self.assertEqual(checks["production_metadata_contract"]["evidence"]["blocked_source_count"], 7)
        self.assertEqual(checks["production_standard_gaps"]["status"], "warn")
        self.assertEqual(checks["standard_source_ingestion"]["status"], "warn")
        self.assertTrue(
            any(gap["check_id"] == "production_authority" for gap in diagnostic["top_gaps"])
        )
        self.assertTrue(
            any(gap["check_id"] == "production_metadata_contract" for gap in diagnostic["top_gaps"])
        )
        self.assertTrue(
            any("真实权威自然资源数据" in item for item in diagnostic["recommendations_zh"])
        )

    def test_blocks_product_without_twm_semantic_surfaces(self):
        from data_agent.fusion.semantic_product_diagnostics import (
            diagnose_semantic_product_readiness,
            validate_semantic_product_diagnostic,
        )

        manifest = {
            "product_type": "semantic_fusion_product",
            "product_id": "sfp-minimal-diagnostic-test",
            "version": "1.1",
            "quality": {"score": 0.9, "warnings": []},
            "ai_metadata": {"chunks": [], "embedding_ready": False},
            "mmfe_bundle": {},
        }

        diagnostic = diagnose_semantic_product_readiness(manifest)
        validation = validate_semantic_product_diagnostic(diagnostic)

        self.assertTrue(validation["valid"], validation["errors"])
        self.assertFalse(diagnostic["summary"]["validation_ready"])
        self.assertFalse(diagnostic["summary"]["production_ready"])
        self.assertEqual(diagnostic["summary"]["status"], "blocked")
        checks = {item["check_id"]: item for item in diagnostic["checks"]}
        self.assertEqual(checks["semantic_relations"]["status"], "fail")
        self.assertEqual(checks["twm_state_input"]["status"], "fail")
        self.assertEqual(checks["multi_objective_interface"]["status"], "fail")

    def test_production_metadata_contract_can_clear_authority_checks(self):
        from data_agent.fusion.production_readiness import build_production_readiness_contract
        from data_agent.fusion.semantic_product_diagnostics import diagnose_semantic_product_readiness

        manifest = {
            "product_type": "semantic_fusion_product",
            "product_id": "sfp-production-metadata-diagnostic-test",
            "version": "1.1",
            "business_output": {"path": "s3://lake/curated/fused.parquet"},
            "quality": {"score": 1.0, "warnings": []},
            "ai_metadata": {"chunks": [{"chunk_id": "c1", "text": "ready"}], "embedding_ready": True},
            "mmfe_bundle": {},
        }
        production_readiness = build_production_readiness_contract(
            manifest,
            sources=[
                {
                    "source_id": "pbf-2026",
                    "role": "permanent_basic_farmland",
                    "source_path": "s3://lake/raw/pbf/2026/data.parquet",
                    "authority": "自然资源主管部门",
                    "authority_level": "department",
                    "license": "authorized_government_use",
                    "access_rights": "authorized",
                    "update_date": "2026-06-01",
                    "lineage": "official release",
                    "crs": "EPSG:4490",
                    "scale_or_resolution": "1:10000",
                    "official_standard_version": "NR_ONE_MAP_TWM_CORE_2026",
                    "security_classification": "internal",
                }
            ],
            timestamp="2026-06-17T00:00:00+00:00",
        )
        manifest["mmfe_bundle"]["production_readiness"] = production_readiness
        state_input = {
            "schema": "mmfe.twm_state_input.v1",
            "production_policy": {
                "contains_synthetic_sources": False,
                "not_for_production": False,
                "authoritative_data_required_for_production": True,
            },
            "semantic_relation_summary": {"total_relation_count": 1, "registered_relation_type_count": 1},
            "state_components": {"hard_constraints": {"relation_count": 1, "hard_constraint": True}},
            "optimization_interface": {
                "objective_count": 1,
                "objective_bindings": [{"objective_id": "hard", "relation_count": 1}],
            },
        }

        diagnostic = diagnose_semantic_product_readiness(
            manifest,
            value_domain_audits=[{"field": "DLBM"}],
            standard_sources=[
                {
                    "standard_identifier": "GB/T 21010-2017",
                    "not_for_production_gap": False,
                }
            ],
            semantic_relations=[{"relation_type": "project_overlaps_pbf"}],
            state_input=state_input,
            semantic_graph={
                "nodes": [
                    {"id": "standard", "type": "standard_source"},
                    {"id": "domain", "type": "value_domain"},
                ],
                "edges": [{"source": "domain", "target": "standard"}],
            },
            semantic_trace_cards={"trace_card_count": 1, "standard_source_path_count": 1, "cards": [{}]},
            timestamp="2026-06-17T00:00:00+00:00",
        )

        checks = {item["check_id"]: item for item in diagnostic["checks"]}
        self.assertEqual(checks["production_metadata_contract"]["status"], "pass")
        self.assertEqual(checks["production_authority"]["status"], "pass")
        self.assertTrue(checks["production_metadata_contract"]["evidence"]["contract_present"])

    def test_standard_source_ingestion_run_quality_can_clear_ingestion_check(self):
        from data_agent.fusion.semantic_product_diagnostics import diagnose_semantic_product_readiness

        manifest = {
            "product_type": "semantic_fusion_product",
            "product_id": "sfp-standard-ingestion-quality-test",
            "version": "1.1",
            "business_output": {"path": "s3://lake/curated/fused.parquet"},
            "quality": {"score": 1.0, "warnings": []},
            "ai_metadata": {"chunks": [{"chunk_id": "c1", "text": "ready"}], "embedding_ready": True},
            "mmfe_bundle": {
                "value_domain_audit_summary": {"audit_count": 1, "requires_review_count": 0},
                "standard_source_registry": {
                    "summary": {
                        "source_count": 1,
                        "official_verified_count": 1,
                        "pending_official_source_count": 0,
                    }
                },
                "standard_source_ingestion_plan": {
                    "summary": {
                        "ready": True,
                        "ready_task_count": 1,
                        "blocked_task_count": 0,
                        "official_source_missing_count": 0,
                        "checksum_missing_count": 0,
                        "fulltext_extraction_missing_count": 0,
                    }
                },
                "standard_source_ingestion_run": {
                    "valid": True,
                    "summary": {
                        "ingested_task_count": 1,
                        "extracted_task_count": 1,
                        "citation_anchor_count": 3,
                        "citation_anchor_quality_pass_count": 1,
                        "citation_anchor_quality_warn_count": 0,
                    },
                },
            },
        }
        state_input = {
            "schema": "mmfe.twm_state_input.v1",
            "production_policy": {"contains_synthetic_sources": True},
            "semantic_relation_summary": {"total_relation_count": 1, "registered_relation_type_count": 1},
            "state_components": {"hard_constraints": {"relation_count": 1, "hard_constraint": True}},
            "optimization_interface": {
                "objective_count": 1,
                "objective_bindings": [{"objective_id": "hard", "relation_count": 1}],
            },
        }

        diagnostic = diagnose_semantic_product_readiness(
            manifest,
            value_domain_audits=[{"field": "DLBM"}],
            standard_sources=[{"standard_identifier": "GB/T 21010-2017", "not_for_production_gap": False}],
            semantic_relations=[{"relation_type": "project_overlaps_pbf"}],
            state_input=state_input,
            semantic_graph={
                "nodes": [
                    {"id": "standard", "type": "standard_source"},
                    {"id": "domain", "type": "value_domain"},
                ],
                "edges": [{"source": "domain", "target": "standard"}],
            },
            semantic_trace_cards={"trace_card_count": 1, "standard_source_path_count": 1, "cards": [{}]},
            timestamp="2026-06-17T00:00:00+00:00",
        )

        checks = {item["check_id"]: item for item in diagnostic["checks"]}
        self.assertEqual(checks["standard_source_ingestion"]["status"], "pass")
        self.assertEqual(checks["standard_source_ingestion"]["evidence"]["run_valid"], True)
        self.assertEqual(checks["standard_source_ingestion"]["evidence"]["citation_anchor_quality_pass_count"], 1)

    def test_api_is_exported_through_fusion_engine_proxy(self):
        from data_agent import fusion_engine

        self.assertEqual(
            fusion_engine.MMFE_PRODUCT_DIAGNOSTIC_SCHEMA,
            "mmfe.semantic_product_diagnostic.v1",
        )
        diagnostic = fusion_engine.diagnose_semantic_product_readiness(
            {
                "product_type": "semantic_fusion_product",
                "product_id": "sfp-proxy-diagnostic-test",
                "mmfe_bundle": {},
            }
        )
        self.assertEqual(diagnostic["product_id"], "sfp-proxy-diagnostic-test")


if __name__ == "__main__":
    unittest.main()
