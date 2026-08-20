#!/usr/bin/env python3
"""Validate the synthetic SWMM--ANUGA exchange contract and write its receipt."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from data_agent.uwm.abu_dhabi_flood import (
    SolverWindowBalance,
    SwmmAnugaCouplingInterface,
    SwmmAnugaCouplingQualityPolicy,
    SwmmAnugaCouplingWindow,
    SwmmAnugaTransfer,
    build_swmm_anuga_coupling_receipt,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECEIPT = Path(
    "docs/customer/abu_dhabi_liveability_site_validation/technical_validation/"
    "swmm_anuga_synthetic_coupling_contract_receipt.json"
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_RECEIPT)
    return parser.parse_args()


def _repository_path(path: Path) -> Path:
    return path if path.is_absolute() else REPOSITORY_ROOT / path


def _interface() -> SwmmAnugaCouplingInterface:
    return SwmmAnugaCouplingInterface(
        interface_id="manhole-a-surface-zone-a",
        swmm_node_id="swmm-node-a",
        anuga_region_id="anuga-region-a",
        maximum_exchange_rate_m3s=0.1,
        provenance_id="fixture:coupling-interface-a",
    )


def _window() -> SwmmAnugaCouplingWindow:
    return SwmmAnugaCouplingWindow(
        run_id="abu-dhabi-swmm-anuga-synthetic-coupling-contract",
        window_start_seconds=0.0,
        window_end_seconds=300.0,
        interfaces=(_interface(),),
        transfers=(
            SwmmAnugaTransfer(
                transfer_id="surcharge-a",
                interface_id="manhole-a-surface-zone-a",
                direction="swmm_to_anuga",
                window_start_seconds=0.0,
                window_end_seconds=300.0,
                volume_m3=12.0,
                provenance_id="fixture:swmm-surcharge-a",
            ),
            SwmmAnugaTransfer(
                transfer_id="surface-return-a",
                interface_id="manhole-a-surface-zone-a",
                direction="anuga_to_swmm",
                window_start_seconds=0.0,
                window_end_seconds=300.0,
                volume_m3=3.0,
                provenance_id="fixture:anuga-surface-return-a",
            ),
        ),
        balances=(
            SolverWindowBalance(
                solver_id="epa_swmm",
                solver_run_reference_id="receipt:swmm-synthetic",
                window_start_seconds=0.0,
                window_end_seconds=300.0,
                storage_start_m3=100.0,
                storage_end_m3=106.0,
                external_inflow_m3=20.0,
                external_outflow_m3=5.0,
                sent_to_counterpart_m3=12.0,
                received_from_counterpart_m3=3.0,
                provenance_id="fixture:swmm-balance",
            ),
            SolverWindowBalance(
                solver_id="anuga_2d",
                solver_run_reference_id="receipt:anuga-synthetic",
                window_start_seconds=0.0,
                window_end_seconds=300.0,
                storage_start_m3=50.0,
                storage_end_m3=65.0,
                external_inflow_m3=10.0,
                external_outflow_m3=4.0,
                sent_to_counterpart_m3=3.0,
                received_from_counterpart_m3=12.0,
                provenance_id="fixture:anuga-balance",
            ),
        ),
    )


def main() -> None:
    args = _arguments()
    output = _repository_path(args.output)
    os.chdir(REPOSITORY_ROOT)
    receipt = build_swmm_anuga_coupling_receipt(
        _window(), SwmmAnugaCouplingQualityPolicy()
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        + "\n"
    ).encode("ascii")
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    os.replace(temporary, output)
    print(json.dumps({"output": str(output), "receipt_sha256": receipt["receipt_sha256"]}))


if __name__ == "__main__":
    main()
