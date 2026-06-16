from __future__ import annotations

import re
from typing import Any
from dataclasses import dataclass, field

from app.schemas import GenreConfig, ImageCue


@dataclass(frozen=True)
class GenreIntentProfile:
    positive_terms: tuple[str, ...]
    negative_terms: tuple[str, ...]
    required_context: tuple[str, ...]
    query_expansions: tuple[str, ...] = field(default_factory=tuple)
    rewrites: tuple[tuple[tuple[str, ...], str], ...] = field(default_factory=tuple)
    reject_rules: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AssetIntent:
    genre_id: str
    mood: str = "neutral"
    positive_terms: tuple[str, ...] = field(default_factory=tuple)
    negative_terms: tuple[str, ...] = field(default_factory=tuple)
    required_context: tuple[str, ...] = field(default_factory=tuple)
    query_expansions: tuple[str, ...] = field(default_factory=tuple)
    reject_rules: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = field(default_factory=tuple)
    allow_child: bool = False


_BASE_NEGATIVE = (
    "meme",
    "logo",
    "watermark",
    "icon",
    "clipart",
    "selfie",
)

_CHILD_TERMS = {"child", "children", "kid", "kids", "baby"}

_PROFILES: dict[str, GenreIntentProfile] = {
    "scary_stories": GenreIntentProfile(
        positive_terms=(
            "horror",
            "scary",
            "dark",
            "eerie",
            "creepy",
            "haunted",
            "shadow",
            "night",
            "abandoned",
            "bloody",
            "blood",
            "fog",
            "old",
        ),
        negative_terms=_BASE_NEGATIVE
        + (
            "cute",
            "happy",
            "smiling",
            "child",
            "children",
            "kid",
            "kids",
            "baby",
            "pain",
            "injury",
            "injured",
            "wound",
            "doctor",
            "patient",
            "clinic",
            "surgery",
            "medical",
            "hospital bed",
            "portrait",
        ),
        required_context=("horror", "dark"),
        query_expansions=("eerie horror", "dark cinematic", "no people"),
        rewrites=(
            (("handprint", "hand print", "palm print"), "bloody handprint on dark wall horror"),
            (("footprint", "footprints"), "muddy footprints in dark hallway horror"),
            (("hospital", "medical", "doctor"), "abandoned hospital corridor horror"),
            (("mirror",), "cracked mirror dark room horror"),
            (("door", "doorway"), "old door dark hallway horror"),
            (("window",), "foggy window red handprint horror"),
            (("basement",), "dark basement stairs horror"),
            (("doll", "toy"), "haunted doll abandoned bedroom horror"),
            (("forest", "woods"), "dark forest path horror fog"),
            (("house", "home"), "abandoned house hallway horror"),
            (("shadow",), "human shadow dark wall horror"),
            (("letter", "note"), "old handwritten note dark table horror"),
        ),
        reject_rules=(
            (("handprint", "hand print", "palm print"), ("child", "kid", "baby", "doctor", "patient", "clinic", "surgery", "pain", "injury")),
            (("blood", "bloody"), ("clinic", "surgery", "doctor", "patient")),
        ),
    ),
    "mystery_stories": GenreIntentProfile(
        positive_terms=("mystery", "clue", "evidence", "detective", "shadow", "envelope", "locked", "noir", "puzzle"),
        negative_terms=_BASE_NEGATIVE + ("cute", "party", "beach", "gym", "wedding", "medical", "cartoon"),
        required_context=("mystery", "clue"),
        query_expansions=("cinematic mystery", "detective clue", "moody lighting"),
        rewrites=(
            (("phone", "voicemail", "message"), "phone voicemail screen mystery clue"),
            (("envelope", "letter"), "sealed envelope on table mystery clue"),
            (("note",), "handwritten note on dark table mystery clue"),
            (("key",), "old key on table mystery clue"),
            (("door", "doorway"), "locked door dim hallway mystery"),
            (("camera", "photo"), "old photograph evidence mystery"),
        ),
        reject_rules=((("voicemail", "message", "phone"), ("party", "selfie", "smiling", "beach")),),
    ),
    "history_facts": GenreIntentProfile(
        positive_terms=("historic", "ancient", "museum", "archive", "archaeological", "ruins", "documentary", "artifact", "stone", "old map"),
        negative_terms=_BASE_NEGATIVE + ("modern business", "office", "selfie", "gym", "fashion", "cartoon", "cute"),
        required_context=("historic", "documentary"),
        query_expansions=("museum artifact", "archival documentary", "ancient ruins"),
        rewrites=(
            (("roman", "rome", "empire"), "roman ruins ancient history documentary"),
            (("road", "street", "traffic"), "ancient stone road historic documentary"),
            (("map",), "old historical map archive documentary"),
            (("battle", "war"), "historic battlefield monument documentary"),
            (("king", "queen", "crown", "emperor"), "ancient statue museum artifact"),
            (("ship",), "historic sailing ship museum documentary"),
        ),
        reject_rules=((("ancient", "historic", "roman"), ("office", "business", "gym", "fashion", "selfie")),),
    ),
    "science_facts": GenreIntentProfile(
        positive_terms=("science", "laboratory", "microscope", "research", "molecule", "space", "data", "macro", "experiment", "neuron"),
        negative_terms=_BASE_NEGATIVE + ("business", "office", "marketing", "fashion", "selfie", "party", "cute"),
        required_context=("science", "laboratory"),
        query_expansions=("scientific macro", "research laboratory", "educational science"),
        rewrites=(
            (("brain", "neuron", "nervous"), "human brain neuron model science laboratory"),
            (("cell", "cells", "bacteria", "microbe"), "microscope cells science laboratory"),
            (("dna", "gene", "genetic"), "dna helix molecular science"),
            (("space", "planet", "star", "galaxy"), "planet space astronomy science"),
            (("experiment", "chemical", "chemistry"), "laboratory experiment science glassware"),
            (("robot", "ai", "machine"), "robotics laboratory technology science"),
        ),
        reject_rules=((("brain", "neuron", "cell", "dna"), ("business", "office", "fashion", "party", "selfie")),),
    ),
    "reddit_stories": GenreIntentProfile(
        positive_terms=("realistic", "conversation", "living room", "kitchen", "phone", "message", "family", "argument", "document", "dramatic"),
        negative_terms=_BASE_NEGATIVE + ("horror", "monster", "blood", "ancient", "laboratory", "cartoon", "fantasy"),
        required_context=("realistic", "conversation"),
        query_expansions=("realistic drama", "tense conversation", "everyday home"),
        rewrites=(
            (("phone", "message", "text"), "phone message screen realistic drama"),
            (("father", "mother", "family", "daughter", "son"), "tense family conversation living room"),
            (("boyfriend", "girlfriend", "partner"), "young couple tense conversation living room"),
            (("money", "debt", "bank", "bill"), "bank papers kitchen table realistic drama"),
            (("office", "job", "boss", "coworker"), "tense office conversation desk"),
            (("neighbor", "landlord", "tenant"), "apartment hallway neighbor conversation"),
        ),
        reject_rules=((("family", "conversation", "message"), ("horror", "blood", "monster", "ancient", "laboratory")),),
    ),
    "relationship_stories": GenreIntentProfile(
        positive_terms=("couple", "conversation", "living room", "phone", "message", "family", "argument", "realistic", "emotional", "kitchen"),
        negative_terms=_BASE_NEGATIVE + ("horror", "monster", "blood", "ancient", "laboratory", "cartoon", "fantasy"),
        required_context=("realistic", "relationship"),
        query_expansions=("relationship drama", "tense conversation", "home interior"),
        rewrites=(
            (("phone", "message", "text"), "phone message screen relationship drama"),
            (("boyfriend", "girlfriend", "partner", "couple"), "couple tense conversation living room"),
            (("wedding", "marriage", "husband", "wife"), "married couple tense kitchen conversation"),
            (("family", "father", "mother"), "family relationship conversation living room"),
            (("letter", "note"), "relationship note on kitchen table"),
        ),
        reject_rules=((("couple", "relationship", "message"), ("horror", "blood", "monster", "ancient", "laboratory")),),
    ),
    "motivational_stories": GenreIntentProfile(
        positive_terms=("determined", "training", "sunrise", "gym", "runner", "mountain", "work", "goal", "focus", "success", "study"),
        negative_terms=_BASE_NEGATIVE + ("horror", "blood", "medical", "ancient", "monster", "party", "fashion"),
        required_context=("motivational", "determined"),
        query_expansions=("cinematic motivation", "focused effort", "goal achievement"),
        rewrites=(
            (("failure", "failed", "struggle"), "determined person working late motivational"),
            (("student", "exam", "study"), "student studying desk determined motivation"),
            (("gym", "workout", "training"), "athlete training gym cinematic motivation"),
            (("run", "runner", "race"), "runner training sunrise motivation"),
            (("mountain", "climb"), "person climbing mountain sunrise motivation"),
            (("success", "goal", "win"), "person reaching goal sunrise motivation"),
        ),
        reject_rules=((("motivation", "determined", "goal"), ("horror", "blood", "monster", "ancient", "medical")),),
    ),
}

