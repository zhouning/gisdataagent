"""Unit tests for editor_session."""
from __future__ import annotations

import pytest
from data_agent.standards_platform.drafting.editor_session import compute_checksum


def test_compute_checksum_is_stable():
    assert compute_checksum("hello") == compute_checksum("hello")


def test_compute_checksum_changes_with_content():
    assert compute_checksum("hello") != compute_checksum("hello!")


def test_compute_checksum_returns_16_hex():
    c = compute_checksum("any content")
    assert len(c) == 16
    int(c, 16)  # must be valid hex
