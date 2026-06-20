from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import (
    Genre,
    GenreHook,
    GenreRule,
    ReferenceVideo,
    ScriptAnalysis,
    SfxAsset,
    TopicExpansionRule,
    TopicResearchSource,
    VisualStyleRule,
)


DEFAULT_GENRES = [
    {
        "id": "scary_stories",
        "display_name": "Scary Stories",
        "category": "story",
        "tone": "Slow dread with simple words, concrete real-world details, and a believable final reveal.",
        "caption_preset": "horror_red",
        "music_mood": "dark ambient",
        "hooks": ["At {time}, {subject} noticed {detail}.", "The first warning was {detail}."],
        "visual_keywords": "dark hallway, old door, phone screen, shadow figure, abandoned room, mirror",
        "negative_visual_keywords": "cartoon, anime, fantasy monster, gore, random school hallway",
    },
    {
        "id": "history_facts",
        "display_name": "History Facts",
        "category": "facts",
        "tone": "Mini documentary with names, dates, places, and one surprising real-world detail.",
        "caption_preset": "documentary_gold",
        "music_mood": "documentary pulse",
        "hooks": ["Most people do not know {fact}.", "This real place changed because of {event}."],
        "visual_keywords": "historic city street, archive photo, museum object, map close up",
        "negative_visual_keywords": "fantasy, fictional city, game art",
    },
    {
        "id": "reddit_stories",
        "display_name": "Reddit Stories",
        "category": "story",
        "tone": "Conversational, direct, believable, and easy to follow.",
        "caption_preset": "clean_pro",
        "music_mood": "light tension",
        "hooks": ["I thought {person} was joking until {detail}.", "What would you do if {problem}?"],
        "visual_keywords": "family dinner, phone message, apartment living room, tense conversation",
        "negative_visual_keywords": "celebrity, cartoon, fantasy",
    },
    {
        "id": "comics",
        "display_name": "Comics",
        "category": "story",
        "tone": "Bold comic-book narration with heroic stakes, clear conflict, fast visual beats, and simple words.",
        "caption_preset": "clean_pro",
        "music_mood": "heroic pulse",
        "hooks": ["Every great comic fight starts with {conflict}.", "The panel that changes everything is {detail}."],
        "visual_keywords": "comic hero, city rooftop, masked figure, villain shadow, action lines, speech bubble",
        "negative_visual_keywords": "movie still, actor face, studio logo, gore",
    },
]

