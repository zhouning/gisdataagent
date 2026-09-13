"""Versioned S2 business rule configuration."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


RULES_PATH = Path(__file__).with_name("business_rules_v1.json")


@lru_cache(maxsize=1)
def load_business_rules() -> dict[str, Any]:
    payload = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    if payload.get("schema") != "uwm.livability_s2.business_rules.v1":
        raise RuntimeError("s2_business_rules_schema_invalid")
    if not payload.get("version"):
        raise RuntimeError("s2_business_rules_version_missing")
    return payload


def facility_criticality(facility_class: str, user_declared: bool) -> tuple[bool, str]:
    rules = load_business_rules()
    configured = facility_class in set(rules.get("critical_facility_classes") or [])
    if configured:
        return True, "versioned_business_rule"
    if user_declared:
        return True, "user_scenario_declaration"
    return False, "not_classified_as_critical"
