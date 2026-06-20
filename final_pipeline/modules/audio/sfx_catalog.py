from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.paths import DATA_DIR
from app.schemas import SfxCue


SFX_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"}
SFX_MATCH_THRESHOLD = 18
MAX_PROMPT_SFX = 24

SFX_SYNONYMS = {
    "bass": ["bass", "impact", "boom", "thud", "rumble"],
    "boom": ["boom", "impact", "bass", "thunder"],
    "break": ["impact", "crack", "smash", "boom"],
    "broke": ["impact", "crack", "smash", "boom"],
    "build": ["riser", "whoosh", "suspense"],
    "buzz": ["notification", "ding", "beep"],
    "camera": ["shutter", "click", "ding"],
    "concrete": ["impact", "boom", "smash", "stone"],
    "crack": ["impact", "boom", "smash", "stone"],
    "creak": ["riser", "suspense"],
    "damage": ["damage", "impact", "minecraft"],
    "deep": ["bass", "rumble", "impact"],
    "digital": ["digital", "glitch", "static"],
    "ding": ["ding", "notification", "beep"],
    "door": ["impact", "creak", "riser"],
    "error": ["error", "windows", "beep"],
    "fight": ["whoosh", "impact", "damage"],
    "glitch": ["glitch", "digital", "static"],
    "growl": ["bass", "rumble", "impact"],
    "hit": ["hit", "impact", "boom"],
    "impact": ["impact", "bass", "boom"],
    "knock": ["impact", "boom", "bass"],
    "metal": ["impact", "whoosh", "boom"],
    "mirror": ["impact", "crack", "glitch"],
    "notification": ["notification", "ding", "beep"],
    "paper": ["ding", "notification"],
    "phone": ["notification", "ding", "buzz"],
    "punch": ["damage", "impact", "hit"],
    "reveal": ["impact", "boom", "riser"],
    "riser": ["riser", "whoosh", "suspense"],
    "rumble": ["bass", "impact", "boom"],
    "shield": ["impact", "metal", "boom"],
    "shutter": ["ding", "notification", "click"],
    "smash": ["impact", "boom", "damage"],
    "static": ["glitch", "digital", "error"],
    "sting": ["impact", "riser", "boom"],
    "stinger": ["impact", "riser", "boom"],
    "stone": ["impact", "boom", "hit"],
    "suspense": ["riser", "impact", "glitch"],
    "swoosh": ["whoosh", "riser"],
    "thud": ["impact", "boom", "bass"],
    "thunder": ["impact", "boom", "bass"],
    "transition": ["whoosh", "riser"],
    "vibration": ["notification", "ding", "buzz"],
    "whoosh": ["whoosh", "riser"],
    "window": ["error", "windows", "beep"],
    "windows": ["error", "windows", "beep"],
}

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


@dataclass
class SfxCatalogEntry:
    id: str
    name: str
    path: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    use_cases: list[str] = field(default_factory=list)
    intensity: str = ""
    duration_ms: int = 0
    source: str = "file_scan"


def resolve_sfx_cues(sfx_cues: list[SfxCue], sfx_dir: Path | None = None) -> tuple[list[str], list[dict[str, Any]]]:
    sfx_root = sfx_dir or DATA_DIR / "assets" / "sfx"
    trace: list[dict[str, Any]] = []
    if not sfx_cues:
        return [], trace

    catalog = load_sfx_catalog(sfx_root)
    if not catalog:
        reason = f"SFX directory not found or empty: {sfx_root}"
        return [], [
            {
                "trigger_word": cue.trigger_word,
                "sfx_type": cue.sfx_type,
                "status": "missing_library",
                "reason": reason,
            }
            for cue in sfx_cues
        ]

    resolved: list[str] = []
    for cue in sfx_cues:
        match, strategy, score = match_sfx_entry(cue, catalog)
        if match:
            resolved.append(match.path)
            trace.append(
                {
                    "trigger_word": cue.trigger_word,
                    "sfx_type": cue.sfx_type,
                    "timestamp_hint": cue.timestamp_hint,
                    "status": "matched",
                    "strategy": strategy,
                    "score": score,
                    "sfx_id": match.id,
                    "sfx_name": match.name,
                    "tags": match.tags,
                    "use_cases": match.use_cases,
                    "path": match.path,
                }
            )
        else:
            trace.append(
                {
                    "trigger_word": cue.trigger_word,
                    "sfx_type": cue.sfx_type,
                    "timestamp_hint": cue.timestamp_hint,
                    "status": "missing",
                    "strategy": "no_catalog_match",
                    "available_sfx_count": len(catalog),
                }
            )
    return resolved, trace


