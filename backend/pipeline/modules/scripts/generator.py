from __future__ import annotations

import json
import re
from typing import Any

from agents.prompts.script_prompts import (
    MAX_OUTPUT_TOKENS,
    SYSTEM_PROMPT,
    messages_with_user,
    render_messages_for_single_prompt,
)
from app.schemas import GenreConfig, ImageCue, ScriptOutput, SfxCue
from modules.llm.strict_json import generate_strict_json
from modules.safety.guardrails import redact_secrets, validate_generated_text, validate_video_topic
from modules.scripts.structure import parse_script_sections


def build_user_prompt(
    topic: str,
    genre: GenreConfig,
    duration: int,
    reference_scripts: list[dict[str, Any]],
    user_notes: str = "",
    growth_context: dict[str, Any] | None = None,
) -> str:
    """Build the script prompt.

    Budget: max input 6000 chars, max output 4096 tokens.
    """
    validate_video_topic(topic)
    payload = {
        "topic": redact_secrets(topic),
        "genre": {
            "genre_id": genre.genre_id,
            "display_name": genre.display_name,
            "tone": genre.tone,
            "layout": genre.layout,
            "caption_preset": genre.caption_preset,
            "word_count_min": genre.word_count_min,
            "word_count_max": genre.word_count_max,
            "banned_phrases": genre.banned_phrases,
        },
        "duration": duration,
        "reference_scripts": reference_scripts[:2],
        "user_notes": redact_secrets(user_notes or ""),
        "growth_context": _compact_growth_context(growth_context or {}),
    }
    messages = messages_with_user(json.dumps(payload, indent=2, ensure_ascii=True))
    return render_messages_for_single_prompt(messages)


def generate_script(
    provider,
    topic: str,
    genre: GenreConfig,
    duration: int,
    reference_scripts: list[dict[str, Any]],
    user_notes: str = "",
    growth_context: dict[str, Any] | None = None,
) -> ScriptOutput:
    """Generate a script with the configured online LLM provider."""
    if not provider:
        raise RuntimeError("No online LLM provider configured")
    user_prompt = build_user_prompt(topic, genre, duration, reference_scripts, user_notes, growth_context)
    compact_context = _compact_growth_context(growth_context or {})

    def validate(data: dict[str, Any]) -> None:
        validate_script_json_shape(data)
        validate_script_grounding(data, genre, compact_context)

    data = generate_strict_json(
        provider,
        SYSTEM_PROMPT,
        user_prompt,
        MAX_OUTPUT_TOKENS,
        schema_name="script",
        validate=validate,
        attempts=3,
    )
    return script_from_mapping(data, provider=getattr(provider, "name", "online"), requested_duration=duration)


