from __future__ import annotations

from pathlib import Path
from typing import Any

from app.logger import ModuleLogger


class BaseAgent:
    """Small base class that gives each agent isolated logs."""

    name = "base_agent"

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.logger = ModuleLogger(run_dir, self.name)

    def log_input(self, data: Any) -> None:
        self.logger.write_input(data)

    def log_output(self, data: Any) -> None:
        self.logger.write_output(data)

    def event(self, message: str, **fields: Any) -> None:
        self.logger.event(message, **fields)

    def provenance(self, message: str, source: str, **fields: Any) -> None:
        self.logger.event(message, source=source, **fields)