SFX_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"}
SFX_HINTS = {
    "bass-impact": {
        "description": "Low bass impact for heavy hits, deep rumbles, growls, or ominous reveals.",
        "tags": ["bass", "impact", "boom", "thud", "rumble", "growl", "reveal"],
        "aliases": ["deep_growl", "low_rumble", "bass_hit", "heavy_thud", "dramatic_impact", "soft_hit"],
        "use_cases": ["deep creature growl substitute", "dramatic reveal", "heavy hit", "ominous beat"],
        "intensity": "high",
    },
    "digital-glitch-noise-hd": {
        "description": "Harsh digital glitch noise for corrupted screens, static, and tech failure.",
        "tags": ["digital", "glitch", "static", "noise", "error", "tech"],
        "aliases": ["static_glitch", "digital_static", "tv_static", "screen_glitch", "signal_glitch"],
        "use_cases": ["corrupted screen", "security camera glitch", "tech failure", "horror static"],
        "intensity": "medium",
    },
    "ding": {
        "description": "Short clean ding for small notifications, clues, or UI-style confirmation.",
        "tags": ["ding", "notification", "beep", "clue", "small"],
        "aliases": ["soft_ding", "clue_ding", "message_ding", "camera_shutter", "paper_rustle"],
        "use_cases": ["small clue reveal", "message arrives", "light confirmation"],
        "intensity": "low",
    },
    "error": {
        "description": "Short error tone for warnings, failed actions, alarms, or danger beats.",
        "tags": ["error", "beep", "warning", "alarm", "fail"],
        "aliases": ["error_beep", "warning_beep", "alarm_beep", "system_error"],
        "use_cases": ["warning moment", "system failure", "wrong choice", "alarm beat"],
        "intensity": "medium",
    },
    "glitch-sfx": {
        "description": "Compact glitch hit for jumpy edits, distortion, static, and reveal accents.",
        "tags": ["glitch", "static", "digital", "distortion", "hit"],
        "aliases": ["static_glitch", "glitch_hit", "distortion_hit", "screen_glitch"],
        "use_cases": ["quick glitch transition", "distorted reveal", "screen interruption"],
        "intensity": "medium",
    },
    "impact-cinematic-boom": {
        "description": "Cinematic boom impact for smashes, cracks, collisions, thunder, and major reveals.",
        "tags": ["impact", "boom", "smash", "crack", "stone", "concrete", "thunder", "metal", "reveal"],
        "aliases": [
            "concrete_smash",
            "stone_crack",
            "glass_crack",
            "mirror_crack",
            "metal_impact",
            "thunder_hit",
            "door_slam",
            "heavy_impact",
            "soft_hit",
        ],
        "use_cases": ["object breaking", "hard collision", "thunder hit", "dramatic reveal", "metal hit"],
        "intensity": "high",
    },
    "minecraft-damage": {
        "description": "Short damage hit for punches, comedic hits, light impacts, or game-like damage.",
        "tags": ["damage", "hit", "punch", "impact", "game"],
        "aliases": ["damage_hit", "punch_hit", "small_impact", "fight_hit"],
        "use_cases": ["quick punch", "small damage beat", "playful impact"],
        "intensity": "medium",
    },
    "notification": {
        "description": "Notification sound for phone buzzes, message alerts, reminders, and attention beats.",
        "tags": ["notification", "phone", "message", "buzz", "ding", "alert"],
        "aliases": ["phone_buzz", "phone_notification", "message_alert", "text_message", "phone_alert"],
        "use_cases": ["phone message", "new alert", "social media notification", "attention beat"],
        "intensity": "low",
    },
    "riser": {
        "description": "Rising tension sound for suspense builds, transitions, and pre-reveal moments.",
        "tags": ["riser", "suspense", "build", "transition", "tension", "whoosh"],
        "aliases": ["suspense_riser", "tension_build", "horror_riser", "slow_build", "door_creak", "heartbeat"],
        "use_cases": ["build suspense", "lead into reveal", "transition between beats", "horror tension"],
        "intensity": "medium",
    },
    "simple-whoosh": {
        "description": "Simple whoosh for quick movement, transitions, swipes, and fast cuts.",
        "tags": ["whoosh", "swoosh", "transition", "movement", "swipe"],
        "aliases": ["fast_whoosh", "transition_whoosh", "swipe_whoosh", "quick_whoosh", "metal_whoosh"],
        "use_cases": ["quick visual transition", "fast movement", "swipe edit", "action movement"],
        "intensity": "low",
    },
    "whoosh-effect": {
        "description": "Whoosh effect for larger transitions, movement sweeps, and action passes.",
        "tags": ["whoosh", "transition", "movement", "sweep", "swoosh"],
        "aliases": ["big_whoosh", "transition_whoosh", "movement_whoosh", "metal_whoosh"],
        "use_cases": ["strong transition", "action sweep", "large motion pass"],
        "intensity": "medium",
    },
    "windows-error-sound-effect": {
        "description": "Classic-style error sound for computer failure, warnings, or uncomfortable mistakes.",
        "tags": ["windows", "error", "beep", "computer", "warning"],
        "aliases": ["windows_error", "computer_error", "system_error", "error_beep"],
        "use_cases": ["computer warning", "failed action", "awkward mistake", "system alert"],
        "intensity": "medium",
    },
}


def seed_pipeline_knowledge(db: Session) -> None:
    for item in DEFAULT_GENRES:
        genre = db.get(Genre, item["id"])
        if genre is None:
            genre = Genre(id=item["id"], display_name=item["display_name"])
            db.add(genre)
        genre.category = item["category"]
        genre.tone = item["tone"]
        genre.caption_preset = item["caption_preset"]
        genre.music_mood = item["music_mood"]
        genre.is_active = True
        _ensure_hooks(db, genre.id, item["hooks"])
        _ensure_rule(db, genre.id, "tone_rule", item["tone"])
        _ensure_visual_style(db, genre.id, item)
    _ensure_topic_expansion_rules(db)
    _ensure_reference_examples(db)
    _ensure_sfx_assets(db)
    db.commit()


def _ensure_hooks(db: Session, genre_id: str, hooks: list[str]) -> None:
    existing = {(row.genre_id, row.template) for row in db.query(GenreHook).filter(GenreHook.genre_id == genre_id)}
    for template in hooks:
        if (genre_id, template) not in existing:
            db.add(GenreHook(genre_id=genre_id, template=template, hook_type="template"))


