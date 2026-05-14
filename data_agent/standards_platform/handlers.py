"""Event dispatch: event_type -> handler. Handlers chain subsequent events."""
from __future__ import annotations

from .ingestion.extractor_runner import run_extractor
from .analysis.structurer import structure_extracted
from .analysis.embedder import embed_version
from .analysis.deduper import find_similar_clauses
from .ingestion.web_fetcher import fetch as web_fetch, save_manual
from . import outbox, repository
from ..observability import get_logger

logger = get_logger("standards_platform.handlers")


def dispatch(event: dict) -> None:
    et = event["event_type"]; p = event["payload"]
    logger.info("dispatch %s (event_id=%s, attempts=%d)", et, event.get("id"),
                event.get("attempts", 0))
    if et == "extract_requested":
        extracted = run_extractor(p["file_path"])
        outbox.enqueue("structure_requested",
                       {"document_id": p["document_id"],
                        "version_id": p["version_id"],
                        "extracted": extracted})
    elif et == "structure_requested":
        structure_extracted(doc_id=p["document_id"], version_id=p["version_id"],
                            payload=p["extracted"])
        outbox.enqueue("embed_requested", {"version_id": p["version_id"]})
    elif et == "embed_requested":
        embed_version(version_id=p["version_id"])
        outbox.enqueue("dedupe_requested", {"version_id": p["version_id"]})
    elif et == "dedupe_requested":
        find_similar_clauses(version_id=p["version_id"])
        # Final step for P0: mark document as drafting.
        doc_id = p.get("document_id")
        if doc_id is None:
            eng = __import__("data_agent.db_engine", fromlist=["get_engine"]).get_engine()
            from sqlalchemy import text as _t
            with eng.connect() as c:
                row = c.execute(_t("SELECT document_id FROM std_document_version WHERE id = :v"),
                                {"v": p["version_id"]}).first()
                if row:
                    doc_id = row.document_id
        if doc_id:
            repository.update_document_status(doc_id, "drafting")
    elif et == "web_snapshot_requested":
        web_fetch(p["url"])
    else:
        raise ValueError(f"unknown event type: {et}")
