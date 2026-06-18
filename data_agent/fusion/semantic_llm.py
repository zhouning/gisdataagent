"""Fusion v2.0 — LLM Semantic Understanding module.

Uses Gemini for deep field semantics understanding, derivable field inference,
and semantic field matching between data sources.
"""
import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


class SemanticLLM:
    """LLM-driven semantic understanding for data fusion field matching."""

    def __init__(self, model: str = "gemini-2.5-flash"):
        self.model = model

    async def understand_field_semantics(
        self,
        field_name: str,
        sample_values: list,
        context: str = "",
    ) -> dict:
        """Classify a field's semantic type, unit, and description.

        Args:
            field_name: Column name.
            sample_values: Sample values from the column.
            context: Optional context (e.g., data source description).

        Returns:
            Dict with {semantic_type, unit, description, equivalent_terms}.
        """
        prompt = (
            "你是 GIS 数据分析专家。请根据字段名和样本值，判断该字段的语义类型。\n\n"
            f"字段名: {field_name}\n"
            f"样本值: {sample_values[:10]}\n"
            + (f"上下文: {context}\n" if context else "")
            + '\n请返回JSON: {"semantic_type": "类型", "unit": "单位或空", '
            '"description": "中文描述", "equivalent_terms": ["等价术语"]}\n'
            "只返回JSON。"
        )
        text = await self._call_gemini(prompt)
        if not text:
            return _fallback_field_semantics(field_name, sample_values, context)
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return _normalize_semantic_type_payload(parsed, field_name)
        except (json.JSONDecodeError, TypeError):
            return _fallback_field_semantics(field_name, sample_values, context, description=text)
        return _fallback_field_semantics(field_name, sample_values, context)

    async def infer_derivable_fields(
        self,
        available_fields: list[str],
        target_field: str,
    ) -> Optional[str]:
        """Ask LLM if target_field can be computed from available_fields.

        Returns:
            Formula string (e.g., "floors * 3.0") or None if not derivable.
        """
        prompt = (
            "你是 GIS 数据处理专家。请判断目标字段是否能从已有字段计算得出。\n\n"
            f"已有字段: {available_fields}\n"
            f"目标字段: {target_field}\n\n"
            '如果可以，返回 JSON: {"derivable": true, "formula": "计算公式", "description": "说明"}\n'
            '如果不可以，返回: {"derivable": false}\n'
            "只返回JSON。"
        )
        text = await self._call_gemini(prompt)
        if not text:
            return _fallback_derivable_formula(available_fields, target_field)
        try:
            result = json.loads(text)
            if result.get("derivable"):
                return result.get("formula")
        except (json.JSONDecodeError, TypeError):
            pass
        return _fallback_derivable_formula(available_fields, target_field)

    async def match_fields_semantically(
        self,
        source_fields: list[dict],
        target_fields: list[dict],
    ) -> list[dict]:
        """Deep semantic matching of two field sets using a single LLM call.

        Args:
            source_fields: List of {name, dtype, sample_values}.
            target_fields: List of {name, dtype, sample_values}.

        Returns:
            List of {left, right, confidence, reasoning}.
        """
        # Truncate sample values for prompt efficiency
        src_info = [{
            "name": f["name"],
            "dtype": f.get("dtype", ""),
            "samples": f.get("sample_values", [])[:5],
        } for f in source_fields[:20]]

        tgt_info = [{
            "name": f["name"],
            "dtype": f.get("dtype", ""),
            "samples": f.get("sample_values", [])[:5],
        } for f in target_fields[:20]]

        prompt = (
            "你是 GIS 数据融合专家。请将源字段与目标字段进行语义匹配。\n\n"
            f"源字段:\n{json.dumps(src_info, ensure_ascii=False, indent=2)}\n\n"
            f"目标字段:\n{json.dumps(tgt_info, ensure_ascii=False, indent=2)}\n\n"
            '返回 JSON 数组: [{"left": "源字段名", "right": "目标字段名", '
            '"confidence": 0.0-1.0, "reasoning": "匹配理由"}]\n'
            "只匹配语义相同的字段对，不确定的不要匹配。只返回JSON数组。"
        )
        text = await self._call_gemini(prompt)
        if not text:
            return _fallback_field_matches(source_fields, target_fields)
        try:
            matches = json.loads(text)
            if isinstance(matches, list):
                normalized = []
                for match in matches:
                    if isinstance(match, dict) and match.get("left") and match.get("right"):
                        normalized.append({
                            "left": match["left"],
                            "right": match["right"],
                            "confidence": _safe_float(match.get("confidence"), 0.0),
                            "reasoning": str(match.get("reasoning") or match.get("reason") or ""),
                        })
                return normalized or _fallback_field_matches(source_fields, target_fields)
        except (json.JSONDecodeError, TypeError):
            pass
        return _fallback_field_matches(source_fields, target_fields)

    async def detect_semantic_types(
        self,
        columns: list[dict],
    ) -> dict[str, str]:
        """Batch classify all columns into semantic types.

        Args:
            columns: List of {name, dtype, sample_values}.

        Returns:
            {column_name: semantic_type}.
        """
        col_info = [{
            "name": c["name"],
            "dtype": c.get("dtype", ""),
            "samples": c.get("sample_values", [])[:5],
        } for c in columns[:30]]

        prompt = (
            "你是 GIS 数据分类专家。请为每个字段标注语义类型。\n\n"
            f"字段列表:\n{json.dumps(col_info, ensure_ascii=False, indent=2)}\n\n"
            '返回 JSON 对象: {"字段名": "语义类型"}\n'
            "常见语义类型: id, name, area, perimeter, elevation, slope, "
            "land_use, address, coordinate, date, population, building, unknown\n"
            "只返回JSON。"
        )
        text = await self._call_gemini(prompt)
        if not text:
            return _fallback_semantic_types(columns)
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return _normalize_semantic_types_map(result, columns)
        except (json.JSONDecodeError, TypeError):
            pass
        return _fallback_semantic_types(columns)

    async def _call_gemini(self, prompt: str) -> str:
        """Call Gemini API with graceful degradation.

        Returns raw text (markdown fences stripped) or "" on failure.
        """
        try:
            from google import genai
            client = genai.Client()
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
            )
            text = response.text.strip()
            # Strip markdown code fence
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            return text
        except Exception as e:
            logger.warning("Gemini API call failed: %s", e)
            return ""


