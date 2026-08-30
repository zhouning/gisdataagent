from __future__ import annotations

import zipfile

import pytest

from scripts.run_nx_sample_ingest import _paper9_readiness, _safe_extract


def test_safe_extract_rejects_zip_slip(tmp_path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../escape.txt", "blocked")
    with pytest.raises(ValueError, match="unsafe archive member"):
        _safe_extract(archive, tmp_path / "out", 1024)
    assert not (tmp_path / "escape.txt").exists()


def test_paper9_readiness_is_fail_closed_for_demo_candidates():
    report = _paper9_readiness(
        {
            "assets": [
                {
                    "asset_id": "a",
                    "raw_path": "raw/a",
                    "layers": [
                        {
                            "name": "DLTB",
                            "mapping": {"ea_model_candidate": "DLTB", "status": "manual_review"},
                        },
                        {
                            "name": "STBHHX",
                            "mapping": {"ea_model_candidate": "STBHHX", "status": "accepted"},
                        },
                    ],
                }
            ]
        }
    )
    assert report["ready"] is False
    assert report["blocking_missing_or_unverified"] == ["DEM"]
    assert report["production_ready"] is False
