"""Tests for grid_anonymize_pg (PG direct) + verify_anonymization + k/DP features.

Uses a fully mocked SQLAlchemy engine to avoid DB dependency in CI.
For real DB integration testing, see scripts/declassify_cq_dltb_e2e.py.

Note: grid_anonymize.py uses deferred imports, so patch at ``data_agent.db_engine.get_engine``
not at ``data_agent.db_engine.get_engine``.
"""

import json
from unittest.mock import MagicMock, patch

import pytest


_PATCH_TARGET = "data_agent.db_engine.get_engine"


# ---------------------------------------------------------------------------
# Helpers for mocking engine.connect() context manager
# ---------------------------------------------------------------------------

def _mock_engine(execute_side_effects):
    """Build a mock engine whose .connect() returns a conn whose .execute()
    yields the given side effects in order.

    side effects are tuples: ("fetchone", row) | ("scalar", val)
                           | ("fetchall", rows) | ("execute_ok", None)
    """
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    engine.connect.return_value.__exit__.return_value = False

    results = []
    for kind, payload in execute_side_effects:
        r = MagicMock()
        if kind == "fetchone":
            r.fetchone.return_value = payload
        elif kind == "scalar":
            r.scalar.return_value = payload
        elif kind == "fetchall":
            r.fetchall.return_value = payload
        elif kind == "execute_ok":
            pass
        elif kind == "rowcount":
            r.rowcount = payload
        results.append(r)
    conn.execute.side_effect = results
    conn.commit = MagicMock()
    return engine, conn


# ---------------------------------------------------------------------------
# Test grid_anonymize_pg
# ---------------------------------------------------------------------------

