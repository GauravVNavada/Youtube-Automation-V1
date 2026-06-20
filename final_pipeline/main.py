from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from agents.asset_agent import AssetAgent
from agents.audio_agent import AudioAgent
from agents.caption_agent import CaptionAgent
from agents.music_agent import MusicAgent
from agents.render_agent import RenderAgent
from agents.research_agent import ResearchAgent
from agents.script_agent import ScriptAgent
from agents.thumbnail_agent import ThumbnailAgent
from agents.timed_visual_agent import TimedVisualAgent
from agents.topic_discovery_agent import TopicDiscoveryAgent
from agents.validation_agent import ValidationAgent
from app.config import get_settings
from app.logger import ErrorLogger
from app.paths import DATA_DIR, create_run_dir, ensure_data_dirs
from app.schemas import (
    AssetBundle,
    AudioBundle,
    CaptionBundle,
    GenreConfig,
    GrowthContext,
    ImageCue,
    MusicBundle,
    NicheProfile,
    PipelineContext,
    RenderResult,
    ResearchOutput,
    ResearchSource,
    ScriptOutput,
    SfxCue,
    ThumbnailOutput,
    TimedVisualCue,
    TopicCandidate,
    TopicDiscoveryOutput,
    WordTimestamp,
)
from modules.llm.factory import LLMConfig, create_llm_provider
from modules.assets.subject_lock import infer_subject_lock


