#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_agent.uwm.traditional_livability_s7_gated_product import build_gated_s7_product


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--s7-snapshot", type=Path, required=True)
    parser.add_argument("--s1-snapshot", type=Path, required=True)
    parser.add_argument("--facility-product", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = build_gated_s7_product(
        s7_snapshot=json.loads(args.s7_snapshot.read_text(encoding="utf-8")),
        s1_snapshot=json.loads(args.s1_snapshot.read_text(encoding="utf-8")),
        facility_product=json.loads(args.facility_product.read_text(encoding="utf-8")),
        output_dir=args.output_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ready") else 2


if __name__ == "__main__":
    raise SystemExit(main())
