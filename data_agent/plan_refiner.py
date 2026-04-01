"""
Plan Refiner — adjust workflow steps based on execution feedback.

After each DAG layer completes, PlanRefiner can:
- Insert repair steps (e.g., CRS fix before spatial join)
- Remove redundant steps (e.g., skip cleaning if data already clean)
- Adjust downstream parameters based on upstream outputs
- Simplify analysis depth when token budget is tight
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .observability import get_logger

logger = get_logger("plan_refiner")


# ---------------------------------------------------------------------------
# Repair templates — auto-inserted when specific errors are detected
# ---------------------------------------------------------------------------

REPAIR_TEMPLATES: dict[str, dict] = {
    "crs_mismatch": {
        "step_id": "repair_crs_{after}",
        "label": "自动修复: CRS 标准化",
        "pipeline_type": "general",
        "prompt": "对数据执行 CRS 标准化到 EPSG:4490: standardize_crs(file_path='{file_path}', target_crs='EPSG:4490')",
        "critical": False,
    },
    "null_values": {
        "step_id": "repair_nulls_{after}",
        "label": "自动修复: 空值填充",
        "pipeline_type": "general",
        "prompt": "填充数据空值: auto_fix_defects(file_path='{file_path}')",
        "critical": False,
    },
    "topology_error": {
        "step_id": "repair_topo_{after}",
        "label": "自动修复: 拓扑修复",
        "pipeline_type": "general",
        "prompt": "修复拓扑错误: auto_fix_defects(file_path='{file_path}')",
        "critical": False,
    },
}

# Error message patterns → repair template key
ERROR_REPAIR_MAPPING: dict[str, str] = {
    "crs": "crs_mismatch",
    "坐标系": "crs_mismatch",
    "coordinate": "crs_mismatch",
    "projection": "crs_mismatch",
    "null": "null_values",
    "空值": "null_values",
    "nan": "null_values",
    "topology": "topology_error",
    "拓扑": "topology_error",
    "self-intersection": "topology_error",
}


@dataclass
class RefinementResult:
    """Result of a plan refinement pass."""
    steps: list[dict]
    changes: list[str] = field(default_factory=list)
    inserted_count: int = 0
    removed_count: int = 0
    adjusted_count: int = 0

    def to_dict(self) -> dict:
        return {
            "changes": self.changes,
            "inserted": self.inserted_count,
            "removed": self.removed_count,
            "adjusted": self.adjusted_count,
        }


class PlanRefiner:
    """Adjusts remaining workflow steps based on execution results."""

    def refine(self, remaining_steps: list[dict],
               step_results: list[dict],
               node_outputs: dict) -> RefinementResult:
        """Main entry: refine remaining steps based on completed results.

        Args:
            remaining_steps: Steps not yet executed (will be modified)
            step_results: Results from completed steps
            node_outputs: Accumulated outputs keyed by step_id

        Returns:
            RefinementResult with modified steps and change log
        """
        steps = copy.deepcopy(remaining_steps)
        changes = []
        inserted = 0
        removed = 0
        adjusted = 0

        # 1. Auto-insert repair steps based on errors in completed results
        for sr in step_results:
            if sr.get("status") == "failed" and sr.get("error"):
                error_msg = sr["error"].lower()
                for pattern, template_key in ERROR_REPAIR_MAPPING.items():
                    if pattern in error_msg:
                        template = REPAIR_TEMPLATES.get(template_key)
                        if template:
                            repair = self._make_repair_step(
                                template, sr["step_id"],
                                sr.get("files", [""])[0] if sr.get("files") else "",
                            )
                            # Insert at beginning of remaining steps
                            steps.insert(0, repair)
                            changes.append(f"Inserted repair '{repair['label']}' for error in '{sr['step_id']}'")
                            inserted += 1
                        break

        # 2. Inject upstream context into downstream prompts
        for step in steps:
            prompt = step.get("prompt", "")
            for step_id, output in node_outputs.items():
                placeholder = f"{{{step_id}.output}}"
                if placeholder in prompt:
                    report_text = str(output.get("report", ""))[:2000]
                    step["prompt"] = prompt.replace(placeholder, report_text)
                    adjusted += 1
                    changes.append(f"Injected '{step_id}' output into '{step.get('step_id', '')}'")

        # 3. Remove redundant steps (if upstream already completed the work)
        steps_to_remove = []
        for i, step in enumerate(steps):
            label_lower = step.get("label", "").lower()
            # If a "clean" step exists but upstream already cleaned successfully
            if "清洗" in label_lower or "clean" in label_lower:
                for sr in step_results:
                    if sr.get("status") == "completed" and "clean" in sr.get("step_id", "").lower():
                        steps_to_remove.append(i)
                        changes.append(f"Removed redundant '{step.get('label', '')}' — already done")
                        removed += 1

        for idx in reversed(steps_to_remove):
            steps.pop(idx)

        return RefinementResult(
            steps=steps,
            changes=changes,
            inserted_count=inserted,
            removed_count=removed,
            adjusted_count=adjusted,
        )

    def insert_repair_step(self, steps: list[dict], after_step_id: str,
                           repair_config: dict) -> list[dict]:
        """Insert a repair step after a specified step."""
        steps = copy.deepcopy(steps)
        insert_idx = len(steps)
        for i, step in enumerate(steps):
            if step.get("step_id") == after_step_id:
                insert_idx = i + 1
                break

        repair = copy.deepcopy(repair_config)
        repair.setdefault("step_id", f"repair_{after_step_id}")
        repair.setdefault("depends_on", [after_step_id])
        steps.insert(insert_idx, repair)
        return steps

    def remove_step(self, steps: list[dict], step_id: str) -> list[dict]:
        """Remove a step and update dependencies."""
        steps = copy.deepcopy(steps)
        # Find the step to remove
        removed_deps = []
        new_steps = []
        for step in steps:
            if step.get("step_id") == step_id:
                removed_deps = step.get("depends_on", [])
                continue
            # Update dependencies: if any step depended on removed step,
            # re-point to removed step's dependencies
            deps = step.get("depends_on", [])
            if step_id in deps:
                deps = [d for d in deps if d != step_id] + removed_deps
                step["depends_on"] = list(set(deps))
            new_steps.append(step)
        return new_steps

    def adjust_params(self, step: dict, key: str, new_value: str) -> dict:
        """Adjust a parameter in a step's prompt or params."""
        step = copy.deepcopy(step)
        if "params" in step and key in step["params"]:
            step["params"][key] = new_value
        elif key in step:
            step[key] = new_value
        return step

    def _make_repair_step(self, template: dict, after_step_id: str,
                          file_path: str) -> dict:
        """Create a concrete repair step from a template."""
        repair = copy.deepcopy(template)
        repair["step_id"] = template["step_id"].format(after=after_step_id)
        repair["prompt"] = template["prompt"].format(file_path=file_path)
        repair["depends_on"] = [after_step_id]
        return repair
