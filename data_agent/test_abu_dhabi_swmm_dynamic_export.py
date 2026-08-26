from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from data_agent.uwm.abu_dhabi_flood.swmm_dynamic_export import (
    export_customer_swmm_dynamic_diagnostic,
)


def _source(tmp_path: Path) -> tuple[Path, Path]:
    npz_path = tmp_path / "diagnostic.npz"
    np.savez(
        npz_path,
        pilot_01_elapsed_seconds=np.asarray([900, 1800], dtype="int64"),
        pilot_01_node_state=np.zeros((2, 1, 6), dtype="float32"),
        pilot_01_edge_state=np.ones((2, 2, 4), dtype="float32"),
    )
    manifest_path = tmp_path / "diagnostic.json"
    manifest_path.write_text(
        json.dumps({"schema": "gwm.abu_dhabi_flood.customer_gdb_swmm_gwm_dynamic_diagnostic.v1"}),
        encoding="utf-8",
    )
    return npz_path, manifest_path


def test_dynamic_export_writes_auditable_csv_and_manifest(tmp_path: Path):
    npz_path, manifest_path = _source(tmp_path)
    output = tmp_path / "export"
    result = export_customer_swmm_dynamic_diagnostic(
        input_npz=npz_path,
        input_manifest=manifest_path,
        output_root=output,
    )
    assert result["status"] == "csv_exported_diagnostic_only"
    assert {item["row_count"] for item in result["files"]} == {2, 4}
    assert (
        (output / "customer_swmm_dynamic_node_states.csv")
        .read_text()
        .splitlines()[0]
        .startswith("pilot_id,time_index")
    )
    assert (output / "customer_swmm_dynamic_csv_export_manifest.json").is_file()
    assert result["admission"]["gwm_training_admitted"] is False


def test_dynamic_export_rejects_public_repository_output(tmp_path: Path):
    npz_path, manifest_path = _source(tmp_path)
    repository = Path(__file__).resolve().parents[1]
    with pytest.raises(ValueError, match="outside_public_repository"):
        export_customer_swmm_dynamic_diagnostic(
            input_npz=npz_path,
            input_manifest=manifest_path,
            output_root=repository / "customer-private-output",
        )
