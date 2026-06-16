from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from agents.asset_agent import AssetAgent
from agents.audio_agent import AudioAgent
from agents.caption_agent import CaptionAgent
from agents.render_agent import RenderAgent
from agents.research_agent import ResearchAgent
from agents.script_agent import ScriptAgent
from agents.thumbnail_agent import ThumbnailAgent
from agents.topic_discovery_agent import TopicDiscoveryAgent
from agents.validation_agent import ValidationAgent
from app.config import get_settings
from app.logger import ErrorLogger
from app.paths import DATA_DIR, create_run_dir, ensure_data_dirs
from app.schemas import GenreConfig, ImageCue, PipelineContext, ResearchOutput, ScriptOutput, TopicDiscoveryOutput
from modules.llm.factory import LLMConfig, create_llm_provider
from modules.safety.guardrails import validate_video_topic
from modules.scripts.generator import _ensure_image_cue_density
from modules.scripts.structure import polish_script_ending
from modules.scripts.validator import validate_script
from modules.visuals.style_router import build_visual_style_plan, visual_style_to_dict


MAX_SCRIPT_REPAIR_ATTEMPTS = 3


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a local YouTube Short.")
    parser.add_argument("--topic", required=True, help="Topic for the short")
    parser.add_argument("--genre", default="scary_stories", help="Genre id")
    parser.add_argument("--duration", type=int, default=30)
    parser.add_argument("--notes", default="", help="Optional user style notes")
    parser.add_argument("--settings-json", default="", help="Optional JSON generation settings")
    args = parser.parse_args()
    if args.duration < 10 or args.duration > 180:
        parser.error("--duration must be between 10 and 180 seconds")
    validate_video_topic(args.topic)
    generation_settings = _parse_settings(args.settings_json)

    settings = get_settings()
    visual_style = build_visual_style_plan(args.topic, args.genre, args.notes)
    visual_style_payload = visual_style_to_dict(visual_style)
    pipeline_topic = visual_style.sanitized_topic or args.topic
    ensure_data_dirs()
    run_dir = create_run_dir()
    errors = ErrorLogger(run_dir)
    context = PipelineContext(
        topic=pipeline_topic,
        genre_id=args.genre,
        duration=args.duration,
        run_dir=str(run_dir),
        user_notes=args.notes,
    )

    stage = "bootstrap"
    try:
        genre = run_stage(
            errors,
            stage,
            lambda: load_genre(args.genre),
            context=context,
        )
        genre = _genre_for_duration(genre, args.duration)
        references = run_stage(
            errors,
            "load_references",
            lambda: load_reference_scripts(args.genre),
            context=context,
        )
        print(f"[run] {run_dir}")
        if visual_style.mode == "illustration":
            print(f"[visual] {visual_style.render_style} image-first mode; stock video disabled for safer stylized assets.")
        provider = run_stage(
            errors,
            "llm_provider",
            lambda: create_llm_provider(
                LLMConfig(
                    provider=settings.llm_provider,
                    api_key=settings.llm_api_key,
                    model=settings.llm_model,
                    openai_api_key=settings.openai_api_key,
                    openai_model=settings.openai_model,
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
                "has_openai_key": bool(settings.openai_api_key),
                "has_anthropic_key": bool(settings.anthropic_api_key),
                "has_groq_key": bool(settings.groq_api_key),
                "has_gemini_key": bool(settings.gemini_api_key),
            },
        )
        print("[1/8] Discovering topic angles...")
        discovery = run_stage(
            errors,
            "topic_discovery_agent",
            lambda: TopicDiscoveryAgent(run_dir).run(
                pipeline_topic,
                genre,
                references,
                provider=provider,
            ),
            context={
                "topic": pipeline_topic,
                "original_topic": args.topic,
                "visual_style": visual_style_payload,
                "genre": args.genre,
                "reference_count": len(references),
            },
        )
        print("[2/8] Building research brief...")
        research = run_stage(
            errors,
            "research_agent",
            lambda: ResearchAgent(run_dir).run(
                discovery.selected_topic,
                genre,
                discovery,
                references,
                grounding_plan=discovery.grounding_plan,
            ),
            context={
                "topic": discovery.selected_topic,
                "selected_angle": discovery.selected_angle,
            },
        )
        growth_context = build_growth_context(discovery, research, visual_style_payload)

        pipeline_constraints = _pipeline_constraints(genre, generation_settings, args.duration, visual_style_payload)
        validator = ValidationAgent(run_dir)

        print("[3/8] Generating script...")
        script = run_stage(
            errors,
            "script_agent",
            lambda: generate_script_until_valid(
                script_agent=ScriptAgent(run_dir),
                validator=validator,
                provider=provider,
                topic=discovery.selected_topic,
                genre=genre,
                duration=args.duration,
                reference_scripts=references,
                user_notes=_notes_with_settings(args.notes, generation_settings, pipeline_constraints),
                requested_image_count=int(pipeline_constraints["image_count"]),
                constraints=pipeline_constraints,
                growth_context=growth_context,
                visual_style=visual_style_payload,
            ),
            context={
                "topic": discovery.selected_topic,
                "original_topic": args.topic,
                "growth_context": growth_context,
                "visual_style": visual_style_payload,
                "genre": args.genre,
                "duration": args.duration,
                "constraints": pipeline_constraints,
            },
        )

        print("[4/8] Fetching assets...")
        assets = run_stage(
            errors,
            "asset_agent",
            lambda: AssetAgent(run_dir).run(
                script.image_cues,
                script.sfx_cues,
                genre,
                pexels_key=settings.pexels_api_key,
                pixabay_key=settings.pixabay_api_key,
                visual_style=visual_style_payload,
                intent_provider=provider,
                topic=discovery.selected_topic,
                growth_context=growth_context,
            ),
            context={
                "image_cues": script.image_cues,
                "has_pexels_key": bool(settings.pexels_api_key),
                "has_pixabay_key": bool(settings.pixabay_api_key),
                "visual_style": visual_style_payload,
            },
        )
        asset_check = run_stage(
            errors,
            "validate_assets",
            lambda: validator.validate_assets(assets),
            context={"assets": assets},
        )
        run_stage(
            errors,
            "validate_assets_result",
            lambda: ensure_passed(asset_check.issues),
            context={"issues": asset_check.issues},
        )

        print("[5/8] Generating audio...")
        audio = run_stage(
            errors,
            "audio_agent",
            lambda: AudioAgent(run_dir).run(
                script.narration,
                script.word_count,
                args.duration,
                genre,
                google_tts_credentials=settings.google_tts_credentials,
                voice_speed_multiplier=float(pipeline_constraints["voice_speed_multiplier"]),
                edge_tts_voice=settings.edge_tts_voice,
            ),
            context={
                "word_count": script.word_count,
                "duration": args.duration,
                "has_google_tts_credentials": bool(settings.google_tts_credentials),
            },
        )
        audio_check = run_stage(
            errors,
            "validate_audio",
            lambda: validator.validate_audio(audio),
            context={"audio": audio},
        )
        run_stage(
            errors,
            "validate_audio_result",
            lambda: ensure_passed(audio_check.issues),
            context={"issues": audio_check.issues},
        )

        print("[6/8] Building captions...")
        captions = run_stage(
            errors,
            "caption_agent",
            lambda: CaptionAgent(run_dir).run(
                audio.word_timestamps,
                genre.caption_preset,
                script.emphasis_words,
                words_per_caption=int(pipeline_constraints["caption_words_per_phrase"]),
            ),
            context={
                "word_count": len(audio.word_timestamps),
                "caption_preset": genre.caption_preset,
            },
        )
        caption_check = run_stage(
            errors,
            "validate_captions",
            lambda: validator.validate_captions(captions),
            context={"captions": captions},
        )
        run_stage(
            errors,
            "validate_captions_result",
            lambda: ensure_passed(caption_check.issues),
            context={"issues": caption_check.issues},
        )

        print("[7/8] Rendering video...")
        render = run_stage(
            errors,
            "render_agent",
            lambda: RenderAgent(run_dir).run(
                assets,
                audio,
                captions,
                music_volume=float(pipeline_constraints["music_volume"]),
                visual_style=visual_style_payload,
            ),
            context={
                "image_count": len(assets.image_paths),
                "video_count": len([path for path in assets.video_paths if path]),
                "audio_path": audio.final_audio_path,
                "caption_path": captions.ass_path,
                "visual_style": visual_style_payload,
            },
        )
        render_check = run_stage(
            errors,
            "validate_render",
            lambda: validator.validate_render(render),
            context={"render": render},
        )
        run_stage(
            errors,
            "validate_render_result",
            lambda: ensure_passed(render_check.issues),
            context={"issues": render_check.issues},
        )

        print("[8/8] Generating thumbnails...")
        thumbnails = run_stage(
            errors,
            "thumbnail_agent",
            lambda: ThumbnailAgent(run_dir).run(
                script,
                assets,
                render,
                discovery,
                research,
            ),
            context={
                "video_path": render.video_path,
                "title": script.title,
                "hook_line": script.hook_line,
            },
        )

        print("[8/8] Complete.")
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


def generate_script_until_valid(
    *,
    script_agent: ScriptAgent,
    validator: ValidationAgent,
    provider,
    topic: str,
    genre: GenreConfig,
    duration: int,
    reference_scripts: list[dict[str, Any]],
    user_notes: str,
    requested_image_count: int,
    constraints: dict[str, Any],
    growth_context: dict[str, Any] | None = None,
    visual_style: dict[str, Any] | None = None,
) -> ScriptOutput:
    """Generate, self-check, validate, and repair the script before downstream stages run."""
    issues: list[str] = []
    last_script: ScriptOutput | None = None
    for attempt in range(1, MAX_SCRIPT_REPAIR_ATTEMPTS + 1):
        attempt_notes = user_notes if not issues else _notes_with_repair(user_notes, issues, attempt, constraints)
        script_agent.provenance(
            "Script attempt started",
            mode="ai",
            attempt=attempt,
            max_attempts=MAX_SCRIPT_REPAIR_ATTEMPTS,
            constraints=constraints,
            repair_issues=issues,
        )
        script = script_agent.run(
            provider=provider,
            topic=topic,
            genre=genre,
            duration=duration,
            reference_scripts=reference_scripts,
            user_notes=attempt_notes,
            attempt=attempt,
            constraints=constraints,
            growth_context=growth_context or {},
            visual_style=visual_style or {},
        )
        script.image_cues = _ensure_image_cue_density(script.image_cues, script.narration, requested_image_count)
        script = _enforce_script_word_budget(script, genre.word_count_max, constraints, script_agent, attempt)
        script = polish_script_ending(
            script,
            genre.genre_id,
            min(genre.word_count_max, _int_setting(constraints, "script_target_word_count_max", genre.word_count_max)),
        )
        last_script = script

        self_check = validate_script(script, genre.word_count_min, genre.word_count_max, genre.genre_id)
        script_agent.provenance(
            "Script self-check complete",
            mode="deterministic",
            attempt=attempt,
            passed=self_check.passed,
            issues=self_check.issues,
            word_count=script.word_count,
            image_cue_count=len(script.image_cues),
        )

        validation_check = validator.validate_script_output(
            script,
            genre,
            attempt=attempt,
            constraints=constraints,
        )
        issues = _merge_issues(self_check.issues, validation_check.issues)
        if not issues:
            validator.provenance(
                "Script accepted for downstream agents",
                mode="deterministic",
                attempt=attempt,
                word_count=script.word_count,
                image_cue_count=len(script.image_cues),
            )
            return script

        validator.provenance(
            "Script auto-repair requested",
            mode="deterministic",
            attempt=attempt,
            next_attempt=attempt + 1 if attempt < MAX_SCRIPT_REPAIR_ATTEMPTS else None,
            issues=issues,
        )

    ensure_passed([f"Script failed after {MAX_SCRIPT_REPAIR_ATTEMPTS} repair attempts: {'; '.join(issues)}"])
    if last_script:
        return last_script
    raise RuntimeError("Script generation failed before producing an output")


def ensure_passed(issues: list[str]) -> None:
    if issues:
        raise RuntimeError("; ".join(issues))


def _enforce_script_word_budget(
    script: ScriptOutput,
    hard_max_words: int,
    constraints: dict[str, Any],
    script_agent: ScriptAgent,
    attempt: int,
) -> ScriptOutput:
    target_max = _int_setting(constraints, "script_target_word_count_max", hard_max_words)
    allowed_max = min(hard_max_words, target_max)
    words = script.narration.split()
    if len(words) <= allowed_max:
        script.word_count = len(words)
        return script

    trimmed_narration = _trim_to_complete_sentence(script.narration, allowed_max)
    trimmed_words = trimmed_narration.split()
    if len(trimmed_words) < 18:
        trimmed_narration = " ".join(words[:allowed_max]).rstrip(" ,;:") + "."
        trimmed_words = trimmed_narration.split()
    old_word_count = len(words)
    script.narration = trimmed_narration
    script.word_count = len(trimmed_words)
    script.hook_line = _first_sentence(trimmed_narration) or script.hook_line
    script.image_cues = _filter_cues_for_word_count(script.image_cues, script.word_count)
    script_agent.provenance(
        "Script narration trimmed to word budget",
        mode="deterministic",
        attempt=attempt,
        old_word_count=old_word_count,
        new_word_count=script.word_count,
        hard_max_words=hard_max_words,
        target_max_words=target_max,
    )
    return script


def _trim_to_complete_sentence(text: str, max_words: int) -> str:
    words = text.split()
    clipped = " ".join(words[:max_words]).strip()
    sentence_endings = list(re.finditer(r"[.!?][\"')\]]*(?=\s|$)", clipped))
    if sentence_endings:
        return clipped[: sentence_endings[-1].end()].strip()
    full_text_endings = list(re.finditer(r"[.!?][\"')\]]*(?=\s|$)", text))
    for match in full_text_endings:
        candidate = text[: match.end()].strip()
        if len(candidate.split()) <= max_words:
            clipped = candidate
        else:
            break
    return clipped if clipped.endswith((".", "!", "?")) else clipped.rstrip(" ,;:") + "."


def _first_sentence(text: str) -> str:
    match = re.search(r"^.*?[.!?](?=\s|$)", text.strip())
    return match.group(0).strip() if match else ""


def _filter_cues_for_word_count(cues: list[ImageCue], word_count: int) -> list[ImageCue]:
    filtered: list[ImageCue] = []
    for cue in cues:
        match = re.search(r"word_(\d+)", cue.timestamp_hint or "")
        if not match or int(match.group(1)) < word_count:
            filtered.append(cue)
    return filtered or cues[:1]


def _parse_settings(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid settings JSON: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _notes_with_settings(
    notes: str,
    settings: dict[str, Any],
    constraints: dict[str, Any] | None = None,
) -> str:
    parts = [notes.strip()]
    if settings:
        parts.append(f"Generation settings JSON: {json.dumps(settings, ensure_ascii=True)}")
    if constraints:
        parts.append(f"Master constraints JSON: {json.dumps(constraints, ensure_ascii=True)}")
        parts.append(
            "Required execution order: Master decides route and constraints; topic discovery and research enrich the idea; "
            "Script writes within constraints and growth context; Script self-checks; Validation checks; invalid scripts "
            "auto-repair; only then continue."
        )
        parts.append(
            "Script structure policy: return script_sections with header, mid, and footer. Header hooks the viewer, "
            "mid develops only relevant beats/facts and includes at least one believable alert beat, and footer delivers a specific reveal, consequence, lesson, or why-it-matters ending."
        )
        parts.append(
            "Language policy: use layman English a 12-year-old can understand. Use short sentences and common words. "
            "Avoid vague endings like 'the warning finally made sense' unless the script clearly explains what the warning means."
        )
    return "\n".join(part for part in parts if part)


def _notes_with_repair(
    base_notes: str,
    issues: list[str],
    attempt: int,
    constraints: dict[str, Any],
) -> str:
    issue_lines = "\n".join(f"- {issue}" for issue in issues)
    word_budget = constraints.get("narration_word_count", {}) if isinstance(constraints, dict) else {}
    target_max = constraints.get("script_target_word_count_max") if isinstance(constraints, dict) else None
    target_words = constraints.get("script_target_word_count") if isinstance(constraints, dict) else None
    word_instruction = ""
    if word_budget:
        word_instruction = (
            f"\nWord budget repair: hard range is {word_budget.get('min')} to {word_budget.get('max')} words. "
            f"Write around {target_words or word_budget.get('min')} words and do not exceed "
            f"{target_max or word_budget.get('max')} words. Count the words before returning JSON."
        )
    return (
        f"{base_notes}\n"
        f"Repair required before continuing. Attempt {attempt - 1} failed these issues:\n"
        f"{issue_lines}\n"
        f"{word_instruction}\n"
        "Structure repair: keep script_sections as header, mid, footer. Remove unrelated facts. "
        "The mid section needs one believable alert beat or shocking turn. "
        "The footer must conclude the idea with a specific payoff, not a pause, silence, blackout, direct stop, or vague line like 'the warning finally made sense'. "
        "Use layman English, short sentences, and common words.\n"
        "Return a complete replacement script JSON object. Do not explain the repair.\n"
        f"Hard constraints JSON: {json.dumps(constraints, ensure_ascii=True)}"
    ).strip()


def _merge_issues(*issue_groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in issue_groups:
        for issue in group:
            if issue not in seen:
                seen.add(issue)
                merged.append(issue)
    return merged


def build_growth_context(
    discovery: TopicDiscoveryOutput,
    research: ResearchOutput,
    visual_style: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = asdict(discovery.niche_profile)
    visual_style_payload = visual_style or {}
    external_sources = [
        source
        for source in research.source_snippets
        if _usable_grounding_source(source, visual_style_payload)
    ]
    prompt_sources = [
        source
        for source in research.source_snippets
        if not getattr(source, "url", "") or _usable_grounding_source(source, visual_style_payload)
    ]
    return {
        "selected_topic": discovery.selected_topic,
        "selected_angle": discovery.selected_angle,
        "candidate_topics": [asdict(candidate) for candidate in discovery.candidates[:6]],
        "research_brief": research.brief,
        "source_snippets": [asdict(source) for source in prompt_sources[:5]],
        "grounding_plan": discovery.grounding_plan,
        "grounding_status": "external_sources_found" if external_sources else "local_only_no_external_sources",
        "grounding_anchors": [source.title for source in external_sources[:5]],
        "niche_profile": profile,
        "visual_style": visual_style_payload,
        "thumbnail_hints": _thumbnail_hints(discovery, research),
        "title_hints": list(dict.fromkeys(profile.get("title_words", []) + [discovery.selected_angle])),
    }


def _thumbnail_hints(discovery: TopicDiscoveryOutput, research: ResearchOutput) -> list[str]:
    hints = [discovery.selected_angle]
    hints.extend(discovery.niche_profile.thumbnail_text_rules[:3])
    hints.extend(research.facts[:2])
    return [hint for hint in hints if str(hint).strip()]


def _usable_grounding_source(source: Any, visual_style: dict[str, Any]) -> bool:
    if not getattr(source, "url", "") or str(getattr(source, "source", "")).startswith("local"):
        return False
    if visual_style.get("mode") == "illustration":
        return False
    raw_text = f"{getattr(source, 'title', '')} {getattr(source, 'snippet', '')}".lower()
    text = f" {re.sub(r'[^a-z0-9 ]', ' ', raw_text)} "
    blocked = (
        " marvel ", " comics ", " comic ", " stock ", " character ", " characters ",
        " fictional ", " superhero ", " superheroes ", " teams organizations ",
        " fandom ", " fan wiki ", " movie ", " film ", " television ", " anime ",
    )
    return not any(term in text for term in blocked)


def _pipeline_constraints(
    genre: GenreConfig,
    settings: dict[str, Any],
    duration: int,
    visual_style: dict[str, Any] | None = None,
) -> dict[str, Any]:
    image_count = max(_int_setting(settings, "image_count", 8), _minimum_image_cues(duration))
    target_max_words = max(genre.word_count_min, genre.word_count_max - _word_safety_margin(duration))
    target_words = max(genre.word_count_min, int((genre.word_count_min + target_max_words) / 2))
    style = visual_style or {}
    asset_policy = (
        "image-first stylized visual search; skip Pexels stock video; sanitize famous IP names; prefer original-character illustration cues"
        if style.get("asset_strategy") == "image_first"
        else "stock video b-roll preferred with online image fallback; every cue needs concrete visible nouns"
    )
    return {
        "genre_id": genre.genre_id,
        "duration_seconds": int(duration),
        "narration_word_count": {"min": genre.word_count_min, "max": genre.word_count_max},
        "script_target_word_count": target_words,
        "script_target_word_count_max": target_max_words,
        "script_word_safety_margin": genre.word_count_max - target_max_words,
        "image_count": image_count,
        "voice_speed_multiplier": _float_setting(settings, "voice_speed", 1.0),
        "caption_words_per_phrase": _int_setting(settings, "caption_words", 4),
        "music_volume": _float_setting(settings, "music_volume", 0.18),
        "language": "layman English for a 12-year-old, short spoken sentences, common words, clear cause-and-effect",
        "script_format": "strict JSON object only",
        "asset_policy": asset_policy,
        "visual_style": style,
        "audio_policy": "Google TTS when configured, otherwise EdgeTTS with Whisper word alignment",
        "narrative_structure": {
            "required_sections": ["header", "mid", "footer"],
            "header": "hook and promise the idea",
            "mid": "only relevant beats or facts, with at least one believable alert beat or shocking turn",
            "footer": "specific payoff, reveal, consequence, lesson, or why the fact matters",
            "bad_endings": ["pause", "silence", "blackout", "direct stop", "to be continued", "vague made-sense ending"],
        },
    }


def _int_setting(settings: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(settings.get(key, default))
    except (TypeError, ValueError):
        return default


def _float_setting(settings: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(settings.get(key, default))
    except (TypeError, ValueError):
        return default


def _minimum_image_cues(duration: int) -> int:
    if duration >= 120:
        return 18
    if duration >= 90:
        return 14
    if duration >= 60:
        return 10
    if duration >= 45:
        return 8
    return 6


def _word_safety_margin(duration: int) -> int:
    if duration < 30:
        return 5
    if duration < 60:
        return 8
    return 12


def load_reference_scripts(genre_id: str) -> list[dict[str, Any]]:
    path = DATA_DIR / "reference_scripts" / f"{genre_id}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


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


def _genre_for_duration(genre: GenreConfig, duration: int) -> GenreConfig:
    min_words = max(18, int(duration * 1.75))
    max_words = max(min_words + 8, int(duration * 2.55))
    if duration < 30:
        max_words += 5
    return replace(genre, word_count_min=min_words, word_count_max=max_words)


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
