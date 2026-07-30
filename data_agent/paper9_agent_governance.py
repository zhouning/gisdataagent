"""Governed audit and verified episodic memory for Paper9 agent runs.

The module is deliberately independent from Google ADK.  ADK tools call these
deterministic functions so model decisions remain observable while acceptance
of a spatial plan stays under code-enforced domain constraints.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EXPECTED_PACKAGE_VERSION = "0.3.3"
EXPECTED_ALGORITHM_VERSION = "2.2.3"
AUDIT_SCHEMA_VERSION = "paper9.agent_audit.v1"
EPISODE_SCHEMA_VERSION = "paper9.verified_episode.v1"

_store_lock = threading.Lock()


@dataclass(frozen=True)
class Paper9AuditPolicy:
    """Hard gates and bounded recovery policy for a Paper9 plan."""

    cultivated_area_floor_delta_ha: float = 0.0
    require_slope_improvement: bool = True
    require_contiguity_improvement: bool = True
    max_replans: int = 1


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evaluate_paper9_summary(
    summary: Mapping[str, Any],
    *,
    policy: Paper9AuditPolicy | None = None,
    attempt: int = 0,
) -> dict[str, Any]:
    """Evaluate Paper9 output and return a machine-actionable recovery branch."""

    policy = policy or Paper9AuditPolicy()
    raw_records = summary.get("results") or summary.get("records") or []
    records: list[dict[str, Any]] = []
    failures: list[str] = []

    if not isinstance(raw_records, list) or not raw_records:
        failures.append("No MPC result records were produced.")
    else:
        for index, raw in enumerate(raw_records):
            if not isinstance(raw, Mapping):
                failures.append(f"Episode {index} is not a structured result record.")
                continue
            episode = raw.get("episode", index)
            cultivated = _float_or_none(raw.get("cultivated_area_change_ha"))
            slope = _float_or_none(raw.get("slope_change_pct"))
            contiguity = _float_or_none(raw.get("cont_change"))
            record = {
                "episode": episode,
                "cultivated_area_change_ha": cultivated,
                "slope_change_pct": slope,
                "cont_change": contiguity,
                "baimu_count_change": _float_or_none(raw.get("baimu_count_change")),
                "baimu_area_change_ha": _float_or_none(raw.get("baimu_area_change_ha")),
                "total_reward": _float_or_none(raw.get("total_reward")),
                "steps_run": raw.get("steps_run"),
            }
            records.append(record)

            if cultivated is None:
                failures.append(f"Episode {episode} is missing cultivated_area_change_ha.")
            elif cultivated < policy.cultivated_area_floor_delta_ha:
                failures.append(
                    f"Episode {episode} cultivated area delta {cultivated:.6f} ha is below "
                    f"the required {policy.cultivated_area_floor_delta_ha:.6f} ha."
                )
            if policy.require_slope_improvement:
                if slope is None:
                    failures.append(f"Episode {episode} is missing slope_change_pct.")
                elif slope >= 0:
                    failures.append(
                        f"Episode {episode} did not reduce mean cultivated-land slope."
                    )
            if policy.require_contiguity_improvement:
                if contiguity is None:
                    failures.append(f"Episode {episode} is missing cont_change.")
                elif contiguity <= 0:
                    failures.append(
                        f"Episode {episode} did not improve cultivated-land contiguity."
                    )

    passed = not failures
    can_replan = bool(records) and attempt < policy.max_replans
    if passed:
        next_action = "commit_verified_episode"
        recovery_hints: list[str] = []
    elif can_replan:
        next_action = "replan_once"
        recovery_hints = [
            "Keep cultivated_area_floor_delta_ha at or above 0.",
            "Change only planning search parameters supported by the current ensemble.",
            "Run the hard-gate audit again before presenting or committing the result.",
        ]
    else:
        next_action = "stop_and_request_human_review"
        recovery_hints = [
            "Do not present the run as successful.",
            "Preserve the failed audit and tool trace for review.",
        ]

    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "hard_constraint_passed": passed,
        "failure_reasons": failures,
        "records": records,
        "policy": asdict(policy),
        "attempt": attempt,
        "retryable": can_replan and not passed,
        "next_action": next_action,
        "recovery_hints": recovery_hints,
    }


def audit_paper9_run(
    out_dir: str | Path,
    *,
    policy: Paper9AuditPolicy | None = None,
    attempt: int = 0,
    write: bool = True,
) -> dict[str, Any]:
    """Audit one Paper9 output directory and optionally persist the decision."""

    root = Path(out_dir).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"out_dir not found: {root}")

    mpc_path = root / "mpc_summary.json"
    upstream_audit_path = root / "audit_summary.json"
    if mpc_path.is_file():
        summary = json.loads(mpc_path.read_text(encoding="utf-8"))
        source_path = mpc_path
    elif upstream_audit_path.is_file():
        upstream = json.loads(upstream_audit_path.read_text(encoding="utf-8"))
        summary = {"results": (upstream.get("constraint_status") or {}).get("records", [])}
        source_path = upstream_audit_path
    else:
        raise ValueError(f"No mpc_summary.json or audit_summary.json under {root}")

    result = evaluate_paper9_summary(summary, policy=policy, attempt=attempt)
    spatial_candidates = [
        root / "optimized_dltb.shp",
        root / "DLTB_optimized.shp",
        root / "optimized_dltb.fgb",
        root / "mpc_land_use.npy",
    ]
    artifacts = {
        "summary": {
            "path": str(source_path),
            "exists": True,
            "sha256": _sha256(source_path),
        },
        "optimized_spatial_result": {
            "path": next((str(path) for path in spatial_candidates if path.is_file()), None),
            "exists": any(path.is_file() for path in spatial_candidates),
        },
    }
    result["out_dir"] = str(root)
    result["artifacts"] = artifacts
    result["all_expected_outputs_exist"] = artifacts["optimized_spatial_result"]["exists"]
    if not result["all_expected_outputs_exist"]:
        result["hard_constraint_passed"] = False
        result["failure_reasons"].append("No optimized spatial result artifact was found.")
        result["retryable"] = False
        result["next_action"] = "stop_and_request_human_review"
        result["recovery_hints"] = [
            "Do not present the run as successful.",
            "Repair output generation before rerunning the planning stage.",
        ]

    if write:
        audit_path = root / "paper9_agent_audit.json"
        audit_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        result["audit_path"] = str(audit_path)
    return result


class Paper9EpisodeStore:
    """Append-only store containing only hard-gate-verified Paper9 episodes."""

    def __init__(self, path: str | Path | None = None):
        default = (
            Path.home()
            / ".gis-data-agent"
            / "paper9"
            / "verified_episodes.jsonl"
        )
        self.path = Path(path or os.environ.get("PAPER9_AGENT_MEMORY_PATH") or default)

    def commit(
        self,
        *,
        audit: Mapping[str, Any],
        dataset: str,
        goal: str,
        plan_args: Mapping[str, Any] | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not audit.get("hard_constraint_passed"):
            raise ValueError("Only hard-gate-passed runs may enter verified memory.")
        if not audit.get("all_expected_outputs_exist"):
            raise ValueError("Verified memory requires complete spatial output artifacts.")

        stable = {
            "dataset": str(dataset or "unknown").strip().lower(),
            "goal": str(goal or "").strip(),
            "out_dir": audit.get("out_dir"),
            "summary_sha256": ((audit.get("artifacts") or {}).get("summary") or {}).get(
                "sha256"
            ),
            "plan_args": dict(plan_args or {}),
        }
        episode_id = hashlib.sha256(
            json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:20]
        record = {
            "schema_version": EPISODE_SCHEMA_VERSION,
            "episode_id": episode_id,
            "verified_at": datetime.now(UTC).isoformat(),
            **stable,
            "audit": {
                "policy": audit.get("policy"),
                "records": audit.get("records"),
                "hard_constraint_passed": True,
            },
            "provenance": dict(provenance or {}),
        }

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _store_lock:
            existing = {item.get("episode_id") for item in self.recall(limit=10_000)}
            if episode_id not in existing:
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
        record["already_existed"] = episode_id in existing
        record["memory_path"] = str(self.path)
        return record

    def recall(self, *, dataset: str = "", limit: int = 3) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        dataset_key = str(dataset or "").strip().lower()
        records: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("schema_version") != EPISODE_SCHEMA_VERSION:
                continue
            if dataset_key and item.get("dataset") != dataset_key:
                continue
            records.append(item)
        return records[-max(0, int(limit)) :][::-1]
