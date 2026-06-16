from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.base import BaseAgent
from app.schemas import GenreConfig, ScriptOutput
from agents.prompts.script_prompts import MAX_OUTPUT_TOKENS
from modules.scripts.generator import generate_script
from modules.visuals.style_router import apply_visual_style_to_script, visual_style_to_dict


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
        attempt: int = 1,
        constraints: dict[str, Any] | None = None,
        growth_context: dict[str, Any] | None = None,
        visual_style: dict[str, Any] | None = None,
    ) -> ScriptOutput:
        payload = {
            "topic": topic,
            "genre_id": genre.genre_id,
            "duration": duration,
            "attempt": attempt,
            "reference_count": len(reference_scripts),
            "user_notes": user_notes,
            "constraints": constraints or {},
            "growth_context": growth_context or {},
            "visual_style": visual_style_to_dict(visual_style),
            "max_input_chars": 6000,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
        }
        self.log_input(payload)
        self.provenance(
            "Generating script",
            mode="ai",
            provider=getattr(provider, "name", "unknown"),
            attempt=attempt,
        )
        output = generate_script(provider, topic, genre, duration, reference_scripts, user_notes, growth_context)
        output = apply_visual_style_to_script(output, visual_style)
        self.provenance(
            "Script generated",
            mode="ai",
            word_count=output.word_count,
            image_cue_count=len(output.image_cues),
            provider=output.provider,
            attempt=attempt,
            visual_style=visual_style_to_dict(visual_style),
        )
        self.log_output(output)
        return output
