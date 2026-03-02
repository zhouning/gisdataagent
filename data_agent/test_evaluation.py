"""Offline structure tests for ADK evaluation files.

Verifies that all eval sets, configs, and the umbrella eval_agent
are correctly structured — without calling the Gemini API.
"""

import json
import unittest
from pathlib import Path


EVALS_DIR = Path(__file__).parent / "evals"

EXPECTED_PIPELINES = ["optimization", "governance", "general", "planner"]
EXPECTED_CASE_COUNT = {
    "optimization": 3,
    "governance": 3,
    "general": 3,
    "planner": 3,
}


class TestEvalAgentImport(unittest.TestCase):
    """Verify the umbrella eval_agent module loads correctly."""

    def test_eval_agent_importable(self):
        from data_agent.evals.agent import root_agent
        self.assertEqual(root_agent.name, "EvalUmbrella")

    def test_eval_agent_has_all_pipelines(self):
        from data_agent.evals.agent import root_agent
        names = [a.name for a in root_agent.sub_agents]
        self.assertIn("DataPipeline", names)
        self.assertIn("GovernancePipeline", names)
        self.assertIn("GeneralPipeline", names)
        self.assertIn("Planner", names)

    def test_eval_agent_sub_agent_count(self):
        from data_agent.evals.agent import root_agent
        self.assertEqual(len(root_agent.sub_agents), 4)

    def test_backward_compat_import(self):
        from data_agent.eval_agent import root_agent
        self.assertEqual(root_agent.name, "EvalUmbrella")


class TestEvalDirectoryStructure(unittest.TestCase):
    """Verify the evals/ directory layout is correct."""

    def test_evals_directory_exists(self):
        self.assertTrue(EVALS_DIR.is_dir(), f"{EVALS_DIR} does not exist")

    def test_pipeline_directories_exist(self):
        for name in EXPECTED_PIPELINES:
            d = EVALS_DIR / name
            self.assertTrue(d.is_dir(), f"Missing pipeline dir: {d}")

    def test_fixtures_directory_exists(self):
        self.assertTrue((EVALS_DIR / "fixtures").is_dir())

    def test_sample_parcels_fixture_exists(self):
        fixture = EVALS_DIR / "fixtures" / "sample_parcels.geojson"
        self.assertTrue(fixture.is_file(), f"Missing fixture: {fixture}")


class TestEvalSetFiles(unittest.TestCase):
    """Verify .test.json files are valid EvalSet JSON."""

    def _load_eval_set(self, pipeline: str):
        test_files = sorted((EVALS_DIR / pipeline).glob("*.test.json"))
        self.assertTrue(len(test_files) > 0, f"No .test.json in {pipeline}")
        results = []
        for f in test_files:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            results.append((f.name, data))
        return results

    def test_optimization_eval_set_valid(self):
        for name, data in self._load_eval_set("optimization"):
            self.assertIn("eval_set_id", data, f"{name} missing eval_set_id")
            self.assertIn("eval_cases", data, f"{name} missing eval_cases")
            self.assertEqual(len(data["eval_cases"]), EXPECTED_CASE_COUNT["optimization"])

    def test_governance_eval_set_valid(self):
        for name, data in self._load_eval_set("governance"):
            self.assertIn("eval_set_id", data)
            self.assertEqual(len(data["eval_cases"]), EXPECTED_CASE_COUNT["governance"])

    def test_general_eval_set_valid(self):
        for name, data in self._load_eval_set("general"):
            self.assertIn("eval_set_id", data)
            self.assertEqual(len(data["eval_cases"]), EXPECTED_CASE_COUNT["general"])

    def test_planner_eval_set_valid(self):
        for name, data in self._load_eval_set("planner"):
            self.assertIn("eval_set_id", data)
            self.assertEqual(len(data["eval_cases"]), EXPECTED_CASE_COUNT["planner"])

    def test_total_eval_case_count(self):
        total = 0
        for pipeline in EXPECTED_PIPELINES:
            for _, data in self._load_eval_set(pipeline):
                total += len(data["eval_cases"])
        self.assertEqual(total, 12)


