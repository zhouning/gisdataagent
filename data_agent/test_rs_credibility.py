"""Tests for RS Phase 3 — Intelligent Credibility (v22.0)."""
import pytest

from data_agent.rs_credibility import (
    check_spatial_constraints,
    cross_validate_results,
    run_debate,
    validate_generated_code,
    FactCheckResult,
)


# ---------------------------------------------------------------------------
# Spatial Constraint Checks
# ---------------------------------------------------------------------------

def test_check_negative_area():
    claims = [{"text": "面积为 -50 km²", "type": "area", "value": -50}]
    results = check_spatial_constraints(claims)
    assert len(results) == 1
    assert not results[0].verified


def test_check_valid_area():
    claims = [{"text": "面积 120 km²", "type": "area", "value": 120}]
    results = check_spatial_constraints(claims)
    assert results[0].verified


def test_check_percentage_out_of_range():
    claims = [{"text": "覆盖率 150%", "type": "percentage", "value": 150}]
    results = check_spatial_constraints(claims)
    assert not results[0].verified


def test_check_valid_percentage():
    claims = [{"text": "耕地占 35%", "type": "percentage", "value": 35}]
    results = check_spatial_constraints(claims)
    assert results[0].verified


def test_check_coordinate_valid():
    claims = [{"text": "位于 (30, 120)", "type": "coordinate", "value": (30, 120)}]
    results = check_spatial_constraints(claims)
    assert results[0].verified


def test_check_coordinate_invalid():
    claims = [{"text": "位于 (95, 200)", "type": "coordinate", "value": (95, 200)}]
    results = check_spatial_constraints(claims)
    assert not results[0].verified


def test_check_multiple_claims():
    claims = [
        {"text": "面积 50 km²", "type": "area", "value": 50},
        {"text": "占比 30%", "type": "percentage", "value": 30},
        {"text": "位于 (31, 121)", "type": "coordinate", "value": (31, 121)},
    ]
    results = check_spatial_constraints(claims)
    assert len(results) == 3
    assert all(r.verified for r in results)


# ---------------------------------------------------------------------------
# Cross Validation
# ---------------------------------------------------------------------------

def test_cross_validate_agreement():
    results = [
        {"changed_pct": 25.0, "accuracy": 0.85},
        {"changed_pct": 27.0, "accuracy": 0.82},
    ]
    cv = cross_validate_results(results)
    assert cv["agreement_rate"] > 50


def test_cross_validate_disagreement():
    results = [
        {"changed_pct": 10.0, "score": 0.9},
        {"changed_pct": 80.0, "score": 0.2},
    ]
    cv = cross_validate_results(results)
    assert len(cv["inconsistencies"]) > 0


def test_cross_validate_single():
    cv = cross_validate_results([{"x": 1}])
    assert cv["agreement_rate"] == 100.0


# ---------------------------------------------------------------------------
# Multi-Agent Debate
# ---------------------------------------------------------------------------

def test_debate_confirmed():
    analysis = [
        {"method": "NDVI差异", "changed_area_pct": 25.0},
        {"method": "分类后比较", "changed_area_pct": 30.0},
    ]
    fact_checks = [
        {"verified": True, "claim": "面积合理"},
        {"verified": True, "claim": "坐标正确"},
    ]
    result = run_debate("土地利用发生显著变化", analysis, fact_checks)
    assert result.verdict == "confirmed"
    assert result.confidence > 0.5


def test_debate_refuted():
    analysis = [
        {"method": "A", "changed_area_pct": 0, "confidence": 0.1},
        {"method": "B", "changed_area_pct": 0, "confidence": 0.2},
    ]
    fact_checks = [
        {"verified": False, "explanation": "数据范围错误"},
        {"verified": False, "explanation": "时间不匹配"},
    ]
    result = run_debate("发生大规模变化", analysis, fact_checks)
    assert result.verdict in ("refuted", "revised")


def test_debate_empty():
    result = run_debate("测试结论", [], [])
    assert result.verdict == "confirmed"  # no evidence = default


def test_debate_to_dict():
    result = run_debate("test", [{"method": "x", "changed_area_pct": 10}])
    d = result.to_dict()
    assert "verdict" in d
    assert "confidence" in d


# ---------------------------------------------------------------------------
# Code Validation
# ---------------------------------------------------------------------------

def test_validate_safe_code():
    code = "import numpy as np\nresult = np.mean([1,2,3])"
    result = validate_generated_code(code)
    assert result["valid"]
    assert result["line_count"] == 2


def test_validate_blocked_os_system():
    code = "import os\nos.system('rm -rf /')"
    result = validate_generated_code(code)
    assert not result["valid"]
    assert len(result["issues"]) > 0


def test_validate_blocked_subprocess():
    code = "import subprocess\nsubprocess.run(['ls'])"
    result = validate_generated_code(code)
    assert not result["valid"]


def test_validate_blocked_eval():
    code = "x = eval('1+1')"
    result = validate_generated_code(code)
    assert not result["valid"]


def test_validate_blocked_exec():
    code = "exec('print(1)')"
    result = validate_generated_code(code)
    assert not result["valid"]
