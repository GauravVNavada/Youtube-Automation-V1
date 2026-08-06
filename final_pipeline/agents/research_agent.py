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
        plan = grounding_plan or discovery.grounding_plan
        self.log_input(
            {
                "topic": topic,
                "genre_id": genre.genre_id,
                "selected_angle": discovery.selected_angle,
                "candidate_count": len(discovery.candidates),
                "grounding_plan": plan,
                "free_sources": ["local_reference", "local_profile", "duckduckgo", "reddit", "wikipedia"],
            }
        )
        self.provenance(
            "Researching selected topic angle",
            "deterministic",
            mode="research",
            topic=topic,
            angle=discovery.selected_angle,
            method="local references plus free/no-key source lookups",
        )
        output = build_research_brief(
            topic,
            genre,
            discovery,
            discovery.niche_profile,
            reference_scripts,
            grounding_plan=plan,
        )
        self.provenance(
            "Research brief complete",
            "deterministic",
            mode="research",
            fact_count=len(output.facts),
            source_count=len(output.source_snippets),
            source_errors=output.source_errors,
        )
        self.log_output(output)
        return output
