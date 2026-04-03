"""Fusion v2.0 — LLM Semantic Understanding module.

Uses Gemini for deep field semantics understanding, derivable field inference,
and semantic field matching between data sources.
"""
import json
import logging
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
            return {"semantic_type": "unknown", "unit": "", "description": "", "equivalent_terms": []}
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return {"semantic_type": "unknown", "unit": "", "description": text, "equivalent_terms": []}

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
            return None
        try:
            result = json.loads(text)
            if result.get("derivable"):
                return result.get("formula")
        except (json.JSONDecodeError, TypeError):
            pass
        return None

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
            return []
        try:
            matches = json.loads(text)
            if isinstance(matches, list):
                return matches
        except (json.JSONDecodeError, TypeError):
            pass
        return []

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
            return {}
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, TypeError):
            pass
        return {}

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
