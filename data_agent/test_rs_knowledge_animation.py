"""Tests for RS knowledge base + DRL animation (v22.0)."""
import os
import tempfile
import numpy as np
import pytest

from data_agent.rs_knowledge import (
    get_spectral_index, search_indices_by_application,
    get_classification_system, get_processing_workflow,
    list_all_knowledge,
)
from data_agent.drl_animation import (
    generate_optimization_gif, generate_summary_frame, HAS_PIL,
)


# ---------------------------------------------------------------------------
# RS Knowledge Base
# ---------------------------------------------------------------------------

def test_get_spectral_index():
    ndvi = get_spectral_index("NDVI")
    assert ndvi is not None
    assert ndvi["name"] == "归一化植被指数"
    assert "formula" in ndvi


def test_get_spectral_index_case_insensitive():
    assert get_spectral_index("ndwi") is not None


def test_get_spectral_index_not_found():
    assert get_spectral_index("FAKE_INDEX") is None


def test_search_indices_by_application():
    results = search_indices_by_application("植被")
    assert len(results) >= 1
    assert any(r["index"] == "NDVI" for r in results)


def test_search_indices_water():
    results = search_indices_by_application("水体")
    assert any(r["index"] == "NDWI" for r in results)


def test_search_indices_no_match():
    assert search_indices_by_application("量子计算") == []


def test_get_classification_system():
    gb = get_classification_system("GB/T_21010")
    assert gb is not None
    assert gb["country"] == "中国"
    assert "01" in gb["categories"]


def test_get_processing_workflow():
    veg = get_processing_workflow("vegetation_monitoring")
    assert veg is not None
    assert len(veg["steps"]) >= 5


def test_list_all_knowledge():
    all_k = list_all_knowledge()
    assert "spectral_indices" in all_k
    assert "NDVI" in all_k["spectral_indices"]
    assert len(all_k["classification_systems"]) >= 3
    assert len(all_k["processing_workflows"]) >= 3


# ---------------------------------------------------------------------------
# DRL Animation
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAS_PIL, reason="PIL not installed")
def test_generate_gif():
    # Create simple 5x5 grid states
    states = []
    base = np.ones((5, 5), dtype=np.int32)
    for i in range(10):
        grid = base.copy()
        grid[i % 5, i % 5] = 2  # change one cell per step
        states.append(grid)

    d = tempfile.mkdtemp()
    path = os.path.join(d, "test.gif")
    result = generate_optimization_gif(states, path, size=(200, 200), frame_duration=100)
    assert result is not None
    assert os.path.exists(path)
    assert os.path.getsize(path) > 100


@pytest.mark.skipif(not HAS_PIL, reason="PIL not installed")
def test_generate_gif_empty():
    d = tempfile.mkdtemp()
    path = os.path.join(d, "empty.gif")
    assert generate_optimization_gif([], path) is None


@pytest.mark.skipif(not HAS_PIL, reason="PIL not installed")
def test_generate_summary_frame():
    before = np.array([[1, 1, 2], [2, 3, 3], [1, 1, 1]], dtype=np.int32)
    after = np.array([[1, 2, 2], [2, 3, 1], [1, 1, 2]], dtype=np.int32)
    png_bytes = generate_summary_frame(before, after, size=(300, 200))
    assert png_bytes is not None
    assert len(png_bytes) > 100
    # Verify it's a valid PNG
    assert png_bytes[:4] == b'\x89PNG'


def test_generate_gif_no_pil():
    """Without PIL, returns None gracefully."""
    from unittest.mock import patch
    with patch("data_agent.drl_animation.HAS_PIL", False):
        assert generate_optimization_gif([np.zeros((3, 3))], "/tmp/x.gif") is None
        assert generate_summary_frame(np.zeros((3, 3)), np.zeros((3, 3))) is None
