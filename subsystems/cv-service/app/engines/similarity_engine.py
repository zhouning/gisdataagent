from typing import Any


class SimilarityEngine:
    """Image similarity engine for duplicate/change detection."""

    def __init__(self, model_name: str = "resnet50"):
        self.model_name = model_name
        self._model = None

    def load(self) -> None:
        """Load feature extraction model. Stub."""
        self._model = "loaded"

    def compute_similarity(self, image_a_path: str, image_b_path: str) -> dict[str, Any]:
        """Compute similarity between two images."""
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load() first.")
        return {
            "ssim": 0.87,
            "cosine_similarity": 0.92,
            "pixel_diff_percentage": 4.3,
            "changed_regions": [
                {"x": 200, "y": 300, "w": 100, "h": 80, "type": "addition"},
            ],
        }
