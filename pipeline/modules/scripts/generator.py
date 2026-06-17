from __future__ import annotations

import json
import re
from typing import Any

from agents.prompts.script_prompts import (
    MAX_INPUT_CHARS,
    MAX_OUTPUT_TOKENS,
    SYSTEM_PROMPT,
    messages_with_user,
    render_messages_for_single_prompt,
)
from app.schemas import GenreConfig, GrowthContext, ImageCue, ResearchOutput, ScriptOutput, SfxCue
from modules.assets.subject_lock import apply_subject_lock_to_cues, infer_subject_lock
from modules.scripts.structure import polish_script_ending, validate_narrative_structure


def build_user_prompt(
    topic: str,
    genre: GenreConfig,
    duration: int,
    reference_scripts: list[dict[str, Any]],
    user_notes: str = "",
    growth_context: GrowthContext | dict[str, Any] | None = None,
) -> str:
    research = _filter_research_for_topic(_compact_research(growth_context), topic)
    payload = {
        "raw_request": topic,
        "topic": topic,
        "genre_id": genre.genre_id,
        "platform": "youtube_shorts",
        "duration_seconds": duration,
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
        "reference_scripts": [_compact_reference(item) for item in _select_references(topic, reference_scripts, limit=6)],
        "user_notes": user_notes or "",
        "research": research,
    }
    messages = messages_with_user(_safe_user_payload_json(payload))
    return render_messages_for_single_prompt(messages[1:])


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
        try:
            data = provider.generate_json(SYSTEM_PROMPT, user_prompt + _retry_note(attempt, last_error), MAX_OUTPUT_TOKENS)
            script = script_from_mapping(data, provider=getattr(provider, "name", "online"), topic=topic, research=research)
            script = _repair_script(script, genre, research)
            script.estimated_duration = duration
            issues = validate_script_grounding(script, research) + validate_script_relevance(script, topic) + validate_narrative_structure(script.narration)
            issues += validate_image_cues(script.image_cues)
            if script.word_count > genre.word_count_max:
                issues.append(f"script narration too long after repair: {script.word_count} > {genre.word_count_max}")
            if script.word_count < genre.word_count_min - 1:
                issues.append(f"script narration too short after repair: {script.word_count} < {genre.word_count_min}")
            if not issues:
                return script
            last_error = "; ".join(issues)
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
    raise RuntimeError(
        "script generation failed after Gemini retries. "
        f"Last Gemini error: {last_error}. "
        "Local script fallback is disabled."
    )


