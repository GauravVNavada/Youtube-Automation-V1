from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from app.schemas import GenreConfig, TopicDiscoveryOutput
from modules.discovery.engine import discover_topics
from modules.discovery.grounding import build_grounding_plan
from modules.niches.profiles import load_niche_profile


class TopicDiscoveryAgent(BaseAgent):
    name = "topic_discovery_agent"

    def run(
        self,
        topic: str,
        genre: GenreConfig,
        reference_scripts: list[dict[str, Any]],
        provider=None,
    ) -> TopicDiscoveryOutput:
        profile = load_niche_profile(genre)
        grounding_plan = build_grounding_plan(topic, genre, provider)
        self.log_input(
            {
                "topic": topic,
                "genre_id": genre.genre_id,
                "reference_count": len(reference_scripts),
                "profile_source": profile.source,
                "grounding_plan": grounding_plan,
                "free_sources": ["local_reference", "local_profile", "duckduckgo", "reddit", "wikipedia"],
            }
        )
        self.provenance(
            "Discovering topic angles",
            "hybrid" if provider else "deterministic",
            mode="topic",
            topic=topic,
            genre_id=genre.genre_id,
            method="grounding plan plus free/no-key web signals",
        )
        output = discover_topics(topic, genre, reference_scripts, profile, grounding_plan=grounding_plan)
        self.provenance(
            "Topic discovery complete",
            "deterministic",
            mode="topic",
            selected_topic=output.selected_topic,
            selected_angle=output.selected_angle,
            candidate_count=len(output.candidates),
            source_errors=output.source_errors,
        )
        self.log_output(output)
        return output
