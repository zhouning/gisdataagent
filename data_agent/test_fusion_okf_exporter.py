"""Tests for generic MMFE OKF sidecar export."""

import json
import tempfile
import unittest
from pathlib import Path


def _semantic_manifest() -> dict:
    return {
        "product_type": "semantic_fusion_product",
        "version": "1.1",
        "product_id": "sfp-okf-test",
        "business_output": {
            "path": "s3://geo-lake/curated/fusion/run-001/fused.parquet",
            "format": "GeoParquet",
            "row_count": 2,
            "column_count": 4,
            "crs": "EPSG:4326",
        },
        "sources": [
            {
                "path": "s3://geo-lake/raw/parcels/data.parquet",
                "data_type": "vector",
                "semantic_domain": "parcel_current",
                "modality": "vector",
                "adapter_family": "lakehouse",
                "columns": ["parcel_id", "land_use_code", "area_m2"],
                "semantic_hints": ["现状地类图斑"],
            }
        ],
        "mmfe_bundle": {
            "layer_summaries": [
                {
                    "role": "parcel_current",
                    "alias_zh": "现状地类图斑",
                    "description_zh": "Semantic parcel layer.",
                    "standard_role": "parcel_current",
                    "object_type": "parcel",
                    "path": "s3://geo-lake/curated/fusion/run-001/fused.parquet",
                    "crs": "EPSG:4326",
                    "field_count": 3,
                    "quality_score": 0.97,
                    "twm_binding": {"object_id": "parcel_id", "area_m2": "area_m2"},
                }
            ],
            "field_semantics": [
                {
                    "layer_role": "parcel_current",
                    "standard_role": "parcel_current",
                    "object_type": "parcel",
                    "field_name": "land_use_code",
                    "field_alias_zh": "地类编码",
                    "contract_requirement": "required",
                    "twm_semantic_key": "land_use_code",
                    "domain_or_rule": json.dumps({"domain": "gb_t_21010_2017_land_use_code"}),
                    "match_type": "standard_field_catalog",
                    "confidence": 0.96,
                }
            ],
            "semantic_relations": [
                {
                    "relation_id": "REL-001",
                    "semantic_relation_type": "project_overlaps_parcel",
                    "source_object_type": "project",
                    "source_object_id": "PRJ-001",
                    "target_object_type": "parcel",
                    "target_object_id": "P-001",
                    "target_standard_role": "parcel_current",
                    "predicate_zh": "占用现状图斑",
                    "business_semantic_zh": "Project overlaps parcel for impact analysis.",
                    "twm_usage": "state_builder_project_parcel_impact",
                    "metric_name": "overlap_area_m2",
                    "metric_value": 12.5,
                    "confidence": 0.99,
                    "semantic_strength": "medium",
                }
            ],
            "rule_bindings": [
                {
                    "rule_id": "MMFE-DQ-001",
                    "rule_name_zh": "空间数据质量门槛",
                    "severity": "medium",
                    "target_layer": "parcel_current",
                    "target_standard_role": "parcel_current",
                    "logic": "quality.score >= 0.8",
                }
            ],
            "optimization_summary": {
                "objective_count": 1,
                "scenario_count": 1,
                "objectives": [
                    {
                        "objective_id": "farmland_loss_m2",
                        "objective_name_zh": "耕地损失最小化",
                        "category": "resource",
                        "direction": "min",
                        "unit": "m2",
                        "weight": 1.0,
                        "hard_constraint": False,
                    }
                ],
            },
            "semantic_diagnostic": {
                "schema": "mmfe.semantic_product_diagnostic.v1",
                "product_id": "sfp-okf-test",
                "summary": {
                    "status": "validation_ready_with_production_gaps",
                    "readiness_score": 0.8,
                    "validation_ready": True,
                    "production_ready": False,
                    "check_count": 1,
                    "pass_count": 0,
                    "warn_count": 1,
                    "fail_count": 0,
                },
                "capabilities": {
                    "layer_count": 1,
                    "field_semantic_count": 1,
                    "semantic_relation_count": 1,
                    "semantic_graph_node_count": 0,
                    "semantic_graph_edge_count": 0,
                    "trace_card_count": 0,
                    "objective_count": 1,
                    "ai_chunk_count": 1,
                },
                "checks": [
                    {
                        "check_id": "production_authority",
                        "name_zh": "生产权威数据条件",
                        "status": "warn",
                        "severity": "critical",
                        "required_for_validation": False,
                        "message_zh": "测试数据不是生产权威数据。",
                        "evidence": {"not_for_production": True},
                    }
                ],
                "top_gaps": [
                    {
                        "check_id": "production_authority",
                        "status": "warn",
                        "severity": "critical",
                        "message_zh": "测试数据不是生产权威数据。",
                    }
                ],
                "recommendations_zh": ["进入生产时必须替换为真实权威自然资源数据。"],
            },
        },
        "ai_metadata": {
            "embedding_ready": True,
            "chunks": [
                {
                    "chunk_id": "fusion:product",
                    "text": "Semantic fusion product generated for OKF export.",
                    "metadata": {"strategy": "spatial_join"},
                }
            ],
        },
    }


