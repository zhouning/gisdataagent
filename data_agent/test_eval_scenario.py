"""Tests for eval_scenario module"""
import pytest
from data_agent.eval_scenario import SurveyingQCScenario


def test_surveying_qc_perfect_match():
    scenario = SurveyingQCScenario()
    actual = {"defects": [{"code": "FMT-001"}, {"code": "PRE-002"}]}
    expected = {"defects": [{"code": "FMT-001"}, {"code": "PRE-002"}]}

    metrics = scenario.evaluate(actual, expected)
    assert metrics["defect_precision"] == 1.0
    assert metrics["defect_recall"] == 1.0
    assert metrics["defect_f1"] == 1.0


def test_surveying_qc_partial_match():
    scenario = SurveyingQCScenario()
    actual = {"defects": [{"code": "FMT-001"}, {"code": "FMT-999"}]}
    expected = {"defects": [{"code": "FMT-001"}, {"code": "PRE-002"}]}

    metrics = scenario.evaluate(actual, expected)
    assert metrics["defect_precision"] == 0.5
    assert metrics["defect_recall"] == 0.5
    assert metrics["defect_f1"] == 0.5


def test_surveying_qc_fix_success_rate():
    scenario = SurveyingQCScenario()
    actual = {"defects": [
        {"code": "FMT-001", "fixed": True},
        {"code": "PRE-002", "fixed": False},
    ]}
    expected = {"defects": [
        {"code": "FMT-001", "auto_fixable": True},
        {"code": "PRE-002", "auto_fixable": True},
    ]}

    metrics = scenario.evaluate(actual, expected)
    assert metrics["fix_success_rate"] == 0.5
