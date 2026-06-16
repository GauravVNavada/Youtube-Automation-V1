from __future__ import annotations

from agents.base import BaseAgent
from app.schemas import AudioBundle, GenreConfig, WordTimestamp
from modules.audio.alignment import align_word_timestamps
from modules.audio.google_tts import synthesize_google_tts
from modules.audio.humanizer import humanize_narration_pauses
from modules.audio.probe import analyze_audio_quality, probe_audio_duration_ms
from modules.audio.tts import estimate_duration_ms


class AudioAgent(BaseAgent):
    name = "audio_agent"

    def run(
        self,
        narration: str,
        word_count: int,
        duration: int,
        genre: GenreConfig,
        google_tts_credentials: str = "",
    ) -> AudioBundle:
        provider = "google_tts"
        payload = {
            "word_count": word_count,
            "duration": duration,
            "genre_id": genre.genre_id,
            "provider": provider,
            "has_google_tts_credentials": bool(google_tts_credentials),
        }
        self.log_input(payload)
        audio_dir = self.run_dir / "intermediate" / "audio"
        duration_ms = estimate_duration_ms(word_count, duration, genre.voice_rate)
        narration_path = audio_dir / "narration.wav"
        final_path = audio_dir / "final_audio.wav"
        if not google_tts_credentials:
            raise RuntimeError("GOOGLE_TTS_CREDENTIALS is required for online narration")
        try:
            self.event("Synthesizing Google TTS narration")
            synthesize_google_tts(
                narration,
                narration_path,
                google_tts_credentials,
                speaking_rate=genre.voice_rate,
            )
        except Exception as exc:
            self.event("Google TTS failed", reason=str(exc), duration_ms=duration_ms)
            raise RuntimeError(f"Google TTS failed: {exc}") from exc
        raw_duration_ms = probe_audio_duration_ms(narration_path) or duration_ms
        self.event("Aligning raw Google TTS timestamps", duration_ms=raw_duration_ms)
        alignment = align_word_timestamps(narration_path, narration, raw_duration_ms)
        self.event("Humanizing narration pauses", words=len(alignment.timestamps))
        humanized = humanize_narration_pauses(
            narration_path,
            final_path,
            alignment.timestamps,
            raw_duration_ms,
        )
        actual_duration_ms = probe_audio_duration_ms(final_path) or humanized.duration_ms
        quality = analyze_audio_quality(final_path)
        timestamps = humanized.word_timestamps
        alignment_source = alignment.source
        bundle = AudioBundle(
            narration_path=str(narration_path),
            final_audio_path=str(final_path),
            duration_ms=actual_duration_ms,
            word_timestamps=timestamps,
            provider=provider,
            mean_volume_db=quality.mean_volume_db,
            max_volume_db=quality.max_volume_db,
            longest_silence_seconds=quality.longest_silence_seconds,
            alignment_source=alignment_source,
        )
        self.event(
            "Audio ready",
            path=str(final_path),
            words=len(timestamps),
            provider=provider,
            alignment_source=alignment_source,
            mean_volume_db=quality.mean_volume_db,
            max_volume_db=quality.max_volume_db,
            longest_silence_seconds=quality.longest_silence_seconds,
        )
        self.log_output(bundle)
        return bundle