def validate_script_json_shape(data: dict[str, Any]) -> None:
    """Validate the minimum JSON shape needed to build a script plan."""
    required = [
        "title",
        "narration",
        "hook_line",
        "word_count",
        "estimated_duration",
        "description",
        "hashtags",
        "script_sections",
        "image_cues",
        "sfx_cues",
        "emphasis_words",
    ]
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(f"script JSON is missing required keys: {', '.join(missing)}")

    if not isinstance(data["title"], str) or not data["title"].strip():
        raise ValueError("script JSON title must be a non-empty string")
    if not isinstance(data["narration"], str) or not data["narration"].strip():
        raise ValueError("script JSON narration must be a non-empty string")
    if not isinstance(data["hook_line"], str) or not data["hook_line"].strip():
        raise ValueError("script JSON hook_line must be a non-empty string")
    if not isinstance(data["hashtags"], list):
        raise ValueError("script JSON hashtags must be an array")
    if not isinstance(data["script_sections"], list):
        raise ValueError("script JSON script_sections must be an array")
    if not isinstance(data["image_cues"], list):
        raise ValueError("script JSON image_cues must be an array")
    if not isinstance(data["sfx_cues"], list):
        raise ValueError("script JSON sfx_cues must be an array")
    if not isinstance(data["emphasis_words"], list):
        raise ValueError("script JSON emphasis_words must be an array")

    for index, cue in enumerate(data["image_cues"]):
        if not isinstance(cue, dict):
            raise ValueError(f"script JSON image_cues[{index}] must be an object")
        keyword = str(cue.get("keyword") or "").strip()
        if not keyword:
            raise ValueError(f"script JSON image_cues[{index}].keyword is required")
        if _is_abstract_image_query(keyword):
            repaired = _concrete_image_query(keyword, data)
            if repaired and not _is_abstract_image_query(repaired):
                cue["keyword"] = repaired
            else:
                raise ValueError(
                    f"script JSON image_cues[{index}].keyword is too abstract; "
                    "use concrete subject + object + setting stock-search words"
                )
    section_names: set[str] = set()
    for index, section in enumerate(data["script_sections"]):
        if not isinstance(section, dict):
            raise ValueError(f"script JSON script_sections[{index}] must be an object")
        name = str(section.get("name") or "").strip().lower()
        text = str(section.get("narration") or "").strip()
        purpose = str(section.get("purpose") or "").strip()
        if name not in {"header", "mid", "footer"}:
            raise ValueError(f"script JSON script_sections[{index}].name must be header, mid, or footer")
        if not text:
            raise ValueError(f"script JSON script_sections[{index}].narration is required")
        if not purpose:
            raise ValueError(f"script JSON script_sections[{index}].purpose is required")
        section_names.add(name)
    missing_sections = [name for name in ("header", "mid", "footer") if name not in section_names]
    if missing_sections:
        raise ValueError(f"script JSON script_sections missing: {', '.join(missing_sections)}")


def validate_script_grounding(data: dict[str, Any], genre: GenreConfig, growth_context: dict[str, Any]) -> None:
    if genre.genre_id.lower() not in {"scary_stories", "mystery_stories", "history_facts", "science_facts"}:
        return
    narration = str(data.get("narration") or "")
    title = str(data.get("title") or "")
    text = f"{title} {narration}".lower()
    grounding_plan = growth_context.get("grounding_plan") if isinstance(growth_context.get("grounding_plan"), dict) else {}
    plan_issue = _grounding_plan_issue(text, grounding_plan)
    if plan_issue:
        raise ValueError(plan_issue)
    visual_style = growth_context.get("visual_style") if isinstance(growth_context.get("visual_style"), dict) else {}
    if visual_style.get("mode") == "illustration":
        return
    if growth_context.get("grounding_status") != "external_sources_found":
        if _looks_like_unanchored_specific_claim(text):
            raise ValueError(
                "script invented a generic incident without a real research anchor. "
                "Use a named real place/case/source from research, or ask for a more specific source."
            )
        return
    anchors = [str(item) for item in growth_context.get("grounding_anchors", []) if _usable_grounding_anchor(str(item))]
    for source in growth_context.get("source_snippets", []):
        title = str(source.get("title") or "") if isinstance(source, dict) else ""
        if isinstance(source, dict) and source.get("url") and _usable_grounding_anchor(title):
            anchors.append(title)
    anchor_terms = _grounding_anchor_terms(anchors)
    if not anchor_terms:
        return
    if any(term in text for term in anchor_terms):
        return
    sample = ", ".join(anchor_terms[:5])
    raise ValueError(
        "script is not grounded in the external research. "
        f"Mention or clearly use one real anchor from the provided sources, such as: {sample}"
    )


def _grounding_plan_issue(text: str, grounding_plan: dict[str, Any]) -> str:
    excluded = [str(item).strip().lower() for item in grounding_plan.get("excluded_terms", []) if str(item).strip()]
    if any(term in text for term in excluded):
        return "script used a source/category that the grounding plan excluded. Use only relevant real-world anchors."
    required_terms = _terms_from_items(grounding_plan.get("required_terms", []))
    if not required_terms:
        return ""
    text_terms = set(re.findall(r"[a-z0-9]{3,}", text))
    hits = set(required_terms) & text_terms
    required_min = 1 if len(required_terms) <= 2 else 2
    if len(hits) < required_min:
        return "script drifted away from the user's topic terms. Keep the narration tied to the grounding plan."
    return ""


