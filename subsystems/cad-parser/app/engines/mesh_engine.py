import logging
from typing import Any
from pathlib import Path

import trimesh
import numpy as np

logger = logging.getLogger(__name__)


class MeshEngine:
    """3D mesh parsing engine using trimesh."""

    def parse(self, file_path: str) -> dict[str, Any]:
        """Parse a 3D model file (OBJ, STL, PLY, etc.)."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Model file not found: {file_path}")
        try:
            mesh = trimesh.load(file_path, force="mesh")
        except Exception as e:
            raise ValueError(f"Failed to load mesh: {e}") from e

        bbox_min = mesh.bounds[0].tolist()
        bbox_max = mesh.bounds[1].tolist()
        volume = float(mesh.volume) if mesh.is_watertight else None

        return {
            "vertex_count": len(mesh.vertices),
            "face_count": len(mesh.faces),
            "is_watertight": bool(mesh.is_watertight),
            "volume": volume,
            "bounding_box": {"min": bbox_min, "max": bbox_max},
            "center_of_mass": mesh.center_mass.tolist() if mesh.is_watertight else None,
        }

    def validate_topology(self, file_path: str) -> dict[str, Any]:
        """Check mesh topology: manifold, degenerate faces, duplicate vertices."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Model file not found: {file_path}")
        try:
            mesh = trimesh.load(file_path, force="mesh")
        except Exception as e:
            raise ValueError(f"Failed to load mesh: {e}") from e

        errors: list[str] = []
        warnings: list[str] = []

        if not mesh.is_watertight:
            errors.append("Mesh is not watertight")

        # Degenerate faces
        areas = mesh.area_faces
        degen = int((areas < 1e-10).sum())
        if degen > 0:
            errors.append(f"{degen} degenerate faces (near-zero area)")

        # Duplicate vertices
        unique = len(set(map(tuple, mesh.vertices.tolist())))
        dups = len(mesh.vertices) - unique
        if dups > 0:
            warnings.append(f"{dups} duplicate vertices")

        # Non-manifold edges (edges shared by != 2 faces)
        edges = mesh.edges_sorted
        from collections import Counter
        edge_counts = Counter(map(tuple, edges.tolist()))
        non_manifold = sum(1 for c in edge_counts.values() if c != 2)
        if non_manifold > 0:
            errors.append(f"{non_manifold} non-manifold edges")

        return {
            "is_valid": len(errors) == 0,
            "vertex_count": len(mesh.vertices),
            "face_count": len(mesh.faces),
            "errors": errors,
            "warnings": warnings,
        }
