"""Container-side read-only probes for profile baseline verification."""

from __future__ import annotations

import argparse
import json
from typing import Any

from data_agent.migration_runner import get_schema_report
from data_agent.standards_platform.application.acceptance import (
    standard_elements_fingerprint,
)
from data_agent.standards_platform.application.service import (
    load_released_standard,
    resolve_released_standard_version,
)

from .deployment_profile import DeploymentProfile, load_deployment_profile


def collect_internal_facts(profile: DeploymentProfile) -> dict[str, Any]:
    """Collect only non-secret migration, standard, and route facts."""
    migration = get_schema_report()
    version_id = resolve_released_standard_version(
        doc_code=profile.released_standard.doc_code,
        version_label=profile.released_standard.version_label,
    )
    version, elements = load_released_standard(version_id)

    from data_agent.api.tile_routes import get_tile_routes
    from data_agent.redis_client import check_redis_health

    redis = check_redis_health()

    return {
        "schema": "gis-data-agent.internal-runtime-facts.v1",
        "profile_id": profile.profile_id,
        "migration": {
            "status": migration.status,
            "catalog_count": migration.catalog_count,
            "applied_count": migration.applied_count,
            "catalog_fingerprint": migration.catalog_fingerprint,
            "database_fingerprint": migration.database_fingerprint,
        },
        "released_standard": {
            "doc_code": version["doc_code"],
            "version_label": version["version_label"],
            "status": version["status"],
            "element_count": len(elements),
            "elements_sha256": standard_elements_fingerprint(elements),
        },
        "dependencies": {
            "redis": {
                "status": redis.get("status"),
                "version": redis.get("version"),
            }
        },
        "route_paths": sorted(route.path for route in get_tile_routes()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    args = parser.parse_args(argv)
    try:
        facts = collect_internal_facts(load_deployment_profile(args.profile))
    except Exception as exc:
        print(json.dumps({
            "schema": "gis-data-agent.internal-runtime-facts.v1",
            "status": "error",
            "error_type": type(exc).__name__,
        }, sort_keys=True))
        return 1
    print(json.dumps(facts, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
