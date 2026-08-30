"""Operator CLI for governed virtual-source registration and discovery."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
from pathlib import Path

from dotenv import load_dotenv


def _load_environment() -> None:
    configured = os.environ.get("GDA_OPERATOR_ENV_FILE")
    env_path = Path(configured) if configured else Path(__file__).with_name(".env")
    if env_path.exists():
        load_dotenv(env_path, override=False)
    local_secret_path = Path(__file__).with_name(".vsource-secret.env")
    if local_secret_path.exists():
        os.environ.setdefault("GDA_VSOURCE_SECRET_FILE", str(local_secret_path))
        load_dotenv(local_secret_path, override=False)


def _required_secret(name: str, prompt: str) -> str:
    value = os.environ.get(name)
    if value:
        return value
    value = getpass.getpass(prompt).strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _database_query_config(args: argparse.Namespace) -> dict:
    return {
        "allowed_schemas": list(dict.fromkeys(args.schema)),
        "discovery_mode": "metadata_only",
        "discovery_limit": args.discovery_limit,
        "statement_timeout_ms": args.statement_timeout_ms,
        "lock_timeout_ms": args.lock_timeout_ms,
        "max_rows": args.max_rows,
    }


async def _onboard_database(args: argparse.Namespace) -> dict:
    from .migration_runner import MigrationFailure, verify_schema_state

    try:
        verify_schema_state()
    except MigrationFailure as exc:
        return {
            "status": "error",
            "stage": "control_plane_schema",
            "message": str(exc),
        }

    from .virtual_sources import (
        check_source_health,
        create_virtual_source,
        discover_virtual_source,
        list_virtual_sources,
        update_virtual_source,
    )

    sources = list_virtual_sources(args.owner, include_shared=False)
    requested_source_id = getattr(args, "source_id", None)
    requested_name = str(getattr(args, "name", "") or "").strip()
    if requested_source_id is not None:
        existing = next(
            (source for source in sources if int(source["id"]) == requested_source_id),
            None,
        )
        if existing is None:
            return {
                "status": "error",
                "stage": "source_registration",
                "message": "Requested source_id was not found for this owner",
            }
        source_name = str(existing["source_name"])
    else:
        if not requested_name:
            return {
                "status": "error",
                "stage": "source_registration",
                "message": "--name is required when --source-id is not provided",
            }
        existing = next(
            (source for source in sources if source["source_name"] == requested_name),
            None,
        )
        source_name = requested_name

    source_password = _required_secret(
        "GDA_VSOURCE_PASSWORD",
        "Virtual-source database password: ",
    )
    if not os.environ.get("CHAINLIT_AUTH_SECRET"):
        os.environ["CHAINLIT_AUTH_SECRET"] = _required_secret(
            "GDA_CONTROL_PLANE_ENCRYPTION_SECRET",
            "Control-plane credential encryption secret: ",
        )

    auth_config = {
        "type": "basic",
        "username": args.username,
        "password": source_password,
    }
    query_config = _database_query_config(args)
    if existing:
        source_id = int(existing["id"])
        updated = update_virtual_source(
            source_id,
            args.owner,
            source_type="database",
            endpoint_url=args.endpoint,
            auth_config=auth_config,
            query_config=query_config,
            enabled=True,
        )
        if updated.get("status") != "ok":
            return updated
        registration = "updated"
    else:
        created = create_virtual_source(
            source_name=source_name,
            source_type="database",
            endpoint_url=args.endpoint,
            owner_username=args.owner,
            auth_config=auth_config,
            query_config=query_config,
            refresh_policy="on_demand",
            is_shared=False,
        )
        if created.get("status") != "ok":
            return created
        source_id = int(created["id"])
        registration = "created"

    health = await check_source_health(source_id, args.owner)
    if health.get("health") != "healthy":
        return {
            "status": "error",
            "source_id": source_id,
            "registration": registration,
            "stage": "health_check",
            "message": health.get("message", "health check failed"),
        }
    discovery = await discover_virtual_source(source_id, args.owner)
    return {
        "status": discovery.get("status"),
        "source_id": source_id,
        "source_name": source_name,
        "registration": registration,
        "health": health.get("health"),
        "discovery_status": discovery.get("discovery_status"),
        "discovery_fingerprint": discovery.get("discovery_fingerprint"),
        "profile_fingerprint": discovery.get("profile_fingerprint"),
        "snapshot": discovery.get("snapshot"),
        "profile": discovery.get("profile"),
        "message": discovery.get("message"),
    }


def _export_discovery(args: argparse.Namespace) -> dict:
    from .migration_runner import MigrationFailure, verify_schema_state

    try:
        verify_schema_state()
    except MigrationFailure as exc:
        return {
            "status": "error",
            "stage": "control_plane_schema",
            "message": str(exc),
        }

    from .virtual_sources import get_virtual_source_discovery

    source = get_virtual_source_discovery(args.source_id, args.owner)
    if source is None:
        return {
            "status": "error",
            "stage": "discovery_export",
            "message": "Source not found or not visible to this owner",
        }
    return {"status": "ok", **source}


async def _rediscover_source(args: argparse.Namespace) -> dict:
    """Repeat governed discovery and optionally assert fingerprint stability."""
    from .migration_runner import MigrationFailure, verify_schema_state

    try:
        verify_schema_state()
    except MigrationFailure as exc:
        return {
            "status": "error",
            "stage": "control_plane_schema",
            "message": str(exc),
        }

    from .virtual_sources import discover_virtual_source, get_virtual_source

    source = get_virtual_source(args.source_id, args.owner)
    if source is None or source.get("source_type") != "database":
        return {
            "status": "error",
            "stage": "discovery_validation",
            "message": "Registered database source was not found",
        }
    if not source.get("enabled"):
        return {
            "status": "error",
            "stage": "discovery_validation",
            "message": "Registered database source is disabled",
        }

    discovery = await discover_virtual_source(args.source_id, args.owner)
    if discovery.get("status") != "ok":
        return {
            "status": "error",
            "stage": "discovery_execution",
            "source_id": args.source_id,
            "message": discovery.get("message", "Discovery failed"),
        }

    fingerprint_checks = {
        "discovery_fingerprint": (
            args.expected_discovery_fingerprint,
            discovery.get("discovery_fingerprint"),
        ),
        "profile_fingerprint": (
            args.expected_profile_fingerprint,
            discovery.get("profile_fingerprint"),
        ),
    }
    mismatches = {
        name: {"expected": expected, "actual": actual}
        for name, (expected, actual) in fingerprint_checks.items()
        if expected is not None and expected != actual
    }
    payload = {
        "source_id": args.source_id,
        "discovery_status": discovery.get("discovery_status"),
        "discovery_fingerprint": discovery.get("discovery_fingerprint"),
        "profile_fingerprint": discovery.get("profile_fingerprint"),
        "fingerprint_stable": not mismatches,
        "snapshot": discovery.get("snapshot"),
        "profile": discovery.get("profile"),
    }
    if mismatches:
        return {
            "status": "error",
            "stage": "discovery_stability",
            "fingerprint_mismatches": mismatches,
            **payload,
        }
    return {"status": "ok", **payload}


async def _query_database(args: argparse.Namespace) -> dict:
    from .migration_runner import MigrationFailure, verify_schema_state

    try:
        verify_schema_state()
    except MigrationFailure as exc:
        return {
            "status": "error",
            "stage": "control_plane_schema",
            "message": str(exc),
        }
    if args.limit < 1 or args.limit > 5000:
        return {
            "status": "error",
            "stage": "query_validation",
            "message": "limit must be between 1 and 5000",
        }
    try:
        sql = args.sql_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return {
            "status": "error",
            "stage": "query_validation",
            "message": str(exc),
        }

    from .virtual_sources import get_virtual_source, query_virtual_source

    source = get_virtual_source(args.source_id, args.owner)
    if source is None or source.get("source_type") != "database":
        return {
            "status": "error",
            "stage": "query_validation",
            "message": "Registered database source was not found",
        }
    if not source.get("enabled"):
        return {
            "status": "error",
            "stage": "query_validation",
            "message": "Registered database source is disabled",
        }
    result = await query_virtual_source(
        source,
        limit=args.limit,
        extra_params={"sql": sql, "geom_column": args.geom_column},
        register_result=False,
    )
    if isinstance(result, dict):
        return {
            "status": "error",
            "stage": "query_execution",
            "message": result.get("message", "Database query failed"),
        }
    from .query_result_contract import tabular_result_contract

    try:
        evidence = tabular_result_contract(result, include_rows=args.include_rows)
    except TypeError as exc:
        return {
            "status": "error",
            "stage": "query_execution",
            "message": str(exc),
        }
    payload = {
        "status": "ok",
        "source_id": args.source_id,
        "bounded_limit": args.limit,
        **evidence,
    }
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gda-source-operator",
        description="Register and discover governed GIS Data Agent virtual sources.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    database = subparsers.add_parser(
        "onboard-database",
        help="Register/update a PostgreSQL source, health-check it, and persist metadata.",
    )
    database.add_argument("--source-id", type=int)
    database.add_argument("--name")
    database.add_argument("--endpoint", required=True)
    database.add_argument("--schema", action="append", required=True)
    database.add_argument("--username", required=True)
    database.add_argument("--owner", required=True)
    database.add_argument("--discovery-limit", type=int, default=5000)
    database.add_argument("--statement-timeout-ms", type=int, default=15_000)
    database.add_argument("--lock-timeout-ms", type=int, default=2000)
    database.add_argument("--max-rows", type=int, default=1000)
    discovery = subparsers.add_parser(
        "export-discovery",
        help="Export persisted metadata-only discovery evidence without credentials.",
    )
    discovery.add_argument("--source-id", type=int, required=True)
    discovery.add_argument("--owner", required=True)
    rediscovery = subparsers.add_parser(
        "rediscover-source",
        help="Repeat persisted metadata-only discovery and verify expected fingerprints.",
    )
    rediscovery.add_argument("--source-id", type=int, required=True)
    rediscovery.add_argument("--owner", required=True)
    rediscovery.add_argument("--expected-discovery-fingerprint")
    rediscovery.add_argument("--expected-profile-fingerprint")
    query = subparsers.add_parser(
        "query-database",
        help="Execute one governed read query against a registered database source.",
    )
    query.add_argument("--source-id", type=int, required=True)
    query.add_argument("--owner", required=True)
    query.add_argument("--sql-file", type=Path, required=True)
    query.add_argument("--geom-column", default="")
    query.add_argument("--limit", type=int, default=1000)
    query.add_argument("--include-rows", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    _load_environment()
    args = _parser().parse_args(argv)
    if args.command == "onboard-database":
        result = asyncio.run(_onboard_database(args))
    elif args.command == "export-discovery":
        result = _export_discovery(args)
    elif args.command == "rediscover-source":
        result = asyncio.run(_rediscover_source(args))
    elif args.command == "query-database":
        result = asyncio.run(_query_database(args))
    else:
        raise ValueError(f"unsupported command: {args.command}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