MAX_VALIDATION_REPAIR_ATTEMPTS = 3


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a local YouTube Short.")
    parser.add_argument("--topic", required=True, help="Topic for the short")
    parser.add_argument("--genre", default="scary_stories", help="Genre id")
    parser.add_argument("--duration", type=int, default=45)
    parser.add_argument("--notes", default="", help="Optional user style notes")
    parser.add_argument("--source-prompt", default="", help="Clean source prompt used for generation when display topic differs")
    parser.add_argument("--voice-speed", type=float, default=1.0, help="Voice speed multiplier applied to the genre voice rate")
    parser.add_argument("--caption-words", type=int, default=4, help="Words per caption phrase")
    parser.add_argument("--image-count", type=int, default=8, help="Target visual variety count for agents")
    parser.add_argument("--music-path", default="", help="Uploaded background music path to mix before rendering")
    parser.add_argument("--music-volume", type=float, default=0.12, help="Background music volume")
    parser.add_argument("--visual-motion", choices=["on", "off"], default="on", help="Animate still visuals with subtle motion")
    parser.add_argument("--transition-style", choices=["slide", "fade", "wipe", "cut"], default="slide", help="Visual transition style")
    parser.add_argument("--transition-seconds", type=float, default=0.45, help="Per-transition duration in seconds")
    parser.add_argument("--zoom-variant", choices=["mixed", "center_in", "center_out", "still"], default="mixed", help="Still-image zoom variant")
    parser.add_argument("--min-visual-segment-ms", type=int, default=3500, help="Minimum timed visual cue length in milliseconds")
    parser.add_argument("--style-profile-json", default="", help="Selected desktop calibration style profile")
    parser.add_argument("--agent-instructions-json", default="", help="Desktop master-agent instructions by pipeline agent")
    parser.add_argument("--resume-from-run-dir", default="", help="Parent pipeline run directory to reuse upstream artifacts from")
    parser.add_argument("--rerun-stage", default="", help="Visible stage id to rerun from when resuming parent artifacts")
    args = parser.parse_args()
    source_text = args.source_prompt or args.topic
    topic = strip_duration_instruction(source_text)
    duration = duration_from_topic(source_text) or duration_from_topic(args.topic) or args.duration
    style_profile = _json_arg(args.style_profile_json)
    agent_instructions = _json_arg(args.agent_instructions_json)
    run_notes = _compose_run_notes(args.notes, style_profile, agent_instructions, args.image_count)
    visual_motion = args.visual_motion == "on"

    settings = get_settings()
    ensure_data_dirs()
    run_dir = create_run_dir()
    errors = ErrorLogger(run_dir)
    resume = ResumeContext(
        parent_run_dir=Path(args.resume_from_run_dir) if args.resume_from_run_dir else None,
        rerun_stage=args.rerun_stage,
        run_dir=run_dir,
    )
    context = PipelineContext(
        topic=topic,
        genre_id=args.genre,
        duration=duration,
        run_dir=str(run_dir),
        user_notes=run_notes,
    )

    stage = "bootstrap"
    try:
        genre = run_stage(
            errors,
            stage,
            lambda: load_genre(args.genre),
            context=context,
        )
        references = run_stage(
            errors,
            "load_references",
            lambda: load_reference_scripts(args.genre),
            context=context,
        )
        provider = run_stage(
            errors,
            "llm_provider",
            lambda: create_llm_provider(
                LLMConfig(
                    provider=settings.llm_provider,
                    api_key=settings.llm_api_key,
                    model=settings.llm_model,
                    anthropic_api_key=settings.anthropic_api_key,
                    anthropic_model=settings.anthropic_model,
                    groq_api_key=settings.groq_api_key,
                    groq_model=settings.groq_model,
                    gemini_api_key=settings.gemini_api_key,
                    gemini_model=settings.gemini_model,
                )
            ),
            context={
                "provider": settings.llm_provider,
                "has_llm_api_key": bool(settings.llm_api_key),
                "has_anthropic_key": bool(settings.anthropic_api_key),
                "has_groq_key": bool(settings.groq_api_key),
                "has_gemini_key": bool(settings.gemini_api_key),
            },
        )

        if resume.active:
            resume.prepare_reused_logs()

        print(f"[run] {run_dir}")
        if resume.active:
            print(f"[resume] Reusing parent artifacts before {resume.start_stage}")
        if resume.should_run("topic_discovery_agent"):
            print("[1/10] Discovering grounded angle...")
            discovery = run_stage(
                errors,
                "topic_discovery_agent",
                lambda: TopicDiscoveryAgent(run_dir).run(
                    topic=topic,
                    genre=genre,
                    reference_scripts=references,
                    provider=provider,
                ),
                context=context,
            )
        else:
            discovery = resume.topic_discovery()

        if resume.should_run("research_agent"):
            print("[2/10] Building research brief...")
            research = run_stage(
                errors,
                "research_agent",
                lambda: ResearchAgent(run_dir).run(
                    topic=topic,
                    genre=genre,
                    discovery=discovery,
                    reference_scripts=references,
                ),
                context=context,
            )
        else:
            research = resume.research()
        growth_context = GrowthContext(topic_discovery=discovery, research=research, notes=run_notes)
        script_topic = combine_topic_and_angle(topic, discovery.selected_topic)
        validator = ValidationAgent(run_dir)

        if resume.should_run("script_agent"):
            print("[3/10] Generating script...")
            script, script_check = run_validated_stage(
                errors=errors,
                validator=validator,
                producer_stage="script_agent",
                validation_stage="validate_script",
                producer_fn=lambda feedback: ScriptAgent(run_dir).run(
                    provider=provider,
                    topic=script_topic,
                    genre=genre,
                    duration=duration,
                    reference_scripts=references,
                    user_notes=_notes_with_validator_feedback(run_notes, feedback),
                    growth_context=growth_context,
                    previous_failures=feedback,
                ),
                validator_fn=lambda artifact: validator.validate_script_output(
                    artifact,
                    genre,
                    provider=provider,
                    topic=script_topic,
                    reference_scripts=references,
                ),
                context=context,
            )
        else:
            script = resume.script()
            if resume.start_stage == "validation_agent":
                print("[validation] validate_script attempt 1")
                script_check = run_stage(
                    errors,
                    "validate_script",
                    lambda: validator.validate_script_output(
                        script,
                        genre,
                        provider=provider,
                        topic=script_topic,
                        reference_scripts=references,
                    ),
                    context={"producer_stage": "script_agent", "attempt": 1, "resumed": True},
                )
                ensure_passed(_validator_feedback(script_check) if not script_check.passed else [])
            else:
                script_check = None

        if resume.should_run("audio_agent"):
            print("[4/10] Generating audio...")
            audio, audio_check = run_validated_stage(
                errors=errors,
                validator=validator,
                producer_stage="audio_agent",
                validation_stage="validate_audio",
                producer_fn=lambda feedback: AudioAgent(run_dir).run(
                    script.narration,
                    script.word_count,
                    duration,
                    genre,
                    google_tts_credentials=settings.google_tts_credentials,
                    voice_speed_multiplier=args.voice_speed,
                ),
                validator_fn=validator.validate_audio,
                context={
                    "word_count": script.word_count,
                    "duration": duration,
                    "has_google_tts_credentials": bool(settings.google_tts_credentials),
                },
            )
        else:
            audio = resume.audio()

        if resume.should_run("caption_agent"):
            print("[5/10] Building captions...")
            captions, caption_check = run_validated_stage(
                errors=errors,
                validator=validator,
                producer_stage="caption_agent",
                validation_stage="validate_captions",
                producer_fn=lambda feedback: CaptionAgent(run_dir).run(
                    audio.word_timestamps,
                    genre.caption_preset,
                    script.emphasis_words,
                    words_per_caption=args.caption_words,
                ),
                validator_fn=validator.validate_captions,
                context={
                    "word_count": len(audio.word_timestamps),
                    "caption_preset": genre.caption_preset,
                },
            )
        else:
            captions = resume.captions()

        if resume.should_run("timed_visual_agent"):
            print("[6/10] Building timed visual cues...")
            timed_visual_cues = run_stage(
                errors,
                "timed_visual_agent",
                lambda: TimedVisualAgent(run_dir).run(
                    script=script,
                    audio=audio,
                    genre=genre,
                    topic=script_topic,
                    provider=provider,
                    min_segment_ms=args.min_visual_segment_ms,
                ),
                context={
                    "word_count": len(audio.word_timestamps),
                    "duration_ms": audio.duration_ms,
                    "topic": topic,
                    "min_segment_ms": args.min_visual_segment_ms,
                },
            )
        else:
            timed_visual_cues = resume.timed_visual_cues()

        if resume.should_run("asset_agent"):
            print("[7/10] Fetching assets...")
            assets, asset_check = run_validated_stage(
                errors=errors,
                validator=validator,
                producer_stage="asset_agent",
                validation_stage="validate_assets",
                producer_fn=lambda feedback: AssetAgent(run_dir).run(
                    script.image_cues,
                    script.sfx_cues,
                    genre,
                    pexels_key=settings.pexels_api_key,
                    pixabay_key=settings.pixabay_api_key,
                    unsplash_key=settings.unsplash_access_key,
                    provider=provider,
                    timed_visual_cues=timed_visual_cues,
                ),
                validator_fn=validator.validate_assets,
                context={
                    "image_cues": script.image_cues,
                    "timed_visual_cue_count": len(timed_visual_cues),
                    "has_pexels_key": bool(settings.pexels_api_key),
                    "has_pixabay_key": bool(settings.pixabay_api_key),
                    "has_unsplash_key": bool(settings.unsplash_access_key),
                    "asset_source_order": ["duckduckgo_video", "duckduckgo_image", "pexels_video", "pexels_image", "pixabay_image", "unsplash_image", "wikimedia_image", "openverse_image"],
                },
            )
        else:
            assets = resume.assets()

        if resume.should_run("music_agent"):
            print("[8/11] Preparing music/SFX mix...")
            music = run_stage(
                errors,
                "music_agent",
                lambda: MusicAgent(run_dir).run(
                    audio,
                    assets,
                    sfx_cues=script.sfx_cues,
                    music_path=args.music_path,
                    music_volume=args.music_volume,
                ),
                context={
                    "audio_path": audio.final_audio_path,
                    "uploaded_music_path": args.music_path,
                    "asset_music_path": assets.music_path,
                    "music_volume": args.music_volume,
                    "sfx_cue_count": len(script.sfx_cues),
                    "sfx_path_count": len(assets.sfx_paths),
                    "sfx_asset_ids": assets.sfx_asset_ids,
                },
            )
        else:
            music = resume.music(audio)

        if resume.should_run("render_agent"):
            print("[9/11] Rendering video...")
            render, render_check = run_validated_stage(
                errors=errors,
                validator=validator,
                producer_stage="render_agent",
                validation_stage="validate_render",
                producer_fn=lambda feedback: RenderAgent(run_dir).run(
                    assets,
                    music,
                    captions,
                    music_volume=args.music_volume,
                    visual_motion=visual_motion,
                    transition_style=args.transition_style,
                    transition_seconds=args.transition_seconds,
                    zoom_variant=args.zoom_variant,
                ),
                validator_fn=validator.validate_render,
                context={
                    "image_count": len(assets.image_paths),
                    "video_count": len(assets.video_paths),
                    "media_count": len(assets.media_paths),
                    "media_durations_ms": assets.media_durations_ms,
                    "audio_path": music.final_audio_path,
                    "music_path": music.music_path,
                    "music_mixed": music.mixed,
                    "sfx_mixed": music.sfx_mixed,
                    "sfx_count": len(music.sfx_paths),
                    "sfx_asset_ids": music.sfx_asset_ids,
                    "caption_path": captions.ass_path,
                    "visual_motion": visual_motion,
                    "transition_style": args.transition_style,
                    "transition_seconds": args.transition_seconds,
                    "zoom_variant": args.zoom_variant,
                },
            )
        else:
            render = resume.render()

        if resume.should_run("thumbnail_agent"):
            print("[10/11] Generating thumbnails...")
            thumbnails = run_stage(
                errors,
                "thumbnail_agent",
                lambda: ThumbnailAgent(run_dir).run(script, assets, render, discovery, research),
                context={
                    "title": script.title,
                    "video_path": render.video_path,
                    "image_count": len(assets.image_paths),
                    "video_count": len(assets.video_paths),
                },
            )
        else:
            thumbnails = resume.thumbnails()

        print("[11/11] Complete.")
        print(f"Final video: {render.video_path}")
        print(f"Shorts cover: {thumbnails.shorts_cover_path}")
        print(f"YouTube thumbnail: {thumbnails.youtube_thumbnail_path}")
        return 0
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        print(f"Run logs: {run_dir / 'logs'}", file=sys.stderr)
        print(f"Error details: {run_dir / 'errors'}", file=sys.stderr)
        return 1