def load_sfx_catalog(sfx_dir: Path | None = None) -> list[SfxCatalogEntry]:
    root = sfx_dir or DATA_DIR / "assets" / "sfx"
    db_entries = _load_db_sfx_catalog()
    entries = [entry for entry in db_entries if _entry_path_exists(entry)]
    if entries:
        return _dedupe_catalog(entries)
    return _scan_sfx_catalog(root)


def catalog_for_prompt(limit: int = MAX_PROMPT_SFX) -> list[dict[str, Any]]:
    catalog = load_sfx_catalog(DATA_DIR / "assets" / "sfx")
    return [
        {
            "id": entry.id,
            "name": entry.name,
            "description": entry.description,
            "tags": entry.tags[:10],
            "aliases": entry.aliases[:10],
            "use_cases": entry.use_cases[:6],
            "intensity": entry.intensity,
        }
        for entry in catalog[: max(0, limit)]
    ]


def match_sfx_entry(cue: SfxCue, catalog: list[SfxCatalogEntry]) -> tuple[SfxCatalogEntry | None, str, int]:
    terms = _sfx_search_terms(cue)
    raw_type = _normalized_key(cue.sfx_type)
    best: tuple[int, str, SfxCatalogEntry | None] = (0, "", None)
    for entry in catalog:
        score, strategy = _score_entry(cue, entry, terms, raw_type)
        if score > best[0]:
            best = (score, strategy, entry)
    if best[2] is not None and best[0] >= SFX_MATCH_THRESHOLD:
        return best[2], best[1], best[0]
    return None, "", 0


def infer_sfx_entry_from_path(path: Path, *, source: str = "file_scan") -> SfxCatalogEntry:
    asset_id = _catalog_id_for_path(path)
    hint = _hint_for_stem(path.stem)
    name = _title_from_id(asset_id)
    tags = _dedupe_words([*hint.get("tags", []), *_stem_tokens(path.stem)])
    aliases = _dedupe_words([*hint.get("aliases", []), asset_id])
    use_cases = _dedupe_words(hint.get("use_cases", []))
    return SfxCatalogEntry(
        id=asset_id,
        name=name,
        path=str(path.resolve() if path.exists() else path),
        description=str(hint.get("description") or f"{name} sound effect."),
        tags=tags,
        aliases=aliases,
        use_cases=use_cases,
        intensity=str(hint.get("intensity") or _guess_intensity(tags)),
        duration_ms=0,
        source=source,
    )