class TestEvalCaseStructure(unittest.TestCase):
    """Verify each eval case has required fields."""

    def test_all_cases_have_required_fields(self):
        for pipeline in EXPECTED_PIPELINES:
            test_files = sorted((EVALS_DIR / pipeline).glob("*.test.json"))
            for tf in test_files:
                with open(tf, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                for case in data["eval_cases"]:
                    self.assertIn("eval_id", case, f"Missing eval_id in {tf.name}")
                    self.assertIn("conversation", case, f"Missing conversation in {tf.name}")
                    self.assertTrue(len(case["conversation"]) > 0,
                                    f"Empty conversation in {tf.name}:{case['eval_id']}")
                    inv = case["conversation"][0]
                    self.assertIn("user_content", inv,
                                  f"Missing user_content in {tf.name}:{case['eval_id']}")
                    self.assertIn("final_response", inv,
                                  f"Missing final_response in {tf.name}:{case['eval_id']}")

    def test_all_cases_have_tool_uses(self):
        for pipeline in EXPECTED_PIPELINES:
            test_files = sorted((EVALS_DIR / pipeline).glob("*.test.json"))
            for tf in test_files:
                with open(tf, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                for case in data["eval_cases"]:
                    inv = case["conversation"][0]
                    idata = inv.get("intermediate_data", {})
                    tool_uses = idata.get("tool_uses", [])
                    self.assertTrue(len(tool_uses) > 0,
                                    f"No tool_uses in {tf.name}:{case['eval_id']}")


class TestConfigFiles(unittest.TestCase):
    """Verify test_config.json files are valid."""

    def test_all_pipelines_have_config(self):
        for pipeline in EXPECTED_PIPELINES:
            config_path = EVALS_DIR / pipeline / "test_config.json"
            self.assertTrue(config_path.is_file(), f"Missing config: {config_path}")

    def test_configs_have_criteria(self):
        for pipeline in EXPECTED_PIPELINES:
            config_path = EVALS_DIR / pipeline / "test_config.json"
            with open(config_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertIn("criteria", data, f"No criteria in {pipeline}/test_config.json")
            self.assertTrue(len(data["criteria"]) > 0,
                            f"Empty criteria in {pipeline}/test_config.json")

    def test_optimization_has_trajectory_and_rubric(self):
        with open(EVALS_DIR / "optimization" / "test_config.json", encoding="utf-8") as f:
            data = json.load(f)
        criteria = data["criteria"]
        self.assertIn("tool_trajectory_avg_score", criteria)
        self.assertIn("rubric_based_tool_use_quality_v1", criteria)
        self.assertIn("rubric_based_final_response_quality_v1", criteria)

    def test_governance_has_hallucination_check(self):
        with open(EVALS_DIR / "governance" / "test_config.json", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("hallucinations_v1", data["criteria"])

    def test_general_has_safety_check(self):
        with open(EVALS_DIR / "general" / "test_config.json", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("safety_v1", data["criteria"])

    def test_planner_has_rubric_based(self):
        with open(EVALS_DIR / "planner" / "test_config.json", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("rubric_based_tool_use_quality_v1", data["criteria"])


class TestFixtureData(unittest.TestCase):
    """Verify test fixture data quality."""

    def test_sample_parcels_is_valid_geojson(self):
        fixture = EVALS_DIR / "fixtures" / "sample_parcels.geojson"
        with open(fixture, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["type"], "FeatureCollection")
        self.assertEqual(len(data["features"]), 10)

    def test_sample_parcels_has_required_fields(self):
        fixture = EVALS_DIR / "fixtures" / "sample_parcels.geojson"
        with open(fixture, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        required_fields = {"DLBM", "SLOPE", "AREA", "TBMJ"}
        for feat in data["features"]:
            props = set(feat["properties"].keys())
            self.assertTrue(required_fields.issubset(props),
                            f"Feature {feat['properties'].get('OBJECTID')} missing fields")

    def test_sample_parcels_has_mixed_land_types(self):
        fixture = EVALS_DIR / "fixtures" / "sample_parcels.geojson"
        with open(fixture, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        dlbm_set = {f["properties"]["DLBM"] for f in data["features"]}
        # Should have both farmland (01xx) and forest (03xx)
        has_farmland = any(d.startswith("01") for d in dlbm_set)
        has_forest = any(d.startswith("03") for d in dlbm_set)
        self.assertTrue(has_farmland, "No farmland types found")
        self.assertTrue(has_forest, "No forest types found")


if __name__ == "__main__":
    unittest.main()