class TestGridAnonymizePG:
    def test_missing_geometry_column_errors(self):
        from data_agent.grid_anonymize import grid_anonymize_pg

        engine, _ = _mock_engine([
            ("fetchone", None),  # geometry_columns lookup returns None
        ])
        with patch("data_agent.db_engine.get_engine", return_value=engine):
            result = grid_anonymize_pg(
                source_table="nonexistent",
                output_table="out",
                level="L3",
            )
        assert result["status"] == "error"
        assert "geometry_columns" in result["message"]

    def test_unknown_level_rejected(self):
        from data_agent.grid_anonymize import grid_anonymize_pg
        result = grid_anonymize_pg(
            source_table="cq_dltb",
            output_table="out",
            level="L99",
        )
        assert result["status"] == "error"
        assert "Unknown level" in result["message"]

    def test_db_unavailable(self):
        from data_agent.grid_anonymize import grid_anonymize_pg
        with patch("data_agent.db_engine.get_engine", return_value=None):
            result = grid_anonymize_pg(
                source_table="cq_dltb",
                output_table="out",
                level="L2",
            )
        assert result["status"] == "error"
        assert "unavailable" in result["message"].lower()

    def test_dry_run_returns_plan(self):
        from data_agent.grid_anonymize import grid_anonymize_pg

        engine, _ = _mock_engine([
            ("fetchone", ("shape", 4610)),       # geometry_columns
            ("fetchall", [("bsm", "numeric"),
                          ("dlmc", "character varying"),
                          ("qsdwmc", "character varying"),
                          ("tbmj", "numeric")]), # info schema
            ("fetchone", (35608189.0, 3276508.0, 35610797.0, 3281156.0)),  # bbox
        ])
        with patch("data_agent.db_engine.get_engine", return_value=engine):
            result = grid_anonymize_pg(
                source_table="cq_dltb",
                output_table="cq_dltb_out",
                level="L3",
                keep_attrs=["dlmc", "tbmj"],
                agg_strategy="mode",
                k_anonymity=5,
                dry_run=True,
            )

        assert result["status"] == "dry_run"
        assert result["level"] == "L3"
        assert result["grid_size_m"] == 250.0
        assert "dlmc" in result["kept_attrs"]
        assert "tbmj" in result["kept_attrs"]
        # Sensitive cols from source detected as stripped (even without user request)
        assert "bsm" in result["stripped_sensitive_fields"]
        assert "qsdwmc" in result["stripped_sensitive_fields"]
        assert result["estimated_grid_count"] > 0
        assert "sql_preview" in result

    def test_dry_run_forced_strip_even_when_requested(self):
        """Even if user asks to keep qsdwmc, it's stripped."""
        from data_agent.grid_anonymize import grid_anonymize_pg

        engine, _ = _mock_engine([
            ("fetchone", ("shape", 4610)),
            ("fetchall", [("bsm", "numeric"), ("qsdwmc", "character varying"),
                          ("dlmc", "character varying")]),
            ("fetchone", (0.0, 0.0, 1000.0, 1000.0)),
        ])
        with patch("data_agent.db_engine.get_engine", return_value=engine):
            result = grid_anonymize_pg(
                source_table="cq_dltb",
                output_table="out",
                keep_attrs=["dlmc", "qsdwmc", "bsm"],  # user tries to keep sensitive
                dry_run=True,
            )

        assert "qsdwmc" in result["stripped_sensitive_fields"]
        assert "bsm" in result["stripped_sensitive_fields"]
        assert "qsdwmc" not in result["kept_attrs"]
        assert "bsm" not in result["kept_attrs"]
        assert "dlmc" in result["kept_attrs"]

    def test_grid_count_cap_enforced(self):
        """Over 5M cells → error, not OOM."""
        from data_agent.grid_anonymize import grid_anonymize_pg

        engine, _ = _mock_engine([
            ("fetchone", ("shape", 4326)),
            ("fetchall", [("dlmc", "text")]),
            # huge bbox → would produce > 5M L1 cells
            ("fetchone", (0.0, 0.0, 100000.0, 100000.0)),
        ])
        with patch("data_agent.db_engine.get_engine", return_value=engine):
            result = grid_anonymize_pg(
                source_table="cq_dltb",
                output_table="out",
                level="L1",
                dry_run=True,
            )
        assert result["status"] == "error"
        assert "too large" in result["message"]

    def test_auto_srid_mapping(self):
        from data_agent.grid_anonymize import grid_anonymize_pg

        engine, _ = _mock_engine([
            ("fetchone", ("shape", 4610)),  # CGCS2000 geographic
            ("fetchall", [("dlmc", "text")]),
            ("fetchone", (0.0, 0.0, 5000.0, 5000.0)),
        ])
        with patch("data_agent.db_engine.get_engine", return_value=engine):
            result = grid_anonymize_pg(
                source_table="cq_dltb",
                output_table="out",
                level="L3",
                dry_run=True,
            )
        assert result["source_srid"] == 4610
        assert result["target_srid"] == 4523  # metric CGCS2000


# ---------------------------------------------------------------------------
# Test verify_anonymization
# ---------------------------------------------------------------------------

class TestVerifyAnonymization:
    def test_field_leakage_detected(self):
        from data_agent.grid_anonymize import verify_anonymization

        # Simulate output that still contains qsdwmc
        engine, _ = _mock_engine([
            ("fetchall", [("grid_id",), ("dlmc",), ("qsdwmc",), ("geom",), ("_k_source_count",)]),
            ("fetchone", ("shape",)),  # src geom col
            ("fetchone", ("geom",)),   # out geom col
            ("scalar", 0.1),           # jaccard
            ("fetchone", (8, 15.5, 0, 100)),  # k stats
            ("fetchone", (2, 10)),  # l diversity
        ])
        with patch("data_agent.db_engine.get_engine", return_value=engine):
            result = verify_anonymization(
                source_table="cq_dltb",
                output_table="cq_dltb_leaky",
            )

        assert result["status"] == "ok"
        leakage = result["tests"]["field_leakage"]
        assert leakage["score"] > 0
        assert "qsdwmc" in leakage["leaked_fields"]

    def test_safe_output_low_risk(self):
        from data_agent.grid_anonymize import verify_anonymization

        engine, _ = _mock_engine([
            ("fetchall", [("grid_id",), ("dlmc",), ("tbmj",), ("geom",), ("_k_source_count",)]),
            ("fetchone", ("shape",)),
            ("fetchone", ("geom",)),
            ("scalar", 0.05),
            ("fetchone", (10, 25.3, 0, 500)),
            ("fetchone", (1, 10)),  # low l-diversity risk
        ])
        with patch("data_agent.db_engine.get_engine", return_value=engine):
            result = verify_anonymization(
                source_table="cq_dltb",
                output_table="cq_dltb_grid_L3",
            )

        assert result["overall_risk_score"] < 30
        assert "安全" in result["verdict"] or "可接受" in result["verdict"]

    def test_high_reconstruction_risk(self):
        from data_agent.grid_anonymize import verify_anonymization

        engine, _ = _mock_engine([
            ("fetchall", [("grid_id",), ("dlmc",), ("geom",), ("_k_source_count",)]),
            ("fetchone", ("shape",)),
            ("fetchone", ("geom",)),
            ("scalar", 0.95),                 # near-perfect overlap = high risk
            ("fetchone", (3, 4.2, 150, 200)),  # many k<5 violations
            ("fetchone", (8, 10)),
        ])
        with patch("data_agent.db_engine.get_engine", return_value=engine):
            result = verify_anonymization(
                source_table="cq_dltb",
                output_table="cq_dltb_bad",
            )

        assert result["tests"]["geometry_reconstruction"]["score"] > 80
        assert result["tests"]["k_anonymity"]["score"] > 50
        assert result["overall_risk_score"] > 40