def _looks_like_unanchored_specific_claim(text: str) -> bool:
    claim_words = ("reported", "records show", "police", "witness", "newspaper", "locals say", "case", "incident")
    concrete_detail_words = ("school", "hospital", "hotel", "room", "hallway", "house", "door", "photo", "video")
    has_claim = any(item in text for item in claim_words)
    has_detail = any(item in text for item in concrete_detail_words)
    return has_claim and has_detail


def _grounding_anchor_terms(anchors: list[str]) -> list[str]:
    terms: list[str] = []
    blocked = {
        "the", "and", "for", "with", "from", "that", "this", "list",
        "reported", "haunted", "locations", "story", "stories", "facts",
    }
    for anchor in anchors:
        clean = re.sub(r"[^A-Za-z0-9 ]+", " ", anchor).strip()
        if not clean:
            continue
        lowered = " ".join(clean.lower().split())
        words = [word for word in lowered.split() if len(word) > 2 and word not in blocked]
        if len(words) >= 2:
            terms.append(" ".join(words[:3]))
            terms.append(" ".join(words[-2:]))
        elif words:
            terms.append(words[0])
    return list(dict.fromkeys(term for term in terms if len(term) >= 4))


def _usable_grounding_anchor(anchor: str) -> bool:
    text = f" {re.sub(r'[^a-z0-9 ]', ' ', str(anchor).lower())} "
    blocked = (
        " marvel ", " comics ", " comic ", " stock ", " character ", " characters ",
        " fictional ", " superhero ", " superheroes ", " teams organizations ",
        " fandom ", " wiki ", " movie ", " film ", " television ", " anime ",
    )
    words = [word for word in text.split() if len(word) > 2]
    return bool(words) and not any(term in text for term in blocked)


def _terms_from_items(items: Any) -> list[str]:
    terms: list[str] = []
    for item in items or []:
        terms.extend(re.findall(r"[a-z0-9]{3,}", str(item).lower()))
    blocked = {"the", "and", "for", "with", "from", "that", "this", "real", "story", "stories"}
    return [term for term in dict.fromkeys(terms) if term not in blocked]


def _compact_growth_context(growth_context: dict[str, Any]) -> dict[str, Any]:
    """Keep free research context useful without blowing up the script prompt."""
    if not growth_context:
        return {}
    compact = {
        "selected_topic": str(growth_context.get("selected_topic") or "")[:220],
        "selected_angle": str(growth_context.get("selected_angle") or "")[:180],
        "research_brief": str(growth_context.get("research_brief") or "")[:1200],
        "grounding_plan": {},
        "grounding_status": str(growth_context.get("grounding_status") or "")[:80],
        "grounding_anchors": [str(item)[:160] for item in growth_context.get("grounding_anchors", [])[:5] if _usable_grounding_anchor(str(item))],
        "thumbnail_hints": [str(item)[:80] for item in growth_context.get("thumbnail_hints", [])[:6]],
        "title_hints": [str(item)[:80] for item in growth_context.get("title_hints", [])[:8]],
        "visual_style": {},
        "candidate_topics": [],
        "source_snippets": [],
        "niche_profile": {},
    }
    for item in growth_context.get("candidate_topics", [])[:5]:
        if isinstance(item, dict):
            compact["candidate_topics"].append(
                {
                    "topic": str(item.get("topic") or "")[:160],
                    "angle": str(item.get("angle") or "")[:120],
                    "hook": str(item.get("hook") or "")[:180],
                    "source": str(item.get("source") or "")[:40],
                }
            )
    for item in growth_context.get("source_snippets", [])[:4]:
        if isinstance(item, dict):
            compact["source_snippets"].append(
                {
                    "title": str(item.get("title") or "")[:120],
                    "snippet": str(item.get("snippet") or "")[:240],
                    "source": str(item.get("source") or "")[:40],
                    "url": str(item.get("url") or "")[:220],
                }
            )
    grounding_plan = growth_context.get("grounding_plan") or {}
    if isinstance(grounding_plan, dict):
        compact["grounding_plan"] = {
            "required_terms": [str(item)[:80] for item in grounding_plan.get("required_terms", [])[:12]],
            "excluded_terms": [str(item)[:80] for item in grounding_plan.get("excluded_terms", [])[:16]],
            "grounding_note": str(grounding_plan.get("grounding_note") or "")[:240],
        }
    profile = growth_context.get("niche_profile") or {}
    if isinstance(profile, dict):
        compact["niche_profile"] = {
            "hook_templates": [str(item)[:120] for item in profile.get("hook_templates", [])[:4]],
            "tone_rules": [str(item)[:140] for item in profile.get("tone_rules", [])[:4]],
            "visual_keywords": [str(item)[:60] for item in profile.get("visual_keywords", [])[:8]],
            "hashtag_hints": [str(item)[:40] for item in profile.get("hashtag_hints", [])[:6]],
        }
    visual_style = growth_context.get("visual_style") or {}
    if isinstance(visual_style, dict):
        compact["visual_style"] = {
            "mode": str(visual_style.get("mode") or "")[:40],
            "render_style": str(visual_style.get("render_style") or "")[:40],
            "asset_strategy": str(visual_style.get("asset_strategy") or "")[:60],
            "sanitized_topic": str(visual_style.get("sanitized_topic") or "")[:220],
            "search_style_terms": [str(item)[:70] for item in visual_style.get("search_style_terms", [])[:4]],
            "blocked_terms": [str(item)[:40] for item in visual_style.get("blocked_terms", [])[:8]],
            "prompt_guidance": [str(item)[:180] for item in visual_style.get("prompt_guidance", [])[:5]],
        }
    return compact