def run_stage(errors: ErrorLogger, stage: str, fn, context: Any | None = None):
    try:
        return fn()
    except Exception as exc:
        errors.record(stage=stage, exc=exc, context=context)
        raise


def run_validated_stage(
    *,
    errors: ErrorLogger,
    validator: ValidationAgent,
    producer_stage: str,
    validation_stage: str,
    producer_fn,
    validator_fn,
    context: Any | None = None,
    max_attempts: int = MAX_VALIDATION_REPAIR_ATTEMPTS,
):
    feedback: list[str] = []
    last_issues: list[str] = []
    for attempt in range(1, max_attempts + 1):
        stage_name = producer_stage if attempt == 1 else f"{producer_stage}_repair_{attempt}"
        if feedback:
            print(f"[repair] {producer_stage} retrying after validator feedback")
        artifact = run_stage(
            errors,
            stage_name,
            lambda: producer_fn(feedback),
            context=_context_with_feedback(context, feedback, attempt),
        )
        check_stage = validation_stage if attempt == 1 else f"{validation_stage}_repair_{attempt}"
        print(f"[validation] {validation_stage} attempt {attempt}")
        check = run_stage(
            errors,
            check_stage,
            lambda: validator_fn(artifact),
            context={"producer_stage": producer_stage, "attempt": attempt},
        )
        if check.passed:
            if attempt > 1:
                validator.event(
                    "Validation repair passed",
                    target_agent=producer_stage,
                    attempt=attempt,
                )
            return artifact, check

        last_issues = list(check.issues)
        feedback = _validator_feedback(check)
        validator.event(
            "Validation failed; returning feedback to responsible agent",
            target_agent=producer_stage,
            loop_back_to=producer_stage,
            repair_attempt=attempt + 1,
            attempt=attempt,
            issues=check.issues,
            repair_notes=getattr(check, "repair_notes", []),
        )

    ensure_passed(feedback or last_issues)
    raise RuntimeError("Validation failed without issues")