# ---------------------------------------------------------------------------
# Test Laplace noise helper
# ---------------------------------------------------------------------------

class TestLaplaceNoise:
    def test_reproducible_with_seed(self):
        import numpy as np
        from data_agent.grid_anonymize import _apply_laplace_noise

        values = np.array([100.0, 200.0, 300.0])
        r1 = _apply_laplace_noise(values, epsilon=1.0, sensitivity=1.0, seed=42)
        r2 = _apply_laplace_noise(values, epsilon=1.0, sensitivity=1.0, seed=42)
        assert np.allclose(r1, r2)

    def test_smaller_epsilon_more_noise(self):
        import numpy as np
        from data_agent.grid_anonymize import _apply_laplace_noise

        values = np.array([100.0] * 1000)
        r_strong = _apply_laplace_noise(values, epsilon=0.1, sensitivity=1.0, seed=1)
        r_weak = _apply_laplace_noise(values, epsilon=10.0, sensitivity=1.0, seed=1)
        assert r_strong.std() > r_weak.std()


# ---------------------------------------------------------------------------
# Test toolset wrappers return parseable JSON
# ---------------------------------------------------------------------------

class TestToolsetWrappers:
    def test_grid_anonymize_pg_wrapper_produces_json(self):
        from data_agent.toolsets.governance_tools import grid_anonymize_pg as wrapper

        engine, _ = _mock_engine([
            ("fetchone", ("shape", 4610)),
            ("fetchall", [("dlmc", "text"), ("tbmj", "numeric")]),
            ("fetchone", (0.0, 0.0, 1000.0, 1000.0)),
        ])
        with patch("data_agent.db_engine.get_engine", return_value=engine):
            result_str = wrapper(
                source_table="cq_dltb",
                output_table="test_out",
                level="L3",
                keep_attrs="dlmc,tbmj",
                dry_run=True,
            )
        assert isinstance(result_str, str)
        result = json.loads(result_str)
        assert result["status"] == "dry_run"

    def test_verify_wrapper_produces_json(self):
        from data_agent.toolsets.governance_tools import verify_anonymization as wrapper

        engine, _ = _mock_engine([
            ("fetchall", [("grid_id",), ("dlmc",), ("geom",)]),
            ("fetchone", ("shape",)),
            ("fetchone", ("geom",)),
            ("scalar", 0.2),
            ("fetchone", (7, 10.0, 0, 100)),
            ("fetchone", (3, 10)),
        ])
        with patch("data_agent.db_engine.get_engine", return_value=engine):
            result_str = wrapper(
                source_table="cq_dltb",
                output_table="cq_dltb_out",
                sample_size=50,
            )
        result = json.loads(result_str)
        assert result["status"] == "ok"
        assert "overall_risk_score" in result
