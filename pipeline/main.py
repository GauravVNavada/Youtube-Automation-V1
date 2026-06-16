from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agents.asset_agent import AssetAgent
from agents.audio_agent import AudioAgent
from agents.caption_agent import CaptionAgent
from agents.render_agent import RenderAgent
from agents.research_agent import ResearchAgent
from agents.script_agent import ScriptAgent
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

    settings = get_settings()
    ensure_data_dirs()
    run_dir = create_run_dir()
    errors = ErrorLogger(run_dir)
    context = PipelineContext(
        topic=args.topic,
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
        print("[1/8] Discovering grounded angle...")
        discovery = run_stage(
            errors,
            "topic_discovery_agent",
            lambda: TopicDiscoveryAgent(run_dir).run(
                topic=args.topic,
                genre=genre,
                reference_scripts=references,
                provider=provider,
            ),
            context=context,
        )

        print("[2/8] Building research brief...")
        research = run_stage(
            errors,
            "research_agent",
            lambda: ResearchAgent(run_dir).run(
                topic=args.topic,
                genre=genre,
                discovery=discovery,
                reference_scripts=references,
            ),
            context=context,
        )
        growth_context = GrowthContext(topic_discovery=discovery, research=research, notes=args.notes)

        print("[3/8] Generating script...")
        script = run_stage(
            errors,
            "script_agent",
            lambda: ScriptAgent(run_dir).run(
                provider=provider,
                topic=discovery.selected_topic,
                genre=genre,
                duration=args.duration,
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
            ),
            context={
                "image_cues": script.image_cues,
                "has_pexels_key": bool(settings.pexels_api_key),
                "has_pixabay_key": bool(settings.pixabay_api_key),
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
            lambda: RenderAgent(run_dir).run(assets, audio, captions),
            context={
                "image_count": len(assets.image_paths),
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

        print("[8/8] Complete.")
        print(f"Final video: {render.video_path}")
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
