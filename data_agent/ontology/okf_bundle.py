"""Official OKF v0.2 bundle access and references for ontology consumers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

OKF_VERSION = "0.2"
OKF_COMPATIBILITY = "0.2+"
OKF_BUNDLE_ID = "natural-resource-ontology-knowledge-v2"
OKF_BUNDLE_ROOT = Path(__file__).with_name("okf_bundle")

_QUERY_CONCEPTS = {
    "concept_explanation": "assets/natural-resource-ontology",
    "hierarchy": "assets/natural-resource-ontology",
    "relation_path": "assets/natural-resource-ontology",
    "transition_rules": "assets/land-use-transition-model",
    "schema_mapping": "assets/semantic-mapping-catalog",
}

_SCENARIO_COMPUTATIONS = {
    "heping_review": "computations/heping-land-conversion-precheck",
    "banzhu_adjustment": "computations/banzhu-land-structure-analysis",
}


def scenario_computation_id(scenario_id: str) -> str:
    try:
        return _SCENARIO_COMPUTATIONS[scenario_id]
    except KeyError as exc:
        raise KeyError(f"no OKF computation is registered for {scenario_id}") from exc


def okf_reference(*, query_type: str, scenario_id: str | None = None) -> dict[str, Any]:
    """Return a pointer to a real OKF concept, not an inline pseudo-bundle."""
    if query_type == "demo_scenario_analysis":
        concept_id = scenario_computation_id(scenario_id or "heping_review")
        role = "attested_computation_contract"
    else:
        concept_id = _QUERY_CONCEPTS.get(query_type, "assets/natural-resource-ontology")
        role = "knowledge_concept"
    path = f"{concept_id}.md"
    return {
        "okf_version": OKF_VERSION,
        "compatibility": OKF_COMPATIBILITY,
        "bundle_id": OKF_BUNDLE_ID,
        "concept_id": concept_id,
        "role": role,
        "resource": f"/api/ontology/okf?path={path}",
        "bundle_index": "/api/ontology/okf?path=index.md",
    }


def resolve_okf_resource(relative_path: str) -> Path:
    """Resolve one bundle resource without allowing traversal outside the bundle."""
    normalized = str(relative_path or "index.md").strip().lstrip("/")
    if not normalized:
        normalized = "index.md"
    candidate = (OKF_BUNDLE_ROOT / normalized).resolve()
    root = OKF_BUNDLE_ROOT.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("OKF resource path escapes the bundle")
    if not candidate.is_file():
        raise KeyError(normalized)
    return candidate


def load_concept_frontmatter(concept_id: str) -> dict[str, Any]:
    path = resolve_okf_resource(f"{concept_id}.md")
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"OKF concept {concept_id} has no YAML frontmatter")
    _, frontmatter, _ = text.split("---", 2)
    payload = yaml.safe_load(frontmatter) or {}
    if not isinstance(payload, dict) or not payload.get("type"):
        raise ValueError(f"OKF concept {concept_id} has no type")
    return payload


def validate_ontology_okf_bundle() -> dict[str, Any]:
    """Validate required v0.2 structure and the local computation contracts."""
    errors: list[str] = []
    concept_count = 0
    try:
        root_text = resolve_okf_resource("index.md").read_text(encoding="utf-8")
        if not root_text.startswith("---\n"):
            errors.append("index.md: missing root frontmatter")
        else:
            _, raw, _ = root_text.split("---", 2)
            meta = yaml.safe_load(raw) or {}
            if meta != {"okf_version": OKF_VERSION}:
                errors.append("index.md: root frontmatter must only declare okf_version 0.2")
    except (KeyError, OSError, ValueError, yaml.YAMLError) as exc:
        errors.append(f"index.md: {exc}")

    for path in sorted(OKF_BUNDLE_ROOT.rglob("*.md")):
        if path.name in {"index.md", "log.md"}:
            continue
        concept_count += 1
        rel = path.relative_to(OKF_BUNDLE_ROOT).as_posix()
        try:
            concept_id = rel.removesuffix(".md")
            meta = load_concept_frontmatter(concept_id)
            if meta.get("type") == "Attested Computation":
                if not meta.get("runtime"):
                    errors.append(f"{rel}: runtime is required")
                parameters = meta.get("parameters")
                if not isinstance(parameters, list):
                    errors.append(f"{rel}: parameters must be a typed list")
                executor = meta.get("executor")
                if not isinstance(executor, dict) or not executor.get("resource"):
                    errors.append(f"{rel}: executor.resource is required")
                elif not isinstance(executor.get("receipt"), list):
                    errors.append(f"{rel}: executor.receipt must be a list")
                else:
                    try:
                        resolve_okf_resource(str(executor["resource"]))
                    except (KeyError, ValueError):
                        errors.append(f"{rel}: executor resource is missing")
                attester = meta.get("attester")
                if not isinstance(attester, dict) or not attester.get("resource"):
                    errors.append(f"{rel}: attester.resource is required")
                else:
                    try:
                        resolve_okf_resource(str(attester["resource"]))
                    except (KeyError, ValueError):
                        errors.append(f"{rel}: attester resource is missing")
                computation = meta.get("computation")
                if not computation:
                    errors.append(f"{rel}: computation resource is required")
                else:
                    try:
                        resolve_okf_resource(str(computation))
                    except (KeyError, ValueError):
                        errors.append(f"{rel}: computation resource is missing")
        except (OSError, ValueError, yaml.YAMLError) as exc:
            errors.append(f"{rel}: {exc}")

    return {
        "okf_version": OKF_VERSION,
        "bundle_id": OKF_BUNDLE_ID,
        "valid": not errors,
        "concept_count": concept_count,
        "errors": errors,
    }
