"""LLM-grounded semantic query planning for governed DLTB data."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .dltb_vertical_demo import SEMANTIC_SOURCE, DLTBVerticalDemo
from .offline_ingest import _utc_now
from .openai_compatible_llm import (
    OpenAICompatibleLLMConfig,
    chat_completion,
)

ALLOWED_INTENTS = {
    "group_summary",
    "area_consistency",
    "parcel_lookup",
    "dataset_summary",
}
ALLOWED_GROUPS = {None, "land_use_code", "located_admin_name", "owner_admin_name"}
ALLOWED_METRICS = {"feature_count", "parcel_area_sqm", "area_pct"}
ALLOWED_FILTERS = {
    "feature_identifier": {"eq"},
    "land_use_code": {"eq", "prefix"},
    "land_use_name": {"eq", "contains"},
    "located_admin_name": {"eq", "contains"},
    "owner_admin_name": {"eq", "contains"},
}

SYSTEM_PROMPT = """你是 GIS Data Agent 的自然资源语义查询规划器。
你的任务不是直接回答问题，也不能生成 SQL；只能把问题转换为一个受控 JSON 语义 AST。

数据模型与本体约束：
- dataset 只能是 land_parcel_current，对应本体类 LandParcel（地类图斑）。
- 可用语义属性：feature_identifier（图斑标识/BSM）、land_use_code（地类编码/DLBM）、
  land_use_name（地类名称/DLMC）、located_admin_name（坐落单位/ZLDWMC）、
  owner_admin_name（权属单位/QSDWMC）、parcel_area_sqm（图斑面积/TBMJ）。
- intent 只能是 group_summary、area_consistency、parcel_lookup、dataset_summary。
- group_by 只能是 land_use_code、located_admin_name、owner_admin_name 或 null。
- metrics 只能从 feature_count、parcel_area_sqm、area_pct 中选择。
- filter operator 只能是 eq、prefix、contains。
- 耕地语义应转换为 land_use_code prefix 01。
- parcel_lookup 必须把编号放在 feature_identifier 的 eq filter 中。

只输出一个 JSON 对象，不要 Markdown、解释、SQL 或额外文字：
{"intent":"group_summary","dataset":"land_parcel_current","group_by":"land_use_code","metrics":["feature_count","parcel_area_sqm","area_pct"],"filters":[],"limit":100}
"""


def _strip_json_fence(value: str) -> str:
    text = str(value or "").strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.I | re.S)
    return match.group(1).strip() if match else text


def parse_semantic_ast(value: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        payload = dict(value)
    else:
        try:
            payload = json.loads(_strip_json_fence(value))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("LLM response is not a valid JSON semantic AST") from exc
    if not isinstance(payload, dict):
        raise ValueError("semantic AST must be a JSON object")
    if isinstance(payload.get("semantic_ast"), dict):
        payload = dict(payload["semantic_ast"])

    intent = str(payload.get("intent") or "").strip()
    if intent not in ALLOWED_INTENTS:
        raise ValueError(f"unsupported semantic intent: {intent or '<empty>'}")
    dataset = str(payload.get("dataset") or "").strip()
    if dataset != SEMANTIC_SOURCE:
        raise ValueError(f"unsupported semantic dataset: {dataset or '<empty>'}")
    group_by = payload.get("group_by")
    if group_by not in ALLOWED_GROUPS:
        raise ValueError(f"unsupported group_by field: {group_by}")

    metrics = payload.get("metrics") or []
    if not isinstance(metrics, list) or any(metric not in ALLOWED_METRICS for metric in metrics):
        raise ValueError("semantic AST contains an unsupported metric")
    filters = payload.get("filters") or []
    if not isinstance(filters, list) or len(filters) > 8:
        raise ValueError("semantic AST filters must be a list with at most 8 items")
    normalized_filters = []
    for item in filters:
        if not isinstance(item, dict):
            raise ValueError("each semantic filter must be an object")
        # Qwen occasionally emits the JSON-schema synonym ``attribute`` even
        # though the prompt names ``field``. Accept that one harmless alias,
        # then continue through the same strict whitelist.
        field = str(item.get("field") or item.get("attribute") or "").strip()
        operator = str(item.get("operator") or "").strip()
        value = item.get("value")
        if field not in ALLOWED_FILTERS or operator not in ALLOWED_FILTERS[field]:
            raise ValueError(f"unsupported semantic filter: {field} {operator}")
        if value is None or not str(value).strip() or len(str(value)) > 200:
            raise ValueError(f"invalid filter value for {field}")
        normalized_filters.append({"field": field, "operator": operator, "value": str(value)})

    if intent == "parcel_lookup" and not any(
        item["field"] == "feature_identifier" and item["operator"] == "eq"
        for item in normalized_filters
    ):
        raise ValueError("parcel_lookup requires feature_identifier eq filter")
    if intent == "group_summary" and group_by is None and not metrics:
        metrics = ["feature_count", "parcel_area_sqm"]

    try:
        limit = int(payload.get("limit") or 100)
    except (TypeError, ValueError) as exc:
        raise ValueError("semantic AST limit must be an integer") from exc
    limit = max(1, min(limit, 1000))
    return {
        "intent": intent,
        "dataset": dataset,
        "group_by": group_by,
        "metrics": list(dict.fromkeys(metrics)),
        "filters": normalized_filters,
        "limit": limit,
    }


def _append_audit(projection_path: str | Path, record: dict[str, Any]) -> None:
    projection_file = Path(projection_path).expanduser().resolve()
    if projection_file.is_dir():
        projection_file = projection_file / "semantic_projection.json"
    audit_path = projection_file.parent / "semantic_query_audit.jsonl"
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def query_dltb_with_llm(
    projection_path: str | Path,
    question: str,
    *,
    limit: int = 100,
    config: OpenAICompatibleLLMConfig | None = None,
    client_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Plan with Qwen, validate against ontology/semantic fields, then execute."""

    projection = DLTBVerticalDemo.load_projection(projection_path)
    field_names = json.dumps(
        sorted((projection.get("fields") or {}).keys()), ensure_ascii=False
    )
    user_prompt = (
        f"用户问题：{str(question).strip()}\n"
        f"调用方最大返回行数：{max(1, min(int(limit), 1000))}\n"
        f"当前语义投影字段：{field_names}"
    )
    raw, llm_evidence = chat_completion(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        config=config,
        max_tokens=800,
        client_factory=client_factory,
    )
    ast = parse_semantic_ast(raw)
    ast["limit"] = min(ast["limit"], max(1, min(int(limit), 1000)))
    result = DLTBVerticalDemo.execute_semantic_ast(projection_path, ast)
    query_id = str(uuid.uuid4())
    result.update(
        {
            "query_id": query_id,
            "question": str(question).strip(),
            "semantic_ast": ast,
            "llm": llm_evidence,
            "executor": {
                "engine": "geopandas",
                "source_kind": "governed_geoparquet",
                "projection_id": projection.get("projection_id"),
                "row_count": len(result.get("rows") or []),
                "status": "succeeded",
            },
        }
    )
    _append_audit(
        projection_path,
        {
            "schema": "gda.dltb-semantic-query-audit.v1",
            "query_id": query_id,
            "timestamp": _utc_now(),
            "question": str(question).strip(),
            "semantic_ast": ast,
            "llm": llm_evidence,
            "executor": result["executor"],
        },
    )
    return result
