from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess

from agents.base import BaseAgent
from app.schemas import AudioBundle, GenreConfig, WordTimestamp
from modules.audio.alignment import align_word_timestamps
from modules.audio.edge_tts import synthesize_edge_tts
from modules.audio.google_tts import synthesize_google_tts
from modules.audio.humanizer import humanize_narration_pauses
from modules.audio.probe import analyze_audio_quality, probe_audio_duration_ms
from modules.audio.timing import evenly_spaced_word_timestamps
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
        provider = "google_tts" if google_tts_credentials else "edge_tts"
        payload = {
            "word_count": word_count,
            "duration": duration,
            "genre_id": genre.genre_id,
            "provider_order": ["google_tts", "edge_tts", "tone_fallback"],
            "has_google_tts_credentials": bool(google_tts_credentials),
        }
        self.log_input(payload)
        audio_dir = self.run_dir / "intermediate" / "audio"
        duration_ms = estimate_duration_ms(word_count, duration, genre.voice_rate)
        narration_path = audio_dir / "narration.wav"
        final_path = audio_dir / "final_audio.wav"
        audio_dir.mkdir(parents=True, exist_ok=True)

        if google_tts_credentials:
            try:
                self.event("Synthesizing Google TTS narration")
                synthesize_google_tts(
                    narration,
                    narration_path,
                    google_tts_credentials,
                    speaking_rate=genre.voice_rate,
                )
                provider = "google_tts"
            except Exception as exc:
                self.event("Google TTS failed; trying Edge TTS", reason=str(exc), duration_ms=duration_ms)
                provider, narration_path = self._try_edge_tts(narration, audio_dir, genre.voice_rate, duration_ms)
        else:
            provider, narration_path = self._try_edge_tts(narration, audio_dir, genre.voice_rate, duration_ms)

        raw_duration_ms = probe_audio_duration_ms(narration_path) or duration_ms
        if provider == "google_tts":
            timestamps, alignment_source = self._word_timestamps(narration_path, narration, raw_duration_ms)
        else:
            words = [word for word in re.findall(r"\S+", narration) if word.strip()]
            self.event("Using estimated word timing for fallback narration", provider=provider, words=len(words))
            timestamps = evenly_spaced_word_timestamps(words, raw_duration_ms)
            alignment_source = "estimated"
        if provider == "google_tts" and alignment_source == "whisper":
            self.event("Humanizing narration pauses", words=len(timestamps))
            humanized = humanize_narration_pauses(
                narration_path,
                final_path,
                timestamps,
                raw_duration_ms,
            )
            timestamps = humanized.word_timestamps
            actual_duration_ms = probe_audio_duration_ms(final_path) or humanized.duration_ms
        else:
            _convert_or_copy_audio(narration_path, final_path)
            actual_duration_ms = probe_audio_duration_ms(final_path) or raw_duration_ms
        quality = analyze_audio_quality(final_path)
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

    def _try_edge_tts(
        self,
        narration: str,
        audio_dir: Path,
        speaking_rate: float,
        duration_ms: int,
    ) -> tuple[str, Path]:
        edge_path = audio_dir / "narration_edge.mp3"
        try:
            self.event("Synthesizing Edge TTS narration")
            synthesize_edge_tts(narration, edge_path, speaking_rate=speaking_rate)
            return "edge_tts", edge_path
        except Exception as exc:
            self.event("Edge TTS failed; using deterministic audio fallback", reason=str(exc), duration_ms=duration_ms)
            fallback_path = audio_dir / "narration_fallback.wav"
            _generate_tone_fallback(fallback_path, duration_ms)
            return "tone_fallback", fallback_path

    def _word_timestamps(
        self,
        audio_path: str | Path,
        narration: str,
        duration_ms: int,
    ) -> tuple[list[WordTimestamp], str]:
        try:
            self.event("Aligning narration timestamps", duration_ms=duration_ms)
            alignment = align_word_timestamps(audio_path, narration, duration_ms)
            return alignment.timestamps, alignment.source
        except Exception as exc:
            words = [word for word in re.findall(r"\S+", narration) if word.strip()]
            self.event("Whisper alignment failed; using estimated word timing", reason=str(exc), words=len(words))
            return evenly_spaced_word_timestamps(words, duration_ms), "estimated"


def _convert_or_copy_audio(source_path: str | Path, target_path: Path) -> None:
    source = Path(source_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() == ".wav":
        if source.resolve() != target_path.resolve():
            shutil.copyfile(source, target_path)
        return
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        shutil.copyfile(source, target_path)
        return
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(source),
            "-acodec",
            "pcm_s16le",
            "-ar",
            "44100",
            "-ac",
            "2",
            str(target_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Could not convert narration audio: {proc.stderr[-1000:]}")


def _generate_tone_fallback(output_path: Path, duration_ms: int) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for deterministic audio fallback")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration_seconds = max(10.0, duration_ms / 1000.0)
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=220:duration={duration_seconds:.3f}",
            "-af",
            "volume=12dB",
            "-ar",
            "44100",
            "-ac",
            "2",
            str(output_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Could not generate fallback audio: {proc.stderr[-1000:]}")
