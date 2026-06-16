from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from app.schemas import GenreConfig, ResearchOutput, TopicDiscoveryOutput
from modules.discovery.research import build_research_brief


class ResearchAgent(BaseAgent):
    name = "research_agent"

    def run(
        self,
        topic: str,
        genre: GenreConfig,
        discovery: TopicDiscoveryOutput,
        reference_scripts: list[dict[str, Any]],
        grounding_plan: dict | None = None,
    ) -> ResearchOutput:
        payload = {
            "topic": topic,
            "genre_id": genre.genre_id,
            "selected_angle": discovery.selected_angle,
            "candidate_count": len(discovery.candidates),
            "grounding_plan": grounding_plan or {},
            "free_sources": ["local_reference", "local_profile", "duckduckgo", "reddit", "wikipedia"],
        }
        self.log_input(payload)
        self.provenance(
            "Researching selected topic angle",
            mode="deterministic",
            topic=topic,
            angle=discovery.selected_angle,
            method="local references plus free/no-key source lookups",
        )
        output = build_research_brief(topic, genre, discovery, discovery.niche_profile, reference_scripts, grounding_plan=grounding_plan)
        self.provenance(
            "Research brief complete",
            mode="deterministic",
            fact_count=len(output.facts),
            source_count=len(output.source_snippets),
            source_errors=output.source_errors,
        )
        self.log_output(output)
        return output