_ALIASES = {
    "relationship": "relationship_stories",
    "motivational": "motivational_stories",
    "science": "science_facts",
    "history": "history_facts",
    "mystery": "mystery_stories",
    "scary": "scary_stories",
    "reddit": "reddit_stories",
}


def build_asset_intent(
    cue: ImageCue,
    genre: GenreConfig,
    asset_intent_profile: GenreIntentProfile | dict[str, Any] | None = None,
) -> AssetIntent:
    return build_asset_intent_from_profile(cue, genre, asset_intent_profile)


def build_asset_intent_from_profile(
    cue: ImageCue,
    genre: GenreConfig,
    asset_intent_profile: GenreIntentProfile | dict[str, Any] | None = None,
) -> AssetIntent:
    genre_id = _canonical_genre_id(genre)
    profile = _profile_for(genre, asset_intent_profile)
    text = _normalize(f"{cue.keyword} {cue.mood}")
    allow_child = any(_term_present(term, text) for term in _CHILD_TERMS | {"daughter", "son"})
    negative_terms = (
        tuple(term for term in profile.negative_terms if term not in _CHILD_TERMS)
        if allow_child
        else profile.negative_terms
    )
    return AssetIntent(
        genre_id=genre_id,
        mood=cue.mood,
        positive_terms=profile.positive_terms + _mood_positive_terms(cue.mood),
        negative_terms=negative_terms,
        required_context=profile.required_context,
        query_expansions=profile.query_expansions,
        reject_rules=profile.reject_rules,
        allow_child=allow_child,
    )


