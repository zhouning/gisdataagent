"""
Multimodal input processing for GIS Data Agent.
Handles image understanding, PDF parsing, and file type classification.
"""

import io
import os
import logging
from enum import Enum
from typing import Optional

from google.genai import types

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Upload type classification
# ---------------------------------------------------------------------------

class UploadType(str, Enum):
    """Classification of uploaded file types."""
    SPATIAL = "spatial"
    IMAGE = "image"
    PDF = "pdf"
    DOCUMENT = "document"
    UNKNOWN = "unknown"


SPATIAL_EXTS = {
    ".shp", ".geojson", ".gpkg", ".kml", ".kmz",
    ".tif", ".tiff", ".json",
}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
PDF_EXTS = {".pdf"}
DOC_EXTS = {".doc", ".docx", ".xls", ".xlsx", ".csv"}


def classify_upload(path: str) -> UploadType:
    """Classify a file path into an UploadType based on extension."""
    ext = os.path.splitext(path)[1].lower()
    if ext in SPATIAL_EXTS:
        return UploadType.SPATIAL
    if ext in IMAGE_EXTS:
        return UploadType.IMAGE
    if ext in PDF_EXTS:
        return UploadType.PDF
    if ext in DOC_EXTS:
        return UploadType.DOCUMENT
    return UploadType.UNKNOWN


# ---------------------------------------------------------------------------
# Image processing
# ---------------------------------------------------------------------------

def prepare_image_part(path: str, max_size: int = 1024) -> Optional[types.Part]:
    """
    Read an image file, resize if needed, and return as a types.Part
    suitable for Gemini multimodal input.

    Args:
        path: Path to the image file.
        max_size: Maximum dimension (width or height) in pixels.

    Returns:
        types.Part with inline_data, or None on error.
    """
    try:
        from PIL import Image

        img = Image.open(path)

        # Convert RGBA/palette to RGB for JPEG encoding
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")

        # Resize if exceeds max_size
        w, h = img.size
        if max(w, h) > max_size:
            ratio = max_size / max(w, h)
            new_w, new_h = int(w * ratio), int(h * ratio)
            img = img.resize((new_w, new_h), Image.LANCZOS)
            logger.debug("Resized image %s from %dx%d to %dx%d", path, w, h, new_w, new_h)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        data = buf.getvalue()

        return types.Part.from_bytes(data=data, mime_type="image/jpeg")
    except Exception as e:
        logger.warning("Failed to prepare image part for %s: %s", path, e)
        return None


# ---------------------------------------------------------------------------
# PDF processing
# ---------------------------------------------------------------------------

def extract_pdf_text(path: str, max_pages: int = 20) -> str:
    """
    Extract text content from a PDF file using pypdf.

    Args:
        path: Path to the PDF file.
        max_pages: Maximum number of pages to extract.

    Returns:
        Extracted text string (may be empty if extraction fails).
    """
    try:
        from pypdf import PdfReader

        reader = PdfReader(path)
        pages = reader.pages[:max_pages]
        text_parts = []
        for page in pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)

        total_pages = len(reader.pages)
        text = "\n".join(text_parts)
        logger.debug(
            "Extracted PDF text from %s: %d/%d pages, %d chars",
            path, min(len(pages), total_pages), total_pages, len(text),
        )
        return text
    except Exception as e:
        logger.warning("Failed to extract PDF text from %s: %s", path, e)
        return ""


def prepare_pdf_part(
    path: str, max_bytes: int = 20 * 1024 * 1024
) -> Optional[types.Part]:
    """
    Read a PDF file and return as a types.Part for Gemini's native PDF
    understanding capability.

    Args:
        path: Path to the PDF file.
        max_bytes: Maximum file size in bytes (default 20 MB).

    Returns:
        types.Part with inline_data (application/pdf), or None if too large or error.
    """
    try:
        file_size = os.path.getsize(path)
        if file_size > max_bytes:
            logger.warning(
                "PDF %s too large (%d bytes > %d), skipping native PDF part",
                path, file_size, max_bytes,
            )
            return None

        with open(path, "rb") as f:
            data = f.read()

        return types.Part.from_bytes(data=data, mime_type="application/pdf")
    except Exception as e:
        logger.warning("Failed to prepare PDF part for %s: %s", path, e)
        return None


# ---------------------------------------------------------------------------
# Content builder
# ---------------------------------------------------------------------------

def build_multimodal_content(
    text: str, extra_parts: Optional[list] = None
) -> types.Content:
    """
    Build a types.Content object with text and optional multimodal parts.

    Args:
        text: The text prompt.
        extra_parts: Optional list of types.Part (images, PDFs, etc.)

    Returns:
        types.Content suitable for ADK Runner.run_async().
    """
    parts = [types.Part(text=text)]
    if extra_parts:
        parts.extend(extra_parts)
    return types.Content(role="user", parts=parts)
