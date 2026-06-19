from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _configured_path(env_name: str, default: Path) -> Path:
    configured = os.environ.get(env_name, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return default


DATA_DIR = _configured_path("MODULARSHORTS_DATA_DIR", PROJECT_ROOT / "data")
RUNS_DIR = _configured_path("MODULARSHORTS_RUNS_DIR", PROJECT_ROOT / "runs")


def get_runs_dir() -> Path:
    """Return the run output directory, with an override for isolated tests."""
    return RUNS_DIR


def create_run_dir() -> Path:
    """Create a unique run directory for one CLI execution."""
    runs_dir = get_runs_dir()
    runs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = runs_dir / f"run_{stamp}"
    suffix = 1
    while run_dir.exists():
        suffix += 1
        run_dir = runs_dir / f"run_{stamp}_{suffix}"

    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    (run_dir / "errors").mkdir(parents=True, exist_ok=True)
    (run_dir / "intermediate").mkdir(parents=True, exist_ok=True)
    (run_dir / "output").mkdir(parents=True, exist_ok=True)
    return run_dir


def ensure_data_dirs() -> None:
    """Ensure runtime-created data directories exist."""
    for path in (
        DATA_DIR / "assets" / "music",
        DATA_DIR / "assets" / "sfx",
    ):
        path.mkdir(parents=True, exist_ok=True)
