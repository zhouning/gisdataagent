"""LLM-based source_type + doc_code classification."""
from __future__ import annotations

import json
import re
from typing import Optional

from ...model_gateway import create_model
from ...observability import get_logger

logger = get_logger("standards_platform.ingestion.classifier")

_PROMPT = """你是数据标准元数据抽取助手。给定标准文档的文件名与开头片段，
返回严格 JSON：{{"source_type": one of [national,industry,enterprise,international,draft],
"doc_code": "...", "confidence": 0..1}}。
- national 例：GB / GB/T  - industry 例：CJ / CH / TD / SL
- international 例：ISO / IEC / OGC  - enterprise 例：内部编号
- 不能识别时 source_type=draft，doc_code 用文件名 stem。
filename: {filename}
excerpt: {excerpt}
"""


def classify(*, filename: str, text_excerpt: str,
             model_name: str = "gemini-2.5-flash") -> dict:
    excerpt = text_excerpt[:1500]
    try:
        model = create_model(model_name)
        rsp = model.generate(_PROMPT.format(filename=filename, excerpt=excerpt))
        raw = getattr(rsp, "text", "") or str(rsp)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            raise ValueError("no JSON in LLM response")
        data = json.loads(m.group(0))
        return {
            "source_type": data.get("source_type", "draft"),
            "doc_code": data.get("doc_code") or filename.rsplit(".", 1)[0],
            "confidence": float(data.get("confidence", 0.0)),
        }
    except Exception as e:
        logger.warning("classify failed: %s", e)
        return {"source_type": "draft",
                "doc_code": filename.rsplit(".", 1)[0],
                "confidence": 0.0}
