from typing import Any
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class YoloEngine:
    """YOLO-based object detection engine."""

    def __init__(self, model_path: str = "yolov8n.pt", device: str = "cuda"):
        self.model_path = model_path
        self.device = device
        self._model = None

    def load_model(self) -> None:
        """Load YOLO model from disk."""
        try:
            from ultralytics import YOLO
            path = Path(self.model_path)
            if not path.exists():
                logger.warning("Model file %s not found, downloading default", self.model_path)
            self._model = YOLO(str(self.model_path))
            self._model.to(self.device)
            logger.info("YOLO model loaded from %s on %s", self.model_path, self.device)
        except Exception as e:
            logger.error("Failed to load YOLO model: %s", e)
            self._model = None

    def detect(self, image_path: str, conf: float = 0.25) -> list[dict[str, Any]]:
        """Run detection on an image. Returns list of bounding boxes."""
        if self._model is None:
            return []
        try:
            results = self._model(image_path, conf=conf, verbose=False)
            detections = []
            for r in results:
                for box in r.boxes:
                    xyxy = box.xyxy[0].tolist()
                    detections.append({
                        "x1": xyxy[0], "y1": xyxy[1],
                        "x2": xyxy[2], "y2": xyxy[3],
                        "confidence": float(box.conf[0]),
                        "class_name": r.names[int(box.cls[0])],
                    })
            return detections
        except Exception as e:
            logger.error("Detection failed on %s: %s", image_path, e)
            return []

    def detect_cad_layers(self, image_path: str) -> dict[str, Any]:
        """Detect CAD layer elements in an image."""
        detections = self.detect(image_path, conf=0.2)
        layer_map: dict[str, list] = {}
        for d in detections:
            cls = d["class_name"]
            layer_map.setdefault(cls, []).append(d)
        layers = [
            {"name": name, "element_count": len(items), "type": name}
            for name, items in layer_map.items()
        ]
        return {"layers": layers, "total_detections": len(detections)}
