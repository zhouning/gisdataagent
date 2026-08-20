#!/usr/bin/env python3
"""Generate the blocked Abu Dhabi K0 customer data-request receipt."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from data_agent.uwm.abu_dhabi_flood import (
    build_k0_data_request_receipt,
    default_k0_data_request_package,
    verify_k0_data_request_receipt,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECEIPT = Path(
    "docs/customer/abu_dhabi_liveability_site_validation/technical_validation/"
    "k0_data_request_contract_receipt.json"
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_RECEIPT)
    return parser.parse_args()


def main() -> None:
    args = _arguments()
    output = args.output if args.output.is_absolute() else REPOSITORY_ROOT / args.output
    os.chdir(REPOSITORY_ROOT)
    receipt = build_k0_data_request_receipt(default_k0_data_request_package())
    verify_k0_data_request_receipt(receipt)
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            receipt,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    os.replace(temporary, output)
    print(
        json.dumps(
            {"output": str(output), "receipt_sha256": receipt["receipt_sha256"]}
        )
    )


if __name__ == "__main__":
    main()
