from __future__ import annotations

from pathlib import Path

from agents.base import BaseAgent
from app.schemas import (
    AssetBundle,
    AudioBundle,
    CaptionBundle,
    GenreConfig,
    RenderResult,
    ScriptOutput,
    ValidationResult,
)
from modules.scripts.validator import validate_script
from modules.scripts.generator import (
    _compact_research,
    _filter_research_for_topic,
    validate_image_cues,
    validate_script_grounding,
    validate_script_originality,
    validate_script_relevance,
    validate_script_subjective_with_llm,
)
from modules.scripts.structure import validate_narrative_structure


class ValidationAgent(BaseAgent):
    name = "validation_agent"

    def validate_script_output(
        self,
        script: ScriptOutput,
        genre: GenreConfig,
        provider=None,
        topic: str = "",
        reference_scripts: list[dict] | None = None,
        growth_context=None,
    ) -> ValidationResult:
        research = _filter_research_for_topic(_compact_research(growth_context), topic)
        payload = {
            "stage": "script",
            "word_count": script.word_count,
            "topic": topic,
            "reference_count": len(reference_scripts or []),
            "uses_research_grounding": bool(research),
            "uses_llm_subjective_validation": bool(provider and topic),
            "validation_max_input_chars": 3000,
            "validation_max_output_tokens": 300,
        }
        self.log_input(payload)
        result = validate_script(script, genre.word_count_min, genre.word_count_max)
        result.issues.extend(validate_script_grounding(script, research))
        result.issues.extend(validate_narrative_structure(script.narration))
        if topic:
            result.issues.extend(validate_script_relevance(script, topic))
        result.issues.extend(validate_script_originality(script, reference_scripts or []))
        result.issues.extend(validate_image_cues(script.image_cues))
        if provider and topic:
            result.issues.extend(validate_script_subjective_with_llm(provider, script, topic, reference_scripts or []))
        result.passed = not result.issues
        result.repair_notes = _repair_notes_for_stage("script", result.issues)
        self.event("Script validation complete", passed=result.passed, issues=result.issues)
        self.log_output(result)
        return result

    def validate_assets(self, assets: AssetBundle) -> ValidationResult:
        issues = list(assets.subject_lock_issues)
        media_paths = assets.media_paths or assets.image_paths
        if len(media_paths) < 3:
            issues.append("At least 3 visual media assets are required")
        for path in media_paths:
            if not Path(path).exists():
                issues.append(f"Missing media asset: {path}")
        for path in assets.image_paths:
            if not Path(path).exists():
                issues.append(f"Missing image: {path}")
        for path in assets.video_paths:
            if not Path(path).exists():
                issues.append(f"Missing video: {path}")
        if assets.media_durations_ms:
            if len(assets.media_durations_ms) != len(assets.media_paths):
                issues.append("Timed media durations must match media_paths")
            if len(assets.media_start_ms) != len(assets.media_paths) or len(assets.media_end_ms) != len(assets.media_paths):
                issues.append("Timed media start/end lists must match media_paths")
            previous_end = -1
            for index, duration_ms in enumerate(assets.media_durations_ms):
                if int(duration_ms) <= 0:
                    issues.append(f"Timed media duration must be positive at index {index}")
                if index < len(assets.media_start_ms) and index < len(assets.media_end_ms):
                    start_ms = int(assets.media_start_ms[index])
                    end_ms = int(assets.media_end_ms[index])
                    if end_ms <= start_ms:
                        issues.append(f"Timed media end must be after start at index {index}")
                    if previous_end > start_ms:
                        issues.append(f"Timed media windows overlap at index {index}")
                    previous_end = end_ms
        return ValidationResult(passed=not issues, issues=issues, repair_notes=_repair_notes_for_stage("assets", issues))

    def validate_audio(self, audio: AudioBundle) -> ValidationResult:
        issues = []
        if not Path(audio.final_audio_path).exists():
            issues.append("Final audio file is missing")
        if audio.duration_ms < 10000:
            issues.append("Audio duration must be greater than 10 seconds")
        if not audio.word_timestamps:
            issues.append("Word timestamps are missing")
        if audio.provider not in {"google_tts", "edge_tts", "tone_fallback"}:
            issues.append(f"Unknown audio provider: {audio.provider}")
        if audio.alignment_source not in {"whisper", "estimated"}:
            issues.append(f"Unknown caption alignment source: {audio.alignment_source}")
        if audio.mean_volume_db is not None and audio.mean_volume_db < -35:
            issues.append(f"Audio is too quiet: mean volume {audio.mean_volume_db:.1f} dB")
        if audio.max_volume_db is not None and audio.max_volume_db < -12:
            issues.append(f"Audio has no strong speech peaks: max volume {audio.max_volume_db:.1f} dB")
        if audio.longest_silence_seconds is not None and audio.longest_silence_seconds > 2.0:
            issues.append(
                f"Audio has a long silent gap: {audio.longest_silence_seconds:.2f}s"
            )
        return ValidationResult(passed=not issues, issues=issues, repair_notes=_repair_notes_for_stage("audio", issues))

    def validate_captions(self, captions: CaptionBundle) -> ValidationResult:
        issues = []
        if not Path(captions.srt_path).exists():
            issues.append("SRT captions are missing")
        if not Path(captions.ass_path).exists():
            issues.append("ASS captions are missing")
        return ValidationResult(passed=not issues, issues=issues, repair_notes=_repair_notes_for_stage("captions", issues))

    def validate_render(self, result: RenderResult) -> ValidationResult:
        issues = []
        if not Path(result.video_path).exists():
            issues.append("Final video is missing")
        if result.width != 1080 or result.height != 1920:
            issues.append(f"Final video must be 1080x1920, got {result.width}x{result.height}")
        if result.duration_seconds < 10:
            issues.append("Final video duration must be greater than 10 seconds")
        if not has_audio_stream(result.video_path):
            issues.append("Final video is missing a playable audio stream")
        return ValidationResult(passed=not issues, issues=issues, repair_notes=_repair_notes_for_stage("render", issues))


def has_audio_stream(video_path: str) -> bool:
    import json
    import shutil
    import subprocess

    ffprobe = shutil.which("ffprobe")
    if not ffprobe or not Path(video_path).exists():
        return False
    proc = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,sample_rate,channels",
            "-of",
            "json",
            video_path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        return False
    streams = json.loads(proc.stdout or "{}").get("streams", [])
    if not streams:
        return False
    stream = streams[0]
    return bool(stream.get("codec_name")) and int(stream.get("channels", 0) or 0) > 0


def _repair_notes_for_stage(stage: str, issues: list[str]) -> list[str]:
    if not issues:
        return []
    joined = "; ".join(issues)
    defaults = {
        "script": "Regenerate the script using the validator issues as constraints. Keep the original user topic, normalize aliases naturally, and fix word count, hook, ending, and image cues.",
        "assets": "Refetch or replace weak assets using the same script cues. Prefer usable subject-matching media and avoid missing or placeholder files.",
        "audio": "Regenerate narration audio and timing files. Keep provider default speed unless the user explicitly requested a speed change.",
        "captions": "Regenerate captions from the audio word timestamps and keep caption files present and ordered.",
        "render": "Render again from the validated audio, captions, and assets, then verify output dimensions, duration, and audio stream.",
    }
    return [defaults.get(stage, "Regenerate the artifact using the validator issues as constraints."), f"Validator issues: {joined}"]
