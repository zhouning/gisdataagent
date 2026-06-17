"""Tests for exporting TWM MMFE semantic products as OKF bundles."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


MMFE_DIR = Path("data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion")
SCRIPT = Path("scripts/export_twm_mmfe_okf_bundle.py")


class TestTwmMmfeOkfExport(unittest.TestCase):
    def test_exports_okf_sidecar_bundle_from_twm_mmfe_product(self):
        self.assertTrue(MMFE_DIR.exists(), f"missing fixture: {MMFE_DIR}")
        self.assertTrue(SCRIPT.exists(), f"missing script: {SCRIPT}")

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "okf_bundle"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--mmfe-dir",
                    str(MMFE_DIR),
                    "--out-dir",
                    str(out_dir),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            summary = json.loads(result.stdout)

            self.assertEqual(summary["status"], "ok")
            self.assertEqual(summary["schema"], "mmfe.okf_export.v1")
            self.assertTrue(summary["valid"], summary["errors"])
            self.assertTrue(summary["validation"]["valid"], summary["validation"]["errors"])
            self.assertGreater(summary["validation"]["concept_count"], 100)

            dataset_doc = out_dir / "datasets" / "semantic_product.md"
            layer_doc = out_dir / "layers" / "parcel_current.md"
            field_doc = out_dir / "fields" / "parcel_current" / "dlbm.md"
            rule_doc = out_dir / "rules" / "twm-farm-001.md"
            objective_doc = out_dir / "objectives" / "pbf_overlap_m2.md"
            contract_doc = out_dir / "twm" / "state_input_contract.md"
            state_input_doc = out_dir / "twm" / "state_input.md"
            value_domain_doc = out_dir / "standards" / "value_domain_audit.md"
            standard_source_doc = out_dir / "standards" / "source_registry.md"
            trace_cards_doc = out_dir / "graphs" / "semantic_trace_cards.md"
            ontology_doc = out_dir / "graphs" / "semantic_ontology.md"
            diagnostic_doc = out_dir / "diagnostics" / "semantic_product_readiness.md"
            relation_doc = (
                out_dir
                / "relations"
                / "project_overlaps_permanent_basic_farmland"
                / "project_overlaps_pbf-000000.md"
            )

            for path in [
                dataset_doc,
                layer_doc,
                field_doc,
                rule_doc,
                objective_doc,
                contract_doc,
                state_input_doc,
                value_domain_doc,
                standard_source_doc,
                trace_cards_doc,
                ontology_doc,
                diagnostic_doc,
                relation_doc,
            ]:
                self.assertTrue(path.exists(), str(path))
                self.assertIn("type:", path.read_text(encoding="utf-8").split("---", 2)[1])

            dataset_text = dataset_doc.read_text(encoding="utf-8")
            self.assertIn("type: \"MMFE Semantic Product\"", dataset_text)
            self.assertIn("Field semantic mappings | 274", dataset_text)
            self.assertIn("Value-domain audits | 6", dataset_text)
            self.assertIn("Semantic relations | 728", dataset_text)
            self.assertIn("[现状地类图斑](/layers/parcel_current.md)", dataset_text)
            self.assertIn("[永久基本农田占用最小化](/objectives/pbf_overlap_m2.md)", dataset_text)

            layer_text = layer_doc.read_text(encoding="utf-8")
            self.assertIn("object_type: \"parcel\"", layer_text)
            self.assertIn("| `land_use_code` | `DLBM` |", layer_text)
            self.assertIn("[DLBM](/fields/parcel_current/dlbm.md)", layer_text)

            field_text = field_doc.read_text(encoding="utf-8")
            self.assertIn("title: \"地类编码\"", field_text)
            self.assertIn("twm_semantic_key: \"land_use_code\"", field_text)
            self.assertIn("alignment_decision: \"accept\"", field_text)
            self.assertIn("| Alignment decision | `accept` |", field_text)
            self.assertIn("\"domain\": \"gb_t_21010_2017_land_use_code\"", field_text)
            self.assertIn("\"type\": \"value_domain\"", field_text)

            rule_text = rule_doc.read_text(encoding="utf-8")
            self.assertIn("Target layer | [synthetic_projects](/layers/synthetic_projects.md)", rule_text)
            self.assertIn("Constraint layer | [synthetic_pbf](/layers/synthetic_pbf.md)", rule_text)

            objective_text = objective_doc.read_text(encoding="utf-8")
            self.assertIn("hard_constraint: true", objective_text)
            self.assertIn("Direction | `min`", objective_text)

            contract_text = contract_doc.read_text(encoding="utf-8")
            self.assertIn("State builder policy | `load_semantic_product_then_dereference_raw_sources`", contract_text)
            self.assertIn("object_id=YJJBNTTBBH", contract_text)

            state_input_text = state_input_doc.read_text(encoding="utf-8")
            self.assertIn("type: \"TWM State Input\"", state_input_text)
            self.assertIn("Relation count | 728", state_input_text)
            self.assertIn("| `hard_constraints` | 67 |", state_input_text)
            self.assertIn("`pbf_overlap_m2`", state_input_text)

            value_domain_text = value_domain_doc.read_text(encoding="utf-8")
            self.assertIn("type: \"Value Domain Audit\"", value_domain_text)
            self.assertIn("Audit count | 6", value_domain_text)
            self.assertIn("| [parcel_current](/layers/parcel_current.md) | `DLBM` |", value_domain_text)
            self.assertIn("`gb_t_21010_2017_land_use_code`", value_domain_text)

            standard_source_text = standard_source_doc.read_text(encoding="utf-8")
            self.assertIn("type: \"Standard Source Registry\"", standard_source_text)
            self.assertIn("Source count | 7", standard_source_text)
            self.assertIn("Officially verified | 1", standard_source_text)
            self.assertIn("Pending official source evidence | 6", standard_source_text)
            self.assertIn("`GB/T 21010-2017`", standard_source_text)
            self.assertIn("`official_fulltext_available`", standard_source_text)
            self.assertIn("openstd.samr.gov.cn", standard_source_text)

            trace_cards_text = trace_cards_doc.read_text(encoding="utf-8")
            self.assertIn("type: \"MMFE Semantic Trace Cards\"", trace_cards_text)
            self.assertIn("Trace cards | 14", trace_cards_text)
            self.assertIn("`field:parcel_current.DLBM`", trace_cards_text)
            self.assertIn("Standard Paths", trace_cards_text)

            ontology_text = ontology_doc.read_text(encoding="utf-8")
            self.assertIn("type: \"MMFE Semantic Ontology\"", ontology_text)
            self.assertIn("Fields | 274", ontology_text)
            self.assertIn("Value domains | 6", ontology_text)
            self.assertIn("Relation types | 7", ontology_text)
            self.assertIn("Optimization objectives | 13", ontology_text)
            self.assertIn("`project_overlaps_permanent_basic_farmland`", ontology_text)
            self.assertIn("[TWM-FARM-001](/rules/twm-farm-001.md)", ontology_text)

            diagnostic_text = diagnostic_doc.read_text(encoding="utf-8")
            self.assertIn("type: \"MMFE Semantic Product Diagnostic\"", diagnostic_text)
            self.assertIn("Status | `validation_ready_with_production_gaps`", diagnostic_text)
            self.assertIn("Validation ready | `True`", diagnostic_text)
            self.assertIn("Production ready | `False`", diagnostic_text)
            self.assertIn("Semantic relations | 728", diagnostic_text)
            self.assertIn("`production_authority`", diagnostic_text)
            self.assertIn("真实权威自然资源数据", diagnostic_text)

            relation_text = relation_doc.read_text(encoding="utf-8")
            self.assertIn("type: \"MMFE Semantic Relation\"", relation_text)
            self.assertIn("semantic_relation_type: \"project_overlaps_permanent_basic_farmland\"", relation_text)
            self.assertIn("触碰永久基本农田", relation_text)
            self.assertIn("| Objective | `pbf_overlap_m2` |", relation_text)


if __name__ == "__main__":
    unittest.main()
