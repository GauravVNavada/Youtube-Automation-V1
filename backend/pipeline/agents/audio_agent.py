from __future__ import annotations

from agents.base import BaseAgent
from app.schemas import AudioBundle, GenreConfig, WordTimestamp
from modules.audio.alignment import align_word_timestamps
from modules.audio.edge_tts import synthesize_edge_tts
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
        voice_speed_multiplier: float = 1.0,
        edge_tts_voice: str = "en-US-GuyNeural",
    ) -> AudioBundle:
        provider = "google_tts" if google_tts_credentials else "edge_tts"
        payload = {
            "word_count": word_count,
            "duration": duration,
            "genre_id": genre.genre_id,
            "provider": provider,
            "has_google_tts_credentials": bool(google_tts_credentials),
            "edge_tts_voice": edge_tts_voice,
            "voice_speed_multiplier": voice_speed_multiplier,
        }
        self.log_input(payload)
        audio_dir = self.run_dir / "intermediate" / "audio"
        speaking_rate = max(0.65, min(1.4, genre.voice_rate * voice_speed_multiplier))
        duration_ms = estimate_duration_ms(word_count, duration, speaking_rate)
        narration_path = audio_dir / "narration.wav"
        final_path = audio_dir / "final_audio.wav"
        provider = self._synthesize_narration(
            narration=narration,
            narration_path=narration_path,
            google_tts_credentials=google_tts_credentials,
            speaking_rate=speaking_rate,
            duration_ms=duration_ms,
            edge_tts_voice=edge_tts_voice,
        )
        raw_duration_ms = probe_audio_duration_ms(narration_path) or duration_ms
        self.provenance(
            "Aligning narration timestamps",
            mode="deterministic",
            duration_ms=raw_duration_ms,
            provider=provider,
        )
        alignment = align_word_timestamps(narration_path, narration, raw_duration_ms)
        self.provenance("Humanizing narration pauses", mode="deterministic", words=len(alignment.timestamps))
        humanized = humanize_narration_pauses(
            narration_path,
            final_path,
            alignment.timestamps,
            raw_duration_ms,
        )
        self.provenance(
            "Narration pause pass complete",
            mode="deterministic",
            source_duration_ms=raw_duration_ms,
            output_duration_ms=humanized.duration_ms,
            removed_ms=humanized.removed_ms,
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
        self.provenance(
            "Audio ready",
            mode="deterministic",
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

    def _synthesize_narration(
        self,
        *,
        narration: str,
        narration_path,
        google_tts_credentials: str,
        speaking_rate: float,
        duration_ms: int,
        edge_tts_voice: str,
    ) -> str:
        if google_tts_credentials:
            try:
                self.provenance(
                    "Synthesizing Google TTS narration",
                    mode="deterministic",
                    provider="google_tts",
                    method="external TTS service, no LLM",
                )
                synthesize_google_tts(
                    narration,
                    narration_path,
                    google_tts_credentials,
                    speaking_rate=speaking_rate,
                )
                return "google_tts"
            except Exception as exc:
                self.provenance(
                    "Google TTS failed; trying EdgeTTS fallback",
                    mode="fallback",
                    reason=str(exc),
                    duration_ms=duration_ms,
                )
        try:
            self.provenance(
                "Synthesizing EdgeTTS narration",
                mode="deterministic",
                provider="edge_tts",
                method="free EdgeTTS service, no LLM",
            )
            synthesize_edge_tts(narration, narration_path, voice_name=edge_tts_voice, speaking_rate=speaking_rate)
            return "edge_tts"
        except Exception as exc:
            self.provenance("EdgeTTS failed", mode="fallback", reason=str(exc), duration_ms=duration_ms)
            if google_tts_credentials:
                raise RuntimeError(f"Google TTS failed and EdgeTTS fallback failed: {exc}") from exc
            raise RuntimeError(f"EdgeTTS failed: {exc}") from exc
