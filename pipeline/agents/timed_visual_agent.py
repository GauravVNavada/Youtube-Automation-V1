from __future__ import annotations

import json
from pathlib import Path

from agents.base import BaseAgent
from app.logger import to_jsonable
from app.schemas import AudioBundle, GenreConfig, ScriptOutput, TimedVisualCue
from modules.visuals.timed_cues import MIN_VISUAL_SEGMENT_MS, generate_timed_visual_cues


class TimedVisualAgent(BaseAgent):
    name = "timed_visual_agent"

    def run(
        self,
        *,
        script: ScriptOutput,
        audio: AudioBundle,
        genre: GenreConfig,
        topic: str = "",
        provider=None,
        min_segment_ms: int = MIN_VISUAL_SEGMENT_MS,
    ) -> list[TimedVisualCue]:
        payload = {
            "word_count": len(audio.word_timestamps),
            "duration_ms": audio.duration_ms,
            "genre_id": genre.genre_id,
            "topic": topic,
            "min_segment_ms": min_segment_ms,
            "rewrite_provider": getattr(provider, "name", "none") if provider else "none",
        }
        self.log_input(payload)
        try:
            cues, meta = generate_timed_visual_cues(
                script=script,
                words=audio.word_timestamps,
                genre=genre,
                duration_ms=audio.duration_ms,
                topic=topic,
                provider=provider,
                min_segment_ms=min_segment_ms,
            )
        except Exception as exc:
            cues = []
            meta = {"error": f"{type(exc).__name__}: {exc}"}
            self.event("Timed visual cue generation failed; script image cues will be used", error=meta["error"])

        artifact_path = _write_timed_cues(self.run_dir, cues)
        self.event(
            "Timed visual cues ready",
            cue_count=len(cues),
            timed_visual_cues_path=artifact_path,
            **meta,
        )
        self.log_output(
            {
                "timed_visual_cues_path": artifact_path,
                "cue_count": len(cues),
                "cues": cues,
                **meta,
            }
        )
        return cues


def _write_timed_cues(run_dir: Path, cues: list[TimedVisualCue]) -> str:
    path = run_dir / "logs" / "timed_visual_agent" / "timed_visual_cues.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(cues), indent=2, ensure_ascii=True), encoding="utf-8")
    return str(path)
