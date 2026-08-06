from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess

from agents.base import BaseAgent
from app.paths import DATA_DIR
from app.schemas import AssetBundle, AudioBundle, MusicBundle, SfxCue, WordTimestamp
from modules.audio.sfx_catalog import resolve_sfx_cues
from modules.audio.probe import analyze_audio_quality, probe_audio_duration_ms


MAX_SFX_PER_RUN = 8
SFX_GAIN = 0.4
SFX_PRE_LAP_MS = 200
SFX_MAX_SECONDS = 5.0


class MusicAgent(BaseAgent):
    name = "music_agent"

    def run(
        self,
        audio: AudioBundle,
        assets: AssetBundle,
        sfx_cues: list[SfxCue] | None = None,
        music_path: str = "",
        music_volume: float = 0.12,
    ) -> MusicBundle:
        selected_music = _selected_music_path(music_path)
        selected_music_exists = selected_music if selected_music and selected_music.exists() else None
        sfx_paths = list(assets.sfx_paths)
        sfx_asset_ids = list(assets.sfx_asset_ids)
        sfx_asset_names = list(assets.sfx_asset_names)
        sfx_selection_trace: list[dict] = []
        if not sfx_paths and sfx_cues:
            sfx_paths, sfx_selection_trace = resolve_sfx_cues(sfx_cues, DATA_DIR / "assets" / "sfx")
            sfx_asset_ids = [
                str(item.get("sfx_id"))
                for item in sfx_selection_trace
                if isinstance(item, dict) and item.get("status") == "matched" and item.get("sfx_id")
            ]
            sfx_asset_names = [
                str(item.get("sfx_name"))
                for item in sfx_selection_trace
                if isinstance(item, dict) and item.get("status") == "matched" and item.get("sfx_name")
            ]
            if sfx_paths:
                self.event(
                    "SFX resolved from catalog during music mix",
                    sfx_count=len(sfx_paths),
                    sfx_ids=sfx_asset_ids,
                )
        sfx_placements = _sfx_placements(
            sfx_paths,
            sfx_cues or [],
            audio.word_timestamps,
            audio.duration_ms,
            sfx_asset_ids,
            sfx_asset_names,
        )
        payload = {
            "input_audio_path": audio.final_audio_path,
            "asset_music_path": assets.music_path,
            "selected_music_path": str(selected_music) if selected_music else "",
            "music_volume": music_volume,
            "sfx_paths": sfx_paths,
            "sfx_asset_ids": sfx_asset_ids,
            "sfx_asset_names": sfx_asset_names,
            "sfx_selection_trace": sfx_selection_trace or assets.sfx_selection_trace,
            "sfx_cues": sfx_cues or [],
            "sfx_placements": sfx_placements,
            "duration_ms": audio.duration_ms,
        }
        self.log_input(payload)

        if selected_music and not selected_music.exists():
            self.event("Selected music missing; continuing with SFX only", path=str(selected_music))

        if not selected_music_exists and not sfx_placements:
            reason = "No uploaded music selected and no SFX placements"
            if selected_music:
                reason = f"Selected music file is missing and no SFX placements were available: {selected_music}"
            bundle = self._skipped(audio, music_volume, reason)
            self.event("No music or SFX selected; keeping clean narration audio")
            self.log_output(bundle)
            return bundle

        output_path = self.run_dir / "intermediate" / "audio" / "final_audio_with_music.wav"
        self.event(
            "Mixing audio layers",
            music_path=str(selected_music_exists) if selected_music_exists else "",
            sfx_count=len(sfx_placements),
            output_path=str(output_path),
        )
        _mix_audio_layers(
            narration_path=Path(audio.final_audio_path),
            music_path=selected_music_exists,
            output_path=output_path,
            duration_ms=audio.duration_ms,
            music_volume=music_volume,
            sfx_placements=sfx_placements,
        )
        duration_ms = probe_audio_duration_ms(output_path) or audio.duration_ms
        quality = analyze_audio_quality(output_path)
        bundle = MusicBundle(
            input_audio_path=audio.final_audio_path,
            final_audio_path=str(output_path),
            music_path=str(selected_music_exists) if selected_music_exists else None,
            duration_ms=duration_ms,
            music_volume=music_volume,
            mixed=bool(selected_music_exists),
            status="succeeded",
            sfx_paths=[placement["path"] for placement in sfx_placements],
            sfx_asset_ids=[str(placement.get("sfx_id") or "") for placement in sfx_placements],
            sfx_asset_names=[str(placement.get("sfx_name") or "") for placement in sfx_placements],
            sfx_timings_ms=[int(placement["position_ms"]) for placement in sfx_placements],
            sfx_mixed=bool(sfx_placements),
            mean_volume_db=quality.mean_volume_db,
            max_volume_db=quality.max_volume_db,
            longest_silence_seconds=quality.longest_silence_seconds,
        )
        self.event(
            "Audio layer mix ready",
            path=str(output_path),
            music_path=str(selected_music_exists) if selected_music_exists else "",
            sfx_count=len(sfx_placements),
            sfx_ids=bundle.sfx_asset_ids,
            sfx_timings_ms=bundle.sfx_timings_ms,
            mean_volume_db=quality.mean_volume_db,
            max_volume_db=quality.max_volume_db,
            longest_silence_seconds=quality.longest_silence_seconds,
        )
        self.log_output(bundle)
        return bundle

    def _skipped(self, audio: AudioBundle, music_volume: float, reason: str) -> MusicBundle:
        return MusicBundle(
            input_audio_path=audio.final_audio_path,
            final_audio_path=audio.final_audio_path,
            music_path=None,
            duration_ms=audio.duration_ms,
            music_volume=music_volume,
            mixed=False,
            status="skipped",
            skipped_reason=reason,
            sfx_paths=[],
            sfx_asset_ids=[],
            sfx_asset_names=[],
            sfx_timings_ms=[],
            sfx_mixed=False,
            mean_volume_db=audio.mean_volume_db,
            max_volume_db=audio.max_volume_db,
            longest_silence_seconds=audio.longest_silence_seconds,
        )


