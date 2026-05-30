"""Unit tests for sql_distinct_guard."""
from __future__ import annotations

from data_agent.sql_distinct_guard import detect_join_multiplication, format_retry_hint


def test_simple_count_without_distinct_with_spatial_join_fires():
    sql = """
    SELECT l.dlmc, COUNT(b.id) AS cnt
    FROM cq_land_use l JOIN cq_buildings b ON ST_Contains(l.geom, b.geom)
    GROUP BY l.dlmc
    """
    findings = detect_join_multiplication(sql)
    assert findings, "should flag COUNT without DISTINCT on spatial JOIN"
    assert findings[0][0] == "high"


def test_count_distinct_on_spatial_join_passes():
    sql = """
    SELECT l.dlmc, COUNT(DISTINCT b.id) AS cnt
    FROM cq_land_use l JOIN cq_buildings b ON ST_Contains(l.geom, b.geom)
    GROUP BY l.dlmc
    """
    findings = detect_join_multiplication(sql)
    # COUNT has DISTINCT; AVG also without distinct but AVG is OK
    # Conservative: this should still pass without HIGH findings
    high_findings = [f for f in findings if f[0] == "high"]
    assert not high_findings


def test_no_join_no_finding():
    sql = "SELECT COUNT(*) FROM cq_buildings WHERE floor > 10"
    findings = detect_join_multiplication(sql)
    assert not findings


def test_non_spatial_join_no_finding():
    sql = """
    SELECT a.x, COUNT(b.y) FROM a JOIN b ON a.id = b.fk GROUP BY a.x
    """
    findings = detect_join_multiplication(sql)
    assert not findings  # not a spatial join


def test_empty_sql():
    assert detect_join_multiplication("") == []
    assert detect_join_multiplication(None) == []


def test_unparseable_sql():
    findings = detect_join_multiplication("THIS IS NOT SQL ###")
    assert findings == []  # graceful degrade


def test_format_retry_hint():
    findings = [("high", "msg1"), ("medium", "msg2")]
    hint = format_retry_hint(findings)
    assert "HIGH" in hint
    assert "MEDIUM" in hint
    assert "msg1" in hint
    assert "msg2" in hint


def test_format_empty():
    assert format_retry_hint([]) == ""


if __name__ == "__main__":
    import pytest, sys
    sys.exit(pytest.main([__file__, "-v"]))
