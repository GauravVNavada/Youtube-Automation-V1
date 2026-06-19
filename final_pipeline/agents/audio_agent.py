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


INITIAL_AUDIO_SILENCE_MS = 220
SENTENCE_AUDIO_GAP_MS = 180


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
    ) -> AudioBundle:
        provider = "google_tts" if google_tts_credentials else "edge_tts"
        effective_voice_rate = max(0.5, min(1.6, genre.voice_rate * voice_speed_multiplier))
        payload = {
            "word_count": word_count,
            "duration": duration,
            "genre_id": genre.genre_id,
            "genre_voice_rate": genre.voice_rate,
            "voice_speed_multiplier": voice_speed_multiplier,
            "effective_voice_rate": effective_voice_rate,
            "provider_order": ["google_tts", "edge_tts", "tone_fallback"],
            "has_google_tts_credentials": bool(google_tts_credentials),
        }
        self.log_input(payload)
        audio_dir = self.run_dir / "intermediate" / "audio"
        duration_ms = estimate_duration_ms(word_count, duration, effective_voice_rate)
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
                    speaking_rate=effective_voice_rate,
                )
                provider = "google_tts"
            except Exception as exc:
                self.event("Google TTS failed; trying Edge TTS", reason=str(exc), duration_ms=duration_ms)
                provider, narration_path = self._try_edge_tts(narration, audio_dir, effective_voice_rate, duration_ms)
        else:
            provider, narration_path = self._try_edge_tts(narration, audio_dir, effective_voice_rate, duration_ms)

        raw_duration_ms = probe_audio_duration_ms(narration_path) or duration_ms
        if provider in {"google_tts", "edge_tts"}:
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
        sentence_gap_path = audio_dir / "final_audio_sentence_gaps.wav"
        inserted_ms, gap_timestamps = _insert_sentence_gaps(
            final_path,
            sentence_gap_path,
            timestamps,
            actual_duration_ms,
            SENTENCE_AUDIO_GAP_MS,
        )
        if inserted_ms > 0:
            final_path = sentence_gap_path
            timestamps = gap_timestamps
            actual_duration_ms = (probe_audio_duration_ms(final_path) or actual_duration_ms + inserted_ms)
        padded_path = audio_dir / "final_audio_padded.wav"
        if _prepend_silence(final_path, padded_path, INITIAL_AUDIO_SILENCE_MS):
            final_path = padded_path
            timestamps = _shift_word_timestamps(timestamps, INITIAL_AUDIO_SILENCE_MS)
            actual_duration_ms = (probe_audio_duration_ms(final_path) or actual_duration_ms + INITIAL_AUDIO_SILENCE_MS)
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


def _prepend_silence(source_path: Path, target_path: Path, silence_ms: int) -> bool:
    if silence_ms <= 0:
        return False
    ffmpeg = shutil.which("ffmpeg")
    source = Path(source_path)
    if not ffmpeg or not source.exists():
        return False
    target_path.parent.mkdir(parents=True, exist_ok=True)
    seconds = silence_ms / 1000.0
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-t",
            f"{seconds:.3f}",
            "-i",
            "anullsrc=r=44100:cl=stereo",
            "-i",
            str(source),
            "-filter_complex",
            "[0:a][1:a]concat=n=2:v=0:a=1[a]",
            "-map",
            "[a]",
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
    return proc.returncode == 0 and target_path.exists() and target_path.stat().st_size > 0


def _insert_sentence_gaps(
    source_path: Path,
    target_path: Path,
    words: list[WordTimestamp],
    duration_ms: int,
    gap_ms: int,
) -> tuple[int, list[WordTimestamp]]:
    boundaries = _sentence_boundaries(words, duration_ms)
    if not boundaries or gap_ms <= 0:
        return 0, words
    ffmpeg = shutil.which("ffmpeg")
    source = Path(source_path)
    if not ffmpeg or not source.exists():
        return 0, words

    target_path.parent.mkdir(parents=True, exist_ok=True)
    filters: list[str] = []
    concat_labels: list[str] = []
    cursor = 0
    segment_index = 0
    silence_index = 0
    for boundary in boundaries:
        if boundary > cursor:
            label = f"a{segment_index}"
            filters.append(
                f"[0:a]atrim=start={cursor / 1000.0:.3f}:end={boundary / 1000.0:.3f},"
                f"asetpts=PTS-STARTPTS[{label}]"
            )
            concat_labels.append(f"[{label}]")
            segment_index += 1
        silence_label = f"s{silence_index}"
        filters.append(
            f"[1:a]atrim=duration={gap_ms / 1000.0:.3f},asetpts=PTS-STARTPTS[{silence_label}]"
        )
        concat_labels.append(f"[{silence_label}]")
        silence_index += 1
        cursor = boundary
    if cursor < duration_ms:
        label = f"a{segment_index}"
        filters.append(
            f"[0:a]atrim=start={cursor / 1000.0:.3f}:end={duration_ms / 1000.0:.3f},"
            f"asetpts=PTS-STARTPTS[{label}]"
        )
        concat_labels.append(f"[{label}]")

    filters.append("".join(concat_labels) + f"concat=n={len(concat_labels)}:v=0:a=1[aout]")
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(source),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=stereo",
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[aout]",
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
    if proc.returncode != 0 or not target_path.exists() or target_path.stat().st_size <= 0:
        return 0, words
    inserted_ms = len(boundaries) * gap_ms
    return inserted_ms, _shift_after_boundaries(words, boundaries, gap_ms)


def _sentence_boundaries(words: list[WordTimestamp], duration_ms: int) -> list[int]:
    boundaries = []
    for index, word in enumerate(words[:-1]):
        if str(word.word or "").rstrip().endswith((".", "!", "?")):
            boundary = max(0, min(duration_ms - 1, int(word.end_ms)))
            if not boundaries or boundary - boundaries[-1] > 250:
                boundaries.append(boundary)
    return boundaries[:30]


def _shift_after_boundaries(words: list[WordTimestamp], boundaries: list[int], gap_ms: int) -> list[WordTimestamp]:
    shifted = []
    for word in words:
        offset = sum(gap_ms for boundary in boundaries if word.start_ms >= boundary)
        shifted.append(
            WordTimestamp(
                word=word.word,
                start_ms=word.start_ms + offset,
                end_ms=word.end_ms + offset,
            )
        )
    return shifted


def _shift_word_timestamps(words: list[WordTimestamp], offset_ms: int) -> list[WordTimestamp]:
    return [
        WordTimestamp(
            word=word.word,
            start_ms=word.start_ms + offset_ms,
            end_ms=word.end_ms + offset_ms,
        )
        for word in words
    ]


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
