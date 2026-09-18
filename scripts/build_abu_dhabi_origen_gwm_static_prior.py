#!/usr/bin/env python3
"""Build prospective GWM static covariates from an existing private Origen bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from data_agent.uwm.abu_dhabi_flood.hotspot_inventory import (  # noqa: E402
    DEFAULT_BUNDLE_ROOT,
    augment_private_bundle_with_static_prior,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, default=DEFAULT_BUNDLE_ROOT)
    parser.add_argument("--model-grid", type=Path, required=True)
    parser.add_argument("--hotspot-influence-scale-m", type=float, default=1_000.0)
    parser.add_argument("--hotspot-cutoff-m", type=float, default=3_000.0)
    args = parser.parse_args()
    manifest = augment_private_bundle_with_static_prior(
        args.bundle_root,
        args.model_grid,
        hotspot_influence_scale_m=args.hotspot_influence_scale_m,
        hotspot_cutoff_m=args.hotspot_cutoff_m,
    )
    print(json.dumps(manifest["gwm_static_prior"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