def script_from_mapping(data: dict[str, Any], provider: str, requested_duration: int | None = None) -> ScriptOutput:
    cues = [
        ImageCue(
            keyword=str(item.get("keyword") or item.get("image_keyword") or ""),
            timestamp_hint=str(item.get("timestamp_hint") or "word_0"),
            mood=str(item.get("mood") or "neutral"),
        )
        for item in data.get("image_cues", data.get("visual_cues", []))
        if isinstance(item, dict)
    ]
    sfx = [
        SfxCue(
            trigger_word=str(item.get("trigger_word") or ""),
            sfx_type=str(item.get("sfx_type") or "soft_hit"),
            timestamp_hint=str(item.get("timestamp_hint") or "during word"),
        )
        for item in data.get("sfx_cues", data.get("sound_effects", []))
        if isinstance(item, dict)
    ]
    narration = " ".join(str(data.get("narration") or "").split())
    validate_generated_text(narration)
    estimated_duration = requested_duration or int(data.get("estimated_duration") or 30)
    cues = _ensure_image_cue_density(cues, narration, estimated_duration)
    sections = parse_script_sections(data, narration)
    return ScriptOutput(
        title=str(data.get("title") or "Untitled Short")[:60],
        narration=narration,
        hook_line=str(data.get("hook_line") or _first_sentence(narration)),
        word_count=len(_words(narration)),
        estimated_duration=estimated_duration,
        description=str(data.get("description") or ""),
        hashtags=[str(x) for x in data.get("hashtags", ["#shorts"])],
        image_cues=cues,
        sfx_cues=sfx,
        emphasis_words=[str(x) for x in data.get("emphasis_words", [])],
        script_sections=sections,
        provider=provider,
    )


def _ensure_image_cue_density(
    cues: list[ImageCue],
    narration: str,
    duration_or_target_count: int,
) -> list[ImageCue]:
    target_count = (
        duration_or_target_count
        if duration_or_target_count <= 14
        else _target_image_cue_count(duration_or_target_count)
    )
    cleaned = [cue for cue in cues if cue.keyword.strip() and not _is_abstract_image_query(cue.keyword)]
    if len(cleaned) >= target_count:
        return cleaned

    generated = _image_cues_from_narration(narration, target_count)
    seen = {_normalize_keyword(cue.keyword) for cue in cleaned}
    for cue in generated:
        key = _normalize_keyword(cue.keyword)
        if key and key not in seen:
            cleaned.append(cue)
            seen.add(key)
        if len(cleaned) >= target_count:
            break
    return cleaned


