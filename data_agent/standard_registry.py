"""
Data Standard Registry — 预置行业数据标准 + 缺陷分类法，驱动自动化治理 (v15.6).

标准定义文件存放在 ``data_agent/standards/`` 目录 (YAML 格式)。
``StandardRegistry`` 在首次使用时自动加载所有标准，提供按 ID 查询、
列表、以及转为 ``check_field_standards`` 兼容 schema dict 的能力。

``DefectTaxonomy`` 从 ``defect_taxonomy.yaml`` 加载缺陷分类体系，
为治理审查、自动修正、案例库、报告生成提供统一的缺陷编码基础。
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

_STANDARDS_DIR = os.path.join(os.path.dirname(__file__), "standards")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FieldSpec:
    """Single field specification within a data standard."""
    name: str
    type: str = "string"        # string | numeric | integer | date
    required: str = "O"         # M (mandatory) | C (conditional) | O (optional)
    max_length: Optional[int] = None
    allowed: Optional[list] = None
    description: str = ""


@dataclass
class DataStandard:
    """A complete data standard definition."""
    id: str
    name: str
    version: str = "1.0"
    source: str = ""
    description: str = ""
    fields: list[FieldSpec] = field(default_factory=list)
    code_tables: dict[str, list[dict]] = field(default_factory=dict)
    formulas: list[dict] = field(default_factory=list)  # e.g. [{"expr":"A = B - C","tolerance":0.01}]

    def get_mandatory_fields(self) -> list[str]:
        return [f.name for f in self.fields if f.required == "M"]

    def get_field(self, name: str) -> Optional[FieldSpec]:
        for f in self.fields:
            if f.name == name:
                return f
        return None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class StandardRegistry:
    """Singleton registry of data standards loaded from YAML files."""

    _standards: dict[str, DataStandard] = {}
    _loaded: bool = False

    @classmethod
    def _ensure_loaded(cls):
        if not cls._loaded:
            cls.load_from_directory(_STANDARDS_DIR)
            cls._loaded = True

    @classmethod
    def load_from_directory(cls, dir_path: str) -> int:
        """Load all YAML standard files from a directory. Returns count loaded."""
        try:
            import yaml
        except ImportError:
            logger.warning("PyYAML not installed — cannot load standards")
            return 0

        if not os.path.isdir(dir_path):
            logger.warning("Standards directory does not exist: %s", dir_path)
            return 0

        count = 0
        for fname in sorted(os.listdir(dir_path)):
            if not fname.endswith(('.yaml', '.yml')):
                continue
            fpath = os.path.join(dir_path, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                if not data or not isinstance(data, dict):
                    continue
                std = cls._parse_standard(data)
                if std:
                    cls._standards[std.id] = std
                    count += 1
                    logger.debug("Loaded standard: %s (%s)", std.id, std.name)
            except Exception as e:
                logger.warning("Failed to load standard %s: %s", fname, e)
        return count

    @classmethod
    def _parse_standard(cls, data: dict) -> Optional[DataStandard]:
        sid = data.get("id")
        if not sid:
            return None
        fields = []
        for fd in data.get("fields", []):
            if not fd.get("name"):
                continue
            fields.append(FieldSpec(
                name=fd["name"],
                type=fd.get("type", "string"),
                required=fd.get("required", "O"),
                max_length=fd.get("max_length"),
                allowed=fd.get("allowed"),
                description=fd.get("description", ""),
            ))
        return DataStandard(
            id=sid,
            name=data.get("name", sid),
            version=data.get("version", "1.0"),
            source=data.get("source", ""),
            description=data.get("description", ""),
            fields=fields,
            code_tables=data.get("code_tables", {}),
            formulas=data.get("formulas", []),
        )

    @classmethod
    def get(cls, standard_id: str) -> Optional[DataStandard]:
        cls._ensure_loaded()
        return cls._standards.get(standard_id)

    @classmethod
    def list_standards(cls) -> list[dict]:
        cls._ensure_loaded()
        return [
            {"id": s.id, "name": s.name, "version": s.version,
             "source": s.source, "field_count": len(s.fields),
             "code_table_count": len(s.code_tables)}
            for s in cls._standards.values()
        ]

    @classmethod
    def all_ids(cls) -> list[str]:
        cls._ensure_loaded()
        return list(cls._standards.keys())

    @classmethod
    def get_field_schema(cls, standard_id: str) -> dict:
        """Convert a standard to check_field_standards compatible schema dict.

        Returns dict like: {"DLBM": {"type": "string", "allowed": [...]}, ...}
        """
        std = cls.get(standard_id)
        if not std:
            return {}
        schema = {}
        for f in std.fields:
            entry: dict = {}
            if f.type:
                entry["type"] = f.type
            if f.allowed:
                entry["allowed"] = f.allowed
            elif f.name in std.code_tables:
                codes = [item.get("code", item.get("value", ""))
                         for item in std.code_tables[f.name] if item]
                if codes:
                    entry["allowed"] = codes
            if entry:
                schema[f.name] = entry
        return schema

    @classmethod
    def get_code_table(cls, standard_id: str, table_name: str) -> list[dict]:
        """Get a specific code table from a standard."""
        std = cls.get(standard_id)
        if not std:
            return []
        return std.code_tables.get(table_name, [])

    @classmethod
    def get_code_mapping(cls, mapping_id: str) -> Optional[dict]:
        """Load a code mapping file from standards/code_mappings/ directory."""
        try:
            import yaml
        except ImportError:
            return None
        mappings_dir = os.path.join(_STANDARDS_DIR, "code_mappings")
        for fname in os.listdir(mappings_dir) if os.path.isdir(mappings_dir) else []:
            if not fname.endswith(('.yaml', '.yml')):
                continue
            fpath = os.path.join(mappings_dir, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                if data and data.get("id") == mapping_id:
                    return data
            except Exception:
                continue
        return None

    @classmethod
    def reset(cls):
        """Clear loaded standards (for testing)."""
        cls._standards.clear()
        cls._loaded = False


# ---------------------------------------------------------------------------
# Defect Taxonomy
# ---------------------------------------------------------------------------

@dataclass
class DefectType:
    """Single defect type definition within the taxonomy."""
    code: str               # e.g. "FMT-001"
    category: str           # format_error | precision_deviation | topology_error | info_missing | norm_violation
    severity: str           # A (critical) | B (major) | C (minor)
    name: str
    description: str = ""
    product_types: list[str] = field(default_factory=list)
    auto_fixable: bool = False
    fix_strategy: str = ""


@dataclass
class DefectCategory:
    """A top-level defect category."""
    id: str
    name: str
    description: str = ""


@dataclass
class SeverityLevel:
    """Severity level definition."""
    code: str       # A | B | C
    name: str
    weight: int = 1
    description: str = ""


class DefectTaxonomy:
    """Singleton registry of defect types loaded from defect_taxonomy.yaml.

    Provides structured access to the defect classification system used by
    governance audit, auto-fix engine, case library, and report generation.
    """

    _defects: dict[str, DefectType] = {}
    _categories: dict[str, DefectCategory] = {}
    _severity_levels: dict[str, SeverityLevel] = {}
    _loaded: bool = False

    @classmethod
    def _ensure_loaded(cls):
        if not cls._loaded:
            cls._load()
            cls._loaded = True

    @classmethod
    def _load(cls):
        """Load defect taxonomy from YAML file."""
        try:
            import yaml
        except ImportError:
            logger.warning("PyYAML not installed — cannot load defect taxonomy")
            return

        fpath = os.path.join(_STANDARDS_DIR, "defect_taxonomy.yaml")
        if not os.path.isfile(fpath):
            logger.warning("Defect taxonomy file not found: %s", fpath)
            return

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception as e:
            logger.warning("Failed to load defect taxonomy: %s", e)
            return

        if not data or not isinstance(data, dict):
            return

        # Parse severity levels
        for sl in data.get("severity_levels", []):
            code = sl.get("code", "")
            if code:
                cls._severity_levels[code] = SeverityLevel(
                    code=code,
                    name=sl.get("name", code),
                    weight=sl.get("weight", 1),
                    description=sl.get("description", ""),
                )

        # Parse categories
        for cat in data.get("categories", []):
            cid = cat.get("id", "")
            if cid:
                cls._categories[cid] = DefectCategory(
                    id=cid,
                    name=cat.get("name", cid),
                    description=cat.get("description", ""),
                )

        # Parse defect types
        for d in data.get("defects", []):
            code = d.get("code", "")
            if not code:
                continue
            cls._defects[code] = DefectType(
                code=code,
                category=d.get("category", ""),
                severity=d.get("severity", "C"),
                name=d.get("name", ""),
                description=d.get("description", ""),
                product_types=d.get("product_types", []),
                auto_fixable=d.get("auto_fixable", False),
                fix_strategy=d.get("fix_strategy", ""),
            )

        logger.debug(
            "Loaded defect taxonomy: %d defects, %d categories, %d severity levels",
            len(cls._defects), len(cls._categories), len(cls._severity_levels),
        )

    # --- Query methods ---

    @classmethod
    def get_by_code(cls, code: str) -> Optional[DefectType]:
        """Get a defect type by its code (e.g. 'FMT-001')."""
        cls._ensure_loaded()
        return cls._defects.get(code)

    @classmethod
    def get_by_category(cls, category: str) -> list[DefectType]:
        """Get all defect types in a category (e.g. 'format_error')."""
        cls._ensure_loaded()
        return [d for d in cls._defects.values() if d.category == category]

    @classmethod
    def get_by_severity(cls, severity: str) -> list[DefectType]:
        """Get all defect types of a severity level (A/B/C)."""
        cls._ensure_loaded()
        return [d for d in cls._defects.values() if d.severity == severity]

    @classmethod
    def get_auto_fixable(cls) -> list[DefectType]:
        """Get all defect types that can be automatically fixed."""
        cls._ensure_loaded()
        return [d for d in cls._defects.values() if d.auto_fixable]

    @classmethod
    def get_for_product(cls, product_type: str) -> list[DefectType]:
        """Get all defect types applicable to a product type (e.g. 'CAD')."""
        cls._ensure_loaded()
        return [d for d in cls._defects.values() if product_type in d.product_types]

    @classmethod
    def all_defects(cls) -> list[DefectType]:
        """Get all defect types."""
        cls._ensure_loaded()
        return list(cls._defects.values())

    @classmethod
    def all_categories(cls) -> list[DefectCategory]:
        """Get all defect categories."""
        cls._ensure_loaded()
        return list(cls._categories.values())

    @classmethod
    def all_severity_levels(cls) -> list[SeverityLevel]:
        """Get all severity levels."""
        cls._ensure_loaded()
        return list(cls._severity_levels.values())

    @classmethod
    def get_severity_weight(cls, severity: str) -> int:
        """Get the weight for a severity level code."""
        cls._ensure_loaded()
        sl = cls._severity_levels.get(severity)
        return sl.weight if sl else 1

    @classmethod
    def compute_quality_score(cls, defect_codes: list[str], total_items: int = 100) -> dict:
        """Compute a quality score based on found defects.

        Uses GB/T 24356 weighted scoring: score = 100 - sum(severity_weight * count) / total_items * 100
        Returns dict with score, grade, category_breakdown.
        """
        cls._ensure_loaded()
        if total_items <= 0:
            return {"score": 0, "grade": "不合格", "defect_count": len(defect_codes)}

        weighted_sum = 0
        category_counts: dict[str, int] = {}
        severity_counts: dict[str, int] = {"A": 0, "B": 0, "C": 0}

        for code in defect_codes:
            dt = cls._defects.get(code)
            if not dt:
                continue
            weight = cls.get_severity_weight(dt.severity)
            weighted_sum += weight
            category_counts[dt.category] = category_counts.get(dt.category, 0) + 1
            severity_counts[dt.severity] = severity_counts.get(dt.severity, 0) + 1

        score = max(0, 100 - (weighted_sum / total_items) * 100)
        score = round(score, 1)

        if score >= 90:
            grade = "优秀"
        elif score >= 75:
            grade = "良好"
        elif score >= 60:
            grade = "合格"
        else:
            grade = "不合格"

        return {
            "score": score,
            "grade": grade,
            "defect_count": len(defect_codes),
            "weighted_sum": weighted_sum,
            "severity_counts": severity_counts,
            "category_counts": category_counts,
        }

    @classmethod
    def list_summary(cls) -> list[dict]:
        """Return a summary list of all defect types for API/UI display."""
        cls._ensure_loaded()
        return [
            {
                "code": d.code,
                "category": d.category,
                "severity": d.severity,
                "name": d.name,
                "auto_fixable": d.auto_fixable,
                "product_types": d.product_types,
            }
            for d in cls._defects.values()
        ]

    @classmethod
    def reset(cls):
        """Clear loaded taxonomy (for testing)."""
        cls._defects.clear()
        cls._categories.clear()
        cls._severity_levels.clear()
        cls._loaded = False