def ensure_passed(issues: list[str]) -> None:
    if issues:
        raise RuntimeError("; ".join(issues))


def _validator_feedback(check) -> list[str]:
    notes = [str(item).strip() for item in getattr(check, "repair_notes", []) if str(item).strip()]
    issues = [str(item).strip() for item in getattr(check, "issues", []) if str(item).strip()]
    return (notes + [f"Validator issue: {issue}" for issue in issues])[:8]


def _context_with_feedback(context: Any | None, feedback: list[str], attempt: int) -> Any:
    if not feedback:
        return context
    return {
        "context": context,
        "validation_repair_attempt": attempt,
        "validator_feedback": feedback,
    }


def _notes_with_validator_feedback(notes: str, feedback: list[str]) -> str:
    if not feedback:
        return notes
    bullets = "\n".join(f"- {item}" for item in feedback[:8])
    feedback_block = (
        "VALIDATOR FEEDBACK FROM PREVIOUS SCRIPT ATTEMPT:\n"
        f"{bullets}\n"
        "Regenerate the script around the original user request. Do not copy the failed output."
    )
    return "\n\n".join(part for part in (notes.strip(), feedback_block) if part)


def _json_arg(value: str) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


PIPELINE_EXECUTION_STAGES = [
    "topic_discovery_agent",
    "research_agent",
    "script_agent",
    "audio_agent",
    "caption_agent",
    "timed_visual_agent",
    "asset_agent",
    "music_agent",
    "render_agent",
    "thumbnail_agent",
]
PIPELINE_STAGE_INDEX = {stage: index for index, stage in enumerate(PIPELINE_EXECUTION_STAGES)}
RERUN_STAGE_ALIASES = {
    "desktop_master_agent": "topic_discovery_agent",
    "style_sampler_agent": "topic_discovery_agent",
    "parameter_agent": "topic_discovery_agent",
    "master_agent": "topic_discovery_agent",
    "final_output": "final_output",
    "validation_agent": "validation_agent",
    **{stage: stage for stage in PIPELINE_EXECUTION_STAGES},
}