class TestFusionOkfExporter(unittest.TestCase):
    def test_export_semantic_product_okf_bundle_writes_valid_generic_bundle(self):
        from data_agent.fusion.okf_exporter import (
            OKF_EXPORT_SCHEMA,
            export_semantic_product_okf_bundle,
        )

        with tempfile.TemporaryDirectory() as tmp:
            result = export_semantic_product_okf_bundle(_semantic_manifest(), Path(tmp) / "okf")
            out_dir = Path(result["out_dir"])

            self.assertEqual(result["schema"], OKF_EXPORT_SCHEMA)
            self.assertEqual(result["okf_version"], "0.2")
            self.assertTrue(result["valid"], result["errors"])
            self.assertGreaterEqual(result["concept_count"], 5)
            self.assertTrue((out_dir / "index.md").exists())
            self.assertTrue((out_dir / "datasets" / "semantic_product.md").exists())
            self.assertTrue((out_dir / "layers" / "parcel_current.md").exists())
            self.assertTrue((out_dir / "fields" / "parcel_current" / "land_use_code.md").exists())
            self.assertTrue((out_dir / "relations" / "project_overlaps_parcel" / "rel-001.md").exists())
            self.assertTrue((out_dir / "rules" / "mmfe-dq-001.md").exists())
            self.assertTrue((out_dir / "objectives" / "farmland_loss_m2.md").exists())
            self.assertTrue((out_dir / "ai_chunks" / "fusion-product.md").exists())
            self.assertTrue((out_dir / "diagnostics" / "semantic_product_readiness.md").exists())
            self.assertTrue((out_dir / "graphs" / "semantic_ontology.md").exists())

            dataset_text = (out_dir / "datasets" / "semantic_product.md").read_text(encoding="utf-8")
            root_index_text = (out_dir / "index.md").read_text(encoding="utf-8")
            self.assertIn('okf_version: "0.2"', root_index_text)
            self.assertNotIn("type:", root_index_text.split("---", 2)[1])
            self.assertIn('generated: {"by": "gda-mmfe-okf-exporter/2.0"', dataset_text)
            self.assertIn('sources: [{"id": "parcel_current"', dataset_text)
            self.assertNotIn("timestamp:", dataset_text)
            self.assertIn("Field semantic mappings | 1", dataset_text)
            self.assertIn("Semantic relations | 1", dataset_text)
            self.assertIn("[现状地类图斑](/layers/parcel_current.md)", dataset_text)
            self.assertIn("Ontology fields | 1", dataset_text)
            diagnostic_text = (out_dir / "diagnostics" / "semantic_product_readiness.md").read_text(encoding="utf-8")
            self.assertIn("Status | `validation_ready_with_production_gaps`", diagnostic_text)
            self.assertIn("真实权威自然资源数据", diagnostic_text)
            ontology_text = (out_dir / "graphs" / "semantic_ontology.md").read_text(encoding="utf-8")
            self.assertIn("type: \"MMFE Semantic Ontology\"", ontology_text)
            self.assertIn("Fields | 1", ontology_text)

    def test_okf_exporter_is_available_through_fusion_engine_proxy(self):
        from data_agent import fusion_engine

        self.assertEqual(fusion_engine.OKF_EXPORT_SCHEMA, "mmfe.okf_export.v2")
        self.assertEqual(fusion_engine.OKF_VERSION, "0.2")
        bundle = fusion_engine.build_okf_bundle_from_semantic_product(_semantic_manifest())
        self.assertIn("datasets/semantic_product.md", bundle)


if __name__ == "__main__":
    unittest.main()
