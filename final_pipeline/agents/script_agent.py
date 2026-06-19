from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.base import BaseAgent
from app.schemas import GenreConfig, ScriptOutput
from modules.scripts.generator import generate_script


class ScriptAgent(BaseAgent):
    name = "script_agent"

    def run(
        self,
        provider,
        topic: str,
        genre: GenreConfig,
        duration: int,
        reference_scripts: list[dict[str, Any]],
        user_notes: str = "",
        growth_context=None,
    ) -> ScriptOutput:
        payload = {
            "topic": topic,
            "genre_id": genre.genre_id,
            "duration": duration,
            "reference_count": len(reference_scripts),
            "user_notes": user_notes,
            "has_growth_context": bool(growth_context),
            "max_input_chars": 6000,
            "max_output_tokens": 4096,
        }
        self.log_input(payload)
        self.event("Generating script", provider=getattr(provider, "name", "unknown"))
        output = generate_script(provider, topic, genre, duration, reference_scripts, user_notes, growth_context)
        self.event("Script generated", word_count=output.word_count, provider=output.provider)
        self.log_output(output)
        return output
