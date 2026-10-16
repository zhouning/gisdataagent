"""Authenticated chat adapter for registered BIRD product sources."""
from __future__ import annotations

import asyncio
import json
import logging
import time

logger = logging.getLogger(__name__)


def visible_chat_sources() -> list[dict]:
    from sqlalchemy import text
    from .db_engine import get_engine
    from .user_context import current_user_id, current_user_role

    username = current_user_id.get()
    if not username or username == "anonymous":
        return []
    engine = get_engine()
    if engine is None:
        raise RuntimeError("Source catalog unavailable")
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT db_id,source_name,table_count FROM agent_bird_databases
            WHERE owner_username=:username OR :is_admin ORDER BY db_id
        """), {"username": username, "is_admin": current_user_role.get() == "admin"}).all()
    return [{"db_id": row[0], "label": row[1], "table_count": row[2]} for row in rows]


def _run_selected_question(question: str, db_id: str) -> dict:
    from .bird_source import registered_database
    from .nl2sql_executor import run_nl2semantic2sql

    # A browser selection never grants access. Validate under this request's
    # authenticated identity, before model invocation, and again at execution.
    registered_database(db_id)
    return json.loads(run_nl2semantic2sql(question, execution_engine="postgis", bird_db_id=db_id))


def answer_presentation(report: dict, db_id: str, language: str, total_ms: float) -> dict | None:
    result = report.get("execution") or {}
    if report.get("status") != "ok" or result.get("status") != "ok":
        return None
    rows = result.get("data") or []
    columns = result.get("columns") or []
    calls = report.get("llm_calls") or []
    usage = report.get("llm_usage") or {}
    row_count = int(result.get("rows") or 0)
    return {
        "schema": "nl2sql.answer.v1", "language": language,
        "title": {"zh": "查询结果", "en": "Query results", "ar": "نتائج الاستعلام"}[language],
        "row_count": row_count, "displayed_row_count": len(rows),
        "truncated": bool(result.get("truncated")) or row_count > len(rows),
        "columns": [{"key": name, "label": name, "role": "attribute", "numeric": False} for name in columns],
        "rows": rows, "visualization": {"kind": "table"}, "timing": {"total_ms": total_ms},
        "model": {"invoked": bool(calls), "model": calls[-1].get("model") if calls else None,
                  "input_tokens": usage.get("input_tokens", 0), "output_tokens": usage.get("output_tokens", 0)},
        "evidence": {"database_name": f"bird_{db_id}", "read_only": True, "sql": report.get("sql")},
    }


async def handle_bird_chat(question: str, metadata: dict) -> bool:
    """Return true only for an explicit selection, including denied selections."""
    db_id = metadata.get("nl2sql_bird_db_id")
    if db_id is None or db_id == "":
        return False
    import chainlit as cl
    from .bird_source import DB_ID_RE

    language = str(metadata.get("locale") or "zh").split("-")[0]
    language = language if language in {"zh", "en", "ar"} else "en"
    errors = {
        "zh": "所选数据源不可用或你没有访问权限。请重新选择数据源。",
        "en": "The selected source is unavailable or you do not have access. Please select a source again.",
        "ar": "مصدر البيانات المحدد غير متاح أو ليس لديك إذن للوصول إليه. يرجى الاختيار مرة أخرى.",
    }
    if not isinstance(db_id, str) or not DB_ID_RE.fullmatch(db_id):
        await cl.Message(content=errors[language]).send()
        return True
    progress = cl.Message(content={"zh": "正在查询所选数据源…", "en": "Querying the selected source…",
                                   "ar": "جارٍ الاستعلام من مصدر البيانات المحدد…"}[language])
    await progress.send()
    started = time.perf_counter()
    try:
        # to_thread copies ContextVars; retain the authenticated user and role.
        report = await asyncio.to_thread(_run_selected_question, question, db_id)
        presentation = answer_presentation(report, db_id, language, (time.perf_counter() - started) * 1000)
        progress.metadata = {"routing_info": {"intent": "NL2SQL", "pipeline": "run_nl2semantic2sql",
                                               "pipeline_name": f"BIRD · {db_id}"},
                             "bird_query": {"db_id": db_id, "status": report.get("status"),
                                            "query_policy": report.get("query_policy") or {},
                                            "registered_ir_status": (report.get("registered_ir") or {}).get("status")}}
        if presentation is not None:
            progress.content = presentation["title"]
            progress.metadata["nl2sql_presentation"] = presentation
        else:
            logger.warning("Selected BIRD query failed source=%s status=%s", db_id, report.get("status"))
            if report.get("error") == "query_unsupported":
                progress.content = {"zh": "当前查询能力暂不支持这个问题所需的计算，未执行查询。请调整问题或联系管理员完善指标配置。",
                                    "en": "This question requires a calculation that is not supported yet. No query was executed. Please revise the question or ask an administrator to update the metric configuration.",
                                    "ar": "يتطلب هذا السؤال حساباً غير مدعوم حالياً. لم يُنفذ أي استعلام. يرجى تعديل السؤال أو طلب تحديث إعدادات المقاييس من المسؤول."}[language]
            else:
                progress.content = {"zh": "此次查询未能完成，请检查问题或数据源配置。", "en": "The query could not be completed. Check the question or source configuration.",
                                    "ar": "تعذر إكمال الاستعلام. يرجى مراجعة السؤال أو إعدادات المصدر."}[language]
    except (PermissionError, ValueError):
        progress.content = errors[language]
    except Exception:
        logger.exception("Selected BIRD chat query failed")
        progress.content = {"zh": "查询服务暂时不可用，请稍后重试。", "en": "The query service is temporarily unavailable. Please try again.",
                            "ar": "خدمة الاستعلام غير متاحة مؤقتاً. يرجى المحاولة مرة أخرى."}[language]
    await progress.update()
    cl.user_session.set("last_response_text", progress.content)
    return True
