"""LLM-based schema alignment — use Gemini to map fields across data sources.

Replaces fragile regex/pinyin rules with a single LLM call that does full
schema-level reasoning. Opt-in via use_llm_schema=True in _find_field_matches().
"""
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def llm_align_schemas(
    left_columns: list[dict],
    right_columns: list[dict],
    domain_context: str = "",
) -> list[dict]:
    """Use Gemini 2.0 Flash to align two table schemas.

    Sends column metadata (name, dtype, null_pct, sample_values) to the LLM
    and gets back a structured field mapping.

    Args:
        left_columns: Column metadata from source 1.
        right_columns: Column metadata from source 2.
        domain_context: Optional domain context (e.g., "land use", "census").

    Returns:
        List of match dicts: [{left, right, confidence, reasoning}, ...]
        Empty list on failure (graceful degradation).
    """
    if not left_columns or not right_columns:
        return []

    # Format column info concisely
    def _fmt_cols(cols):
        return [
            {
                "name": c.get("name", ""),
                "dtype": c.get("dtype", ""),
                "null_pct": c.get("null_pct", 0),
            }
            for c in cols[:30]  # cap at 30 columns
        ]

    left_info = json.dumps(_fmt_cols(left_columns), ensure_ascii=False)
    right_info = json.dumps(_fmt_cols(right_columns), ensure_ascii=False)

    prompt = (
        "你是GIS数据融合专家。请分析两个数据源的字段列表，"
        "找出语义上对应的字段对。\n\n"
        f"数据源A字段:\n{left_info}\n\n"
        f"数据源B字段:\n{right_info}\n\n"
        + (f"领域上下文: {domain_context}\n\n" if domain_context else "")
        + "请返回JSON数组，每个元素格式:\n"
        '{"left": "字段A名", "right": "字段B名", "confidence": 0.0-1.0, "reasoning": "理由"}\n'
        "只返回JSON数组。不匹配的字段不要包含。"
    )

    try:
        from google import genai
        client = genai.Client()
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        text = response.text.strip()
        # Strip markdown code fence if present
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        matches = json.loads(text)
        if not isinstance(matches, list):
            logger.warning("LLM schema alignment returned non-list: %s", type(matches))
            return []

        # Validate and normalize
        valid = []
        left_names = {c.get("name", "").lower() for c in left_columns}
        right_names = {c.get("name", "").lower() for c in right_columns}

        for m in matches:
            left_name = m.get("left", "")
            right_name = m.get("right", "")
            confidence = m.get("confidence", 0.7)

            if (left_name.lower() in left_names and
                    right_name.lower() in right_names and
                    confidence >= 0.5):
                valid.append({
                    "left": left_name,
                    "right": right_name,
                    "confidence": round(float(confidence), 2),
                    "match_type": "llm_schema",
                    "reasoning": m.get("reasoning", ""),
                })

        logger.info("LLM schema alignment: %d/%d matches validated", len(valid), len(matches))
        return valid

    except Exception as e:
        logger.warning("LLM schema alignment failed: %s — falling back to heuristics", e)
        return []
