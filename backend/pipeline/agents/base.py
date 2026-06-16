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

    def provenance(
        self,
        message: str,
        *,
        mode: str,
        ai_used: bool | None = None,
        deterministic: bool | None = None,
        **fields: Any,
    ) -> None:
        """Log whether a step used AI, deterministic code, or a hybrid path."""
        normalized = mode.strip().lower().replace(" ", "_")
        if ai_used is None:
            ai_used = normalized in {"ai", "hybrid"}
        if deterministic is None:
            deterministic = normalized in {"deterministic", "fallback", "hybrid"}
        self.event(
            message,
            execution_mode=normalized,
            ai_used=ai_used,
            deterministic=deterministic,
            **fields,
        )
