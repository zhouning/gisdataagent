import logging
from typing import Any
from pathlib import Path

import ezdxf

logger = logging.getLogger(__name__)


class DxfEngine:
    """DXF file parsing engine using ezdxf."""

    def parse(self, file_path: str) -> dict[str, Any]:
        """Parse a DXF file and return layers, entity counts, bounding box."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"DXF file not found: {file_path}")
        try:
            doc = ezdxf.readfile(file_path)
        except Exception as e:
            raise ValueError(f"Failed to parse DXF: {e}") from e

        msp = doc.modelspace()
        layers: dict[str, int] = {}
        all_x, all_y = [], []

        for entity in msp:
            layer_name = entity.dxf.layer
            layers[layer_name] = layers.get(layer_name, 0) + 1
            try:
                bbox = entity.bbox()
                if bbox is not None and bbox.has_data:
                    all_x.extend([bbox.extmin.x, bbox.extmax.x])
                    all_y.extend([bbox.extmin.y, bbox.extmax.y])
            except Exception:
                pass

        bounding_box = {}
        if all_x and all_y:
            bounding_box = {
                "min_x": min(all_x), "min_y": min(all_y),
                "max_x": max(all_x), "max_y": max(all_y),
            }

        version = doc.dxfversion if hasattr(doc, "dxfversion") else "unknown"
        return {
            "layers": list(layers.keys()),
            "entity_counts": layers,
            "total_entities": sum(layers.values()),
            "bounding_box": bounding_box,
            "metadata": {"version": version},
        }

    def get_entities(self, file_path: str, layer: str | None = None) -> list[dict[str, Any]]:
        """Get entity details from a DXF file, optionally filtered by layer."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"DXF file not found: {file_path}")
        try:
            doc = ezdxf.readfile(file_path)
        except Exception as e:
            raise ValueError(f"Failed to parse DXF: {e}") from e

        msp = doc.modelspace()
        entities = []
        for entity in msp:
            if layer and entity.dxf.layer != layer:
                continue
            entry: dict[str, Any] = {
                "type": entity.dxftype(),
                "layer": entity.dxf.layer,
            }
            etype = entity.dxftype()
            try:
                if etype == "LINE":
                    entry["start"] = [entity.dxf.start.x, entity.dxf.start.y]
                    entry["end"] = [entity.dxf.end.x, entity.dxf.end.y]
                elif etype in ("LWPOLYLINE", "POLYLINE"):
                    pts = [[p[0], p[1]] for p in entity.get_points()]
                    entry["points"] = pts
                    entry["closed"] = entity.closed if hasattr(entity, "closed") else False
                elif etype == "CIRCLE":
                    entry["center"] = [entity.dxf.center.x, entity.dxf.center.y]
                    entry["radius"] = entity.dxf.radius
                elif etype == "ARC":
                    entry["center"] = [entity.dxf.center.x, entity.dxf.center.y]
                    entry["radius"] = entity.dxf.radius
                    entry["start_angle"] = entity.dxf.start_angle
                    entry["end_angle"] = entity.dxf.end_angle
                elif etype in ("TEXT", "MTEXT"):
                    entry["insert"] = [entity.dxf.insert.x, entity.dxf.insert.y]
                    entry["text"] = entity.dxf.text if hasattr(entity.dxf, "text") else ""
                elif etype == "POINT":
                    entry["location"] = [entity.dxf.location.x, entity.dxf.location.y]
            except Exception:
                pass
            entities.append(entry)
        return entities
