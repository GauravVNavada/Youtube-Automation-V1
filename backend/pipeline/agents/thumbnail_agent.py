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
        payload = {
            "title": script.title,
            "hook_line": script.hook_line,
            "video_path": render.video_path,
            "image_count": len(assets.image_paths),
            "selected_angle": discovery.selected_angle,
            "research_fact_count": len(research.facts),
            "output_dir": str(output_dir),
        }
        self.log_input(payload)
        self.provenance(
            "Generating free thumbnails",
            mode="deterministic",
            output_dir=str(output_dir),
            method="frame extraction/image fallback plus Pillow templates",
        )
        output = create_thumbnail_set(
            video_path=render.video_path,
            image_paths=assets.image_paths,
            output_dir=output_dir,
            title=script.title,
            hook_line=script.hook_line,
            profile=discovery.niche_profile,
            selected_angle=discovery.selected_angle,
            facts=research.facts,
        )
        self.provenance(
            "Thumbnails ready",
            mode="deterministic",
            shorts_cover_path=output.shorts_cover_path,
            youtube_thumbnail_path=output.youtube_thumbnail_path,
            source_image_path=output.source_image_path,
            text_lines=output.text_lines,
        )
        self.log_output(output)
        return output
