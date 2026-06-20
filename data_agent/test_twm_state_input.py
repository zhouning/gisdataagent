"""Tests for deriving TWM state-input artifacts from MMFE semantic products."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


MMFE_DIR = Path("data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion")
SCRIPT = Path("scripts/build_twm_state_input_from_mmfe.py")


class TestTwmStateInput(unittest.TestCase):
    def test_builds_state_input_from_twm_mmfe_product(self):
        from data_agent.fusion.twm_state_input import (
            TWM_STATE_INPUT_SCHEMA,
            build_twm_state_input_from_semantic_product,
            validate_twm_state_input,
        )

        manifest = json.loads((MMFE_DIR / "twm_mmfe_semantic_product.json").read_text(encoding="utf-8"))
        relations = _read_csv(MMFE_DIR / "twm_mmfe_semantic_relations.csv")
        contract = json.loads((MMFE_DIR / "twm_state_input_contract.json").read_text(encoding="utf-8"))

        payload = build_twm_state_input_from_semantic_product(
            manifest,
            semantic_relations=relations,
            input_contract=contract,
            timestamp="2026-06-17T00:00:00+00:00",
        )
        validation = validate_twm_state_input(payload)

        self.assertTrue(validation["valid"], validation["errors"])
        self.assertEqual(payload["schema"], TWM_STATE_INPUT_SCHEMA)
        self.assertEqual(payload["source_product"]["product_id"], manifest["product_id"])
        self.assertEqual(len(payload["object_role_registry"]), 9)
        self.assertEqual(payload["semantic_relation_summary"]["total_relation_count"], 728)
        self.assertEqual(payload["semantic_relation_summary"]["registered_relation_type_count"], 7)
        self.assertEqual(
            payload["semantic_relation_summary"]["relation_type_distribution"][
                "project_overlaps_permanent_basic_farmland"
            ],
            39,
        )
        self.assertEqual(
            payload["semantic_relation_summary"]["relation_type_distribution"][
                "project_overlaps_ecological_redline"
            ],
            28,
        )
        self.assertEqual(
            payload["semantic_relation_summary"]["relation_type_distribution"][
                "project_observed_by_remote_sensing_tile"
            ],
            71,
        )

        project_binding = _find_role(payload["object_role_registry"], "synthetic_projects")
        self.assertEqual(project_binding["standard_role"], "project")
        self.assertEqual(project_binding["twm_binding"]["object_id"], "XMDM")

        pbf_component = payload["state_components"]["hard_constraints"]
        self.assertEqual(pbf_component["relation_count"], 67)
        self.assertTrue(pbf_component["hard_constraint"])
        self.assertIn("pbf_overlap_m2", pbf_component["objective_ids"])
        self.assertIn("eco_overlap_m2", pbf_component["objective_ids"])
        self.assertIn("TWM-FARM-001", pbf_component["rule_ids"])
        self.assertIn("TWM-ECO-001", pbf_component["rule_ids"])

        dynamic_component = payload["state_components"]["dynamic_transitions"]
        self.assertEqual(dynamic_component["relation_count"], 78)
        self.assertIn("annual_change_of_parcel", dynamic_component["relation_types"])

        rs_component = payload["state_components"]["remote_sensing_evidence"]
        self.assertEqual(rs_component["relation_count"], 71)
        self.assertIn("robustness_score", rs_component["objective_ids"])

        objective_bindings = {
            item["objective_id"]: item
            for item in payload["optimization_interface"]["objective_bindings"]
        }
        self.assertTrue(objective_bindings["pbf_overlap_m2"]["hard_constraint"])
        self.assertEqual(objective_bindings["pbf_overlap_m2"]["relation_count"], 39)
        self.assertEqual(objective_bindings["eco_overlap_m2"]["relation_count"], 28)
        self.assertEqual(objective_bindings["planning_conflict_m2"]["relation_count"], 151)
        self.assertEqual(objective_bindings["farmland_gain_m2"]["relation_count"], 78)
        self.assertTrue(payload["production_policy"]["contains_synthetic_sources"])
        self.assertTrue(payload["production_policy"]["not_for_production"])
        self.assertEqual(payload["standard_readiness"]["missing_value_domains"], {})
        self.assertIn(
            "gb_t_21010_2017_land_use_code",
            payload["standard_readiness"]["loaded_value_domains"],
        )
        self.assertEqual(payload["standard_readiness"]["value_domain_audit"]["audit_count"], 6)
        self.assertEqual(payload["standard_readiness"]["value_domain_audit"]["status_distribution"], {"valid": 6})
        self.assertEqual(payload["standard_readiness"]["standard_sources"]["source_count"], 7)
        self.assertEqual(payload["standard_readiness"]["standard_sources"]["official_verified_count"], 1)
        self.assertEqual(payload["standard_readiness"]["standard_sources"]["pending_official_source_count"], 6)
        self.assertIn(
            "GB/T 21010-2017",
            payload["standard_readiness"]["standard_sources"]["officially_verified_identifiers"],
        )

    def test_does_not_require_synthetic_filenames_for_roles(self):
        from data_agent.fusion.twm_state_input import build_twm_state_input_from_semantic_product

        manifest = {
            "product_type": "semantic_fusion_product",
            "version": "1.1",
            "product_id": "sfp-state-input-generic",
            "quality": {"score": 0.9, "warnings": []},
            "mmfe_bundle": {
                "optimization_summary": {
                    "objectives": [
                        {
                            "objective_id": "pbf_overlap_m2",
                            "objective_name_zh": "永久基本农田占用最小化",
                            "hard_constraint": True,
                        }
                    ],
                    "hard_constraint_objectives": ["pbf_overlap_m2"],
                },
            },
        }
        contract = {
            "role_bindings": [
                {
                    "role": "authoritative_pbf_2026",
                    "standard_role": "pbf",
                    "object_type": "control_boundary",
                    "source_path": "pbf_authoritative.geojson",
                    "twm_binding": {"object_id": "PBF_ID"},
                },
                {
                    "role": "project_cases",
                    "standard_role": "project",
                    "object_type": "project",
                    "source_path": "projects.geojson",
                    "twm_binding": {"object_id": "PROJECT_ID"},
                },
            ]
        }
        relations = [
            {
                "relation_id": "REL-001",
                "semantic_relation_type": "project_overlaps_permanent_basic_farmland",
                "source_object_type": "project",
                "source_object_id": "PRJ-001",
                "target_object_type": "permanent_basic_farmland",
                "target_object_id": "PBF-001",
                "target_standard_role": "pbf",
                "twm_usage": "hard_constraint_pbf_overlap",
                "objective_id": "pbf_overlap_m2",
                "rule_id": "TWM-FARM-001",
                "metric_name": "overlap_area_m2",
                "metric_value": "100.5",
                "requires_rule_review": "true",
            }
        ]

        payload = build_twm_state_input_from_semantic_product(
            manifest,
            semantic_relations=relations,
            input_contract=contract,
        )

        self.assertEqual(len(payload["object_role_registry"]), 2)
        self.assertEqual(payload["object_role_registry"][0]["role"], "authoritative_pbf_2026")
        self.assertFalse(payload["production_policy"]["contains_synthetic_sources"])
        self.assertEqual(payload["state_components"]["hard_constraints"]["relation_count"], 1)
        self.assertEqual(
            payload["optimization_interface"]["objective_bindings"][0]["relation_types"],
            ["project_overlaps_permanent_basic_farmland"],
        )

    def test_validation_rejects_role_type_registry_break(self):
        from data_agent.fusion.twm_state_input import (
            build_twm_state_input_from_semantic_product,
            validate_twm_state_input,
        )

        manifest = json.loads((MMFE_DIR / "twm_mmfe_semantic_product.json").read_text(encoding="utf-8"))
        relations = _read_csv(MMFE_DIR / "twm_mmfe_semantic_relations.csv")
        contract = json.loads((MMFE_DIR / "twm_state_input_contract.json").read_text(encoding="utf-8"))
        payload = build_twm_state_input_from_semantic_product(
            manifest,
            semantic_relations=relations,
            input_contract=contract,
        )
        payload["canonical_object_type_registry"] = [
            row for row in payload["canonical_object_type_registry"] if row.get("object_type") != "project"
        ]

        validation = validate_twm_state_input(payload)

        self.assertFalse(validation["valid"])
        self.assertTrue(
            any("object_type is not in canonical_object_type_registry: project" in error for error in validation["errors"]),
            validation["errors"],
        )

    def test_validation_rejects_unknown_hard_constraint_references(self):
        from data_agent.fusion.twm_state_input import (
            build_twm_state_input_from_semantic_product,
            validate_twm_state_input,
        )

        manifest = json.loads((MMFE_DIR / "twm_mmfe_semantic_product.json").read_text(encoding="utf-8"))
        relations = _read_csv(MMFE_DIR / "twm_mmfe_semantic_relations.csv")
        contract = json.loads((MMFE_DIR / "twm_state_input_contract.json").read_text(encoding="utf-8"))
        payload = build_twm_state_input_from_semantic_product(
            manifest,
            semantic_relations=relations,
            input_contract=contract,
        )
        hard_constraints = payload["state_components"]["hard_constraints"]
        hard_constraints["rule_ids"] = list(hard_constraints["rule_ids"]) + ["TWM-MISSING-999"]
        hard_constraints["objective_ids"] = list(hard_constraints["objective_ids"]) + ["missing_overlap_m2"]

        validation = validate_twm_state_input(payload)

        self.assertFalse(validation["valid"])
        self.assertTrue(
            any("unknown semantic relation rule_id: TWM-MISSING-999" in error for error in validation["errors"]),
            validation["errors"],
        )
        self.assertTrue(
            any("unknown objective_id: missing_overlap_m2" in error for error in validation["errors"]),
            validation["errors"],
        )

    def test_script_writes_state_input_sidecar(self):
        self.assertTrue(SCRIPT.exists(), f"missing script: {SCRIPT}")
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "twm_state_input.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--mmfe-dir",
                    str(MMFE_DIR),
                    "--out-path",
                    str(out_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            summary = json.loads(result.stdout)
            self.assertEqual(summary["status"], "ok")
            self.assertTrue(summary["valid"], summary["errors"])
            self.assertEqual(summary["relation_count"], 728)
            self.assertEqual(summary["hard_constraint_relation_count"], 67)
            self.assertEqual(summary["objective_binding_count"], 13)
            self.assertTrue(out_path.exists())
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["semantic_relation_summary"]["total_relation_count"], 728)

    def test_state_input_api_is_exported_through_fusion_engine_proxy(self):
        from data_agent import fusion_engine

        self.assertEqual(fusion_engine.TWM_STATE_INPUT_SCHEMA, "mmfe.twm_state_input.v1")
        payload = fusion_engine.build_twm_state_input_from_semantic_product(
            {
                "product_type": "semantic_fusion_product",
                "product_id": "sfp-proxy-test",
                "mmfe_bundle": {},
            },
            semantic_relations=[],
            input_contract={"role_bindings": []},
        )
        self.assertEqual(payload["source_product"]["product_id"], "sfp-proxy-test")


def _read_csv(path: Path) -> list[dict]:
    import csv

    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _find_role(bindings: list[dict], role: str) -> dict:
    for binding in bindings:
        if binding.get("role") == role:
            return binding
    raise AssertionError(f"role not found: {role}")


if __name__ == "__main__":
    unittest.main()