class ResumeContext:
    def __init__(self, parent_run_dir: Path | None, rerun_stage: str, run_dir: Path):
        self.parent_run_dir = parent_run_dir.expanduser().resolve() if parent_run_dir else None
        self.rerun_stage = str(rerun_stage or "").strip()
        self.start_stage = RERUN_STAGE_ALIASES.get(self.rerun_stage, self.rerun_stage)
        self.run_dir = run_dir
        self.active = bool(self.parent_run_dir and self.rerun_stage)
        self._outputs: dict[str, dict[str, Any]] = {}
        if self.active and self.start_stage not in {*PIPELINE_EXECUTION_STAGES, "validation_agent", "final_output"}:
            raise ValueError(f"Unsupported rerun stage: {self.rerun_stage}")

    def should_run(self, stage: str) -> bool:
        if not self.active:
            return True
        if self.start_stage == "final_output":
            return False
        if self.start_stage == "validation_agent":
            return PIPELINE_STAGE_INDEX[stage] > PIPELINE_STAGE_INDEX["script_agent"]
        return PIPELINE_STAGE_INDEX[stage] >= PIPELINE_STAGE_INDEX[self.start_stage]

    def prepare_reused_logs(self) -> None:
        if not self.active:
            return
        if not self.parent_run_dir or not self.parent_run_dir.exists():
            raise FileNotFoundError(f"Parent pipeline run directory not found: {self.parent_run_dir}")
        for stage in PIPELINE_EXECUTION_STAGES:
            if not self.should_run(stage):
                self._copy_stage_log(stage)
        if self.start_stage not in {"topic_discovery_agent", "research_agent", "script_agent", "validation_agent"}:
            self._copy_stage_log("validation_agent")

    def topic_discovery(self) -> TopicDiscoveryOutput:
        data = self._stage_output("topic_discovery_agent")
        return TopicDiscoveryOutput(
            original_topic=str(data.get("original_topic", "")),
            selected_topic=str(data.get("selected_topic", "")),
            selected_angle=str(data.get("selected_angle", "")),
            candidates=[_topic_candidate(item) for item in data.get("candidates", []) if isinstance(item, dict)],
            niche_profile=_niche_profile(data.get("niche_profile", {})),
            source_errors=[str(item) for item in data.get("source_errors", [])],
            grounding_plan=dict(data.get("grounding_plan") or {}),
        )

    def research(self) -> ResearchOutput:
        data = self._stage_output("research_agent")
        return ResearchOutput(
            topic=str(data.get("topic", "")),
            brief=str(data.get("brief", "")),
            facts=[str(item) for item in data.get("facts", [])],
            source_snippets=[_research_source(item) for item in data.get("source_snippets", []) if isinstance(item, dict)],
            source_errors=[str(item) for item in data.get("source_errors", [])],
        )

    def script(self) -> ScriptOutput:
        data = self._stage_output("script_agent")
        return ScriptOutput(
            title=str(data.get("title", "")),
            narration=str(data.get("narration", "")),
            hook_line=str(data.get("hook_line", "")),
            word_count=int(data.get("word_count") or 0),
            estimated_duration=int(data.get("estimated_duration") or 0),
            description=str(data.get("description", "")),
            hashtags=[str(item) for item in data.get("hashtags", [])],
            image_cues=[_image_cue(item) for item in data.get("image_cues", []) if isinstance(item, dict)],
            sfx_cues=[_sfx_cue(item) for item in data.get("sfx_cues", []) if isinstance(item, dict)],
            emphasis_words=[str(item) for item in data.get("emphasis_words", [])],
            provider=str(data.get("provider", "unknown")),
        )

    def audio(self) -> AudioBundle:
        data = self._stage_output("audio_agent")
        return AudioBundle(
            narration_path=str(data.get("narration_path", "")),
            final_audio_path=str(data.get("final_audio_path", "")),
            duration_ms=int(data.get("duration_ms") or 0),
            word_timestamps=[_word_timestamp(item) for item in data.get("word_timestamps", []) if isinstance(item, dict)],
            provider=str(data.get("provider", "")),
            mean_volume_db=_optional_float(data.get("mean_volume_db")),
            max_volume_db=_optional_float(data.get("max_volume_db")),
            longest_silence_seconds=_optional_float(data.get("longest_silence_seconds")),
            alignment_source=str(data.get("alignment_source", "unknown")),
        )

    def captions(self) -> CaptionBundle:
        data = self._stage_output("caption_agent")
        return CaptionBundle(
            srt_path=str(data.get("srt_path", "")),
            ass_path=str(data.get("ass_path", "")),
            phrase_count=int(data.get("phrase_count") or 0),
            word_count=int(data.get("word_count") or 0),
        )

    def timed_visual_cues(self) -> list[TimedVisualCue]:
        data = self._stage_output("timed_visual_agent")
        cues = data.get("cues")
        if not isinstance(cues, list):
            cues_path = Path(str(data.get("timed_visual_cues_path") or ""))
            if cues_path.exists():
                try:
                    cues = json.loads(cues_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    cues = []
        return [_timed_visual_cue(item) for item in (cues or []) if isinstance(item, dict)]

    def assets(self) -> AssetBundle:
        data = self._stage_output("asset_agent")
        return AssetBundle(
            image_paths=[str(item) for item in data.get("image_paths", [])],
            sfx_paths=[str(item) for item in data.get("sfx_paths", [])],
            music_path=str(data.get("music_path")) if data.get("music_path") else None,
            sources=[str(item) for item in data.get("sources", [])],
            sfx_asset_ids=[str(item) for item in data.get("sfx_asset_ids", [])],
            sfx_asset_names=[str(item) for item in data.get("sfx_asset_names", [])],
            video_paths=[str(item) for item in data.get("video_paths", [])],
            media_paths=[str(item) for item in data.get("media_paths", [])],
            media_types=[str(item) for item in data.get("media_types", [])],
            stock_video_search_terms=[str(item) for item in data.get("stock_video_search_terms", [])],
            subject_lock_issues=[str(item) for item in data.get("subject_lock_issues", [])],
            asset_selection_trace=[dict(item) for item in data.get("asset_selection_trace", []) if isinstance(item, dict)],
            sfx_selection_trace=[dict(item) for item in data.get("sfx_selection_trace", []) if isinstance(item, dict)],
            asset_trace_path=str(data.get("asset_trace_path", "")),
            media_start_ms=[int(item) for item in data.get("media_start_ms", [])],
            media_end_ms=[int(item) for item in data.get("media_end_ms", [])],
            media_durations_ms=[int(item) for item in data.get("media_durations_ms", [])],
            timed_visual_cues=[
                _timed_visual_cue(item)
                for item in data.get("timed_visual_cues", [])
                if isinstance(item, dict)
            ],
            timed_visual_cues_path=str(data.get("timed_visual_cues_path", "")),
        )

    def music(self, fallback_audio: AudioBundle) -> MusicBundle:
        path = self._parent_log_dir("music_agent") / "output.json" if self.parent_run_dir else None
        if not path or not path.exists():
            return MusicBundle(
                input_audio_path=fallback_audio.final_audio_path,
                final_audio_path=fallback_audio.final_audio_path,
                music_path=None,
                duration_ms=fallback_audio.duration_ms,
                music_volume=0.0,
                mixed=False,
                status="skipped",
                skipped_reason="Parent run has no music_agent output",
                sfx_paths=[],
                sfx_asset_ids=[],
                sfx_asset_names=[],
                sfx_timings_ms=[],
                sfx_mixed=False,
                mean_volume_db=fallback_audio.mean_volume_db,
                max_volume_db=fallback_audio.max_volume_db,
                longest_silence_seconds=fallback_audio.longest_silence_seconds,
            )
        data = self._stage_output("music_agent")
        return MusicBundle(
            input_audio_path=str(data.get("input_audio_path", fallback_audio.final_audio_path)),
            final_audio_path=str(data.get("final_audio_path", fallback_audio.final_audio_path)),
            music_path=str(data.get("music_path")) if data.get("music_path") else None,
            duration_ms=int(data.get("duration_ms") or fallback_audio.duration_ms),
            music_volume=float(data.get("music_volume") or 0.0),
            mixed=bool(data.get("mixed")),
            status=str(data.get("status") or ("succeeded" if data.get("mixed") else "skipped")),
            skipped_reason=str(data.get("skipped_reason", "")),
            sfx_paths=[str(item) for item in data.get("sfx_paths", [])],
            sfx_asset_ids=[str(item) for item in data.get("sfx_asset_ids", [])],
            sfx_asset_names=[str(item) for item in data.get("sfx_asset_names", [])],
            sfx_timings_ms=[int(item) for item in data.get("sfx_timings_ms", [])],
            sfx_mixed=bool(data.get("sfx_mixed")),
            mean_volume_db=_optional_float(data.get("mean_volume_db")),
            max_volume_db=_optional_float(data.get("max_volume_db")),
            longest_silence_seconds=_optional_float(data.get("longest_silence_seconds")),
        )

    def render(self) -> RenderResult:
        data = self._stage_output("render_agent")
        return RenderResult(
            video_path=str(data.get("video_path", "")),
            width=int(data.get("width") or 0),
            height=int(data.get("height") or 0),
            duration_seconds=float(data.get("duration_seconds") or 0.0),
            renderer=str(data.get("renderer", "ffmpeg")),
        )

    def thumbnails(self) -> ThumbnailOutput:
        data = self._stage_output("thumbnail_agent")
        return ThumbnailOutput(
            shorts_cover_path=str(data.get("shorts_cover_path", "")),
            youtube_thumbnail_path=str(data.get("youtube_thumbnail_path", "")),
            source_image_path=str(data.get("source_image_path", "")),
            text_lines=[str(item) for item in data.get("text_lines", [])],
        )

    def _stage_output(self, stage: str) -> dict[str, Any]:
        if stage not in self._outputs:
            path = self._parent_log_dir(stage) / "output.json"
            if not path.exists():
                raise FileNotFoundError(f"Cannot resume from {stage}; missing parent output: {path}")
            data = json.loads(path.read_text(encoding="utf-8"))
            self._outputs[stage] = _remap_parent_paths(data, self.parent_run_dir)
        return self._outputs[stage]

    def _copy_stage_log(self, stage: str) -> None:
        source = self._parent_log_dir(stage)
        if not source.exists():
            return
        target = self.run_dir / "logs" / stage
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)

    def _parent_log_dir(self, stage: str) -> Path:
        assert self.parent_run_dir is not None
        return self.parent_run_dir / "logs" / stage


