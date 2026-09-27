"""Regression tests for the pre-simulation Abu Dhabi land/water mask."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "run_abu_dhabi_swmm_anuga_bidirectional_pilot.py"
)


def _load_script_module():
    spec = importlib.util.spec_from_file_location("abu_dhabi_masked_pilot", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_land_mask_is_applied_before_mesh_construction():
    module = _load_script_module()
    x = np.asarray([0.0, 1.0, 2.0])
    y = np.asarray([2.0, 1.0, 0.0])
    land_mask = np.asarray([[True, False], [True, True]])

    coordinates, triangles, triangle_to_cell, boundary = module.build_land_masked_cross_mesh(
        x,
        y,
        land_mask,
    )

    assert triangles.shape == (12, 3)
    assert triangle_to_cell.shape == (12,)
    assert set(triangle_to_cell.tolist()) == {0, 2, 3}
    assert 1 not in triangle_to_cell
    assert np.all(land_mask.reshape(-1)[triangle_to_cell])
    assert boundary
    assert set(boundary.values()) == {"outer_domain", "permanent_water"}

    points = coordinates[triangles]
    signed_double_area = (
        (points[:, 1, 0] - points[:, 0, 0])
        * (points[:, 2, 1] - points[:, 0, 1])
        - (points[:, 1, 1] - points[:, 0, 1])
        * (points[:, 2, 0] - points[:, 0, 0])
    )
    assert np.all(signed_double_area > 0.0)


def test_land_mask_mesh_rejects_empty_domain():
    module = _load_script_module()
    x = np.asarray([0.0, 1.0])
    y = np.asarray([1.0, 0.0])
    land_mask = np.asarray([[False]])

    try:
        module.build_land_masked_cross_mesh(x, y, land_mask)
    except ValueError as error:
        assert str(error) == "pilot_land_mask_has_no_active_cells"
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("empty land mask should fail")
