from __future__ import annotations

from agents.base import BaseAgent
from app.schemas import AssetBundle, AudioBundle, CaptionBundle, RenderResult
from modules.render.plan import write_render_plan
from modules.render.renderer import render_video
from modules.visuals.style_router import visual_style_to_dict


class RenderAgent(BaseAgent):
    name = "render_agent"

    def run(
        self,
        assets: AssetBundle,
        audio: AudioBundle,
        captions: CaptionBundle,
        music_volume: float = 0.18,
        visual_style: dict | None = None,
    ) -> RenderResult:
        output_path = self.run_dir / "output" / "final.mp4"
        plan_path = self.run_dir / "output" / "render_plan.json"
        visual_style_payload = visual_style_to_dict(visual_style)
        render_style = str(visual_style_payload.get("render_style") or assets.visual_style or "natural")
        payload = {
            "image_count": len(assets.image_paths),
            "video_count": len([path for path in assets.video_paths if path]),
            "audio_path": audio.final_audio_path,
            "music_path": assets.music_path,
            "ass_caption_path": captions.ass_path,
            "output_path": str(output_path),
            "render_plan_path": str(plan_path),
            "music_volume": music_volume,
            "visual_style": visual_style_payload,
            "render_style": render_style,
        }
        self.log_input(payload)
        render_plan_path = write_render_plan(
            assets=assets,
            audio=audio,
            captions=captions,
            output_path=output_path,
            plan_path=plan_path,
            music_volume=music_volume,
            render_style=render_style,
        )
        self.provenance(
            "Render plan written",
            mode="deterministic",
            render_plan_path=render_plan_path,
            method="ffmpeg plan assembly",
        )
        self.provenance(
            "Rendering final video",
            mode="deterministic",
            render_style=render_style,
            method="ffmpeg composition",
        )
        meta = render_video(
            image_paths=assets.image_paths,
            video_paths=assets.video_paths,
            audio_path=audio.final_audio_path,
            ass_caption_path=captions.ass_path,
            output_path=output_path,
            duration_ms=audio.duration_ms,
            music_path=assets.music_path,
            music_volume=music_volume,
            render_style=render_style,
        )
        result = RenderResult(
            video_path=meta["video_path"],
            width=meta["width"],
            height=meta["height"],
            duration_seconds=meta["duration_seconds"],
        )
        self.provenance(
            "Render complete",
            mode="deterministic",
            video_path=result.video_path,
            audio_codec=meta.get("audio_codec"),
            audio_sample_rate=meta.get("audio_sample_rate"),
            audio_channels=meta.get("audio_channels"),
            extracted_audio_path=meta.get("extracted_audio_path"),
        )
        self.log_output(result)
        return result
