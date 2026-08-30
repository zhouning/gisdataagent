#!/usr/bin/env python3
"""Run the frozen Chongqing real-data standard-mapping acceptance suite."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent.standards_platform.application.acceptance import (  # noqa: E402
    run_acceptance_protocol,
)
from data_agent.standards_platform.application.service import (  # noqa: E402
    load_released_standard,
    resolve_released_standard_version,
)

DEFAULT_PROTOCOL = (
    REPO_ROOT
    / "benchmarks/standard_mapping_chongqing_v0_1/protocol.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "benchmarks/standard_mapping_chongqing_v0_1/acceptance_report.json"
)
DEFAULT_DATASET_ROOT = (
    REPO_ROOT
    / ".tmp/twm_standard_1128/自然资源一张图数据库标准1128/"
    "规划院提供数据样例及Demo系统功能演示建议/01数据样例"
)
DEFAULT_ARCHIVE = (
    Path.home() / "Downloads/规划院提供数据样例及Demo系统功能演示建议.zip"
)


def _path_from_env(name: str, fallback: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else fallback


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=_path_from_env(
            "GDA_CHONGQING_STANDARD_MAPPING_DATA_ROOT", DEFAULT_DATASET_ROOT
        ),
    )
    parser.add_argument(
        "--archive",
        type=Path,
        default=_path_from_env(
            "GDA_CHONGQING_STANDARD_MAPPING_ARCHIVE", DEFAULT_ARCHIVE
        ),
    )
    parser.add_argument(
        "--observe-unsealed",
        action="store_true",
        help="Emit observed hashes before the protocol is sealed.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    standard_spec = protocol["standard"]
    version_id = resolve_released_standard_version(
        doc_code=standard_spec["doc_code"],
        version_label=standard_spec["version_label"],
    )
    _, elements = load_released_standard(version_id)
    report = run_acceptance_protocol(
        protocol=protocol,
        dataset_root=args.dataset_root,
        archive_path=args.archive,
        standard_version_id=version_id,
        standard_elements=elements,
        allow_unsealed=args.observe_unsealed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": report["status"],
        "technical_pass": report["technical_pass"],
        "promotion_ready": report["promotion_ready"],
        "output": str(args.output),
        "metrics": report["metrics"],
        "observed_seal": report["observed_seal"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"passed", "observed_unsealed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
