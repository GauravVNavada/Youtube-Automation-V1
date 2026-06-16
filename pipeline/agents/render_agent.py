from __future__ import annotations

from agents.base import BaseAgent
from app.schemas import AssetBundle, AudioBundle, CaptionBundle, RenderResult
from modules.render.renderer import render_video


class RenderAgent(BaseAgent):
    name = "render_agent"

    def run(
        self,
        assets: AssetBundle,
        audio: AudioBundle,
        captions: CaptionBundle,
    ) -> RenderResult:
        output_path = self.run_dir / "output" / "final.mp4"
        payload = {
            "image_count": len(assets.image_paths),
            "audio_path": audio.final_audio_path,
            "music_path": assets.music_path,
            "ass_caption_path": captions.ass_path,
            "output_path": str(output_path),
        }
        self.log_input(payload)
        self.event("Rendering final video")
        meta = render_video(
            image_paths=assets.image_paths,
            audio_path=audio.final_audio_path,
            ass_caption_path=captions.ass_path,
            output_path=output_path,
            duration_ms=audio.duration_ms,
            music_path=assets.music_path,
        )
        result = RenderResult(
            video_path=meta["video_path"],
            width=meta["width"],
            height=meta["height"],
            duration_seconds=meta["duration_seconds"],
        )
        self.event(
            "Render complete",
            video_path=result.video_path,
            audio_codec=meta.get("audio_codec"),
            audio_sample_rate=meta.get("audio_sample_rate"),
            audio_channels=meta.get("audio_channels"),
            extracted_audio_path=meta.get("extracted_audio_path"),
        )
        self.log_output(result)
        return result
