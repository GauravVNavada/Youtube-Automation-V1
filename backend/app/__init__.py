"""DesktopApp backend API package."""

from pathlib import Path
import sys


def _ensure_final_pipeline_import_path() -> None:
    project_root = Path(__file__).resolve().parents[2]
    final_pipeline = project_root / "final_pipeline"
    if final_pipeline.exists() and str(final_pipeline) not in sys.path:
        sys.path.append(str(final_pipeline))


_ensure_final_pipeline_import_path()
