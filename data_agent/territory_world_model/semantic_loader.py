from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .models import TwmLayerBinding, TwmSemanticBundle


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_NAMES = ("twm_mmfe_semantic_product.json", "semantic_product.json")
CONTRACT_NAMES = ("twm_state_input_contract.json", "twm_state_input.json")
RELATION_NAMES = ("twm_mmfe_semantic_relations.csv", "semantic_relations.csv")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _first_existing(root: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        candidate = root / name
        if candidate.exists():
            return candidate
    return None


def _resolve_path(root: Path, value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    candidate = Path(raw)
    if candidate.is_absolute() and candidate.exists():
        return str(candidate)

    search_roots = [
        root,
        root.parent,
        root.parent.parent,
        REPO_ROOT,
        Path.cwd(),
    ]
    for base in search_roots:
        probe = base / raw
        if probe.exists():
            return str(probe)
        if raw.startswith("data_agent/"):
            probe = REPO_ROOT / raw
            if probe.exists():
                return str(probe)
    return str((REPO_ROOT / raw) if raw.startswith("data_agent/") else (root / raw))


def _canonical_role(row: dict[str, Any]) -> str:
    role = str(row.get("role") or row.get("semantic_domain") or "").strip()
    standard_role = str(row.get("standard_role") or "").strip()
    layer_alias = str(row.get("role_alias_zh") or row.get("business_role_zh") or "").strip()
    if "annual_change" in role:
        return "annual_change"
    if "remote_sensing" in role:
        return "remote_sensing_tile"
    if standard_role in {"pbf", "eco_redline", "planning_zone", "urban_boundary", "project", "admin_unit"}:
        return standard_role
    if role in {"parcel_current", "parcel"}:
        return "parcel"
    if "生态保护红线" in layer_alias:
        return "eco_redline"
    if "永久基本农田" in layer_alias:
        return "pbf"
    if "建设项目" in layer_alias:
        return "project"
    if "行政区" in layer_alias:
        return "admin_unit"
    return standard_role or role or "feature"


def _object_type_for(canonical_role: str, row: dict[str, Any]) -> str:
    explicit = str(row.get("object_type") or "").strip()
    if canonical_role in {"pbf", "eco_redline", "planning_zone", "urban_boundary"}:
        return "control_boundary"
    if canonical_role == "project":
        return "project"
    if canonical_role == "annual_change":
        return "event"
    if canonical_role == "admin_unit":
        return "admin_unit"
    if canonical_role == "remote_sensing_tile":
        return "remote_sensing_tile"
    if explicit:
        return explicit
    return "feature"


def _layer_binding_from_row(row: dict[str, Any], manifest_path: Path, root: Path) -> TwmLayerBinding:
    canonical_role = _canonical_role(row)
    quality_value = row.get("quality_score")
    quality_score = None
    if quality_value not in (None, ""):
        try:
            quality_score = float(quality_value)
        except Exception:
            quality_score = None

    synthetic = str(row.get("synthetic") or "").strip().lower() in {"1", "true", "yes", "y", "on"}
    not_for_production = str(row.get("not_for_production") or "").strip().lower() in {"1", "true", "yes", "y", "on"}
    field_mapping = row.get("twm_binding") or row.get("field_mapping") or {}
    if isinstance(field_mapping, str) and field_mapping.strip():
        try:
            field_mapping = json.loads(field_mapping)
        except Exception:
            field_mapping = {}
    if not isinstance(field_mapping, dict):
        field_mapping = {}

    quality_snapshot: dict[str, Any] = {}
    if quality_score is not None:
        quality_snapshot["quality_score"] = quality_score
    if row.get("field_count") not in (None, ""):
        quality_snapshot["field_count"] = row.get("field_count")

    source_path = _resolve_path(root, str(row.get("source_path") or row.get("path") or ""))
    return TwmLayerBinding(
        role=str(row.get("role") or row.get("semantic_domain") or canonical_role),
        canonical_role=canonical_role,
        object_type=_object_type_for(canonical_role, row),
        layer_alias=str(
            row.get("role_alias_zh")
            or row.get("business_role_zh")
            or row.get("standard_role_alias_zh")
            or row.get("role")
            or canonical_role
        ),
        source_path=source_path,
        semantic_product_path=str(manifest_path),
        asset_id=int(row["asset_id"]) if str(row.get("asset_id") or "").strip().isdigit() else None,
        time_label=str(row.get("time_label") or ""),
        valid_from=str(row.get("valid_from") or "") or None,
        valid_to=str(row.get("valid_to") or "") or None,
        field_mapping=field_mapping,
        quality_snapshot=quality_snapshot,
        metadata={
            "business_role_zh": row.get("business_role_zh") or "",
            "semantic_readiness": row.get("semantic_readiness") or "",
            "role_alias_zh": row.get("role_alias_zh") or "",
        },
        synthetic=synthetic,
        not_for_production=not_for_production,
    )


def load_semantic_bundle(bundle_dir: str | Path) -> TwmSemanticBundle:
    root = Path(bundle_dir)
    if not root.exists():
        raise FileNotFoundError(f"semantic bundle directory not found: {root}")

    manifest_path = _first_existing(root, MANIFEST_NAMES)
    if manifest_path is None:
        raise FileNotFoundError(f"no semantic product manifest found under {root}")
    manifest = _read_json(manifest_path)

    contract_path = _first_existing(root, CONTRACT_NAMES)
    contract = _read_json(contract_path) if contract_path else {}

    relations_path = _first_existing(root, RELATION_NAMES)
    relations = _read_csv(relations_path) if relations_path else []

    role_rows: list[dict[str, Any]] = []
    if isinstance(contract.get("role_bindings"), list):
        role_rows = [row for row in contract["role_bindings"] if isinstance(row, dict)]
    elif isinstance(contract.get("object_role_registry"), list):
        role_rows = [row for row in contract["object_role_registry"] if isinstance(row, dict)]
    elif isinstance(manifest.get("sources"), list):
        role_rows = [row for row in manifest["sources"] if isinstance(row, dict)]

    bindings = [_layer_binding_from_row(row, manifest_path, root) for row in role_rows]
    if not bindings and isinstance(manifest.get("sources"), list):
        bindings = [_layer_binding_from_row(row, manifest_path, root) for row in manifest["sources"] if isinstance(row, dict)]

    quality = manifest.get("quality") if isinstance(manifest.get("quality"), dict) else {}
    source_summary = {
        "source_count": len(bindings),
        "relation_count": len(relations),
        "synthetic_source_count": sum(1 for binding in bindings if binding.synthetic),
        "not_for_production_count": sum(1 for binding in bindings if binding.not_for_production),
    }
    warnings: list[str] = []
    if not contract:
        warnings.append("no contract sidecar was found; role bindings were derived from manifest sources")
    if quality.get("warnings"):
        warnings.extend(str(item) for item in quality.get("warnings") or [])

    state_input_path = _first_existing(root, ("twm_state_input.json",))
    return TwmSemanticBundle(
        root_dir=root,
        manifest_path=manifest_path,
        contract_path=contract_path,
        relations_path=relations_path,
        state_input_path=state_input_path,
        manifest=manifest,
        contract=contract,
        relations=relations,
        layer_bindings=bindings,
        quality=quality,
        source_summary=source_summary,
        warnings=warnings,
    )
