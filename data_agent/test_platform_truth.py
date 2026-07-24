import json

import pytest

from data_agent import platform_truth


def _production_values() -> dict[str, str]:
    return {
        "GDA_DEPLOYMENT_PROFILE": "prod",
        "DATABASE_URL": "postgresql://agent:real-password@db:5432/gis_agent",
        "CHAINLIT_AUTH_SECRET": "a-real-production-secret-that-is-long-enough",
        "CLOUD_STORAGE_PROVIDER": "aws",
        "AWS_ACCESS_KEY_ID": "production-access-key",
        "AWS_SECRET_ACCESS_KEY": "production-storage-secret",
        "AWS_S3_BUCKET": "production-bucket",
        "OLLAMA_API_BASE": "https://models.example.com",
    }


def test_config_report_redacts_secret_values_and_fingerprint_input():
    values = _production_values()

    report = platform_truth.build_config_report(values)
    rendered = json.dumps(report, sort_keys=True)

    assert report["valid"] is True
    assert report["startup_allowed"] is True
    assert report["profile"] == "production"
    assert report["entries"]["DATABASE_URL"]["value"] == "<redacted>"
    assert report["entries"]["CHAINLIT_AUTH_SECRET"]["value"] == "<redacted>"
    assert values["DATABASE_URL"] not in rendered
    assert values["CHAINLIT_AUTH_SECRET"] not in rendered
    assert values["AWS_SECRET_ACCESS_KEY"] not in rendered


def test_production_validation_is_fail_closed_and_cannot_be_disabled():
    values = {
        "GDA_DEPLOYMENT_PROFILE": "production",
        "GDA_CONFIG_STRICT": "false",
    }

    report = platform_truth.build_config_report(values)

    assert report["strict"] is True
    assert report["startup_allowed"] is False
    assert any(
        issue["code"] == "strict_disable_ignored"
        for issue in report["warnings"]
    )
    with pytest.raises(platform_truth.PlatformTruthError):
        platform_truth.assert_startup_config(values)


def test_development_reports_missing_dependencies_but_remains_startable():
    report = platform_truth.assert_startup_config({}, profile="dev")

    assert report["profile"] == "development"
    assert report["entries"]["GDA_DEPLOYMENT_PROFILE"]["source"] == "argument"
    assert report["entries"]["GDA_DEPLOYMENT_PROFILE"]["value"] == "development"
    assert report["valid"] is True
    assert report["startup_allowed"] is True
    assert {
        issue["code"] for issue in report["warnings"]
    } >= {
        "database_unconfigured",
        "auth_secret_missing",
        "storage_unconfigured",
        "model_provider_unconfigured",
    }


def test_database_url_has_precedence_and_conflicts_are_explicit():
    values = {
        "DATABASE_URL": "postgres://direct:secret@primary:5432/authority",
        "POSTGRES_HOST": "secondary",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DATABASE": "other",
        "POSTGRES_USER": "components",
        "POSTGRES_PASSWORD": "secret",
    }

    assert platform_truth.resolve_database_url(values) == (
        "postgresql://direct:secret@primary:5432/authority"
    )
    report = platform_truth.build_config_report(values)
    assert any(
        issue["code"] == "database_source_conflict"
        for issue in report["errors"]
    )


def test_database_url_components_are_encoded_for_uri_safety():
    values = {
        "POSTGRES_HOST": "db",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DATABASE": "gis data/2026",
        "POSTGRES_USER": "agent user",
        "POSTGRES_PASSWORD": "p@ss:+/word",
    }

    assert platform_truth.resolve_database_url(values) == (
        "postgresql://agent%20user:p%40ss%3A%2B%2Fword@"
        "db:5432/gis%20data%2F2026"
    )


def test_database_url_strips_sqlalchemy_driver_for_shared_plain_dsn():
    assert platform_truth.resolve_database_url(
        {"DATABASE_URL": "postgresql+asyncpg://agent:secret@db:5432/gis"}
    ) == "postgresql://agent:secret@db:5432/gis"


def test_repository_source_access_and_runtime_baselines_match():
    static_report = platform_truth.validate_static_contract()

    assert static_report["status"] == "valid"
    assert static_report["environment_access"]["matches_baseline"] is True
    assert static_report["runtime"]["matches_primitive_baseline"] is True
    assert static_report["runtime"]["unregistered_primitives"] == {}


def test_runtime_report_detects_unregistered_background_mechanism(tmp_path):
    source_root = tmp_path / "data_agent"
    source_root.mkdir()
    (source_root / "new_worker.py").write_text(
        "import asyncio\nasyncio.create_task(work())\n",
        encoding="utf-8",
    )

    report = platform_truth.build_runtime_report(source_root)

    assert report["status"] == "invalid"
    assert report["unregistered_primitives"] == {
        "data_agent/new_worker.py": ["async_task"]
    }


def test_snapshot_comparison_reports_config_and_platform_drift():
    unchanged = {
        "platform_fingerprint": "platform-a",
        "config": {"config_fingerprint": "config-a"},
        "runtime": {"inventory_fingerprint": "runtime-a"},
    }
    changed = {
        **unchanged,
        "platform_fingerprint": "platform-b",
        "config": {"config_fingerprint": "config-b"},
    }

    assert platform_truth.compare_platform_snapshots(unchanged, unchanged) == {
        "match": True,
        "differences": {},
    }
    comparison = platform_truth.compare_platform_snapshots(unchanged, changed)
    assert comparison["match"] is False
    assert set(comparison["differences"]) == {
        "platform_fingerprint",
        "config_fingerprint",
    }
