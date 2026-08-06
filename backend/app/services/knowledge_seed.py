from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from app.models import (
    Genre,
    ReferenceExample,
    StaticAsset,
)


DEFAULT_GENRES = [
    {
        "id": "scary_stories",
        "display_name": "Scary Stories",
        "category": "story",
        "tone": "Suspenseful, grounded, simple, and visual. Build dread through evidence, not gore.",
        "caption_preset": "horror_red",
        "music_mood": "dark ambient",
        "hooks": [
            "At {time}, {subject} noticed {detail}.",
            "The first warning was {detail}.",
            "{ordinary_object} should not have been there.",
            "Everyone thought {explanation}. Then {contradiction}.",
        ],
        "banned_phrases": ["you won't believe", "like and subscribe", "smash that bell", "graphic warning"],
        "script_profile": {
            "tone": "slow dread, believable, concrete, no graphic gore",
            "pacing": "open fast, slow the middle for tension, end with one sharp reveal",
            "perspective": "narrator guiding the viewer through a clue chain",
            "sentence_style": "short sentences, one concrete detail each",
            "structure": {
                "opening": "Specific time/place/object in the first sentence. No greeting.",
                "middle": "Ordinary explanation, then a contradiction, then one worse clue.",
                "closing": "Final sentence reveals the impossible-but-believable detail.",
            },
            "retention": {
                "beat_interval_seconds": 4,
                "beats": ["specific hook", "normal explanation", "contradiction", "evidence object", "final reveal"],
                "payoff": "One physical clue changes the meaning of the whole story.",
            },
            "cta_variants": [],
        },
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
        "hooks": [
            "Most people do not know {fact}.",
            "This real place changed because of {event}.",
            "{object} looks ordinary, but it explains {bigger_idea}.",
            "The strange part is not {obvious_detail}. It is {hidden_detail}.",
        ],
        "banned_phrases": ["random fact", "fake history", "you won't believe", "history is crazy"],
        "script_profile": {
            "tone": "curious, precise, plain-spoken, documentary",
            "pacing": "start with the surprising result, then explain the mechanism",
            "perspective": "smart friend explaining one real thing clearly",
            "sentence_style": "short factual sentences with one memorable turn",
            "structure": {
                "opening": "Lead with a counterintuitive fact or object.",
                "middle": "Give 2-3 real anchors. Each anchor should make the surprise clearer.",
                "closing": "End by reframing the fact into a simple lesson or irony.",
            },
            "retention": {
                "beat_interval_seconds": 5,
                "beats": ["counterintuitive fact", "real anchor", "mechanism", "bigger implication", "memorable reframe"],
                "payoff": "The final line should make the opening fact mean something bigger.",
            },
            "cta_variants": [],
        },
        "visual_keywords": "historic city street, archive photo, museum object, map close up",
        "negative_visual_keywords": "fantasy, fictional city, game art",
    },
    {
        "id": "reddit_stories",
        "display_name": "Reddit Stories",
        "category": "story",
        "tone": "Conversational, direct, believable, and easy to follow. Social tension should escalate through proof.",
        "caption_preset": "clean_pro",
        "music_mood": "light tension",
        "hooks": [
            "I thought {person} was joking until {detail}.",
            "What would you do if {problem}?",
            "The message looked normal until I noticed {detail}.",
            "I almost ignored {object}. Then {proof} showed up.",
        ],
        "banned_phrases": ["reddit user said", "upvote", "aita", "story time", "you won't believe"],
        "script_profile": {
            "tone": "natural, direct, believable, low-drama but tense",
            "pacing": "fast setup, social contradiction, concrete proof, clean twist",
            "perspective": "first-person or close third-person, like a friend telling the story",
            "sentence_style": "plain conversational sentences, no melodrama",
            "structure": {
                "opening": "Start with a normal object, message, receipt, bill, key, or note.",
                "middle": "Add a contradiction and then proof the viewer can picture.",
                "closing": "End with the proof changing who the viewer trusts.",
            },
            "retention": {
                "beat_interval_seconds": 4,
                "beats": ["normal setup", "odd detail", "denial or excuse", "proof object", "trust flip"],
                "payoff": "A concrete item reveals the truth without overexplaining.",
            },
            "cta_variants": [],
        },
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
        "hooks": [
            "Every great comic fight starts with {conflict}.",
            "The panel that changes everything is {detail}.",
            "{hero} thought the fight was over. The next panel proved otherwise.",
            "The clue was hidden in {visual_detail}.",
        ],
        "banned_phrases": ["official marvel", "official dc", "movie scene", "cinematic universe"],
        "script_profile": {
            "tone": "bold, visual, energetic, panel-by-panel",
            "pacing": "fast visual beats, each panel adds a clue or raises the stakes",
            "perspective": "comic narrator describing action and visual clues",
            "sentence_style": "short punchy lines with clear visual nouns",
            "structure": {
                "opening": "Start mid-conflict with one visual clue.",
                "middle": "Escalate through 3 panel-like beats and one hidden detail.",
                "closing": "Reveal what the hidden detail meant in a final panel/payoff.",
            },
            "retention": {
                "beat_interval_seconds": 3,
                "beats": ["mid-fight hook", "panel clue", "stakes jump", "hidden detail", "final panel reveal"],
                "payoff": "The final panel should reframe the first clue.",
            },
            "cta_variants": [],
        },
        "visual_keywords": "comic hero, city rooftop, masked figure, villain shadow, action lines, speech bubble",
        "negative_visual_keywords": "movie still, actor face, studio logo, gore",
    },
]

AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"}
SFX_EXTENSIONS = AUDIO_EXTENSIONS
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
        genre.hook_patterns = item["hooks"]
        genre.banned_phrases = item.get("banned_phrases", [])
        genre.visual_style = _visual_style_payload(item)
        genre.topic_rules = _topic_rules_for_genre(genre.id)
        genre.metadata_json = {
            "tone_rule": item["tone"],
            "script_profile": item.get("script_profile", {}),
        }
        genre.is_active = True
    _ensure_niche_genres(db)
    db.flush()
    _ensure_reference_examples(db)
    _ensure_sfx_assets(db)
    _ensure_music_assets(db)
    db.commit()


def _ensure_niche_genres(db: Session) -> None:
    protected_ids = {str(item["id"]) for item in DEFAULT_GENRES}
    for profile in _load_niche_profiles():
        niche_id = _niche_id(profile)
        if not niche_id or niche_id in protected_ids:
            continue
        script = profile.get("script") if isinstance(profile.get("script"), dict) else {}
        visuals = profile.get("visuals") if isinstance(profile.get("visuals"), dict) else {}
        captions = profile.get("captions") if isinstance(profile.get("captions"), dict) else {}
        music = profile.get("music") if isinstance(profile.get("music"), dict) else {}
        voice = profile.get("voice") if isinstance(profile.get("voice"), dict) else {}

        genre = db.get(Genre, niche_id)
        if genre is None:
            genre = Genre(id=niche_id, display_name=str(profile.get("display_name") or _title_from_id(niche_id)))
            db.add(genre)

        word_count_min, word_count_max = _parse_word_count_range(script.get("word_count"))
        genre.display_name = str(profile.get("display_name") or genre.display_name or _title_from_id(niche_id))
        genre.category = _niche_category(niche_id)
        genre.tone = str(script.get("tone") or profile.get("description") or "")
        genre.default_duration_sec = 45
        genre.word_count_min = word_count_min
        genre.word_count_max = word_count_max
        genre.layout = "full_image"
        genre.caption_preset = str(captions.get("highlight_color") or "clean_pro")
        genre.voice_rate = _voice_rate_from_profile(voice)
        genre.music_mood = str(music.get("mood") or "")
        genre.realism_mode = _niche_realism_mode(niche_id)
        genre.hook_patterns = _niche_hook_patterns(script)
        genre.banned_phrases = [str(item) for item in script.get("forbidden_phrases") or [] if str(item).strip()]
        genre.visual_style = _niche_visual_style(visuals, captions, profile)
        genre.topic_rules = _niche_topic_rules(profile)
        genre.metadata_json = {
            "source": "youtube-shorts-pipeline/niches",
            "description": str(profile.get("description") or ""),
            "script_profile": _niche_script_profile(script),
            "voice": voice,
            "captions": captions,
            "music": music,
            "thumbnail": profile.get("thumbnail") if isinstance(profile.get("thumbnail"), dict) else {},
            "discovery": profile.get("discovery") if isinstance(profile.get("discovery"), dict) else {},
            "original_niche_profile": profile,
        }
        genre.notes = "Imported niche profile from youtube-shorts-pipeline."
        genre.is_active = True


