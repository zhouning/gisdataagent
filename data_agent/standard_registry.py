"""
Data Standard Registry — 预置行业数据标准，驱动自动化治理 (v14.5).

标准定义文件存放在 ``data_agent/standards/`` 目录 (YAML 格式)。
``StandardRegistry`` 在首次使用时自动加载所有标准，提供按 ID 查询、
列表、以及转为 ``check_field_standards`` 兼容 schema dict 的能力。
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