def specific_rewrite_for_intent(
    keyword: str,
    genre: GenreConfig,
    asset_intent_profile: GenreIntentProfile | dict[str, Any] | None = None,
) -> str:
    text = _normalize(keyword)
    profile = _profile_for(genre, asset_intent_profile)
    for triggers, replacement in profile.rewrites:
        if any(_term_present(trigger, text) for trigger in triggers):
            return replacement
    return ""


def rewrite_query_for_intent(
    keyword: str,
    genre: GenreConfig,
    mood: str = "neutral",
    asset_intent_profile: GenreIntentProfile | dict[str, Any] | None = None,
) -> str:
    specific = specific_rewrite_for_intent(keyword, genre, asset_intent_profile)
    if specific:
        return specific
    profile = _profile_for(genre, asset_intent_profile)
    words = _important_words(_normalize(keyword))
    base = " ".join(words[:5]) or _fallback_subject_for(genre)
    context = " ".join(profile.required_context[:2])
    if context and not any(_term_present(term, _normalize(base)) for term in profile.required_context):
        base = f"{base} {context}"
    return _clean_query(base)


def expand_query_for_intent(query: str, intent: AssetIntent) -> list[str]:
    base = _clean_query(query)
    variants = [base]
    variants.extend(_clean_query(f"{base} {expansion}") for expansion in intent.query_expansions[:3])
    if intent.required_context:
        variants.append(_clean_query(f"{base} {' '.join(intent.required_context[:2])}"))
    return _dedupe(variants)


def score_intent_alignment(result: object, query: str, intent: AssetIntent) -> int:
    haystack = _normalize(
        " ".join(
            [
                str(getattr(result, "url", "")),
                str(getattr(result, "description", "")),
            ]
        )
    )
    score = 0
    for term in intent.positive_terms:
        if _term_present(term, haystack):
            score += 12
    for term in intent.negative_terms:
        if _term_present(term, haystack):
            score -= 45
    for triggers, bad_terms in intent.reject_rules:
        if any(_term_present(trigger, _normalize(query)) for trigger in triggers):
            if any(_term_present(term, haystack) for term in bad_terms):
                score -= 85
    if any(_term_present(term, haystack) for term in intent.required_context):
        score += 18
    return score


