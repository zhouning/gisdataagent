#!/usr/bin/env python3
"""Build the private serving bundle for the latest 506 customer flood points."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.uwm.abu_dhabi_flood.customer_hotspots_506 import (
    DEFAULT_BUNDLE_ROOT,
    build_private_bundle,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_zip", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_BUNDLE_ROOT)
    parser.add_argument("--expected-count", type=int, default=506)
    args = parser.parse_args()
    result = build_private_bundle(
        args.source_zip,
        args.output,
        expected_count=args.expected_count,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