def _load_niche_profiles() -> list[dict]:
    profiles: list[dict] = []
    for directory in _candidate_niche_dirs():
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            if isinstance(data, dict):
                data.setdefault("name", path.stem)
                profiles.append(data)
    return profiles


def _candidate_niche_dirs() -> list[Path]:
    candidates: list[Path] = []
    for env_name in ("MODULARSHORTS_DATA_DIR", "PLAYGROUND_PIPELINE_DATA_DIR"):
        value = os.environ.get(env_name, "").strip()
        if value:
            candidates.append(Path(value) / "niches")
    backend_or_repo_root = Path(__file__).resolve().parents[2]
    repo_root = backend_or_repo_root.parent if (backend_or_repo_root.parent / "playground").exists() else backend_or_repo_root
    candidates.extend(
        [
            repo_root / "backend" / "data" / "pipeline" / "niches",
            repo_root / "playground" / "data" / "pipeline" / "niches",
            repo_root / "final_pipeline" / "data" / "niches",
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


def _niche_id(profile: dict) -> str:
    raw = str(profile.get("name") or profile.get("id") or "").strip().lower()
    return re.sub(r"[^a-z0-9_]+", "_", raw).strip("_")


def _niche_category(niche_id: str) -> str:
    if niche_id in {"true_crime", "comedy", "entertainment", "travel"}:
        return "story"
    if niche_id in {"finance", "science", "tech", "politics", "education"}:
        return "facts"
    if niche_id in {"fitness", "cooking", "fashion"}:
        return "lifestyle"
    return "general"


def _niche_realism_mode(niche_id: str) -> str:
    if niche_id in {"comedy", "motivation"}:
        return "creative"
    return "inspired_by_real_events"


def _niche_hook_patterns(script: dict) -> list[str]:
    hooks = script.get("hooks") if isinstance(script.get("hooks"), list) else []
    patterns: list[str] = []
    for hook in hooks:
        if isinstance(hook, dict):
            patterns.append(str(hook.get("template") or ""))
        else:
            patterns.append(str(hook or ""))
    return _dedupe_text(patterns)


def _niche_script_profile(script: dict) -> dict:
    return {
        "tone": str(script.get("tone") or ""),
        "pacing": str(script.get("pacing") or ""),
        "perspective": str(script.get("perspective") or ""),
        "sentence_style": str(script.get("sentence_style") or ""),
        "structure": script.get("structure") if isinstance(script.get("structure"), dict) else {},
        "retention": {
            "beat_interval_seconds": 4,
            "beats": _retention_beats_from_structure(script),
            "payoff": "Close with the strongest reveal, reversal, takeaway, or opinion from the niche profile.",
        },
        "cta_variants": [str(item) for item in script.get("cta_variants") or [] if str(item).strip()],
        "hooks": script.get("hooks") if isinstance(script.get("hooks"), list) else [],
    }


def _retention_beats_from_structure(script: dict) -> list[str]:
    structure = script.get("structure") if isinstance(script.get("structure"), dict) else {}
    beats = [key for key in ("opening", "middle", "closing") if structure.get(key)]
    return beats or ["hook", "context", "escalation", "payoff"]


def _niche_visual_style(visuals: dict, captions: dict, profile: dict) -> dict:
    subjects = visuals.get("subjects") if isinstance(visuals.get("subjects"), dict) else {}
    return {
        "layout_type": "full_image",
        "image_or_video_count": 8,
        "image_style": str(visuals.get("style") or "cinematic, professional"),
        "mood": str(visuals.get("mood") or ""),
        "color_palette": visuals.get("color_palette") if isinstance(visuals.get("color_palette"), list) else [],
        "visual_keywords": ", ".join(str(item) for item in subjects.get("prefer") or []),
        "negative_visual_keywords": ", ".join(str(item) for item in subjects.get("avoid") or []),
        "prompt_suffix": str(visuals.get("prompt_suffix") or ""),
        "caption_highlight_color": str(captions.get("highlight_color") or ""),
        "source_policy": "stock_video_first",
        "thumbnail": profile.get("thumbnail") if isinstance(profile.get("thumbnail"), dict) else {},
    }


def _niche_topic_rules(profile: dict) -> list[dict[str, str]]:
    script = profile.get("script") if isinstance(profile.get("script"), dict) else {}
    hooks = script.get("hooks") if isinstance(script.get("hooks"), list) else []
    rules: list[dict[str, str]] = []
    for hook in hooks:
        if not isinstance(hook, dict):
            continue
        when = str(hook.get("when") or "").strip()
        if not when:
            continue
        rules.append(
            {
                "trigger": when,
                "guidance": str(hook.get("template") or ""),
                "retention_move": f"Use the {hook.get('id') or 'niche'} hook when the topic matches this condition.",
            }
        )
    return rules


def _parse_word_count_range(value: object) -> tuple[int, int]:
    numbers = [int(item) for item in re.findall(r"\d+", str(value or ""))]
    if len(numbers) >= 2:
        return numbers[0], numbers[1]
    if len(numbers) == 1:
        return max(50, numbers[0] - 15), numbers[0] + 15
    return 120, 170


def _voice_rate_from_profile(voice: dict) -> float:
    pace = str(voice.get("pace") or "")
    numbers = [int(item) for item in re.findall(r"\d+", pace)]
    if not numbers:
        return 1.0
    return round(max(0.75, min(1.25, numbers[0] / 150)), 2)


def _visual_style_payload(item: dict[str, str]) -> dict[str, str | int]:
    return {
        "layout_type": "full_image",
        "image_or_video_count": 8,
        "image_style": "realistic stock footage and photos",
        "visual_keywords": item["visual_keywords"],
        "negative_visual_keywords": item["negative_visual_keywords"],
        "source_policy": "stock_video_first",
    }


def _topic_rules_for_genre(genre_id: str) -> list[dict[str, str]]:
    rules = {
        "scary_stories": [
            {
                "trigger": "haunted hallway",
                "guidance": "Prefer named real places, folklore settings, or documented historic buildings before generic hallway fiction.",
                "retention_move": "make the hallway ordinary first, then reveal a repeated clue that should be impossible",
            },
            {
                "trigger": "school ghost",
                "guidance": "Use folklore setting and cultural context instead of a random school corridor.",
                "retention_move": "delay the ghost explanation until after a concrete object or recording contradicts it",
            },
        ],
        "history_facts": [
            {
                "trigger": "unknown history",
                "guidance": "Prefer date, place, person, or object anchors and explain cause-effect simply.",
                "retention_move": "open with the surprising outcome, then reveal the mechanism in the middle",
            }
        ],
        "reddit_stories": [
            {
                "trigger": "scam story",
                "guidance": "Use public safety guidance as ground truth, then dramatize as a safe composite story.",
                "retention_move": "use a receipt, message, payment request, or verification code as the proof object",
            }
        ],
        "comics": [
            {
                "trigger": "hidden clue",
                "guidance": "Use original generic hero/villain scenarios and avoid copyrighted identities unless the topic is factual.",
                "retention_move": "make the first panel contain a visual clue that only pays off in the final panel",
            }
        ],
    }
    return rules.get(genre_id, [])


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
            row = db.get(StaticAsset, asset_id)
            if row is None:
                row = StaticAsset(id=asset_id)
                db.add(row)
            row.asset_type = "sfx"
            row.name = _title_from_id(asset_id)
            row.path = str(path.resolve())
            row.description = metadata["description"]
            row.tags = metadata["tags"]
            row.aliases = metadata["aliases"]
            row.use_cases = metadata["use_cases"]
            row.intensity = metadata["intensity"]
            row.mood = ""
            row.source = "local_seed"
            row.enabled = True


def upsert_sfx_asset(db: Session, path: Path, *, source: str = "upload") -> StaticAsset:
    metadata = _sfx_metadata(path)
    asset_id = _sfx_asset_id(path)
    row = db.get(StaticAsset, asset_id)
    if row is None:
        row = StaticAsset(id=asset_id)
        db.add(row)
    row.asset_type = "sfx"
    row.name = _title_from_id(asset_id)
    row.path = str(path.resolve())
    row.description = metadata["description"]
    row.tags = metadata["tags"]
    row.aliases = metadata["aliases"]
    row.use_cases = metadata["use_cases"]
    row.intensity = metadata["intensity"]
    row.mood = ""
    row.source = source
    row.enabled = True
    return row


def _ensure_music_assets(db: Session) -> None:
    seen_paths: set[str] = set()
    for music_dir in _candidate_music_dirs():
        if not music_dir.is_dir():
            continue
        for path in sorted(
            (item for item in music_dir.rglob("*") if item.is_file() and item.suffix.lower() in AUDIO_EXTENSIONS),
            key=lambda item: item.name.lower(),
        ):
            resolved = str(path.resolve())
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            source = "upload" if "uploads" in path.parts else "template"
            upsert_music_asset(db, path, source=source)


def upsert_music_asset(db: Session, path: Path, *, source: str = "upload") -> StaticAsset:
    asset_id = _music_asset_id(path)
    row = db.get(StaticAsset, asset_id)
    if row is None:
        row = StaticAsset(id=asset_id)
        db.add(row)
    row.asset_type = "music"
    row.name = _music_title(path)
    row.path = str(path.resolve())
    row.description = _music_description(path, source)
    row.tags = _music_tags(path, source)
    row.aliases = []
    row.use_cases = []
    row.mood = _music_mood(path)
    row.intensity = ""
    row.source = source
    row.enabled = True
    return row


def _candidate_sfx_dirs() -> list[Path]:
    candidates: list[Path] = []
    for env_name in ("MODULARSHORTS_DATA_DIR", "PLAYGROUND_PIPELINE_DATA_DIR"):
        value = os.environ.get(env_name, "").strip()
        if value:
            candidates.append(Path(value) / "assets" / "sfx")
    backend_or_repo_root = Path(__file__).resolve().parents[2]
    repo_root = backend_or_repo_root.parent if (backend_or_repo_root.parent / "playground").exists() else backend_or_repo_root
    candidates.extend(
        [
            repo_root / "backend" / "data" / "pipeline" / "assets" / "sfx",
            repo_root / "playground" / "data" / "pipeline" / "assets" / "sfx",
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


def _candidate_music_dirs() -> list[Path]:
    candidates: list[Path] = []
    for env_name in ("MODULARSHORTS_DATA_DIR", "PLAYGROUND_PIPELINE_DATA_DIR"):
        value = os.environ.get(env_name, "").strip()
        if value:
            candidates.append(Path(value) / "assets" / "music")
    backend_or_repo_root = Path(__file__).resolve().parents[2]
    repo_root = backend_or_repo_root.parent if (backend_or_repo_root.parent / "playground").exists() else backend_or_repo_root
    candidates.extend(
        [
            repo_root / "backend" / "data" / "pipeline" / "assets" / "music",
            repo_root / "playground" / "data" / "pipeline" / "assets" / "music",
            repo_root / "final_pipeline" / "data" / "assets" / "music",
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


def _music_asset_id(path: Path) -> str:
    tokens = [token for token in _sfx_stem_tokens(path.stem) if not token.isdigit()]
    return "_".join(tokens) or "music_asset"


def _music_title(path: Path) -> str:
    stem = re.sub(r"[-_]+", " ", path.stem).strip()
    stem = re.sub(r"\b[a-f0-9]{8}\b$", "", stem, flags=re.I).strip()
    stem = re.sub(r"\s+", " ", stem)
    return stem.title() or "Music Track"


def _music_description(path: Path, source: str) -> str:
    label = "Uploaded" if source == "upload" else "Template"
    return f"{label} music track for video background beds."


def _music_tags(path: Path, source: str) -> list[str]:
    tags = [source, *_sfx_stem_tokens(path.stem)]
    mood = _music_mood(path)
    if mood:
        tags.append(mood)
    return _dedupe_text(tags)


def _music_mood(path: Path) -> str:
    text = _normalized_sfx_text(path.stem)
    mood_terms = {
        "dark": ("dark", "horror", "scary", "eerie", "ambient"),
        "documentary": ("documentary", "history", "cinematic", "pulse"),
        "upbeat": ("happy", "upbeat", "bright", "fun"),
        "tension": ("tense", "tension", "suspense", "riser"),
        "calm": ("calm", "soft", "lofi", "relax"),
    }
    for mood, terms in mood_terms.items():
        if any(term in text for term in terms):
            return mood
    return "general"


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

        row = db.query(ReferenceExample).filter(ReferenceExample.source_url == source_url).first()
        if row is None:
            row = ReferenceExample(genre_id=genre_id, source_url=source_url)
            db.add(row)
        script = str(item.get("script") or item.get("full_script") or "")
        facts = item.get("facts") if isinstance(item.get("facts"), list) else []
        row.genre_id = genre_id
        row.title = str(item.get("title") or "")[:200]
        row.source_label = str(item.get("channel_name") or item.get("source_type") or "Seed reference")[:120]
        row.script = script
        row.description = str(item.get("real_world_anchor") or item.get("description_first_line") or "")
        row.tags = _reference_tags(item, genre_id)
        row.metrics = {
            "views": int(item.get("views") or 0),
            "likes": int(item.get("likes") or 0),
            "comments": int(item.get("comments") or 0),
            "upload_date": str(_parse_date(item.get("upload_date")) or ""),
        }
        row.analysis = {
            "hook_first_sentence": str(item.get("hook_first_sentence") or _first_sentence(script)),
            "hook_type": str(item.get("hook_type") or "real_world_anchor"),
            "hook_emotional_trigger": str(item.get("hook_emotional_trigger") or "curiosity"),
            "has_twist_reveal": bool(item.get("has_twist_reveal", True)),
            "twist_line": str(item.get("twist_line") or item.get("retention_hook") or ""),
            "ending_type": str(item.get("ending_type") or "grounded_reveal"),
            "last_sentence": str(item.get("last_sentence") or _last_sentence(script)),
            "power_words": _csv(item.get("power_words")),
            "emphasis_words": _csv(item.get("emphasis_words")),
            "sensory_language_used": _csv(item.get("visual_keywords")),
            "retention_hook": str(item.get("retention_hook") or ""),
            "why_it_worked": str(item.get("why_it_worked") or ""),
            "what_to_improve": str(item.get("what_to_improve") or ""),
        }
        row.facts = [str(fact) for fact in facts if str(fact).strip()]
        row.duration_sec = int(item.get("duration_sec") or 45)
        row.word_count = int(item.get("word_count") or len(script.split()))
        row.overall_score = float(item.get("overall_score") or 8.0)
        row.usable_as_few_shot = bool(item.get("usable_as_few_shot", True))
        row.notes = str(item.get("notes") or item.get("real_world_anchor") or "")


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


def _reference_tags(item: dict, genre_id: str) -> list[str]:
    tags = [genre_id]
    tags.extend(str(tag).lstrip("#") for tag in item.get("hashtags") or [])
    tags.extend(str(tag) for tag in item.get("visual_keywords") or [])
    return _dedupe_text(tags)


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