def reject_for_intent(result: object, query: str, intent: AssetIntent) -> bool:
    haystack = _normalize(f"{getattr(result, 'url', '')} {getattr(result, 'description', '')}")
    normalized_query = _normalize(query)
    for triggers, bad_terms in intent.reject_rules:
        if any(_term_present(trigger, normalized_query) for trigger in triggers):
            if any(_term_present(term, haystack) for term in bad_terms):
                return True
    return False


def profile_from_mapping(data: dict[str, Any], genre: GenreConfig | None = None) -> GenreIntentProfile:
    fallback = infer_genre_intent_profile(genre) if genre else GenreIntentProfile(
        positive_terms=("cinematic", "realistic", "relevant"),
        negative_terms=_BASE_NEGATIVE,
        required_context=("cinematic",),
        query_expansions=("relevant scene", "clear subject"),
    )
    return GenreIntentProfile(
        positive_terms=_clean_terms(data.get("positive_terms"), fallback.positive_terms, max_items=14),
        negative_terms=_clean_terms(data.get("negative_terms"), fallback.negative_terms, max_items=14),
        required_context=_clean_terms(data.get("required_context"), fallback.required_context, max_items=5),
        query_expansions=_clean_terms(data.get("query_expansions"), fallback.query_expansions, max_items=8),
        rewrites=_clean_rewrites(data.get("rewrites"), fallback.rewrites),
        reject_rules=_clean_reject_rules(data.get("reject_rules"), fallback.reject_rules),
    )


def profile_to_dict(profile: GenreIntentProfile | dict[str, Any] | None, genre: GenreConfig | None = None) -> dict[str, Any]:
    resolved = _profile_for(genre, profile) if genre else _coerce_profile(profile)
    if resolved is None:
        resolved = infer_genre_intent_profile(None)
    return {
        "positive_terms": list(resolved.positive_terms),
        "negative_terms": list(resolved.negative_terms),
        "required_context": list(resolved.required_context),
        "query_expansions": list(resolved.query_expansions),
        "rewrites": [
            {"triggers": list(triggers), "replacement": replacement}
            for triggers, replacement in resolved.rewrites
        ],
        "reject_rules": [
            {"triggers": list(triggers), "bad_terms": list(bad_terms)}
            for triggers, bad_terms in resolved.reject_rules
        ],
    }


def infer_genre_intent_profile(genre: GenreConfig | None) -> GenreIntentProfile:
    if not genre:
        return GenreIntentProfile(
            positive_terms=("cinematic", "realistic", "relevant"),
            negative_terms=_BASE_NEGATIVE,
            required_context=("cinematic",),
            query_expansions=("relevant scene", "clear subject"),
        )
    genre_id = _canonical_genre_id(genre)
    if genre_id in _PROFILES:
        return _PROFILES[genre_id]
    display = _normalize(f"{getattr(genre, 'display_name', '')} {getattr(genre, 'tone', '')} {' '.join(getattr(genre, 'hook_patterns', []) or [])}")
    for alias, canonical in _ALIASES.items():
        if _term_present(alias, display):
            return _PROFILES[canonical]

    words = _important_words(display)
    positive = tuple(_dedupe_terms([*words[:8], "cinematic", "relevant"]))
    required = tuple(_dedupe_terms(words[:3] or ["cinematic"]))
    expansions = tuple(
        _clean_query(f"{' '.join(words[:3])} {suffix}".strip())
        for suffix in ("clear subject", "relevant scene", "cinematic detail")
    )
    return GenreIntentProfile(
        positive_terms=positive or ("cinematic", "relevant"),
        negative_terms=_BASE_NEGATIVE,
        required_context=required or ("cinematic",),
        query_expansions=tuple(item for item in expansions if item),
    )


def _profile_for(
    genre: GenreConfig | None,
    asset_intent_profile: GenreIntentProfile | dict[str, Any] | None = None,
) -> GenreIntentProfile:
    provided = _coerce_profile(asset_intent_profile, genre)
    if provided:
        return provided
    if not genre:
        return infer_genre_intent_profile(None)
    genre_id = _canonical_genre_id(genre)
    if genre_id in _PROFILES:
        return _PROFILES[genre_id]
    return infer_genre_intent_profile(genre)