def _target_image_cue_count(duration: int) -> int:
    if duration >= 120:
        return 18
    if duration >= 90:
        return 14
    if duration >= 60:
        return 10
    if duration >= 45:
        return 8
    if duration >= 30:
        return 6
    return 6


def _image_cues_from_narration(narration: str, target_count: int) -> list[ImageCue]:
    words = _words(narration)
    if not words:
        return []
    cue_words = _visual_terms(words)
    if not cue_words:
        cue_words = ["story scene", "person room", "dark hallway", "close up object"]

    cues: list[ImageCue] = []
    step = max(1, len(words) // target_count)
    for index in range(target_count):
        start = min(index * step, max(0, len(words) - 1))
        nearby = _visual_terms(words[start : start + 10]) or cue_words
        keyword = _make_search_query(nearby, index)
        cues.append(
            ImageCue(
                keyword=keyword,
                timestamp_hint=f"word_{start}",
                mood=_mood_for_index(index, target_count),
            )
        )
    return cues


def _visual_terms(words: list[str]) -> list[str]:
    blocked = {
        "about", "after", "again", "already", "around", "because", "before",
        "being", "beside", "called", "could", "every", "first", "found",
        "from", "heard", "inside", "itself", "looked", "maybe", "never", "once",
        "opened", "other", "really", "right", "said", "still", "their",
        "there", "these", "then", "thing", "those", "through", "under", "until",
        "where", "which", "while", "would", "feeling", "feelings",
        "overwhelmed", "overwhelming", "emotion", "emotional", "pressure",
        "stress", "anxiety", "fear", "moment", "thing",
    }
    terms: list[str] = []
    for word in words:
        clean = re.sub(r"[^A-Za-z0-9]", "", word).lower()
        if len(clean) < 4 or clean in blocked:
            continue
        terms.append(clean)
    return terms[:8]


def _make_search_query(terms: list[str], index: int) -> str:
    presets = [
        "cinematic room",
        "tense hallway",
        "person close up",
        "mysterious object",
        "dark doorway",
        "dramatic street",
        "quiet bedroom",
        "serious conversation",
    ]
    selected = terms[:3]
    if len(selected) < 2:
        selected.extend(presets[index % len(presets)].split())
    return " ".join(selected[:5])


def _mood_for_index(index: int, total: int) -> str:
    if index == 0:
        return "dramatic"
    if index >= total - 2:
        return "reveal"
    return "eerie" if index % 2 else "neutral"


def _normalize_keyword(keyword: str) -> str:
    return re.sub(r"\s+", " ", keyword.strip().lower())


def _is_abstract_image_query(keyword: str) -> bool:
    text = f" {re.sub(r'[^a-z0-9 ]', ' ', keyword.lower())} "
    abstract_terms = (
        " feeling ",
        " feelings ",
        " overwhelmed ",
        " overwhelming ",
        " emotion ",
        " emotional ",
        " pressure ",
        " anxiety ",
        " fear ",
        " hopeless ",
        " moment ",
        " vibe ",
        " vibes ",
        " idea ",
    )
    if any(term in text for term in abstract_terms):
        return True
    words = [word for word in text.split() if len(word) > 2]
    return len(words) < 3


def _concrete_image_query(keyword: str, data: dict[str, Any]) -> str:
    base_words = _visual_terms(_words(f"{data.get('title') or ''} {data.get('narration') or ''}"))
    if not base_words:
        base_words = ["person", "object", "room"]
    raw = re.sub(r"[^A-Za-z0-9 ]", " ", str(keyword or "")).strip().lower()
    blocked = {"stock", "generic", "scene", "visual", "image", "moment", "characters", "character"}
    cue_words = [word for word in raw.split() if len(word) > 2 and word not in blocked]
    words = (cue_words + base_words + ["room", "closeup"])[:5]
    return " ".join(dict.fromkeys(words))


def _words(text: str) -> list[str]:
    return [w for w in text.split() if w.strip()]


def _first_sentence(text: str) -> str:
    match = re.match(r"(.+?[.!?])(?:\s|$)", text.strip())
    return match.group(1) if match else text.strip()


def _ends_complete_sentence(text: str) -> bool:
    return bool(re.search(r"[.!?][\"')\]]*$", text.strip()))