def _fallback_field_semantics(field_name: str, sample_values: list, context: str, description: str = "") -> dict:
    name = str(field_name or "")
    lname = name.lower()
    samples = [value for value in sample_values if value is not None][:10]
    semantic_type = _guess_semantic_type(name, samples, context)
    unit = _guess_unit(name, samples)
    if not description:
        description = _fallback_description(name, semantic_type, context)
    return {
        "semantic_type": semantic_type,
        "unit": unit,
        "description": description,
        "equivalent_terms": _equivalent_terms(name, semantic_type),
    }


def _fallback_derivable_formula(available_fields: list[str], target_field: str) -> Optional[str]:
    available = {str(field).lower() for field in available_fields}
    target = str(target_field or "").lower()
    if target in {"building_height", "height"} and "floors" in available:
        return "floors * 3.0"
    if target in {"area", "mj", "tbmj"} and {"length", "width"}.issubset(available):
        return "length * width"
    return None


def _fallback_field_matches(source_fields: list[dict], target_fields: list[dict]) -> list[dict]:
    matches = []
    used_targets = set()
    for src in source_fields:
        src_name = str(src.get("name") or "")
        src_type = _guess_semantic_type(src_name, src.get("sample_values") or [], "")
        src_norm = _normalize_name(src_name)
        for tgt in target_fields:
            tgt_name = str(tgt.get("name") or "")
            tgt_norm = _normalize_name(tgt_name)
            if not tgt_norm or tgt_norm in used_targets:
                continue
            if src_norm == tgt_norm or _names_semantically_equivalent(src_norm, tgt_norm, src_type):
                matches.append({
                    "left": src_name,
                    "right": tgt_name,
                    "confidence": 0.9 if src_norm == tgt_norm else 0.82,
                    "reasoning": "offline semantic fallback",
                })
                used_targets.add(tgt_norm)
                break
    return matches


