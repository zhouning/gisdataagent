"""Focused contracts for the real PostgreSQL CDC acceptance."""

from __future__ import annotations

from scripts.certify_chongqing_osm_postgres_cdc import (
    CONNECTOR_BYTES,
    CONNECTOR_SHA1,
    CONNECTOR_SHA256,
    DEFAULT_CONNECTOR,
    DEFAULT_SOURCE,
    build_cdc_plan,
    verify_connector_artifact,
)


def test_cdc_plan_is_deterministic_and_reconciles_operations() -> None:
    first = build_cdc_plan(DEFAULT_SOURCE)
    second = build_cdc_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert len(first["initial"]) == 3
    assert len(first["expected_changelog"]) == 10
    assert len(first["final_rows"]) == 2
    assert first["a_after"]["revision"] == 2
    assert first["c_after"]["revision"] == 2
    assert {line.split("\t", 1)[0] for line in first["expected_changelog"]} == {
        "+I",
        "-U",
        "+U",
        "-D",
    }


def test_cdc_connector_artifact_matches_frozen_supply_chain_identity() -> None:
    evidence = verify_connector_artifact(DEFAULT_CONNECTOR)

    assert evidence == {
        "coordinate": "org.apache.flink:flink-sql-connector-postgres-cdc:3.3.0",
        "bytes": CONNECTOR_BYTES,
        "maven_sha1": CONNECTOR_SHA1,
        "sha256": CONNECTOR_SHA256,
    }