def _selected_music_path(requested: str) -> Path | None:
    raw = str(requested or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _sfx_placements(
    sfx_paths: list[str],
    sfx_cues: list[SfxCue],
    word_timestamps: list[WordTimestamp],
    duration_ms: int,
    sfx_asset_ids: list[str] | None = None,
    sfx_asset_names: list[str] | None = None,
) -> list[dict[str, str | int]]:
    placements: list[dict[str, str | int]] = []
    usable_paths = [Path(path) for path in sfx_paths if path and Path(path).exists()]
    if not usable_paths:
        return placements
    asset_ids = list(sfx_asset_ids or [])
    asset_names = list(sfx_asset_names or [])
    total = min(len(usable_paths), MAX_SFX_PER_RUN)
    for index, path in enumerate(usable_paths[:total]):
        cue = sfx_cues[index] if index < len(sfx_cues) else None
        trigger_ms, strategy = _trigger_time_ms(
            cue,
            word_timestamps,
            duration_ms,
            index=index,
            total=total,
        )
        placement_ms = max(0, int(trigger_ms) - SFX_PRE_LAP_MS)
        placements.append(
            {
                "path": str(path),
                "position_ms": placement_ms,
                "trigger_ms": int(trigger_ms),
                "trigger_word": cue.trigger_word if cue else "",
                "sfx_type": cue.sfx_type if cue else "",
                "sfx_id": asset_ids[index] if index < len(asset_ids) else "",
                "sfx_name": asset_names[index] if index < len(asset_names) else "",
                "strategy": strategy,
            }
        )
    return placements


def _trigger_time_ms(
    cue: SfxCue | None,
    word_timestamps: list[WordTimestamp],
    duration_ms: int,
    *,
    index: int,
    total: int,
) -> tuple[int, str]:
    if cue:
        phrase_time = _match_phrase_start_ms(cue.trigger_word, word_timestamps)
        if phrase_time is not None:
            return phrase_time, "trigger_word"
        hint_time = _timestamp_from_hint(cue.timestamp_hint, word_timestamps, duration_ms)
        if hint_time is not None:
            return hint_time, "timestamp_hint"
    fallback = int(max(0, min(duration_ms, ((index + 1) / (total + 1)) * duration_ms)))
    return fallback, "distributed_fallback"


def _match_phrase_start_ms(trigger_word: str, word_timestamps: list[WordTimestamp]) -> int | None:
    tokens = [_normalized_word(token) for token in str(trigger_word or "").split()]
    tokens = [token for token in tokens if token]
    if not tokens:
        return None
    words = [_normalized_word(item.word) for item in word_timestamps]
    for index in range(0, max(0, len(words) - len(tokens) + 1)):
        if words[index : index + len(tokens)] == tokens:
            return int(word_timestamps[index].start_ms)
    return None


def _timestamp_from_hint(hint: str, word_timestamps: list[WordTimestamp], duration_ms: int) -> int | None:
    text = str(hint or "").strip().lower()
    if not text:
        return None
    word_match = re.search(r"word[_\s-]*(\d+)", text)
    if word_match:
        index = int(word_match.group(1))
        if 0 <= index < len(word_timestamps):
            return int(word_timestamps[index].start_ms)
    ms_match = re.search(r"(\d+(?:\.\d+)?)\s*ms\b", text)
    if ms_match:
        return int(float(ms_match.group(1)))
    sec_match = re.search(r"(\d+(?:\.\d+)?)\s*s(?:ec(?:ond)?s?)?\b", text)
    if sec_match:
        return int(float(sec_match.group(1)) * 1000)
    if "hook" in text or "start" in text or "intro" in text:
        return min(600, duration_ms)
    if "twist" in text or "reveal" in text or "turn" in text:
        return int(duration_ms * 0.72)
    if "ending" in text or "end" in text or "final" in text:
        return int(duration_ms * 0.9)
    return None


def _normalized_word(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _mix_audio_layers(
    *,
    narration_path: Path,
    music_path: Path | None,
    output_path: Path,
    duration_ms: int,
    music_volume: float,
    sfx_placements: list[dict[str, str | int]],
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to mix audio layers")
    if not narration_path.exists():
        raise RuntimeError(f"Narration audio not found: {narration_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration_seconds = max(0.25, duration_ms / 1000.0)
    music_gain = max(0.0, min(0.8, float(music_volume)))
    fade_out_start = max(0.0, duration_seconds - 2.0)
    cmd = [ffmpeg, "-y", "-i", str(narration_path)]
    music_input_index: int | None = None
    if music_path:
        music_input_index = 1
        cmd.extend(["-stream_loop", "-1", "-i", str(music_path)])
    sfx_input_start = 1 + (1 if music_path else 0)
    for placement in sfx_placements:
        cmd.extend(["-i", str(placement["path"])])

    filters = ["[0:a]aresample=44100[narr]"]
    mix_labels = ["[narr]"]
    if music_input_index is not None:
        filters.append(
            (
                f"[{music_input_index}:a]atrim=0:{duration_seconds:.2f},asetpts=PTS-STARTPTS,"
                f"volume={music_gain},afade=t=in:d=1.0,"
                f"afade=t=out:st={fade_out_start:.2f}:d=2.0[bgm]"
            )
        )
        mix_labels.append("[bgm]")
    for index, placement in enumerate(sfx_placements):
        input_index = sfx_input_start + index
        delay_ms = max(0, int(placement["position_ms"]))
        label = f"sfx{index}"
        filters.append(
            (
                f"[{input_index}:a]atrim=0:{SFX_MAX_SECONDS:.2f},asetpts=PTS-STARTPTS,"
                f"volume={SFX_GAIN},adelay={delay_ms}:all=1[{label}]"
            )
        )
        mix_labels.append(f"[{label}]")
    filters.append(
        "".join(mix_labels)
        + f"amix=inputs={len(mix_labels)}:duration=first:dropout_transition=0:"
        "normalize=0,alimiter=limit=0.89:level=disabled[aout]"
    )

    cmd.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[aout]",
            "-t",
            f"{duration_seconds:.3f}",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "44100",
            "-ac",
            "2",
            str(output_path),
        ]
    )
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Audio layer mix failed: {proc.stderr[-1200:]}")
    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise RuntimeError("Audio layer mix produced an unusable audio file")