def _topic_candidate(data: dict[str, Any]) -> TopicCandidate:
    return TopicCandidate(
        topic=str(data.get("topic", "")),
        angle=str(data.get("angle", "")),
        hook=str(data.get("hook", "")),
        score=float(data.get("score") or 0.0),
        source=str(data.get("source", "")),
        keywords=[str(item) for item in data.get("keywords", [])],
    )


def _niche_profile(data: Any) -> NicheProfile:
    data = data if isinstance(data, dict) else {}
    return NicheProfile(
        genre_id=str(data.get("genre_id", "")),
        display_name=str(data.get("display_name", "")),
        hook_templates=[str(item) for item in data.get("hook_templates", [])],
        tone_rules=[str(item) for item in data.get("tone_rules", [])],
        title_words=[str(item) for item in data.get("title_words", [])],
        thumbnail_text_rules=[str(item) for item in data.get("thumbnail_text_rules", [])],
        visual_keywords=[str(item) for item in data.get("visual_keywords", [])],
        negative_visual_keywords=[str(item) for item in data.get("negative_visual_keywords", [])],
        hashtag_hints=[str(item) for item in data.get("hashtag_hints", [])],
        source=str(data.get("source", "default")),
    )


def _research_source(data: dict[str, Any]) -> ResearchSource:
    return ResearchSource(
        title=str(data.get("title", "")),
        url=str(data.get("url", "")),
        snippet=str(data.get("snippet", "")),
        source=str(data.get("source", "")),
    )


def _image_cue(data: dict[str, Any]) -> ImageCue:
    return ImageCue(
        keyword=str(data.get("keyword", "")),
        timestamp_hint=str(data.get("timestamp_hint", "")),
        mood=str(data.get("mood", "neutral")),
        role=str(data.get("role", "supporting_visual")),
        subject_lock=bool(data.get("subject_lock", False)),
        required_subjects=[str(item) for item in data.get("required_subjects", [])],
        aliases=[str(item) for item in data.get("aliases", [])],
        allowed_fallback_level=str(data.get("allowed_fallback_level", "generic_scene")),
    )


def _timed_visual_cue(data: dict[str, Any]) -> TimedVisualCue:
    return TimedVisualCue(
        start_ms=int(data.get("start_ms") or 0),
        end_ms=int(data.get("end_ms") or 0),
        text=str(data.get("text", "")),
        search_query=str(data.get("search_query", "")),
        subject_lock=bool(data.get("subject_lock", False)),
        required_subjects=[str(item) for item in data.get("required_subjects", [])],
        aliases=[str(item) for item in data.get("aliases", [])],
        role=str(data.get("role", "timed_segment")),
        mood=str(data.get("mood", "neutral")),
        allowed_fallback_level=str(data.get("allowed_fallback_level", "generic_scene")),
        source=str(data.get("source", "caption_timing")),
    )


