from __future__ import annotations

import json
import traceback
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


def to_jsonable(value: Any) -> Any:
    """Convert dataclasses, paths, and nested values into JSON-safe data."""
    if is_dataclass(value):
        return to_jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    return value


class ModuleLogger:
    """Per-agent logger that writes input.json, output.json, and events.log."""

    def __init__(self, run_dir: Path, module_name: str):
        self.module_name = module_name
        self.log_dir = run_dir / "logs" / module_name
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.log_dir / "events.log"

    def write_input(self, data: Any) -> None:
        self._write_json("input.json", data)

    def write_output(self, data: Any) -> None:
        self._write_json("output.json", data)

    def event(self, message: str, **fields: Any) -> None:
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "module": self.module_name,
            "message": message,
            **to_jsonable(fields),
        }
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=True) + "\n")

    def _write_json(self, filename: str, data: Any) -> None:
        path = self.log_dir / filename
        path.write_text(
            json.dumps(to_jsonable(data), indent=2, ensure_ascii=True),
            encoding="utf-8",
        )


class ErrorLogger:
    """Run-level error logger that captures failures in a dedicated folder."""

    def __init__(self, run_dir: Path):
        self.error_dir = run_dir / "errors"
        self.error_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.error_dir / "events.log"

    def record(
        self,
        *,
        stage: str,
        exc: BaseException,
        context: Any | None = None,
    ) -> Path:
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "stage": stage,
            "error_type": type(exc).__name__,
            "message": str(exc),
            "context": to_jsonable(context or {}),
            "traceback": traceback.format_exception(type(exc), exc, exc.__traceback__),
        }
        path = self.error_dir / "error.json"
        path.write_text(json.dumps(record, indent=2, ensure_ascii=True), encoding="utf-8")
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=True) + "\n")
        return path
