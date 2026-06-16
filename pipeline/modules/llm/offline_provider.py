from __future__ import annotations

import json
import re

from modules.llm.providers import LLMProvider


class OfflineProvider(LLMProvider):
    name = "offline"

    def generate_json(self, system_prompt: str, user_prompt: str, max_output_tokens: int) -> dict:
        payload = _extract_payload(user_prompt)
        topic = str(payload.get("topic") or "this story")
        genre = payload.get("genre") if isinstance(payload.get("genre"), dict) else {}
        research = payload.get("research") if isinstance(payload.get("research"), dict) else {}
        min_words = int(genre.get("word_count_min") or 80)
        max_words = int(genre.get("word_count_max") or 130)
        duration = int(payload.get("duration") or 30)
        anchor = _anchor(research, topic)
        narration = _fit_words(_narration(topic, anchor, research), min_words, max_words)
        title = _title(topic, anchor)
        return {
            "title": title,
            "narration": narration,
            "hook_line": _first_sentence(narration),
            "word_count": len(narration.split()),
            "estimated_duration": duration,
            "description": f"A short, grounded video about {topic}.",
            "hashtags": ["#shorts", "#facts", "#story"],
            "image_cues": _image_cues(topic, anchor),
            "sfx_cues": [
                {"trigger_word": "warning", "sfx_type": "soft_hit", "timestamp_hint": "during word"},
                {"trigger_word": "found", "sfx_type": "low_boom", "timestamp_hint": "during word"},
            ],
            "emphasis_words": ["real", "warning", "found", "last"],
        }


def _extract_payload(user_prompt: str) -> dict:
    marker = "USER:"
    text = user_prompt.rsplit(marker, 1)[-1] if marker in user_prompt else user_prompt
    start = text.find("{")
    if start < 0:
        return {}
    decoder = json.JSONDecoder()
    try:
        payload, _ = decoder.raw_decode(text[start:])
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _anchor(research: dict, topic: str) -> str:
    for source in research.get("source_snippets", []) or []:
        title = str(source.get("title") or "").strip()
        if title and not title.lower().startswith("list of"):
            return title[:80]
    for fact in research.get("facts", []) or []:
        phrase = " ".join(str(fact).split())[:80]
        if phrase:
            return phrase
    return "a real report about " + topic


def _narration(topic: str, anchor: str, research: dict) -> str:
    fact = ""
    facts = research.get("facts", []) or []
    if facts:
        fact = " ".join(str(facts[0]).split())
    fact_sentence = f"One detail said {fact}." if fact else "One detail was simple enough to check."
    return (
        f"{anchor} gives this {topic} a real starting point. "
        f"At first, it sounds like a normal short video idea. "
        f"Then the warning sign appears: the details are not random, they point to a place, a time, and a reason. "
        f"{fact_sentence} "
        f"That is the part viewers should notice, because a fake story usually hides behind vague words. "
        f"Here, the useful lesson is clear: keep the scene specific, keep the fear believable, and do not invent claims the source does not support. "
        f"The final reveal is not a monster; it is that one real detail can make the whole story feel closer."
    )


def _fit_words(text: str, min_words: int, max_words: int) -> str:
    sentences = re.findall(r"[^.!?]+[.!?]", text)
    while len(" ".join(sentences).split()) < min_words:
        sentences.insert(-1, "The next shot should show the exact object or place, not a random dark room.")
    words = " ".join(sentences).split()
    if len(words) <= max_words:
        return " ".join(sentences)
    trimmed = words[: max(20, max_words - 8)]
    return " ".join(trimmed).rstrip(".,;:") + "."


def _title(topic: str, anchor: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", topic or anchor)
    title = " ".join(words[:7]).title() or "Grounded Short"
    return title[:60]


def _first_sentence(text: str) -> str:
    match = re.match(r"(.+?[.!?])(?:\s|$)", text.strip())
    return match.group(1) if match else text.strip()


def _image_cues(topic: str, anchor: str) -> list[dict[str, str]]:
    base_words = [word.lower() for word in re.findall(r"[A-Za-z0-9]+", f"{topic} {anchor}") if len(word) > 2]
    base = " ".join(base_words[:5]) or "real story location"
    return [
        {"keyword": f"{base} exterior building vertical", "timestamp_hint": "word_0", "mood": "neutral"},
        {"keyword": f"{base} hallway detail close up", "timestamp_hint": "word_18", "mood": "dramatic"},
        {"keyword": f"{base} document phone screen", "timestamp_hint": "word_36", "mood": "neutral"},
        {"keyword": f"{base} warning sign wall", "timestamp_hint": "word_54", "mood": "dramatic"},
        {"keyword": f"{base} empty room final shot", "timestamp_hint": "word_72", "mood": "reveal"},
    ]