def script_from_mapping(
    data: dict[str, Any],
    provider: str,
    topic: str = "",
    research: dict[str, Any] | None = None,
) -> ScriptOutput:
    cues = [
        ImageCue(
            keyword=_concrete_image_query(str(item.get("keyword") or item.get("image_keyword") or "")),
            timestamp_hint=str(item.get("timestamp_hint") or "word_0"),
            mood=str(item.get("mood") or "neutral"),
            role=str(item.get("role") or "supporting_visual"),
            subject_lock=bool(item.get("subject_lock") or False),
            required_subjects=[str(x) for x in item.get("required_subjects", []) if str(x).strip()],
            aliases=[str(x) for x in item.get("aliases", []) if str(x).strip()],
            allowed_fallback_level=str(item.get("allowed_fallback_level") or "generic_scene"),
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
    subject_lock = infer_subject_lock(topic or str(data.get("title") or ""), research)
    cues = apply_subject_lock_to_cues(cues, subject_lock)
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


def _subject_narration(subject: str, opponent: str, topic: str) -> str:
    if "thor" in subject.lower():
        return (
            f"Thor does not enter this fight like a villain. He lands in front of {opponent}, "
            "with thunder rolling above the broken street. The first clash is not about anger. "
            "It is about trust breaking in the middle of a mission. A shield hits the ground. "
            "The hammer flies back into Thor's hand, and everyone stops for one second because they know what it means. "
            f"{_display_entity(opponent)} rush in together, but Thor holds back just enough to avoid hurting his friends. "
            "That is the real tension. The strongest person in the fight is also the one trying hardest not to win. "
            "In the final moment, Thor lowers the hammer and makes them choose: keep fighting him, or remember why they were a team."
        )
    if "iron man" in subject.lower() or "tony stark" in subject.lower():
        return (
            f"{subject} is not fighting {opponent} because he wants to destroy them. "
            "He is fighting because the plan has already gone wrong. The suit lights up in the smoke. "
            "A blast hits the floor, a shield cuts through the sparks, and the room turns into a test of trust. "
            f"{_display_entity(opponent)} push forward together, but every move makes the damage worse. "
            f"{subject} sees the pattern before anyone else: someone is forcing the team to attack each other. "
            "So he stops aiming at his friends and aims at the signal controlling the fight. "
            "The final shot is not a victory pose. It is the team realizing the real enemy was never in the room."
        )
    return (
        f"{subject} steps into the fight against {opponent}, but the scene is not just a loud battle. "
        "It starts with one clear mistake: the team has stopped listening to each other. "
        f"{subject} blocks the first attack, moves through the smoke, and tries to keep the fight from turning ugly. "
        "Every hit raises the stakes. Every pause shows that nobody actually wants this to continue. "
        f"When {opponent} charge in together, the fight becomes a test of control, not strength. "
        f"{subject} finally stops chasing a win and exposes the reason behind the conflict. "
        "The last beat is simple: the team can keep breaking apart, or they can remember what made them powerful together."
    )


def _subject_image_cues(subject: str, opponent: str, subject_lock) -> list[ImageCue]:
    required = [subject] if subject_lock.enabled and subject else []
    aliases = list(subject_lock.aliases) if subject_lock.enabled else []
    locked = bool(required)
    level = "subject_alias" if locked else "generic_scene"
    base = [
        (f"{subject} facing {opponent} battle street", "word_0", "dramatic", "primary_subject"),
        (f"{subject} lightning hammer close up", "word_18", "dramatic", "primary_subject"),
        (f"{opponent} team standing opposite {subject}", "word_36", "neutral", "primary_subject"),
        (f"{subject} shield sparks action scene", "word_54", "dramatic", "primary_subject"),
        (f"{subject} battle smoke final stance", "word_72", "reveal", "primary_subject"),
        (f"{subject} team conflict cinematic frame", "word_90", "neutral", "primary_subject"),
    ]
    return [
        ImageCue(
            keyword=keyword,
            timestamp_hint=timestamp,
            mood=mood,
            role=role,
            subject_lock=locked,
            required_subjects=list(required),
            aliases=list(aliases),
            allowed_fallback_level=level,
        )
        for keyword, timestamp, mood, role in base
    ]


def _subject_sfx_cues(narration: str) -> list[SfxCue]:
    lower = narration.lower()
    cues = []
    if "thunder" in lower:
        cues.append(SfxCue(trigger_word="thunder", sfx_type="thunder_hit", timestamp_hint="during thunder"))
    if "hammer" in lower:
        cues.append(SfxCue(trigger_word="hammer", sfx_type="metal_whoosh", timestamp_hint="during hammer"))
    if "shield" in lower:
        cues.append(SfxCue(trigger_word="shield", sfx_type="metal_impact", timestamp_hint="during shield"))
    return cues[:3]


def _subject_title(subject: str, opponent: str) -> str:
    if opponent and opponent != "the opposing team":
        return f"{subject} Versus {opponent.title()}"[:60]
    return f"{subject} Team Fight"[:60]


def _display_entity(value: str) -> str:
    words = str(value or "").split()
    display = []
    for index, word in enumerate(words):
        if index > 0 and word.lower() in {"the", "of"}:
            display.append(word.lower())
        else:
            display.append(word[:1].upper() + word[1:])
    return " ".join(display)


def _subject_hashtags(subject: str, opponent: str) -> list[str]:
    tags = ["#shorts", "#action"]
    for value in (subject, opponent):
        tag = re.sub(r"[^A-Za-z0-9]+", "", value.title())
        if tag and tag.lower() not in {"theopposingteam"}:
            tags.append(f"#{tag}")
    return tags[:5]


def _opponent_from_topic(topic: str, subject: str) -> str:
    lower = topic.lower()
    if "avengers" in lower and "avengers" not in subject.lower():
        return "the Avengers"
    if "team" in lower:
        return "the team"
    return "the opposing team"


def _readable_topic_subject(topic: str) -> str:
    words = [word for word in re.findall(r"[A-Za-z0-9]+", topic) if word.lower() not in {"can", "make", "video", "short", "duration", "seconds", "secons"}]
    return " ".join(words[:4]).title() or "The Main Subject"


def validate_script_grounding(script: ScriptOutput, research: dict[str, Any]) -> list[str]:
    anchors = _usable_grounding_anchors(research)
    if not anchors:
        return []
    narration = script.narration.lower()
    if any(_anchor_in_text(anchor, narration) for anchor in anchors):
        return []
    examples = ", ".join(anchors[:3])
    return [f"script is not grounded in the external research. Mention or clearly use one real anchor such as: {examples}"]


def validate_script_relevance(script: ScriptOutput, topic: str) -> list[str]:
    subject_lock = infer_subject_lock(topic)
    haystack = " ".join(
        [
            script.title,
            script.narration,
            script.description,
        ]
    ).lower()
    generic_markers = (
        "real starting point",
        "normal short video idea",
        "fake story usually hides",
        "do not invent claims",
        "one detail was simple enough to check",
    )
    if not subject_lock.enabled:
        topic_terms = _topic_relevance_terms(topic)
        if topic_terms:
            matches = sum(1 for term in topic_terms if term in haystack)
            required = 1 if len(topic_terms) == 1 else min(2, len(topic_terms))
            if matches < required:
                return [f"script ignored the requested topic; expected terms like: {', '.join(topic_terms[:4])}"]
        if any(marker in haystack for marker in generic_markers):
            return ["script used generic fallback boilerplate; rewrite around the actual user request"]
        return []
    subjects = [subject_lock.subject, *subject_lock.aliases]
    subject_present = any(str(subject).lower() in haystack for subject in subjects if str(subject).strip())
    terms = _subject_terms(subject_lock.subject)
    if subject_present or (terms and all(term in haystack for term in terms[:2])):
        subject_present = True
    else:
        subject_present = False
    if not subject_present:
        return [
            f"script ignored the requested named subject {subject_lock.subject!r}; rewrite around that subject, not a generic/reference example"
        ]
    if any(marker in haystack for marker in generic_markers):
        return [
            f"script used generic fallback boilerplate for {subject_lock.subject!r}; rewrite concrete action around that subject"
        ]
    if re.search(r"\bcan\s+u\s+make\b|\bmake\s+a\s+video\b", script.title.lower()):
        return [
            f"script title copied the user instruction instead of naming {subject_lock.subject!r}"
        ]
    return []


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
    script.narration = _ground_script_if_needed(script.narration, genre, research)
    script.word_count = len(_words(script.narration))
    script.narration = _lengthen_if_needed(script.narration, genre)
    script.word_count = len(_words(script.narration))
    script.narration = _trim_to_max_words(script.narration, genre)
    script.word_count = len(_words(script.narration))
    if not script.hook_line or script.hook_line not in script.narration:
        script.hook_line = _first_sentence(script.narration)
    while len(script.image_cues) < 5:
        subject_locked = next((cue for cue in script.image_cues if cue.subject_lock), None)
        if subject_locked:
            script.image_cues.append(
                ImageCue(
                    keyword=f"{subject_locked.required_subjects[0]} text card visual",
                    timestamp_hint=f"word_{len(script.image_cues) * 15}",
                    mood="neutral",
                    role="primary_subject",
                    subject_lock=True,
                    required_subjects=list(subject_locked.required_subjects),
                    aliases=list(subject_locked.aliases),
                    allowed_fallback_level="text_card",
                )
            )
        else:
            script.image_cues.append(ImageCue(keyword=_fallback_visual_keyword(script, len(script.image_cues)), timestamp_hint=f"word_{len(script.image_cues) * 15}", mood="neutral"))
    return script


def _trim_to_max_words(narration: str, genre: GenreConfig) -> str:
    words = _words(narration)
    if len(words) <= genre.word_count_max:
        return narration
    sentences = _script_sentences(narration)
    if len(sentences) > 1:
        kept: list[str] = []
        for sentence in sentences:
            candidate = " ".join([*kept, sentence]).strip()
            if len(_words(candidate)) <= genre.word_count_max:
                kept.append(sentence)
            elif kept:
                break
        candidate = " ".join(kept).strip()
        if candidate and len(_words(candidate)) >= genre.word_count_min - 1:
            return _ensure_complete_ending(candidate, genre)
    trimmed = " ".join(words[: genre.word_count_max]).rstrip(" ,;:")
    trimmed = re.sub(r"\s+[^.!?]*$", "", trimmed).strip() or " ".join(words[: genre.word_count_max]).rstrip(" ,;:")
    return _ensure_complete_ending(trimmed, genre)


def _ensure_complete_ending(text: str, genre: GenreConfig) -> str:
    text = text.strip()
    if re.search(r"[.!?][\"')\]]*$", text):
        return text
    closing = _short_closing_sentence(genre.genre_id)
    if len(_words(text)) + len(_words(closing)) <= genre.word_count_max:
        return f"{text}. {closing}".strip()
    return f"{text}."


def _lengthen_if_needed(narration: str, genre: GenreConfig) -> str:
    word_count = len(_words(narration))
    if word_count >= genre.word_count_min:
        return narration
    close_sentence = _short_closing_sentence(genre.genre_id)
    if word_count + len(_words(close_sentence)) <= genre.word_count_max:
        return f"{narration.rstrip()} {close_sentence}".strip()
    return narration


def _short_closing_sentence(genre_id: str) -> str:
    if genre_id in {"scary_stories", "mystery_stories"}:
        return "That small detail was the warning."
    if genre_id == "history_facts":
        return "That detail still matters today."
    return "That is the useful part."


def _ground_script_if_needed(narration: str, genre: GenreConfig, research: dict[str, Any]) -> str:
    anchors = _usable_grounding_anchors(research)
    if not anchors or not narration.strip():
        return narration
    if any(_anchor_in_text(anchor, narration.lower()) for anchor in anchors):
        return narration

    anchor = anchors[0]
    sentence = _anchor_sentence(anchor)
    if len(_words(narration)) + len(_words(sentence)) <= genre.word_count_max:
        sentences = _script_sentences(narration)
        if sentences:
            return " ".join([sentences[0], sentence, *sentences[1:]])
        return f"{sentence} {narration}".strip()

    sentences = _script_sentences(narration)
    if len(sentences) >= 2:
        candidate_sentences = list(sentences)
        candidate_sentences[1] = sentence
        candidate = " ".join(candidate_sentences)
        if len(_words(candidate)) <= genre.word_count_max:
            return candidate

    return narration


def _anchor_sentence(anchor: str) -> str:
    return f"One real anchor here is {anchor.strip()}."


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


def _filter_research_for_topic(research: dict[str, Any], topic: str) -> dict[str, Any]:
    if not isinstance(research, dict) or not research:
        return {}
    topic_terms = set(_topic_relevance_terms(topic))
    if not topic_terms:
        return {}

    def relevant_text(value: Any) -> bool:
        words = set(_keywords(str(value or "")))
        return bool(topic_terms.intersection(words))

    source_snippets = []
    for item in research.get("source_snippets", []) or []:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").lower()
        if source == "local_profile":
            continue
        text = " ".join(str(item.get(key) or "") for key in ("title", "snippet", "url"))
        if relevant_text(text):
            source_snippets.append(item)

    facts = [str(item) for item in research.get("facts", []) or [] if relevant_text(item)]
    selected_topic = str(research.get("selected_topic") or "")
    selected_angle = str(research.get("selected_angle") or "")
    brief = str(research.get("brief") or "")
    return {
        "selected_topic": selected_topic if relevant_text(selected_topic) else "",
        "selected_angle": selected_angle if relevant_text(selected_angle) else "",
        "grounding_plan": research.get("grounding_plan", {}),
        "brief": brief if relevant_text(brief) else "",
        "facts": facts[:6],
        "source_snippets": source_snippets[:5],
    }


def _safe_user_payload_json(payload: dict[str, Any]) -> str:
    text = _payload_json(payload)
    if len(text) <= MAX_INPUT_CHARS:
        return text

    for reference_limit, script_limit, fact_limit, source_limit, snippet_limit in (
        (4, 360, 5, 4, 240),
        (2, 220, 4, 3, 180),
        (1, 120, 2, 1, 140),
        (0, 0, 1, 0, 0),
    ):
        compacted = dict(payload)
        compacted["reference_scripts"] = [
            _compact_reference(item, script_limit=script_limit)
            for item in list(payload.get("reference_scripts") or [])[:reference_limit]
        ]
        compacted["research"] = _shrink_research(
            payload.get("research") if isinstance(payload.get("research"), dict) else {},
            fact_limit=fact_limit,
            source_limit=source_limit,
            snippet_limit=snippet_limit,
        )
        text = _payload_json(compacted)
        if len(text) <= MAX_INPUT_CHARS:
            return text

    minimal = {
        "raw_request": payload.get("raw_request", ""),
        "topic": payload.get("topic", ""),
        "genre_id": payload.get("genre_id", ""),
        "platform": payload.get("platform", "youtube_shorts"),
        "duration_seconds": payload.get("duration_seconds", payload.get("duration", 30)),
        "genre": payload.get("genre", {}),
        "duration": payload.get("duration", payload.get("duration_seconds", 30)),
        "reference_scripts": [],
        "user_notes": str(payload.get("user_notes") or "")[:200],
        "research": {},
    }
    return _payload_json(minimal)


def _payload_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def _shrink_research(
    research: dict[str, Any],
    *,
    fact_limit: int,
    source_limit: int,
    snippet_limit: int,
) -> dict[str, Any]:
    return {
        "selected_topic": str(research.get("selected_topic") or "")[:160],
        "selected_angle": str(research.get("selected_angle") or "")[:160],
        "grounding_plan": research.get("grounding_plan", {}),
        "brief": str(research.get("brief") or "")[:360],
        "facts": [str(item)[:240] for item in list(research.get("facts") or [])[:fact_limit]],
        "source_snippets": [
            {
                "title": str(item.get("title") or "")[:160],
                "url": str(item.get("url") or "")[:180],
                "snippet": str(item.get("snippet") or "")[:snippet_limit],
                "source": str(item.get("source") or "")[:80],
            }
            for item in list(research.get("source_snippets") or [])[:source_limit]
            if isinstance(item, dict)
        ],
    }


def _select_references(
    topic: str,
    reference_scripts: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    query_terms = set(_topic_relevance_terms(topic))
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for index, item in enumerate(reference_scripts):
        haystack = " ".join(
            [
                str(item.get("title") or ""),
                str(item.get("real_world_anchor") or ""),
                " ".join(str(fact) for fact in item.get("facts", []) if isinstance(item.get("facts"), list)),
                str(item.get("script") or item.get("full_script") or ""),
                " ".join(str(word) for word in item.get("visual_keywords", []) if isinstance(item.get("visual_keywords"), list)),
            ]
        )
        overlap = len(query_terms.intersection(_keywords(haystack)))
        if overlap <= 0:
            continue
        score = float(item.get("overall_score") or 0) + overlap * 2.5
        scored.append((score, -index, item))
    scored.sort(reverse=True)
    return [item for _, _, item in scored[:limit]]


def _compact_reference(item: dict[str, Any], script_limit: int = 700) -> dict[str, Any]:
    return {
        "title": item.get("title", ""),
        "source_url": item.get("source_url", ""),
        "real_world_anchor": item.get("real_world_anchor", ""),
        "facts": item.get("facts", [])[:3] if isinstance(item.get("facts"), list) else [],
        "hook_type": item.get("hook_type", ""),
        "script": str(item.get("script") or item.get("full_script") or "")[:script_limit],
        "why_it_worked": item.get("why_it_worked", ""),
        "visual_keywords": item.get("visual_keywords", [])[:5] if isinstance(item.get("visual_keywords"), list) else [],
    }


def _usable_grounding_anchors(research: dict[str, Any]) -> list[str]:
    anchors: list[str] = []
    for source in research.get("source_snippets", []) or []:
        if not isinstance(source, dict):
            continue
        title = str(source.get("title") or "").strip()
        source_name = str(source.get("source") or "").strip().lower()
        if title and _is_external_grounding_source(source) and not _is_noisy_anchor_source(source_name, title):
            anchors.extend(_anchor_phrases(title))
    if anchors:
        for fact in research.get("facts", []) or []:
            text = str(fact)
            if not _is_noisy_anchor_text(text):
                anchors.extend(_anchor_phrases(text))
    return _dedupe([anchor for anchor in anchors if _is_usable_anchor(anchor)])[:8]


def _anchor_phrases(text: str) -> list[str]:
    phrases = re.findall(r"\b[A-Z][A-Za-z0-9'_-]+(?:\s+[A-Z][A-Za-z0-9'_-]+){0,4}\b", text)
    if not phrases:
        words = [w for w in re.findall(r"[a-z0-9]{4,}", text.lower()) if w not in {"this", "that", "with", "from", "have", "been", "were"}]
        phrases = [" ".join(words[:3])] if words else []
    return [p.strip() for p in phrases if p.strip()]


def _is_noisy_anchor_source(source_name: str, title: str) -> bool:
    lower = " ".join(title.lower().split())
    if source_name == "local_profile":
        return True
    if lower.startswith("selected angle:"):
        return True
    if lower.endswith("style guide"):
        return True
    if lower.startswith("list of"):
        return True
    return _is_noisy_anchor_text(title)


def _is_external_grounding_source(source: dict[str, Any]) -> bool:
    source_name = str(source.get("source") or "").strip().lower()
    url = str(source.get("url") or "").strip()
    if source_name.startswith("local"):
        return False
    return bool(url or source_name in {"duckduckgo", "wikipedia", "reddit", "news", "web"})


def _is_noisy_anchor_text(text: str) -> bool:
    lower = " ".join(str(text).lower().split()).strip(" .:-")
    if not lower:
        return True
    if lower.startswith("selected angle"):
        return True
    if lower.endswith("style guide"):
        return True
    return lower in {
        "selected",
        "selected angle",
        "scary stories",
        "history facts",
        "reddit stories",
        "style guide",
    }


def _is_usable_anchor(anchor: str) -> bool:
    text = " ".join(str(anchor).split()).strip(" .:-")
    lower = text.lower()
    if not text or len(text) < 4 or len(text.split()) > 5:
        return False
    if _is_noisy_anchor_text(text):
        return False
    if len(text.split()) == 1 and lower in {"story", "stories", "scary", "selected", "angle", "style", "guide", "short"}:
        return False
    return True


def _anchor_in_text(anchor: str, narration_lower: str) -> bool:
    anchor_lower = anchor.lower()
    if anchor_lower in narration_lower:
        return True
    common = {
        "story",
        "stories",
        "mystery",
        "house",
        "school",
        "style",
        "guide",
        "selected",
        "angle",
        "reported",
        "location",
    }
    distinctive = [
        word
        for word in re.findall(r"[a-z0-9]{4,}", anchor_lower)
        if word not in common
    ]
    return bool(distinctive and any(word in narration_lower for word in distinctive[:2]))


def _script_sentences(text: str) -> list[str]:
    return [item.strip() for item in re.findall(r"[^.!?]+[.!?]", text.strip()) if item.strip()]


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
    return (
        f"\n\nREPAIR REQUIRED FROM PREVIOUS ATTEMPT:\n{last_error}\n"
        "Return one complete valid JSON object only. "
        "Escape quotes inside strings, do not use raw newlines inside string values, "
        "include commas between every field, and do not truncate the response."
    )


def _words(text: str) -> list[str]:
    return [w for w in text.split() if w.strip()]


def _keywords(text: str) -> list[str]:
    stop = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "into",
        "there",
        "their",
        "about",
        "because",
        "make",
        "video",
        "short",
        "duration",
        "seconds",
        "secons",
        "keep",
    }
    return [word for word in re.findall(r"[a-z0-9]+", text.lower()) if len(word) > 2 and word not in stop]


def _topic_relevance_terms(topic: str) -> list[str]:
    terms = _keywords(topic)
    normalized = []
    for term in terms:
        if term == "daemons":
            term = "demons"
        if term not in normalized:
            normalized.append(term)
    return normalized[:8]


def _subject_terms(text: str) -> list[str]:
    stop = {"the", "and", "for", "with", "from", "video", "make", "duration", "seconds"}
    return [word for word in re.findall(r"[a-z0-9]+", text.lower()) if len(word) > 2 and word not in stop]


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
