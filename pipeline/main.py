from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from agents.asset_agent import AssetAgent
from agents.audio_agent import AudioAgent
from agents.caption_agent import CaptionAgent
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
from app.schemas import GenreConfig, GrowthContext, PipelineContext
from modules.llm.factory import LLMConfig, create_llm_provider


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a local YouTube Short.")
    parser.add_argument("--topic", required=True, help="Topic for the short")
    parser.add_argument("--genre", default="scary_stories", help="Genre id")
    parser.add_argument("--duration", type=int, default=45, choices=[30, 45, 60])
    parser.add_argument("--notes", default="", help="Optional user style notes")
    args = parser.parse_args()
    topic = strip_duration_instruction(args.topic)
    duration = duration_from_topic(args.topic) or args.duration

    settings = get_settings()
    ensure_data_dirs()
    run_dir = create_run_dir()
    errors = ErrorLogger(run_dir)
    context = PipelineContext(
        topic=topic,
        genre_id=args.genre,
        duration=duration,
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

        print(f"[run] {run_dir}")
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
        growth_context = GrowthContext(topic_discovery=discovery, research=research, notes=args.notes)
        script_topic = combine_topic_and_angle(topic, discovery.selected_topic)

        print("[3/10] Generating script...")
        script = run_stage(
            errors,
            "script_agent",
            lambda: ScriptAgent(run_dir).run(
                provider=provider,
                topic=script_topic,
                genre=genre,
                duration=duration,
                reference_scripts=references,
                user_notes=args.notes,
                growth_context=growth_context,
            ),
            context=context,
        )

        validator = ValidationAgent(run_dir)
        script_check = run_stage(
            errors,
            "validate_script",
            lambda: validator.validate_script_output(script, genre),
            context={"script": script},
        )
        run_stage(
            errors,
            "validate_script_result",
            lambda: ensure_passed(script_check.issues),
            context={"issues": script_check.issues},
        )

        print("[4/10] Generating audio...")
        audio = run_stage(
            errors,
            "audio_agent",
            lambda: AudioAgent(run_dir).run(
                script.narration,
                script.word_count,
                duration,
                genre,
                google_tts_credentials=settings.google_tts_credentials,
            ),
            context={
                "word_count": script.word_count,
                "duration": duration,
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

        print("[5/10] Building captions...")
        captions = run_stage(
            errors,
            "caption_agent",
            lambda: CaptionAgent(run_dir).run(
                audio.word_timestamps,
                genre.caption_preset,
                script.emphasis_words,
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
            ),
            context={
                "word_count": len(audio.word_timestamps),
                "duration_ms": audio.duration_ms,
                "topic": topic,
            },
        )

        print("[7/10] Fetching assets...")
        assets = run_stage(
            errors,
            "asset_agent",
            lambda: AssetAgent(run_dir).run(
                script.image_cues,
                script.sfx_cues,
                genre,
                pexels_key=settings.pexels_api_key,
                pixabay_key=settings.pixabay_api_key,
                unsplash_key=settings.unsplash_access_key,
                provider=provider,
                timed_visual_cues=timed_visual_cues,
            ),
            context={
                "image_cues": script.image_cues,
                "timed_visual_cue_count": len(timed_visual_cues),
                "has_pexels_key": bool(settings.pexels_api_key),
                "has_pixabay_key": bool(settings.pixabay_api_key),
                "has_unsplash_key": bool(settings.unsplash_access_key),
                "asset_source_order": ["duckduckgo_video", "duckduckgo_image", "pexels_video", "pexels_image", "pixabay_image", "unsplash_image", "wikimedia_image", "openverse_image"],
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

        print("[8/10] Rendering video...")
        render = run_stage(
            errors,
            "render_agent",
            lambda: RenderAgent(run_dir).run(assets, audio, captions),
            context={
                "image_count": len(assets.image_paths),
                "video_count": len(assets.video_paths),
                "media_count": len(assets.media_paths),
                "media_durations_ms": assets.media_durations_ms,
                "audio_path": audio.final_audio_path,
                "caption_path": captions.ass_path,
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

        print("[9/10] Generating thumbnails...")
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

        print("[10/10] Complete.")
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


def ensure_passed(issues: list[str]) -> None:
    if issues:
        raise RuntimeError("; ".join(issues))


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
