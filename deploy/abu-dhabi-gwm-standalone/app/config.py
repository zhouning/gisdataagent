from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error
    if value < 1:
        raise RuntimeError(f"{name} must be at least 1")
    return value


def _nonnegative_float(name: str, default: float) -> float:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be numeric") from error
    if value < 0.0:
        raise RuntimeError(f"{name} must be non-negative")
    return value


def _api_token() -> str:
    token_file = os.environ.get("GWM_API_TOKEN_FILE", "").strip()
    if token_file:
        try:
            token = Path(token_file).read_text(encoding="utf-8").strip()
        except OSError as error:
            raise RuntimeError("GWM_API_TOKEN_FILE cannot be read") from error
    else:
        token = os.environ.get("GWM_API_TOKEN", "").strip()
    if len(token) < 32:
        raise RuntimeError("GWM_API_TOKEN must contain at least 32 characters")
    return token


@dataclass(frozen=True)
class Settings:
    model_dir: Path
    run_dir: Path
    api_token: str
    min_free_disk_gb: float = 5.0
    max_concurrent_runs: int = 1

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            model_dir=Path(os.environ.get("GWM_MODEL_DIR", "/opt/gwm/model")).expanduser().resolve(),
            run_dir=Path(os.environ.get("GWM_RUN_DIR", "/data/runs")).expanduser().resolve(),
            api_token=_api_token(),
            min_free_disk_gb=_nonnegative_float("GWM_MIN_FREE_DISK_GB", 5.0),
            max_concurrent_runs=_positive_int("GWM_MAX_CONCURRENT_RUNS", 1),
        )
