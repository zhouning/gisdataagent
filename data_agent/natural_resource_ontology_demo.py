"""Immutable runtime reader for the natural-resource ontology customer demo."""

from __future__ import annotations

import hashlib
import json
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from .ontology.okf_bundle import okf_reference, validate_ontology_okf_bundle


class DemoBundleError(RuntimeError):
    pass


class NaturalResourceOntologyDemo:
    SCENARIO_IDS = {"heping_review", "banzhu_adjustment"}

    def __init__(self, bundle_dir: str | Path | None = None):
        self.bundle_dir = Path(
            bundle_dir
            or Path(__file__).parent / "demo_data" / "natural_resource_ontology_customer_v1"
        )
        self.manifest = self._load_json("manifest.json")
        self.demo = self._load_json("demo.json")
        self._verify_bundle()

    def _load_json(self, filename: str) -> dict[str, Any]:
        path = self.bundle_dir / filename
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DemoBundleError(f"cannot load demo artifact {filename}: {exc}") from exc

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _verify_bundle(self) -> None:
        expected_ontology = self.manifest.get("ontology") or {}
        active_path = (
            Path(__file__).parent
            / "ontology"
            / "packages"
            / "natural_resource_one_map"
            / "active.json"
        )
        try:
            active = json.loads(active_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DemoBundleError(f"cannot verify active ontology: {exc}") from exc
        for key in ("semantic_version", "content_sha256", "package_id"):
            demo_key = {"semantic_version": "version", "content_sha256": "sha256"}.get(key, key)
            if expected_ontology.get(demo_key) != active.get(key):
                raise DemoBundleError(f"demo ontology {key} does not match active ontology")
        for artifact in self.manifest.get("files") or []:
            filename = str(artifact.get("name") or "")
            if not filename or Path(filename).name != filename:
                raise DemoBundleError("invalid artifact name in demo manifest")
            path = self.bundle_dir / filename
            if not path.is_file() or self._sha256(path) != artifact.get("sha256"):
                raise DemoBundleError(f"demo artifact hash mismatch: {filename}")

    def overview(self) -> dict[str, Any]:
        return {
            "bundle": self.demo["bundle"],
            "ontology": self.demo["ontology"],
            "overview": self.demo["overview"],
            "agent_plan": self.demo["agent_plan"],
            "decision_scope": self.demo["bundle"]["decision_scope"],
            "okf": {
                **okf_reference(
                    query_type="demo_scenario_analysis",
                    scenario_id="heping_review",
                ),
                "validation": validate_ontology_okf_bundle(),
            },
        }

    def scenarios(self) -> list[dict[str, Any]]:
        return deepcopy(self.demo["scenarios"])

    def _scenario(self, scenario_id: str) -> dict[str, Any]:
        if scenario_id not in self.SCENARIO_IDS:
            raise KeyError(scenario_id)
        return next(item for item in self.demo["scenarios"] if item["id"] == scenario_id)

    def _geojson(self, filename: str) -> dict[str, Any]:
        return self._load_json(filename)

    @staticmethod
    def _bounds(feature_collection: dict[str, Any]) -> list[list[float]]:
        coordinates: list[tuple[float, float]] = []

        def visit(value: Any) -> None:
            if (
                isinstance(value, list)
                and len(value) >= 2
                and all(isinstance(item, (int, float)) for item in value[:2])
            ):
                coordinates.append((float(value[0]), float(value[1])))
                return
            if isinstance(value, list):
                for item in value:
                    visit(item)

        for feature in feature_collection.get("features") or []:
            visit((feature.get("geometry") or {}).get("coordinates"))
        if not coordinates:
            return [[29.6, 106.0], [29.9, 106.4]]
        xs, ys = zip(*coordinates, strict=True)
        return [[min(ys), min(xs)], [max(ys), max(xs)]]

    def map_payload(self, scenario_id: str) -> dict[str, Any]:
        self._scenario(scenario_id)
        if scenario_id == "heping_review":
            parcels = self._geojson("heping_changed_parcels.geojson")
            constraints = self._geojson("heping_constraints.geojson")
            zones = self._geojson("heping_construction_zones.geojson")
            layers = [
                {
                    "name": "和平村 · 规划变化地块",
                    "type": "categorized",
                    "geojsonData": parcels,
                    "category_column": "review_status",
                    "category_colors": {
                        "空间冲突": "#c62828",
                        "材料待补": "#d97706",
                        "条件复核": "#eab308",
                        "初筛通过": "#15803d",
                    },
                    "category_labels": {
                        "空间冲突": "空间冲突",
                        "材料待补": "材料待补",
                        "条件复核": "条件复核",
                        "初筛通过": "初筛通过",
                    },
                    "style": {"color": "#ffffff", "weight": 0.8, "fillOpacity": 0.72},
                    "legend_title": "辅助预审结果",
                    "tooltip_fields": [
                        "parcel_id",
                        "JQDLMC",
                        "GHDLMC",
                        "process",
                        "area_ha",
                        "review_status",
                        "review_summary",
                    ],
                    "tooltip_labels": {
                        "parcel_id": "地块",
                        "JQDLMC": "规划前",
                        "GHDLMC": "规划后",
                        "process": "本体过程",
                        "area_ha": "面积(公顷)",
                        "review_status": "预审状态",
                        "review_summary": "判断依据",
                    },
                },
                {
                    "name": "和平村 · 空间约束",
                    "type": "categorized",
                    "geojsonData": constraints,
                    "category_column": "severity",
                    "category_colors": {"critical": "#b91c1c", "warning": "#f59e0b"},
                    "category_labels": {"critical": "禁止/保护性约束", "warning": "条件性约束"},
                    "style": {"color": "#7f1d1d", "weight": 1.6, "fillOpacity": 0.2},
                    "legend_title": "已注册空间约束",
                    "tooltip_fields": ["constraint_type", "GZMC", "rule", "severity"],
                    "tooltip_labels": {
                        "constraint_type": "约束类型",
                        "GZMC": "名称",
                        "rule": "规则",
                        "severity": "级别",
                    },
                },
                {
                    "name": "和平村 · 建设用地管制区",
                    "type": "categorized",
                    "geojsonData": zones,
                    "category_column": "GZQLXDM",
                    "category_colors": {
                        "010": "#22c55e",
                        "020": "#84cc16",
                        "030": "#f59e0b",
                        "040": "#ef4444",
                    },
                    "category_labels": {
                        "010": "允许建设区",
                        "020": "有条件建设区",
                        "030": "限制建设区",
                        "040": "禁止建设区",
                    },
                    "style": {"color": "#334155", "weight": 1, "fillOpacity": 0.16},
                    "legend_title": "建设用地管制区",
                    "tooltip_fields": ["zone_label", "GZQLXDM", "GZQMJ"],
                    "tooltip_labels": {
                        "zone_label": "管制类型",
                        "GZQLXDM": "代码",
                        "GZQMJ": "面积",
                    },
                    "visible": False,
                },
            ]
            bounds = self._bounds(parcels)
        else:
            parcels = self._geojson("banzhu_changed_parcels.geojson")
            layers = [
                {
                    "name": "斑竹村 · 规划变化地块",
                    "type": "categorized",
                    "geojsonData": parcels,
                    "category_column": "process",
                    "category_colors": {
                        "农业结构调整": "#16a34a",
                        "建设占用": "#dc2626",
                        "土地复垦": "#2563eb",
                        "土地整治": "#0f766e",
                        "土地利用转换": "#7c3aed",
                    },
                    "style": {"color": "#ffffff", "weight": 0.7, "fillOpacity": 0.72},
                    "legend_title": "本体识别的转换过程",
                    "tooltip_fields": [
                        "parcel_id",
                        "JQDLMC",
                        "GHDLMC",
                        "source_state",
                        "target_state",
                        "process",
                        "area_ha",
                    ],
                    "tooltip_labels": {
                        "parcel_id": "地块",
                        "JQDLMC": "规划前",
                        "GHDLMC": "规划后",
                        "source_state": "源状态",
                        "target_state": "目标状态",
                        "process": "转换过程",
                        "area_ha": "面积(公顷)",
                    },
                }
            ]
            bounds = self._bounds(parcels)
        center = [
            round((bounds[0][0] + bounds[1][0]) / 2, 6),
            round((bounds[0][1] + bounds[1][1]) / 2, 6),
        ]
        return {
            "scenario_id": scenario_id,
            "center": center,
            "zoom": 14,
            "bounds": bounds,
            "layers": layers,
        }

    def _run_computation(self, scenario_id: str) -> dict[str, Any]:
        scenario = self._scenario(scenario_id)
        steps = [{**step, "status": "completed"} for step in self.demo["agent_plan"]]
        if scenario_id == "heping_review":
            status = scenario["review_status_counts"]
            findings = [
                {
                    "severity": "critical",
                    "title": f"{status.get('空间冲突', 0)} 个变化地块命中保护性空间约束",
                    "action": "进入人工复核，不得据此直接办理建设审批",
                },
                {
                    "severity": "warning",
                    "title": f"{status.get('材料待补', 0)} 个地块涉及建设占用且缺少审批文件关联",
                    "action": "补充法律政策依据和审批文件后重新执行规则校验",
                },
                {
                    "severity": "warning",
                    "title": f"{status.get('条件复核', 0)} 个地块命中地灾或林地条件约束",
                    "action": "联动地灾、林业等业务部门开展条件审查",
                },
                {
                    "severity": "info",
                    "title": "项目台账与规划图斑尚未建立可靠空间关联",
                    "action": "以项目编码或项目名称回填 TDGHDL.XMMC，形成跨表实体链接",
                },
            ]
            headline = (
                f"识别 {scenario['changed_count']} 个变化地块、"
                f"{status.get('空间冲突', 0)} 个空间冲突和 "
                f"{status.get('材料待补', 0)} 个审批证据缺口"
            )
        else:
            rows = scenario["structure_rows"]
            selected = [
                row
                for row in rows
                if row["name"]
                in {"农用地合计", "旱地", "园地", "林地", "坑塘水面", "宅基地（村居住用地）"}
            ]
            findings = [
                {
                    "severity": "info" if row["delta_ha"] >= 0 else "warning",
                    "title": f"{row['name']} {row['direction']} {abs(row['delta_ha']):.2f} 公顷",
                    "action": f"对应本体状态：{row['state']['label']}",
                }
                for row in selected
            ]
            headline = (
                f"规划图斑中识别 {scenario['changed_count']} 个变化地块，"
                "结构表显示农用地净增 9.06 公顷"
            )
        return {
            "run_id": f"demo-{scenario_id}-{self.demo['bundle']['version']}",
            "scenario": scenario,
            "status": "completed",
            "headline": headline,
            "steps": steps,
            "findings": findings,
            "ontology": self.demo["ontology"],
            "decision_scope": self.demo["bundle"]["decision_scope"],
        }

    def run(self, scenario_id: str) -> dict[str, Any]:
        """Run a sanctioned scenario and refuse un-attested results."""
        from .ontology.okf_attestation import execute_attested_scenario

        return execute_attested_scenario(self, scenario_id, self._run_computation)

    def evidence(self, parcel_id: str | None = None) -> dict[str, Any]:
        base = {
            "bundle": self.demo["bundle"],
            "ontology": self.demo["ontology"],
            "sources": self.demo["sources"],
            "field_mappings": self.demo["field_mappings"],
            "quality": self.demo["quality"],
            "okf_reference": okf_reference(
                query_type="demo_scenario_analysis",
                scenario_id="heping_review",
            ),
        }
        if not parcel_id:
            return base
        features = self._geojson("heping_changed_parcels.geojson").get("features") or []
        feature = next(
            (
                item
                for item in features
                if (item.get("properties") or {}).get("parcel_id") == parcel_id
            ),
            None,
        )
        if feature is None:
            raise KeyError(parcel_id)
        properties = feature["properties"]
        source_class = properties["source_state_id"]
        target_class = properties["target_state_id"]
        process_class = properties["process_id"]
        base["parcel"] = feature
        base["semantic_trace"] = {
            "entity": {"id": parcel_id, "class": "gda:nr:class:LandParcel", "label": "地块"},
            "source_state": {
                "class": f"gda:nr:class:{source_class}",
                "label": properties["source_state"],
                "source_value": properties["JQDLMC"],
            },
            "transition": {
                "class": f"gda:nr:class:{process_class}",
                "label": properties["process"],
            },
            "target_state": {
                "class": f"gda:nr:class:{target_class}",
                "label": properties["target_state"],
                "source_value": properties["GHDLMC"],
            },
            "relations": [
                "hasSourceState",
                "affectsParcel",
                "hasTargetState",
                "constrainedBy",
                "authorizedBy",
            ],
        }
        return base

    def governance(self) -> dict[str, Any]:
        return {
            "quality": self.demo["quality"],
            "projects": self.demo["projects"],
            "sources": self.demo["sources"],
            "capability_coverage": self.demo["capability_coverage"],
            "decision_scope": self.demo["bundle"]["decision_scope"],
            "okf": validate_ontology_okf_bundle(),
        }


_service: NaturalResourceOntologyDemo | None = None
_service_lock = threading.Lock()


def get_natural_resource_ontology_demo(*, refresh: bool = False) -> NaturalResourceOntologyDemo:
    global _service
    if _service is None or refresh:
        with _service_lock:
            if _service is None or refresh:
                _service = NaturalResourceOntologyDemo()
    return _service
