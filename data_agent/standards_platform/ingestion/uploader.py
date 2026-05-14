"""File-upload intake: place in user sandbox, create std_document + initial version,
enqueue extract_requested event."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from ...observability import get_logger
from ...user_context import current_user_id, get_user_upload_dir
from .. import outbox, repository

logger = get_logger("standards_platform.ingestion.uploader")

SUPPORTED_EXT = {".docx", ".xmi", ".pdf"}


def ingest_upload(file_path: Path, *, original_name: str,
                  source_type: str = "enterprise",
                  source_url: str | None = None) -> tuple[str, str]:
    """Copy incoming file to the user's sandbox, create doc+version, enqueue extract.

    Returns (document_id, version_id).
    Raises ValueError for unsupported file types or missing user context.
    """
    ext = Path(original_name).suffix.lower()
    if ext not in SUPPORTED_EXT:
        raise ValueError(f"unsupported file type: {ext}")

    user_id = current_user_id.get()
    if not user_id:
        raise ValueError("missing user context; cannot sandbox upload")

    sandbox = Path(get_user_upload_dir()) / "standards"
    sandbox.mkdir(parents=True, exist_ok=True)
    stable_name = f"{uuid.uuid4().hex}{ext}"
    dest = sandbox / stable_name
    shutil.copyfile(file_path, dest)

    doc_code = Path(original_name).stem[:200]

    doc_id = repository.create_document(
        doc_code=doc_code, title=Path(original_name).stem,
        source_type=source_type, owner_user_id=user_id,
        raw_file_path=str(dest), source_url=source_url,
    )
    ver_id = repository.create_version(
        document_id=doc_id, version_label="v1.0", created_by=user_id,
    )
    repository.set_current_version(doc_id, ver_id)

    outbox.enqueue("extract_requested", {
        "document_id": doc_id, "version_id": ver_id,
        "file_path": str(dest), "ext": ext,
    })
    logger.info("ingested document_id=%s version_id=%s ext=%s", doc_id, ver_id, ext)
    return doc_id, ver_id