def _ensure_rule(db: Session, genre_id: str, rule_type: str, value: str) -> None:
    exists = (
        db.query(GenreRule)
        .filter(GenreRule.genre_id == genre_id, GenreRule.rule_type == rule_type, GenreRule.value == value)
        .first()
    )
    if exists is None:
        db.add(GenreRule(genre_id=genre_id, rule_type=rule_type, value=value, weight=1))


def _ensure_visual_style(db: Session, genre_id: str, item: dict[str, str]) -> None:
    style = db.query(VisualStyleRule).filter(VisualStyleRule.genre_id == genre_id).first()
    if style is None:
        style = VisualStyleRule(genre_id=genre_id)
        db.add(style)
    style.layout_type = "full_image"
    style.image_or_video_count = 8
    style.image_style = "realistic stock footage and photos"
    style.visual_keywords = item["visual_keywords"]
    style.negative_visual_keywords = item["negative_visual_keywords"]
    style.source_policy = "stock_video_first"


def _ensure_sfx_assets(db: Session) -> None:
    seen_ids: set[str] = set()
    for sfx_dir in _candidate_sfx_dirs():
        if not sfx_dir.is_dir():
            continue
        for path in sorted(
            (item for item in sfx_dir.rglob("*") if item.is_file() and item.suffix.lower() in SFX_EXTENSIONS),
            key=lambda item: item.name.lower(),
        ):
            asset_id = _sfx_asset_id(path)
            if asset_id in seen_ids:
                continue
            seen_ids.add(asset_id)
            metadata = _sfx_metadata(path)
            row = db.get(SfxAsset, asset_id)
            if row is None:
                row = SfxAsset(id=asset_id)
                db.add(row)
            row.name = _title_from_id(asset_id)
            row.path = str(path.resolve())
            row.description = metadata["description"]
            row.tags = metadata["tags"]
            row.aliases = metadata["aliases"]
            row.use_cases = metadata["use_cases"]
            row.intensity = metadata["intensity"]
            row.source = "local_seed"
            row.enabled = True


def _candidate_sfx_dirs() -> list[Path]:
    candidates: list[Path] = []
    for env_name in ("PLAYGROUND_PIPELINE_DATA_DIR", "MODULARSHORTS_DATA_DIR"):
        value = os.environ.get(env_name, "").strip()
        if value:
            candidates.append(Path(value) / "assets" / "sfx")
    backend_or_repo_root = Path(__file__).resolve().parents[2]
    repo_root = backend_or_repo_root.parent if (backend_or_repo_root.parent / "playground").exists() else backend_or_repo_root
    candidates.extend(
        [
            repo_root / "playground" / "data" / "pipeline" / "assets" / "sfx",
            repo_root / "backend" / "data" / "pipeline" / "assets" / "sfx",
            repo_root / "final_pipeline" / "data" / "assets" / "sfx",
        ]
    )
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key not in seen:
            seen.add(key)
            deduped.append(path)
    return deduped


def _sfx_metadata(path: Path) -> dict[str, list[str] | str]:
    hint = _sfx_hint(path.stem)
    tags = _dedupe_text([*hint.get("tags", []), *_sfx_stem_tokens(path.stem)])
    aliases = _dedupe_text([*hint.get("aliases", []), _sfx_asset_id(path)])
    use_cases = _dedupe_text(hint.get("use_cases", []))
    return {
        "description": str(hint.get("description") or f"{_title_from_id(_sfx_asset_id(path))} sound effect."),
        "tags": tags,
        "aliases": aliases,
        "use_cases": use_cases,
        "intensity": str(hint.get("intensity") or _guess_sfx_intensity(tags)),
    }


def _sfx_hint(stem: str) -> dict[str, list[str] | str]:
    normalized = _normalized_sfx_text(stem)
    for key, hint in SFX_HINTS.items():
        if normalized.startswith(key):
            return hint
    return {}


def _sfx_asset_id(path: Path) -> str:
    tokens = [token for token in _sfx_stem_tokens(path.stem) if not token.isdigit()]
    return "_".join(tokens) or "sfx_asset"


def _sfx_stem_tokens(stem: str) -> list[str]:
    normalized = _normalized_sfx_text(stem)
    return [token for token in normalized.split("-") if token and not re.fullmatch(r"\d{4,}", token)]


