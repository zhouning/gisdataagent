#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_agent.uwm.traditional_livability_s6_s1_product import build_s6_s1_product_bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--facility-product", type=Path, required=True)
    parser.add_argument("--s6-resources", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    facility = json.loads(args.facility_product.read_text(encoding="utf-8"))
    resources = json.loads(args.s6_resources.read_text(encoding="utf-8"))
    result = build_s6_s1_product_bundle(
        facility_product=facility, s6_resources=resources, output_dir=args.output_dir
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ready") else 2


if __name__ == "__main__":
    raise SystemExit(main())
