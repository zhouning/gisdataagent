"""Take docx_extractor or xmi_parser output and write to std_clause /
std_term / std_data_element / std_value_domain. Idempotent (UPSERT by
(document_version_id, ordinal_path/code)).
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text

from ...db_engine import get_engine
from ...observability import get_logger

logger = get_logger("standards_platform.analysis.structurer")


def _ordinal_to_ltree(clause_no: str) -> str:
    cleaned = clause_no.strip().replace(" ", "")
    if not cleaned:
        return "0"
    return cleaned.replace(".", ".")  # already dotted; ltree accepts


def structure_extracted(*, doc_id: str, version_id: str,
                        payload: dict) -> dict[str, int]:
    counts = {"clauses_inserted": 0, "data_elements_inserted": 0,
              "terms_inserted": 0, "value_domains_inserted": 0}
    eng = get_engine()
    if eng is None:
        return counts

    field_rows = payload.get("FieldTable", []) or []
    with eng.begin() as conn:
        clause_id_by_no: dict[str, str] = {}

        for row in field_rows:
            clause_no = str(row.get("clause_no") or row.get("ordinal") or "0")
            ord_path = _ordinal_to_ltree(clause_no)
            cid = str(uuid.uuid4())
            origin = {"page": row.get("page"), "char_span": row.get("char_span")}
            conn.execute(text("""
                INSERT INTO std_clause (id, document_id, document_version_id,
                    ordinal_path, heading, clause_no, kind, body_md, source_origin)
                VALUES (:i, :d, :v, CAST(:p AS ltree), :h, :n, :k, :b, CAST(:o AS jsonb))
                ON CONFLICT (document_version_id, ordinal_path) DO UPDATE
                  SET heading=EXCLUDED.heading, body_md=EXCLUDED.body_md,
                      kind=EXCLUDED.kind, updated_at=now()
                RETURNING id
            """), {"i": cid, "d": doc_id, "v": version_id, "p": ord_path,
                    "h": row.get("heading", ""), "n": clause_no,
                    "k": row.get("kind", "clause"),
                    "b": row.get("body_md", ""),
                    "o": json.dumps(origin, ensure_ascii=False)})
            clause_id_by_no[clause_no] = cid
            counts["clauses_inserted"] += 1
            for de in row.get("data_elements", []) or []:
                conn.execute(text("""
                    INSERT INTO std_data_element (document_version_id, code,
                        name_zh, name_en, definition, datatype, obligation,
                        defined_by_clause_id)
                    VALUES (:v, :c, :z, :e, :df, :dt, :ob, :cl)
                    ON CONFLICT (document_version_id, code) DO UPDATE
                      SET name_zh=EXCLUDED.name_zh, datatype=EXCLUDED.datatype
                """), {"v": version_id, "c": de["code"],
                        "z": de.get("name_zh"), "e": de.get("name_en"),
                        "df": de.get("definition"),
                        "dt": de.get("datatype"),
                        "ob": de.get("obligation", "optional"),
                        "cl": cid})
                counts["data_elements_inserted"] += 1
            for trm in row.get("terms", []) or []:
                conn.execute(text("""
                    INSERT INTO std_term (document_version_id, term_code,
                        name_zh, name_en, definition, defined_by_clause_id)
                    VALUES (:v, :tc, :z, :e, :df, :cl)
                    ON CONFLICT (document_version_id, term_code) DO UPDATE
                      SET name_zh=EXCLUDED.name_zh
                """), {"v": version_id, "tc": trm["term_code"],
                        "z": trm.get("name_zh"), "e": trm.get("name_en"),
                        "df": trm.get("definition"), "cl": cid})
                counts["terms_inserted"] += 1
    return counts
