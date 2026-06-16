from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_render_plan(output_dir: Path, plan: dict[str, Any]) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "render_plan.json"
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=True), encoding="utf-8")
    return str(path)