def _coerce_profile(
    profile: GenreIntentProfile | dict[str, Any] | None,
    genre: GenreConfig | None = None,
) -> GenreIntentProfile | None:
    if isinstance(profile, GenreIntentProfile):
        return profile
    if isinstance(profile, dict) and profile:
        return profile_from_mapping(profile, genre)
    return None


def _canonical_genre_id(genre: GenreConfig) -> str:
    raw = str(getattr(genre, "genre_id", "") or "").strip().lower()
    return _ALIASES.get(raw, raw)


def _fallback_subject_for(genre: GenreConfig) -> str:
    genre_id = _canonical_genre_id(genre)
    return {
        "scary_stories": "dark room object",
        "mystery_stories": "mystery clue table",
        "history_facts": "historic artifact museum",
        "science_facts": "science laboratory object",
        "reddit_stories": "realistic conversation room",
        "relationship_stories": "relationship conversation room",
        "motivational_stories": "determined person training",
    }.get(genre_id, "cinematic relevant scene")


def _mood_positive_terms(mood: str) -> tuple[str, ...]:
    text = _normalize(mood)
    if _term_present("reveal", text):
        return ("reveal", "clue", "dramatic")
    if _term_present("dark", text) or _term_present("eerie", text):
        return ("dark", "eerie")
    if _term_present("dramatic", text):
        return ("dramatic", "cinematic")
    return ()


def _important_words(text: str) -> list[str]:
    blocked = {
        "feeling",
        "emotion",
        "moment",
        "thing",
        "scary",
        "eerie",
        "dramatic",
        "cinematic",
        "photo",
        "image",
        "video",
        "stock",
        "vertical",
        "realistic",
        "relevant",
    }
    words: list[str] = []
    for raw in text.split():
        word = re.sub(r"[^a-z0-9]", "", raw)
        if len(word) < 3 or word in blocked:
            continue
        words.append(word)
    return words


def _clean_terms(value: Any, fallback: tuple[str, ...], max_items: int) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return fallback
    terms = _dedupe_terms(str(item).strip().lower() for item in value if str(item).strip())
    return tuple(terms[:max_items]) or fallback


def _clean_rewrites(value: Any, fallback: tuple[tuple[tuple[str, ...], str], ...]) -> tuple[tuple[tuple[str, ...], str], ...]:
    if not isinstance(value, (list, tuple)):
        return fallback
    rewrites: list[tuple[tuple[str, ...], str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        triggers = _clean_terms(item.get("triggers"), (), max_items=5)
        replacement = _clean_query(str(item.get("replacement") or ""))[:120]
        if triggers and replacement:
            rewrites.append((triggers, replacement))
        if len(rewrites) >= 12:
            break
    return tuple(rewrites) or fallback


def _clean_reject_rules(value: Any, fallback: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]) -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
    if not isinstance(value, (list, tuple)):
        return fallback
    rules: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        triggers = _clean_terms(item.get("triggers"), (), max_items=5)
        bad_terms = _clean_terms(item.get("bad_terms") or item.get("negative_terms"), (), max_items=8)
        if triggers and bad_terms:
            rules.append((triggers, bad_terms))
        if len(rules) >= 10:
            break
    return tuple(rules) or fallback


def _dedupe_terms(values) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        term = _clean_query(str(value or "").lower())
        if not term or term in seen:
            continue
        terms.append(term)
        seen.add(term)
    return terms


def _term_present(term: str, haystack: str) -> bool:
    normalized = _normalize(term).strip()
    if not normalized:
        return False
    if " " in normalized:
        return normalized in haystack
    return bool(re.search(rf"\b{re.escape(normalized)}\b", haystack))


def _clean_query(query: str) -> str:
    return re.sub(r"\s+", " ", str(query or "")).strip()


def _normalize(text: str) -> str:
    return f" {re.sub(r'[^a-z0-9 ]', ' ', str(text or '').lower())} "


def _dedupe(queries: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for query in queries:
        normalized = _clean_query(query)
        key = normalized.lower()
        if normalized and key not in seen:
            cleaned.append(normalized)
            seen.add(key)
    return cleaned
