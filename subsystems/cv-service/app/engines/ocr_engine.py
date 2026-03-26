from typing import Any


class OcrEngine:
    """OCR engine for text extraction from CAD drawings and maps."""

    def __init__(self, lang: str = "ch_sim+en"):
        self.lang = lang
        self._reader = None

    def load(self) -> None:
        """Load OCR model. Stub — real impl uses PaddleOCR or EasyOCR."""
        self._reader = "loaded"

    def extract_text(self, image_path: str) -> list[dict[str, Any]]:
        """Extract text regions from an image."""
        if self._reader is None:
            raise RuntimeError("OCR reader not loaded. Call load() first.")
        return [
            {"text": "建筑面积: 1200m²", "bbox": [100, 200, 350, 230], "confidence": 0.95},
            {"text": "地块编号: A-003", "bbox": [400, 50, 600, 80], "confidence": 0.91},
        ]