def _load_db_sfx_catalog() -> list[SfxCatalogEntry]:
    if os.environ.get("MODULARSHORTS_DB_SFX_CATALOG", "1").strip().lower() in {"0", "false", "no", "off"}:
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
        SELECT id, name, path, description, tags, aliases, use_cases, intensity, duration_ms
        FROM sfx_assets
        WHERE enabled = true
        ORDER BY id ASC
        """
    )
    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
    except Exception:
        return []
    entries: list[SfxCatalogEntry] = []
    for row in rows:
        path = str(row.get("path") or "").strip()
        if not path:
            continue
        entries.append(
            SfxCatalogEntry(
                id=str(row.get("id") or _catalog_id_for_path(Path(path))),
                name=str(row.get("name") or _title_from_id(_catalog_id_for_path(Path(path)))),
                path=path,
                description=str(row.get("description") or ""),
                tags=_as_text_list(row.get("tags")),
                aliases=_as_text_list(row.get("aliases")),
                use_cases=_as_text_list(row.get("use_cases")),
                intensity=str(row.get("intensity") or ""),
                duration_ms=int(row.get("duration_ms") or 0),
                source="database",
            )
        )
    return entries


def _scan_sfx_catalog(sfx_dir: Path) -> list[SfxCatalogEntry]:
    if not sfx_dir.is_dir():
        return []
    entries = [
        infer_sfx_entry_from_path(path)
        for path in sorted(
            (item for item in sfx_dir.rglob("*") if item.is_file() and item.suffix.lower() in SFX_EXTENSIONS),
            key=lambda item: item.name.lower(),
        )
    ]
    return _dedupe_catalog(entries)


def _score_entry(cue: SfxCue, entry: SfxCatalogEntry, terms: list[str], raw_type: str) -> tuple[int, str]:
    entry_keys = {_normalized_key(entry.id), _normalized_key(entry.name), _normalized_key(Path(entry.path).stem)}
    tag_keys = {_normalized_key(item) for item in entry.tags}
    alias_keys = {_normalized_key(item) for item in entry.aliases}
    use_case_text = _normalized_sfx_text(" ".join(entry.use_cases))
    searchable = _normalized_sfx_text(
        " ".join(
            [
                entry.id,
                entry.name,
                Path(entry.path).stem,
                entry.description,
                " ".join(entry.tags),
                " ".join(entry.aliases),
                " ".join(entry.use_cases),
                entry.intensity,
            ]
        )
    )
    if raw_type and raw_type in entry_keys:
        return 120, "catalog_id"
    if raw_type and raw_type in alias_keys:
        return 105, f"catalog_alias:{raw_type}"
    if raw_type and raw_type in tag_keys:
        return 86, f"catalog_tag:{raw_type}"

    best_score = 0
    best_strategy = ""
    for term in terms:
        key = _normalized_key(term)
        text = _normalized_sfx_text(term)
        if not key and not text:
            continue
        score = 0
        strategy = ""
        if key in alias_keys:
            score = 82
            strategy = f"alias:{key}"
        elif key in entry_keys:
            score = 78
            strategy = f"id_or_name:{key}"
        elif key in tag_keys:
            score = 70
            strategy = f"tag:{key}"
        elif text and text in searchable:
            score = 34
            strategy = f"catalog_text:{text}"
        elif text and text in use_case_text:
            score = 30
            strategy = f"use_case:{text}"
        elif _partial_term_match(key, tag_keys | alias_keys):
            score = 24
            strategy = f"partial:{key}"
        if score > best_score:
            best_score = score
            best_strategy = strategy
    return best_score, best_strategy


def _sfx_search_terms(cue: SfxCue) -> list[str]:
    seeds = [
        str(cue.sfx_type or ""),
        str(cue.trigger_word or ""),
        str(cue.timestamp_hint or ""),
    ]
    terms: list[str] = []
    for seed in seeds:
        normalized = _normalized_sfx_text(seed)
        _append_unique(terms, normalized)
        for token in normalized.split("-"):
            _append_unique(terms, token)
            for alias in SFX_SYNONYMS.get(token, []):
                _append_unique(terms, alias)
    return terms


def _normalized_sfx_text(value: str) -> str:
    text = str(value or "").lower().replace("_", "-")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _normalized_key(value: str) -> str:
    return _normalized_sfx_text(value).replace("-", "_")


def _catalog_id_for_path(path: Path) -> str:
    tokens = [token for token in _stem_tokens(path.stem) if not token.isdigit()]
    return "_".join(tokens) or "sfx_asset"


def _stem_tokens(stem: str) -> list[str]:
    normalized = _normalized_sfx_text(stem)
    return [token for token in normalized.split("-") if token and not re.fullmatch(r"\d{4,}", token)]


def _hint_for_stem(stem: str) -> dict[str, Any]:
    normalized = _normalized_sfx_text(stem)
    for key, hint in SFX_HINTS.items():
        if normalized.startswith(key):
            return hint
    return {}


def _title_from_id(asset_id: str) -> str:
    return " ".join(part.capitalize() for part in str(asset_id or "SFX").split("_"))


def _guess_intensity(tags: list[str]) -> str:
    joined = " ".join(tags)
    if any(term in joined for term in ("boom", "impact", "smash", "thunder", "damage")):
        return "high"
    if any(term in joined for term in ("glitch", "riser", "error", "whoosh")):
        return "medium"
    return "low"


def _dedupe_catalog(entries: list[SfxCatalogEntry]) -> list[SfxCatalogEntry]:
    deduped: list[SfxCatalogEntry] = []
    seen: set[str] = set()
    for entry in entries:
        key = entry.id
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def _entry_path_exists(entry: SfxCatalogEntry) -> bool:
    try:
        path = Path(entry.path)
    except OSError:
        return False
    return path.is_file() and path.suffix.lower() in SFX_EXTENSIONS


def _partial_term_match(term: str, candidates: set[str]) -> bool:
    if len(term) < 4:
        return False
    return any(term in candidate or candidate in term for candidate in candidates if len(candidate) >= 4)


def _as_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        return [item.strip() for item in re.split(r"[,;\n]+", raw) if item.strip()]
    return []


def _dedupe_words(values: list[Any]) -> list[str]:
    words: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in words:
            words.append(text)
    return words


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)
