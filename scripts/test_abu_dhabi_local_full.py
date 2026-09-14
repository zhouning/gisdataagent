"""Evaluation integrity checks for the full local benchmark orchestration."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.analyze_abu_dhabi_local_full import (
    route_of,
    summarize,
    summarize_model_generated_free_form,
)
from scripts.evaluate_abu_dhabi_local_full import validate_population
from scripts.resume_abu_dhabi_local_full import _validated_completed_run_ids


class FullPopulationTests(unittest.TestCase):
    def test_duplicate_cannot_replace_a_missing_case(self):
        report = {"cases": [{"case_id": "a"}, {"case_id": "a"}]}
        with self.assertRaisesRegex(ValueError, "population mismatch"):
            validate_population(report, ["a", "b"])

    def test_circuit_open_record_is_not_an_attempt(self):
        report = {
            "cases": [
                {"case_id": "a", "failure_reasons": ["benchmark_infrastructure_circuit_open"]}
            ],
            "metrics": {"infrastructure_failure_case_count": 1},
        }
        population = validate_population(report, ["a"])
        self.assertEqual(population["recorded"], 1)
        self.assertFalse(population["all_cases_attempted"])

    def test_failed_answer_still_counts_as_attempted(self):
        report = {
            "cases": [{"case_id": "a", "status": "failed", "failure_reasons": ["status_match"]}],
            "metrics": {"infrastructure_failure_case_count": 0},
        }
        self.assertTrue(validate_population(report, ["a"])["all_cases_attempted"])


class SeparateScoringTests(unittest.TestCase):
    def test_actual_llm_invocation_takes_precedence_over_route_name(self):
        row = {"observed": {"planner": {"llm_invoked": True, "route": "some_fallback"}}}
        self.assertEqual(route_of(row), "llm")

    def test_missing_planner_is_not_a_deterministic_success(self):
        self.assertEqual(route_of({"observed": {"status": "error"}}), "unobserved")

    def test_stale_gold_is_excluded_but_failed_current_gold_is_in_denominator(self):
        def row(status, freshness, equivalent):
            return {
                "has_gold": True,
                "gold_source_status": freshness,
                "expected_status": "ok",
                "status": status,
                "checks": {"gold_result_equivalence_match": equivalent},
                "observed": {"status": "ok" if equivalent else "rejected"},
                "failure_layer": None if status == "passed" else "unexpected_refusal",
            }

        result = summarize(
            [
                row("passed", "current", True),
                row("failed", "current", False),
                row("failed", "gold_stale_source_result", False),
            ]
        )
        self.assertEqual(result["case_count"], 3)
        self.assertEqual(result["gold_case_count"], 3)
        self.assertEqual(result["current_gold_case_count"], 2)
        self.assertEqual(result["gold_equivalent"], 1)

    def test_model_generated_free_form_excludes_deterministic_routes_and_marks_overlap(self):
        def row(*, route, capabilities, split="holdout", status="passed"):
            return {
                "source_key": "liveability",
                "execution_profile": "semantic_ir_experimental",
                "actual_route": route,
                "capabilities": capabilities,
                "split": split,
                "has_gold": True,
                "gold_source_status": "current",
                "expected_status": "ok",
                "status": status,
                "checks": {"gold_result_equivalence_match": status == "passed"},
                "observed": {"status": "ok" if status == "passed" else "error"},
                "failure_layer": None if status == "passed" else "result_equivalence",
            }

        result = summarize_model_generated_free_form(
            [
                row(route="llm", capabilities=["join", "ranking"]),
                row(route="llm", capabilities=["join"], split="validation", status="failed"),
                row(
                    route="deterministic_reviewed_metric_contract",
                    capabilities=["join", "ranking"],
                ),
            ]
        )

        self.assertEqual(result["overall"]["case_count"], 2)
        self.assertTrue(result["definition"]["actual_llm_invocation_only"])
        self.assertTrue(result["definition"]["capability_rows_overlap"])
        self.assertTrue(result["definition"]["cross_profile_overall_is_diagnostic_only"])
        self.assertEqual(result["overall"]["rates"]["contract_pass"]["total"], 2)
        self.assertEqual(
            result["overall"]["rates"]["current_gold_result_equivalence"]["successes"], 1
        )
        self.assertEqual(
            [(item["profile"], item["case_count"]) for item in result["by_profile"]],
            [("semantic_ir_experimental", 2)],
        )
        by_capability = {item["capability"]: item for item in result["by_capability"]}
        self.assertEqual(by_capability["join"]["case_count"], 2)
        self.assertEqual(by_capability["ranking"]["case_count"], 1)
        self.assertEqual(
            [(item["split"], item["case_count"]) for item in result["by_split"]],
            [("holdout", 1), ("validation", 1)],
        )


class ResumeIntegrityTests(unittest.TestCase):
    @staticmethod
    def manifest(report_sha256: str) -> dict:
        return {
            "model": {"name": "qwen"},
            "sources": {
                "liveability": {"case_ids": ["a"]},
                "makani": {"case_ids": ["b"]},
            },
            "runs": {
                "liveability_baseline_sql": {
                    "report_path": "report.json",
                    "sha256": report_sha256,
                    "population": {
                        "expected": 1,
                        "recorded": 1,
                        "unique": 1,
                        "infrastructure_not_attempted": 0,
                        "infrastructure_failures": 0,
                        "all_cases_attempted": True,
                    },
                }
            },
        }

    def test_only_verified_complete_report_is_skipped(self):
        from scripts.evaluate_abu_dhabi_local_full import sha256, write_json

        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            report = {
                "benchmark": {"execution_profile": "baseline_sql"},
                "model": {"requested": "qwen"},
                "metrics": {"infrastructure_failure_case_count": 0},
                "cases": [{"case_id": "a", "failure_reasons": []}],
            }
            path = output / "report.json"
            write_json(path, report)
            completed = _validated_completed_run_ids(
                self.manifest(sha256(path)), output=output
            )
            self.assertEqual(completed, {"liveability_baseline_sql"})

    def test_changed_registered_report_is_rejected(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / "report.json").write_text("{}\n")
            with self.assertRaisesRegex(ValueError, "changed or is missing"):
                _validated_completed_run_ids(self.manifest("wrong"), output=output)

    def test_single_source_profile_selection_is_preserved_on_resume(self):
        from scripts.evaluate_abu_dhabi_local_full import sha256, write_json

        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            report = {
                "benchmark": {"execution_profile": "semantic_ir_experimental"},
                "model": {"requested": "qwen"},
                "metrics": {"infrastructure_failure_case_count": 0},
                "cases": [{"case_id": "a", "failure_reasons": []}],
            }
            path = output / "report.json"
            write_json(path, report)
            manifest = self.manifest(sha256(path))
            manifest["sources"] = {"liveability": manifest["sources"]["liveability"]}
            manifest["selection"] = {
                "sources": ["liveability"],
                "profiles": ["semantic_ir_experimental"],
            }
            manifest["runs"] = {
                "liveability_semantic_ir_experimental": {
                    **manifest["runs"]["liveability_baseline_sql"],
                    "population": {
                        "expected": 1,
                        "recorded": 1,
                        "unique": 1,
                        "infrastructure_not_attempted": 0,
                        "infrastructure_failures": 0,
                        "all_cases_attempted": True,
                    },
                }
            }

            completed = _validated_completed_run_ids(manifest, output=output)
            self.assertEqual(completed, {"liveability_semantic_ir_experimental"})


if __name__ == "__main__":
    unittest.main()