def _fallback_semantic_types(columns: list[dict]) -> dict[str, str]:
    result = {}
    for column in columns:
        name = str(column.get("name") or "")
        if not name:
            continue
        result[name] = _guess_semantic_type(name, column.get("sample_values") or [], "")
    return result


def _normalize_semantic_type_payload(payload: dict, field_name: str) -> dict:
    semantic_type = str(payload.get("semantic_type") or payload.get("type") or "unknown")
    unit = str(payload.get("unit") or "")
    description = str(payload.get("description") or "")
    equivalent_terms = payload.get("equivalent_terms")
    if not isinstance(equivalent_terms, list):
        equivalent_terms = []
    return {
        "semantic_type": semantic_type,
        "unit": unit,
        "description": description,
        "equivalent_terms": [str(item) for item in equivalent_terms if item],
    }


def _normalize_semantic_types_map(payload: dict, columns: list[dict]) -> dict[str, str]:
    allowed = {}
    names = {str(column.get("name") or "") for column in columns if column.get("name")}
    for key, value in payload.items():
        if key in names:
            allowed[key] = str(value or "unknown")
    return allowed or _fallback_semantic_types(columns)


def _guess_semantic_type(field_name: str, sample_values: list, context: str) -> str:
    text = " ".join([field_name, context, " ".join(str(v) for v in sample_values[:5])]).lower()
    if any(token in text for token in ("面积", "area", "mj", "tbmj", "shape_area")):
        return "area"
    if any(token in text for token in ("高程", "elev", "elevation", "altitude", "dem", "height")):
        return "elevation"
    if any(token in text for token in ("坡度", "slope", "gradient")):
        return "slope"
    if any(token in text for token in ("人口", "population", "pop")):
        return "population"
    if any(token in text for token in ("楼层", "floors", "floor", "cs")):
        return "building"
    if any(token in text for token in ("地类", "land_use", "dlbm", "用地")):
        return "land_use"
    if any(token in text for token in ("日期", "time", "date", "updated", "created")):
        return "date"
    if any(token in text for token in ("id", "编号", "编码", "code", "parcel", "object")):
        return "id"
    return "unknown"


def _guess_unit(field_name: str, sample_values: list) -> str:
    text = str(field_name).lower()
    if any(token in text for token in ("area", "mj", "tbmj")):
        return "m²"
    if any(token in text for token in ("height", "elev", "elevation")):
        return "m"
    return ""


def _fallback_description(field_name: str, semantic_type: str, context: str) -> str:
    if semantic_type == "unknown":
        return f"字段 {field_name} 的语义类型未知"
    if semantic_type == "area":
        return f"字段 {field_name} 表示面积"
    if semantic_type == "land_use":
        return f"字段 {field_name} 表示地类或用地类型"
    if semantic_type == "building":
        return f"字段 {field_name} 表示建筑相关信息"
    if semantic_type == "date":
        return f"字段 {field_name} 表示时间或日期"
    return f"字段 {field_name} 的语义类型为 {semantic_type}"


def _equivalent_terms(field_name: str, semantic_type: str) -> list[str]:
    mapping = {
        "area": ["面积", "AREA", "MJ", "TBMJ"],
        "elevation": ["高程", "elev", "elevation", "altitude", "DEM"],
        "slope": ["坡度", "slope"],
        "population": ["人口", "population", "pop"],
        "building": ["楼层", "floors", "floor", "层数"],
        "land_use": ["地类", "用地", "land_use", "DLBM"],
        "date": ["日期", "时间", "date", "time"],
        "id": ["编号", "编码", "id", "code"],
    }
    return mapping.get(semantic_type, [])


def _names_semantically_equivalent(a: str, b: str, semantic_type: str) -> bool:
    if a == b:
        return True
    terms = {_normalize_name(term) for term in _equivalent_terms("", semantic_type)}
    return a in terms and b in terms


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower())


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
