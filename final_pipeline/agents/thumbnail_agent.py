from __future__ import annotations

from agents.base import BaseAgent
from app.schemas import AssetBundle, RenderResult, ResearchOutput, ScriptOutput, ThumbnailOutput, TopicDiscoveryOutput
from modules.thumbnails.renderer import create_thumbnail_set


class ThumbnailAgent(BaseAgent):
    name = "thumbnail_agent"

    def run(
        self,
        script: ScriptOutput,
        assets: AssetBundle,
        render: RenderResult,
        discovery: TopicDiscoveryOutput,
        research: ResearchOutput,
    ) -> ThumbnailOutput:
        output_dir = self.run_dir / "output" / "thumbnails"
        self.log_input(
            {
                "title": script.title,
                "hook_line": script.hook_line,
                "video_path": render.video_path,
                "image_count": len(assets.image_paths),
                "selected_angle": discovery.selected_angle,
                "research_fact_count": len(research.facts),
                "output_dir": str(output_dir),
            }
        )
        self.provenance(
            "Generating free thumbnails",
            "deterministic",
            mode="thumbnail",
            output_dir=str(output_dir),
            method="image fallback plus simple templates",
        )
        output = create_thumbnail_set(
            render.video_path,
            assets.image_paths,
            output_dir,
            script.title,
            script.hook_line,
            discovery.niche_profile,
            discovery.selected_angle,
            research.facts,
        )
        self.provenance(
            "Thumbnails ready",
            "deterministic",
            mode="thumbnail",
            shorts_cover_path=output.shorts_cover_path,
            youtube_thumbnail_path=output.youtube_thumbnail_path,
            source_image_path=output.source_image_path,
            text_lines=output.text_lines,
        )
        self.log_output(output)
        return output
