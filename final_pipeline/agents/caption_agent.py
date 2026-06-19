from __future__ import annotations

from agents.base import BaseAgent
from app.schemas import CaptionBundle, WordTimestamp
from modules.captions.ass_builder import build_ass
from modules.captions.srt_builder import build_srt


class CaptionAgent(BaseAgent):
    name = "caption_agent"

    def run(
        self,
        word_timestamps: list[WordTimestamp],
        caption_preset: str,
        emphasis_words: list[str],
        words_per_caption: int = 4,
    ) -> CaptionBundle:
        payload = {
            "word_count": len(word_timestamps),
            "caption_preset": caption_preset,
            "emphasis_words": emphasis_words,
            "words_per_caption": words_per_caption,
        }
        self.log_input(payload)
        caption_dir = self.run_dir / "intermediate" / "captions"
        self.event("Building SRT captions")
        srt_path, srt_count = build_srt(word_timestamps, caption_dir / "captions.srt", words_per_caption=words_per_caption)
        self.event("Building ASS captions")
        ass_path, ass_count = build_ass(
            word_timestamps,
            caption_dir / "captions.ass",
            preset=caption_preset,
            emphasis_words=emphasis_words,
            words_per_caption=words_per_caption,
        )
        bundle = CaptionBundle(
            srt_path=srt_path,
            ass_path=ass_path,
            phrase_count=max(srt_count, ass_count),
            word_count=len(word_timestamps),
        )
        self.log_output(bundle)
        return bundle
