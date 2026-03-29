"""Tests for skill output schema validation."""
import unittest


class TestSkillOutputSchemas(unittest.TestCase):

    def test_list_schemas(self):
        from data_agent.skill_output_schemas import list_schemas
        schemas = list_schemas()
        self.assertIsInstance(schemas, list)
        names = [s["name"] for s in schemas]
        # May be empty if pydantic not installed
        if names:
            self.assertIn("quality_report", names)
            self.assertIn("generator", names)

    def test_validate_quality_report_valid(self):
        from data_agent.skill_output_schemas import validate_skill_output, PYDANTIC_AVAILABLE
        if not PYDANTIC_AVAILABLE:
            self.skipTest("pydantic not installed")
        output = {
            "verdict": "pass",
            "pass_rate": 0.95,
            "findings": [{"dimension": "completeness", "severity": "pass", "message": "All fields present"}],
            "recommendations": ["Consider adding CRS metadata"],
            "summary": "Data quality check passed"
        }
        result = validate_skill_output(output, "quality_report")
        self.assertTrue(result["valid"])
        self.assertIn("verdict", result["validated"])

    def test_validate_quality_report_invalid(self):
        from data_agent.skill_output_schemas import validate_skill_output, PYDANTIC_AVAILABLE
        if not PYDANTIC_AVAILABLE:
            self.skipTest("pydantic not installed")
        output = {"verdict": "maybe", "pass_rate": 2.0}  # invalid verdict and pass_rate
        result = validate_skill_output(output, "quality_report")
        self.assertFalse(result["valid"])
        self.assertIn("errors", result)
        self.assertTrue(len(result["errors"]) > 0)

    def test_validate_generator_valid(self):
        from data_agent.skill_output_schemas import validate_skill_output, PYDANTIC_AVAILABLE
        if not PYDANTIC_AVAILABLE:
            self.skipTest("pydantic not installed")
        output = {
            "generated_files": ["/uploads/user1/output.geojson"],
            "parameters_used": {"buffer_distance": 100},
            "quality_metrics": {"feature_count": 42},
            "summary": "Generated buffer zones"
        }
        result = validate_skill_output(output, "generator")
        self.assertTrue(result["valid"])

    def test_validate_reviewer_valid(self):
        from data_agent.skill_output_schemas import validate_skill_output, PYDANTIC_AVAILABLE
        if not PYDANTIC_AVAILABLE:
            self.skipTest("pydantic not installed")
        output = {
            "verdict": "approved",
            "score": 85.0,
            "issues": [{"type": "warning", "msg": "Missing CRS"}],
            "recommendations": ["Add EPSG:4326 CRS"],
            "reviewed_items": 10
        }
        result = validate_skill_output(output, "reviewer")
        self.assertTrue(result["valid"])

    def test_validate_unknown_schema(self):
        from data_agent.skill_output_schemas import validate_skill_output
        result = validate_skill_output({"foo": "bar"}, "nonexistent_schema")
        self.assertTrue(result.get("valid"))
        self.assertTrue(result.get("skipped"))

    def test_try_validate_output_none_schema(self):
        from data_agent.skill_output_schemas import try_validate_output
        output = {"foo": "bar"}
        result = try_validate_output(output, None)
        self.assertEqual(result, output)

    def test_try_validate_output_non_dict(self):
        from data_agent.skill_output_schemas import try_validate_output
        result = try_validate_output("just a string", "quality_report")
        self.assertEqual(result, "just a string")

    def test_pipeline_step_valid(self):
        from data_agent.skill_output_schemas import validate_skill_output, PYDANTIC_AVAILABLE
        if not PYDANTIC_AVAILABLE:
            self.skipTest("pydantic not installed")
        output = {
            "step_name": "buffer_analysis",
            "status": "success",
            "output_files": ["/tmp/buffer.shp"],
            "metrics": {"processing_time": 1.2},
            "duration_seconds": 1.2
        }
        result = validate_skill_output(output, "pipeline_step")
        self.assertTrue(result["valid"])


if __name__ == "__main__":
    unittest.main()
