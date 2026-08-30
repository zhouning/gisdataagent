"""Keep optional runtime imports aligned with the install profiles."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _profile_dependencies(name: str) -> set[str]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return set(project["project"]["optional-dependencies"][name])


def test_scientific_profile_declares_gwm_hdf5_reader() -> None:
    assert "h5py==3.16.0" in _profile_dependencies("scientific")
    assert "h5py==3.16.0" in _profile_dependencies("full")
    assert "h5py==3.16.0" in (ROOT / "requirements.txt").read_text(encoding="utf-8")


def test_documents_profile_declares_pdf_reader() -> None:
    assert "PyMuPDF==1.27.2.2" in _profile_dependencies("documents")
    assert "PyMuPDF==1.27.2.2" in _profile_dependencies("full")
    assert "PyMuPDF==1.27.2.2" in (ROOT / "requirements.txt").read_text(encoding="utf-8")
