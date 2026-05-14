"""Dispatches incoming files to the right parser. Returns a normalised dict."""
from __future__ import annotations

from pathlib import Path

from ...standards.docx_extractor import extract as docx_extract
from ...standards.xmi_parser import parse_xmi_file
from ...observability import get_logger

logger = get_logger("standards_platform.ingestion.extractor_runner")


def run_extractor(file_path: str, *, module_name: str | None = None) -> dict:
    ext = Path(file_path).suffix.lower()
    if ext == ".docx":
        return docx_extract(file_path, module_name or Path(file_path).stem)
    if ext == ".xmi":
        result = parse_xmi_file(file_path)
        return {"modules": getattr(result, "modules", []),
                "classes": getattr(result, "classes", []),
                "associations": getattr(result, "associations", [])}
    raise ValueError(f"unsupported extension: {ext}")
