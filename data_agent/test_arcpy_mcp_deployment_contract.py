"""Deployment contracts for the environment-managed ArcPy MCP service."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]

ARCPY_TIMEOUT_VARIABLES = {
    "ARCPY_MCP_CONNECT_TIMEOUT",
    "ARCPY_MCP_JOB_TIMEOUT",
    "ARCPY_MCP_DL_JOB_TIMEOUT",
    "ARCPY_MCP_UPLOAD_TIMEOUT",
    "ARCPY_MCP_DOWNLOAD_TIMEOUT",
}


def test_legacy_windows_arcpy_seed_is_not_enabled():
    data = yaml.safe_load(
        (ROOT / "data_agent/mcp_servers.yaml").read_text(encoding="utf-8")
    )
    legacy = [
        row for row in data["servers"] if row["name"] == "arcgis-pro-tools"
    ]

    assert not legacy or (
        legacy[0]["enabled"] is False
        and legacy[0]["description"].startswith(
            "Legacy Windows-local ArcPy bridge"
        )
    )


def test_environment_example_documents_remote_arcpy_contract():
    text = (ROOT / "data_agent/.env.example").read_text(encoding="utf-8")
    required = {
        "ARCPY_MCP_ENABLED",
        "ARCPY_MCP_URL",
        "ARCPY_MCP_CA_BUNDLE",
        "ARCPY_MCP_TOKEN",
        "ARCPY_MCP_TOKEN_FILE",
        *ARCPY_TIMEOUT_VARIABLES,
    }

    for variable in required:
        assert variable in text
    assert "ARCPY_MCP_TOKEN_FILE takes precedence" in text
    assert "Never commit either token value" in text


def test_arcpy_compose_override_uses_secret_files_and_timeouts():
    data = yaml.safe_load(
        (ROOT / "docker-compose.arcpy-mcp.yml").read_text(encoding="utf-8")
    )
    app = data["services"]["app"]
    environment = app["environment"]

    assert set(app["secrets"]) == {"arcpy_mcp_token", "arcpy_mcp_ca"}
    assert environment["ARCPY_MCP_ENABLED"] == "true"
    assert environment["ARCPY_MCP_TOKEN_FILE"] == (
        "/run/secrets/arcpy_mcp_token"
    )
    assert environment["ARCPY_MCP_CA_BUNDLE"] == (
        "/run/secrets/arcpy_mcp_ca"
    )
    assert ARCPY_TIMEOUT_VARIABLES <= environment.keys()
    assert "ARCPY_MCP_TOKEN" not in environment
    assert data["secrets"]["arcpy_mcp_token"]["file"] == (
        "${ARCPY_MCP_TOKEN_HOST_FILE}"
    )
    assert data["secrets"]["arcpy_mcp_ca"]["file"] == (
        "${ARCPY_MCP_CA_HOST_FILE}"
    )
