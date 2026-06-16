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
from app.schemas import GenreConfig, GrowthContext, ImageCue, ResearchOutput, ScriptOutput, SfxCue
from modules.scripts.structure import polish_script_ending, validate_narrative_structure


def build_user_prompt(
    topic: str,
    genre: GenreConfig,
    duration: int,
    reference_scripts: list[dict[str, Any]],
    user_notes: str = "",
    growth_context: GrowthContext | dict[str, Any] | None = None,
) -> str:
    payload = {
        "topic": topic,
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
        "user_notes": user_notes or "",
        "research": _compact_research(growth_context),
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
    growth_context: GrowthContext | dict[str, Any] | None = None,
) -> ScriptOutput:
    if not provider:
        raise RuntimeError("No online LLM provider configured")
    user_prompt = build_user_prompt(topic, genre, duration, reference_scripts, user_notes, growth_context)
    research = _compact_research(growth_context)
    last_error = ""
    for attempt in range(1, 4):
        data = provider.generate_json(SYSTEM_PROMPT, user_prompt + _retry_note(attempt, last_error), MAX_OUTPUT_TOKENS)
        script = script_from_mapping(data, provider=getattr(provider, "name", "online"))
        script = _repair_script(script, genre, research)
        issues = validate_script_grounding(script, research) + validate_narrative_structure(script.narration)
        issues += validate_image_cues(script.image_cues)
        if not issues:
            return script
        last_error = "; ".join(issues)
    raise RuntimeError(f"script JSON failed strict validation after 3 attempts: {last_error}")


def script_from_mapping(data: dict[str, Any], provider: str) -> ScriptOutput:
    cues = [
        ImageCue(
            keyword=_concrete_image_query(str(item.get("keyword") or item.get("image_keyword") or "")),
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
    return ScriptOutput(
        title=str(data.get("title") or "Untitled Short")[:60],
        narration=narration,
        hook_line=str(data.get("hook_line") or _first_sentence(narration)),
        word_count=len(_words(narration)),
        estimated_duration=int(data.get("estimated_duration") or 45),
        description=str(data.get("description") or ""),
        hashtags=[str(x) for x in data.get("hashtags", ["#shorts"])],
        image_cues=cues,
        sfx_cues=sfx,
        emphasis_words=[str(x) for x in data.get("emphasis_words", [])],
        provider=provider,
    )


def validate_script_grounding(script: ScriptOutput, research: dict[str, Any]) -> list[str]:
    anchors = _usable_grounding_anchors(research)
    if not anchors:
        return []
    narration = script.narration.lower()
    if any(anchor.lower() in narration for anchor in anchors):
        return []
    examples = ", ".join(anchors[:3])
    return [f"script is not grounded in the external research. Mention or clearly use one real anchor such as: {examples}"]


def validate_image_cues(cues: list[ImageCue]) -> list[str]:
    issues: list[str] = []
    if len(cues) < 5:
        issues.append("script JSON needs at least 5 concrete image_cues")
    for index, cue in enumerate(cues):
        words = [w for w in re.findall(r"[a-z0-9]+", cue.keyword.lower()) if len(w) > 2]
        if len(words) < 3:
            issues.append(f"script JSON image_cues[{index}].keyword is too short; use concrete subject + object + setting stock-search words")
        if any(word in cue.keyword.lower() for word in ("fear", "dread", "emotion", "shock", "mystery", "truth")):
            issues.append(f"script JSON image_cues[{index}].keyword is too abstract; use concrete subject + object + setting stock-search words")
    return issues


def _repair_script(script: ScriptOutput, genre: GenreConfig, research: dict[str, Any]) -> ScriptOutput:
    script.narration = polish_script_ending(script.narration, genre.genre_id)
    script.word_count = len(_words(script.narration))
    if not script.hook_line or script.hook_line not in script.narration:
        script.hook_line = _first_sentence(script.narration)
    while len(script.image_cues) < 5:
        script.image_cues.append(ImageCue(keyword=_fallback_visual_keyword(script, len(script.image_cues)), timestamp_hint=f"word_{len(script.image_cues) * 15}", mood="neutral"))
    return script


def _compact_research(growth_context: GrowthContext | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(growth_context, GrowthContext):
        research = growth_context.research
        discovery = growth_context.topic_discovery
        return {
            "selected_topic": getattr(discovery, "selected_topic", ""),
            "selected_angle": getattr(discovery, "selected_angle", ""),
            "grounding_plan": getattr(discovery, "grounding_plan", {}),
            "brief": getattr(research, "brief", ""),
            "facts": getattr(research, "facts", [])[:6],
            "source_snippets": [
                {"title": item.title, "url": item.url, "snippet": item.snippet, "source": item.source}
                for item in getattr(research, "source_snippets", [])[:5]
            ],
        }
    if isinstance(growth_context, dict):
        return growth_context
    return {}


def _usable_grounding_anchors(research: dict[str, Any]) -> list[str]:
    anchors: list[str] = []
    for source in research.get("source_snippets", []) or []:
        title = str(source.get("title") or "").strip()
        if title and not title.lower().startswith("list of"):
            anchors.extend(_anchor_phrases(title))
    for fact in research.get("facts", []) or []:
        anchors.extend(_anchor_phrases(str(fact)))
    return _dedupe([anchor for anchor in anchors if len(anchor.split()) <= 5])[:8]


def _anchor_phrases(text: str) -> list[str]:
    phrases = re.findall(r"\b[A-Z][A-Za-z0-9'_-]+(?:\s+[A-Z][A-Za-z0-9'_-]+){0,4}\b", text)
    if not phrases:
        words = [w for w in re.findall(r"[a-z0-9]{4,}", text.lower()) if w not in {"this", "that", "with", "from", "have", "been", "were"}]
        phrases = [" ".join(words[:3])] if words else []
    return [p.strip() for p in phrases if p.strip()]


def _concrete_image_query(keyword: str) -> str:
    text = re.sub(r"\b(feeling|emotion|fear|dread|shock|truth|mystery|scary|dramatic|cinematic)\b", " ", keyword.lower())
    text = " ".join(text.split())
    words = re.findall(r"[a-z0-9]+", text)
    if len([w for w in words if len(w) > 2]) >= 3:
        return text[:90]
    return f"{text} person room scene".strip()[:90]


def _fallback_visual_keyword(script: ScriptOutput, index: int) -> str:
    nouns = [w.lower() for w in re.findall(r"[A-Za-z0-9]{4,}", script.narration) if w.lower() not in {"that", "with", "from", "were", "this"}]
    focus = " ".join(nouns[index * 2 : index * 2 + 3]) or "person room scene"
    return f"{focus} real location detail"


def _retry_note(attempt: int, last_error: str) -> str:
    if attempt == 1 or not last_error:
        return ""
    return f"\n\nREPAIR REQUIRED FROM PREVIOUS ATTEMPT:\n{last_error}\nReturn corrected JSON only."


def _words(text: str) -> list[str]:
    return [w for w in text.split() if w.strip()]


def _first_sentence(text: str) -> str:
    match = re.match(r"(.+?[.!?])(?:\s|$)", text.strip())
    return match.group(1) if match else text.strip()


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    output = []
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            output.append(item)
    return output
