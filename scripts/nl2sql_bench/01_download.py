"""Step 1 — Download FloodSQL-Bench from Hugging Face.

Drops Parquet tables + benchmark question/SQL pairs into D:/adk/data/floodsql/.

Pre-req: huggingface-cli login + accept dataset terms at
https://huggingface.co/datasets/HanzhouLiu/FloodSQL-Bench
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ID = "HanzhouLiu/FloodSQL-Bench"
TARGET = Path(__file__).resolve().parents[2] / "data" / "floodsql"


def main() -> int:
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("ERROR: huggingface_hub not installed. Run: pip install huggingface_hub", file=sys.stderr)
        return 2

    TARGET.mkdir(parents=True, exist_ok=True)
    print(f"[download] Pulling {REPO_ID} → {TARGET}")
    try:
        path = snapshot_download(
            repo_id=REPO_ID,
            repo_type="dataset",
            local_dir=str(TARGET),
            local_dir_use_symlinks=False,
        )
    except Exception as e:
        print(f"ERROR: snapshot_download failed: {e}", file=sys.stderr)
        print("Hint: ensure `huggingface-cli login` and dataset terms accepted.", file=sys.stderr)
        return 1

    print(f"[download] OK → {path}")

    # Inventory what we got
    parquets = list(Path(path).rglob("*.parquet"))
    jsons = list(Path(path).rglob("*.json"))
    print(f"[download] Parquet files: {len(parquets)}")
    for p in parquets[:20]:
        print(f"  {p.relative_to(path)} ({p.stat().st_size / 1e6:.1f} MB)")
    print(f"[download] JSON files: {len(jsons)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