def _sfx_cue(data: dict[str, Any]) -> SfxCue:
    return SfxCue(
        trigger_word=str(data.get("trigger_word", "")),
        sfx_type=str(data.get("sfx_type", "")),
        timestamp_hint=str(data.get("timestamp_hint", "during word")),
    )


def _word_timestamp(data: dict[str, Any]) -> WordTimestamp:
    return WordTimestamp(
        word=str(data.get("word", "")),
        start_ms=int(data.get("start_ms") or 0),
        end_ms=int(data.get("end_ms") or 0),
    )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _remap_parent_paths(value: Any, parent_run_dir: Path | None) -> Any:
    if parent_run_dir is None:
        return value
    if isinstance(value, list):
        return [_remap_parent_paths(item, parent_run_dir) for item in value]
    if isinstance(value, dict):
        return {key: _remap_parent_paths(item, parent_run_dir) for key, item in value.items()}
    if not isinstance(value, str):
        return value
    marker = f"/{parent_run_dir.name}/"
    if marker not in value:
        return value
    suffix = value.split(marker, 1)[1]
    candidate = parent_run_dir / suffix
    return str(candidate) if candidate.exists() else value


def _compose_run_notes(
    notes: str,
    style_profile: dict[str, Any],
    agent_instructions: dict[str, Any],
    image_count: int,
) -> str:
    parts = [notes.strip()] if notes.strip() else []
    if style_profile:
        style_bits = [
            style_profile.get("label"),
            style_profile.get("script_angle"),
            style_profile.get("pacing"),
            style_profile.get("visual_style"),
            style_profile.get("audio_style"),
            style_profile.get("caption_style"),
            style_profile.get("notes"),
        ]
        parts.append("Selected style: " + " | ".join(str(item).strip() for item in style_bits if str(item or "").strip()))
    if agent_instructions:
        instruction_text = "; ".join(f"{agent}: {text}" for agent, text in agent_instructions.items() if str(text).strip())
        if instruction_text:
            parts.append("Agent instructions: " + instruction_text)
    if image_count:
        parts.append(f"Target visual variety: about {image_count} non-repeated visual beats when timing allows.")
    return "\n".join(parts)


def load_reference_scripts(genre_id: str) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    path = DATA_DIR / "reference_scripts" / f"{genre_id}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            references.extend(item for item in data if isinstance(item, dict))
    references.extend(_load_db_reference_scripts(genre_id))
    return _dedupe_references(references)


def _load_db_reference_scripts(genre_id: str) -> list[dict[str, Any]]:
    if os.environ.get("MODULARSHORTS_DB_REFERENCES", "1").strip().lower() in {"0", "false", "no", "off"}:
        return []
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return []
    try:
        from sqlalchemy import create_engine, text
    except Exception:
        return []
    query = text(
        """
        SELECT
            rv.genre_id,
            rv.video_url,
            rv.channel_name,
            rv.views,
            rv.likes,
            rv.comments,
            rv.upload_date,
            rv.duration_sec,
            rv.title,
            rv.description_first_line,
            rv.hashtags,
            rv.full_script,
            rv.word_count,
            rv.overall_score,
            rv.notes,
            sa.hook_first_sentence,
            sa.hook_type,
            sa.hook_emotional_trigger,
            sa.has_twist_reveal,
            sa.twist_line,
            sa.ending_type,
            sa.last_sentence,
            sa.power_words,
            sa.emphasis_words,
            sa.sensory_language_used,
            sa.retention_hook,
            sa.likely_share_trigger,
            sa.why_it_worked,
            sa.what_to_improve
        FROM reference_videos rv
        LEFT JOIN script_analysis sa ON sa.reference_video_id = rv.id
        WHERE rv.genre_id = :genre_id AND rv.usable_as_few_shot = true
        ORDER BY rv.overall_score DESC, rv.views DESC, rv.id ASC
        LIMIT 40
        """
    )
    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            rows = connection.execute(query, {"genre_id": genre_id}).mappings().all()
    except Exception:
        return []
    return [_reference_from_db_row(row) for row in rows]


def _reference_from_db_row(row: Any) -> dict[str, Any]:
    return {
        "genre_id": row.get("genre_id", ""),
        "title": row.get("title", ""),
        "source_url": row.get("video_url", ""),
        "channel_name": row.get("channel_name", ""),
        "views": row.get("views", 0),
        "likes": row.get("likes", 0),
        "comments": row.get("comments", 0),
        "upload_date": str(row.get("upload_date") or ""),
        "duration_sec": row.get("duration_sec", 0),
        "description_first_line": row.get("description_first_line", ""),
        "hashtags": _split_csv(row.get("hashtags", "")),
        "script": row.get("full_script", ""),
        "full_script": row.get("full_script", ""),
        "word_count": row.get("word_count", 0),
        "overall_score": row.get("overall_score", 0),
        "notes": row.get("notes", ""),
        "hook_first_sentence": row.get("hook_first_sentence", ""),
        "hook_type": row.get("hook_type", ""),
        "hook_emotional_trigger": row.get("hook_emotional_trigger", ""),
        "has_twist_reveal": row.get("has_twist_reveal", False),
        "twist_line": row.get("twist_line", ""),
        "ending_type": row.get("ending_type", ""),
        "last_sentence": row.get("last_sentence", ""),
        "power_words": _split_csv(row.get("power_words", "")),
        "emphasis_words": _split_csv(row.get("emphasis_words", "")),
        "sensory_language_used": row.get("sensory_language_used", ""),
        "retention_hook": row.get("retention_hook", ""),
        "likely_share_trigger": row.get("likely_share_trigger", ""),
        "why_it_worked": row.get("why_it_worked", ""),
        "what_to_improve": row.get("what_to_improve", ""),
        "source": "database_reference",
    }


