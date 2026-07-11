from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent.uwm.environmental_kernel.product import assemble_chongqing_product


def build_product(*, source_root: Path, output_dir: Path) -> dict:
    base = Path(source_root) / "data/uwm_public_proxy/chongqing_central"
    paths = {
        "evidence": base / "uwm_environmental_evidence_bundle_2024_07_multisource.json",
        "scene": base / "multisource_livability_scene_2026_07_06/uwm_multisource_livability_scene.json",
        "graph": base / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json",
        "tap": base / "tap_pm25_external_dynamics_2026_07_06/tap_external_dynamics_report.json",
    }
    missing = [name for name, path in paths.items() if not path.exists()]
    if missing:
        return {"ready": False, "exit_code": 2, "blockers": [f"missing_{name}" for name in missing]}
    payloads = assemble_chongqing_product(**{name: json.loads(path.read_text(encoding="utf-8")) for name, path in paths.items()})
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary = []
    try:
        for filename, payload in payloads.items():
            path = output_dir / f"{filename}.tmp"
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            temporary.append(path)
        for path in temporary:
            os.replace(path, output_dir / path.name.removesuffix(".tmp"))
    finally:
        for path in temporary:
            if path.exists():
                path.unlink()
    return {"ready": True, "exit_code": 0, "output_dir": str(output_dir), "bundle_id": payloads["scene.json"]["bundle_id"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = build_product(source_root=args.source_root, output_dir=args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
