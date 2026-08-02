"""Focused contracts for Spark/Flink Iceberg interoperability."""

from __future__ import annotations

import pytest

from scripts.certify_chongqing_osm_flink_iceberg_interop import (
    DEFAULT_SOURCE,
    FLINK_AWS,
    FLINK_ICEBERG,
    HADOOP_CLIENT_API,
    HADOOP_CLIENT_RUNTIME,
    POSTGRES_JDBC,
    PREFIX_RE,
    build_interop_plan,
    verify_artifact,
)


def test_interop_plan_is_real_deterministic_and_reconciled() -> None:
    first = build_interop_plan(DEFAULT_SOURCE, commit_tag="run_123")
    second = build_interop_plan(DEFAULT_SOURCE, commit_tag="run_123")

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert len(first["baseline_rows"]) == 3
    assert len(first["final_rows"]) == 4
    assert first["final_rows"][-1]["flink_commit_tag"] == "run_123"
    assert first["baseline_content_sha256"] != first["final_content_sha256"]


@pytest.mark.parametrize(
    "contract",
    (
        FLINK_ICEBERG,
        FLINK_AWS,
        POSTGRES_JDBC,
        HADOOP_CLIENT_API,
        HADOOP_CLIENT_RUNTIME,
    ),
)
def test_flink_iceberg_artifacts_match_frozen_supply_chain(contract) -> None:
    evidence = verify_artifact(contract)

    assert evidence["coordinate"] == contract["coordinate"]
    assert evidence["bytes"] == contract["bytes"]
    assert evidence["maven_sha1"] == contract["maven_sha1"]
    assert evidence["sha256"] == contract["sha256"]


def test_cleanup_prefix_scope_is_fail_closed() -> None:
    assert PREFIX_RE.fullmatch(
        "acceptance/flink-iceberg/gda_flink_iceberg_0123456789/"
    )
    assert not PREFIX_RE.fullmatch("acceptance/flink-iceberg/")
    assert not PREFIX_RE.fullmatch(
        "acceptance/flink-iceberg/gda_flink_iceberg_0123456789/warehouse"
    )