def _dedupe_references(references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in references:
        key = str(item.get("source_url") or item.get("video_url") or item.get("title") or "").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _split_csv(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def duration_from_topic(text: str) -> int | None:
    patterns = (
        r"\bduration\s*(?:of|for|is|:|=|,|-)?\s*(30|45|60)\s*(?:seconds?|secs?|secons?|secnds?|s)?\b",
        r"\b(30|45|60)\s*(?:seconds?|secs?|secons?|secnds?|s)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, str(text or ""), flags=re.I)
        if match:
            return int(match.group(1))
    return None


def combine_topic_and_angle(topic: str, selected_topic: str) -> str:
    topic = " ".join(str(topic or "").split())
    selected_topic = " ".join(str(selected_topic or "").split())
    if not selected_topic or selected_topic.lower() == topic.lower():
        return topic
    if not topic:
        return selected_topic
    if not _topics_overlap(topic, selected_topic):
        return topic
    if selected_topic.lower().startswith(f"{topic.lower()} -"):
        angle = selected_topic[len(topic) + 2 :].strip(" -")
        if not _angle_can_extend_topic(topic, angle):
            return topic
        return selected_topic
    return f"{topic} - {selected_topic}"


def strip_duration_instruction(text: str) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"\b(?:keep|set|use|with)?\s*(?:the\s+)?duration\s*(?:of|for|to|is|:|=|,|-)?\s*(?:30|45|60)\s*(?:seconds?|secs?|secons?|secnds?|s)?\b", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\b(?:keep|set|use)\s+(?:it\s+)?(?:for|to)?\s*(?:30|45|60)\s*(?:seconds?|secs?|secons?|secnds?|s)\b", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\b(?:30|45|60)\s*(?:seconds?|secs?|secons?|secnds?|s)\b", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+([,.;!?])", r"\1", cleaned)
    cleaned = re.sub(r"(?:,\s*)?\b(?:keep|set|use)\b\s*$", " ", cleaned, flags=re.I)
    return " ".join(cleaned.split()).strip(" ,.;")


def _topics_overlap(topic: str, selected_topic: str) -> bool:
    topic_terms = set(_topic_terms_for_overlap(topic))
    selected_terms = set(_topic_terms_for_overlap(selected_topic))
    if not topic_terms or not selected_terms:
        return False
    return bool(topic_terms.intersection(selected_terms))


def _angle_can_extend_topic(topic: str, angle: str) -> bool:
    angle_terms = set(_topic_terms_for_overlap(angle))
    if not angle_terms:
        return False
    subject_lock = infer_subject_lock(topic)
    if not subject_lock.enabled:
        return bool(set(_topic_terms_for_overlap(topic)).intersection(angle_terms))
    subject_terms = set(_topic_terms_for_overlap(subject_lock.subject))
    if subject_terms and subject_terms.issubset(angle_terms):
        return True
    aliases = [subject_lock.subject, *subject_lock.aliases]
    return any(set(_topic_terms_for_overlap(alias)).issubset(angle_terms) for alias in aliases if _topic_terms_for_overlap(alias))


def _topic_terms_for_overlap(text: str) -> list[str]:
    stop = {
        "about",
        "duration",
        "from",
        "keep",
        "make",
        "secons",
        "seconds",
        "short",
        "that",
        "there",
        "this",
        "video",
        "where",
        "with",
    }
    terms = []
    for raw in re.findall(r"[a-z0-9]{3,}", str(text).lower()):
        term = "demons" if raw == "daemons" else raw
        if term not in stop and term not in terms:
            terms.append(term)
    return terms


def load_genre(genre_id: str) -> GenreConfig:
    path = DATA_DIR / "genres" / f"{genre_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Unknown genre: {genre_id}")
    data = parse_simple_yaml(path.read_text(encoding="utf-8"))
    return GenreConfig(
        genre_id=str(data["genre_id"]),
        display_name=str(data["display_name"]),
        word_count_min=int(data["word_count_min"]),
        word_count_max=int(data["word_count_max"]),
        tone=str(data["tone"]),
        layout=str(data["layout"]),
        caption_preset=str(data["caption_preset"]),
        voice_rate=float(data["voice_rate"]),
        music_mood=str(data["music_mood"]),
        hook_patterns=[str(x) for x in data.get("hook_patterns", [])],
        banned_phrases=[str(x) for x in data.get("banned_phrases", [])],
    )


def parse_simple_yaml(text: str) -> dict[str, Any]:
    """Parse the tiny YAML subset used by data/genres."""
    result: dict[str, Any] = {}
    current_key: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("  - ") and current_key:
            result.setdefault(current_key, []).append(_parse_scalar(line[4:]))
            continue
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            current_key = key
            if value == "":
                result[key] = []
            else:
                result[key] = _parse_scalar(value)
    return result


def _parse_scalar(value: str) -> Any:
    value = value.strip().strip('"').strip("'")
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(item.strip()) for item in inner.split(",")]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