def _normalized_sfx_text(value: str) -> str:
    text = str(value or "").lower().replace("_", "-")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _title_from_id(asset_id: str) -> str:
    return " ".join(part.capitalize() for part in str(asset_id or "SFX").split("_"))


def _guess_sfx_intensity(tags: list[str]) -> str:
    joined = " ".join(tags)
    if any(term in joined for term in ("boom", "impact", "smash", "thunder", "damage")):
        return "high"
    if any(term in joined for term in ("glitch", "riser", "error", "whoosh")):
        return "medium"
    return "low"


def _dedupe_text(values: list[object]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _ensure_reference_examples(db: Session) -> None:
    for item in _load_reference_examples():
        genre_id = str(item.get("genre_id") or "").strip()
        source_url = str(item.get("source_url") or item.get("video_url") or "").strip()
        if not genre_id or not source_url:
            continue
        if db.get(Genre, genre_id) is None:
            continue

        video = db.query(ReferenceVideo).filter(ReferenceVideo.video_url == source_url).first()
        if video is None:
            video = ReferenceVideo(genre_id=genre_id, video_url=source_url)
            db.add(video)
        video.genre_id = genre_id
        video.channel_name = str(item.get("channel_name") or item.get("source_type") or "Seed reference")[:120]
        video.channel_subscribers = int(item.get("channel_subscribers") or 0)
        video.views = int(item.get("views") or 0)
        video.likes = int(item.get("likes") or 0)
        video.comments = int(item.get("comments") or 0)
        video.upload_date = _parse_date(item.get("upload_date"))
        video.duration_sec = int(item.get("duration_sec") or 45)
        video.title = str(item.get("title") or "")[:160]
        video.description_first_line = str(item.get("real_world_anchor") or item.get("description_first_line") or "")[:300]
        video.hashtags = _csv(item.get("hashtags") or ["#shorts", f"#{genre_id}"])[:500]
        video.full_script = str(item.get("script") or item.get("full_script") or "")
        video.word_count = int(item.get("word_count") or len(video.full_script.split()))
        video.sentence_count = int(item.get("sentence_count") or _sentence_count(video.full_script))
        video.words_per_second = round(video.word_count / max(1, video.duration_sec), 3)
        video.overall_score = float(item.get("overall_score") or 8.0)
        video.usable_as_few_shot = bool(item.get("usable_as_few_shot", True))
        video.notes = str(item.get("notes") or item.get("real_world_anchor") or "")
        db.flush()

        analysis = video.script_analysis
        if analysis is None:
            analysis = ScriptAnalysis(reference_video_id=video.id)
            db.add(analysis)
        analysis.hook_first_sentence = str(item.get("hook_first_sentence") or _first_sentence(video.full_script))[:500]
        analysis.hook_type = str(item.get("hook_type") or "real_world_anchor")[:80]
        analysis.hook_emotional_trigger = str(item.get("hook_emotional_trigger") or "curiosity")[:80]
        analysis.hook_speed_sec = float(item.get("hook_speed_sec") or 2.5)
        analysis.opening_words = " ".join(video.full_script.split()[:12])[:200]
        analysis.body_sentence_count = max(0, video.sentence_count - 2)
        analysis.has_twist_reveal = bool(item.get("has_twist_reveal", True))
        analysis.twist_line = str(item.get("twist_line") or item.get("retention_hook") or "")[:700]
        analysis.ending_type = str(item.get("ending_type") or "grounded_reveal")[:80]
        analysis.last_sentence = str(item.get("last_sentence") or _last_sentence(video.full_script))[:500]
        analysis.tense_used = str(item.get("tense_used") or "past")[:60]
        analysis.pov_person = str(item.get("pov_person") or "third_person")[:60]
        analysis.narrative_technique = str(item.get("narrative_technique") or "real anchor plus alert beat")[:120]
        analysis.emotional_arc = str(item.get("emotional_arc") or "curiosity to warning to grounded reveal")[:300]
        analysis.power_words = _csv(item.get("power_words"))[:700]
        analysis.emphasis_words = _csv(item.get("emphasis_words"))[:700]
        analysis.sensory_language_used = _csv(item.get("visual_keywords"))[:2000]
        analysis.retention_hook = str(item.get("retention_hook") or "")[:500]
        analysis.likely_share_trigger = str(item.get("likely_share_trigger") or "Useful real-world detail")[:500]
        analysis.why_it_worked = str(item.get("why_it_worked") or "")[:2000]
        analysis.what_to_improve = str(item.get("what_to_improve") or "")[:2000]

        _ensure_topic_research_source(db, item)


def _ensure_topic_research_source(db: Session, item: dict) -> None:
    topic = str(item.get("title") or "").strip()[:300]
    genre_id = str(item.get("genre_id") or "").strip()
    url = str(item.get("source_url") or "").strip()
    if not topic or not genre_id or not url:
        return
    exists = (
        db.query(TopicResearchSource)
        .filter(
            TopicResearchSource.topic == topic,
            TopicResearchSource.genre_id == genre_id,
            TopicResearchSource.url == url,
        )
        .first()
    )
    facts = item.get("facts") if isinstance(item.get("facts"), list) else []
    if exists is None:
        exists = TopicResearchSource(topic=topic, genre_id=genre_id, url=url)
        db.add(exists)
    exists.title = topic
    exists.source_type = str(item.get("source_type") or "reference")[:80]
    exists.snippet = str(item.get("real_world_anchor") or item.get("script") or "")
    exists.extracted_facts = "\n".join(str(fact) for fact in facts)
    exists.credibility_score = 0.85
    exists.relevance_score = float(item.get("overall_score") or 8.0) / 10


def _ensure_topic_expansion_rules(db: Session) -> None:
    rules = [
        {
            "genre_id": "scary_stories",
            "trigger_term": "haunted hallway",
            "search_queries": "haunted hotel corridor real place; haunted school urban legend; reportedly haunted historic building hallway",
            "required_words": "haunted, hallway, corridor, school, hotel, real place",
            "forbidden_words": "cartoon, anime, creepypasta only, fake monster",
            "notes": "Prefer named real places, folklore settings, or documented historic buildings before generic hallway fiction.",
        },
        {
            "genre_id": "scary_stories",
            "trigger_term": "school ghost",
            "search_queries": "school ghost urban legend real folklore; Hanako-san school bathroom legend; real school folklore ghost story",
            "required_words": "school, folklore, legend, real setting",
            "forbidden_words": "random old school hallway, invented demon",
            "notes": "Use folklore setting and cultural context instead of a random school corridor.",
        },
        {
            "genre_id": "history_facts",
            "trigger_term": "unknown history",
            "search_queries": "little known history fact primary source; museum object surprising history; archive document changed history",
            "required_words": "date, place, person, object, primary source",
            "forbidden_words": "myth, unsourced viral claim",
            "notes": "Prefer date/place/object anchors and explain cause-effect simply.",
        },
        {
            "genre_id": "reddit_stories",
            "trigger_term": "scam story",
            "search_queries": "FTC consumer scam warning real example; FBI common scams warning; real life scam red flags",
            "required_words": "red flag, message, payment, verification",
            "forbidden_words": "private personal data, real phone number",
            "notes": "Use real public safety guidance as the ground truth, then dramatize as a safe composite story.",
        },
    ]
    for item in rules:
        row = (
            db.query(TopicExpansionRule)
            .filter(
                TopicExpansionRule.genre_id == item["genre_id"],
                TopicExpansionRule.trigger_term == item["trigger_term"],
            )
            .first()
        )
        if row is None:
            row = TopicExpansionRule(genre_id=item["genre_id"], trigger_term=item["trigger_term"])
            db.add(row)
        row.search_queries = item["search_queries"]
        row.required_words = item["required_words"]
        row.forbidden_words = item["forbidden_words"]
        row.realism_mode = "grounded_real_world_anchor"
        row.notes = item["notes"]


def _load_reference_examples() -> list[dict]:
    data_dir = Path(__file__).resolve().parents[2] / "data" / "pipeline" / "reference_scripts"
    examples: list[dict] = []
    for path in sorted(data_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            examples.extend(item for item in data if isinstance(item, dict))
    return examples


def _parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _csv(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value)


def _sentence_count(text: str) -> int:
    return sum(1 for item in text.replace("!", ".").replace("?", ".").split(".") if item.strip())


def _first_sentence(text: str) -> str:
    for separator in (".", "!", "?"):
        if separator in text:
            return text.split(separator, 1)[0].strip() + separator
    return text.strip()


def _last_sentence(text: str) -> str:
    sentences = [item.strip() for item in text.replace("!", ".").replace("?", ".").split(".") if item.strip()]
    return (sentences[-1] + ".") if sentences else ""
