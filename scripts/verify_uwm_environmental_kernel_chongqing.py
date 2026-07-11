from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


FILES = ("scene.json", "evidence_gate.json", "current_rollout.json", "map.json")


def verify_product(product_dir: Path) -> dict:
    root = Path(product_dir)
    payloads = {name: json.loads((root / name).read_text(encoding="utf-8")) for name in FILES}
    bundle_ids = {payload.get("bundle_id") for payload in payloads.values()}
    rollout = payloads["current_rollout.json"]
    errors = []
    if len(bundle_ids) != 1 or None in bundle_ids:
        errors.append("bundle_id_mismatch")
    if rollout.get("fabricated_value_count") != 0:
        errors.append("fabricated_values_present")
    if rollout.get("not_a_causal_effect_estimate") is not True:
        errors.append("causal_boundary_missing")
    digest = hashlib.sha256("".join(json.dumps(payloads[name], sort_keys=True, ensure_ascii=False) for name in FILES).encode()).hexdigest()
    return {"valid": not errors, "errors": errors, "bundle_id": next(iter(bundle_ids)) if len(bundle_ids) == 1 else None, "fabricated_value_count": rollout.get("fabricated_value_count"), "not_a_causal_effect_estimate": rollout.get("not_a_causal_effect_estimate"), "intervention_status": rollout.get("intervention_status"), "verification_digest": "sha256:" + digest}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("product_dir", type=Path)
    args = parser.parse_args()
    result = verify_product(args.product_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
