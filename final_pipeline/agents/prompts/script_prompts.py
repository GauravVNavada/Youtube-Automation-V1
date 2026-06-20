
from __future__ import annotations

import json
import re
from typing import Any

from agents.prompts.message_base import (
    append_user_message,
    base_messages,
    clean_list,
    clean_text,
    compact_json,
    render_messages_for_single_prompt,
)


MAX_INPUT_CHARS = 6000
MAX_OUTPUT_TOKENS = 4096


SYSTEM_PROMPT = """
You are the SCRIPT_PLAN agent for an AI YouTube Shorts / short-video generator.

Your job is to produce a grounded, usable short-video script plan.
Return exactly one valid JSON object matching OUTPUT_FORMAT.
Output JSON only. No markdown. No comments. No extra text.

The script must feel useful in the real world, not like a random fake scene.
Use easy layman words. Prefer short spoken sentences.
The narration must be spoken voiceover only. No stage directions.

INPUT_FORMAT:
{
  "raw_request": "User's video idea or instruction.",
  "genre_id": "Genre id.",
  "platform": "youtube_shorts | instagram_reels | tiktok | unknown",
  "duration_seconds": 45,
  "target_audience": "Audience description, if known.",
  "mood": "Desired mood or style.",
  "genre": {
    "word_count_min": 90,
    "word_count_max": 120
  },
  "research": {
    "facts": ["Verified facts from research agent."],
    "source_snippets": ["Short snippets or source summaries from research agent."]
  },
  "constraints": ["Optional constraints."],
  "previous_failures": ["Optional prior failures."]
}

OUTPUT_FORMAT:
{
  "title": "YouTube title, max 60 chars",
  "narration": "Full spoken narration only. No stage directions.",
  "hook_line": "Exact first sentence of the narration.",
  "word_count": 108,
  "estimated_duration": 45,
  "description": "Short YouTube description.",
  "hashtags": ["#shorts", "#genre", "#topic"],
  "image_cues": [
    {
      "keyword": "concrete subject object setting",
      "timestamp_hint": "word_0",
      "mood": "dark|eerie|dramatic|neutral|reveal",
      "role": "primary_subject|background|evidence|setting",
      "subject_lock": false,
      "required_subjects": [],
      "aliases": [],
      "allowed_fallback_level": "exact_subject|subject_alias|generic_scene|abstract_symbolic|text_card"
    }
  ],
  "sfx_cues": [
    {
      "trigger_word": "word from narration",
      "sfx_type": "short_snake_case_sound_type",
      "timestamp_hint": "during word"
    }
  ],
  "emphasis_words": ["important", "caption", "words"]
}

Hard rules:
- Output must be valid JSON with only the top-level keys in OUTPUT_FORMAT.
- New image_cues should include the subject-lock fields shown in OUTPUT_FORMAT. Older examples may omit them only as legacy shape.
- Stay within genre.word_count_min and genre.word_count_max when provided.
- If no word range is provided, match duration_seconds naturally.
- The first sentence must hook fast.
- hook_line must exactly equal the first sentence of narration.
- word_count must be the approximate number of spoken words in narration.
- estimated_duration must be realistic for spoken narration.
- The narration must have a proper ending.
- Never cut off randomly.
- The final sentence must close the idea.
- No calls to action.
- No citations, source ids, URLs, or bibliography text in the narration.
- Do not copy source snippets directly.
- Do not put quote marks around titles, names, phrases, or emphasis in the narration.
- Never output empty quote marks such as '' or "" in the narration.
- Avoid dialogue-style quoted text unless the user explicitly asks for dialogue.
- Use simple words. Avoid hard vocabulary unless the topic needs it.
- Every sentence should add one concrete detail.
- Avoid generic filler.
- Avoid fake specificity.
- Avoid unrelated sources just because they share one word with the topic.
- Never copy the few-shot examples as the answer. They show format only.
- If the user asks for a named subject, the script must be about that named subject and must mention it or a clear alias naturally.
- Do not treat duration, platform, genre, or formatting instructions as visual subjects.

Grounding rules:
- Treat local database/reference scripts as inspiration for pacing, structure, hooks, and visual style only.
- Write fresh narration with new wording, new examples, and a new angle for the requested topic.
- Do not copy sentences, paragraph flow, or distinctive phrases from reference scripts or few-shot examples.
- You may invent fresh names, objects, scenes, and wording for fictional/story topics when they are believable and safe.
- If external research facts or web/source snippets exist, narration must clearly use at least one real anchor from them.
- A real anchor can be a named place, event, person, date, source title, urban legend, documented claim, object, or location.
- Use the anchor naturally inside the story or facts.
- Do not treat helper labels like "Selected angle", genre names, or "style guide" as real anchors.
- Do not invent extra claims about real people, places, events, dates, or documents.
- If research is weak or incomplete, keep claims narrow and phrase uncertainty plainly.
- If the topic is factual but research is missing, avoid precise claims, numbers, dates, and named accusations.
- If the topic involves a real person, do not invent private actions, thoughts, crimes, quotes, or motives.
- If the topic involves health, finance, law, politics, disasters, or current news, only use claims supported by research.
- If the topic is fiction, horror, mystery, or Reddit-style drama, make it believable and internally consistent.

Retention rules:
- Add 1-2 alert beats in the middle.
- Alert beats should be shocking but believable.
- Do not make the alert beat random.
- For horror or mystery, the reveal must feel possible.
- For history or facts, the surprise must come from a real anchor or a safe general insight.
- For Reddit-style stories, the twist should be shown through concrete evidence like a message, receipt, letter, photo, bill, key, or document.

Image cue rules:
- Include at least 5 image_cues.
- Make image_cues visually different from each other.
- image_cues must be stock-searchable concrete nouns plus setting.
- Do not use abstract cue keywords like betrayal, secret, destiny, scary moment, shocking truth.
- Do not use generic filler like old school hallway unless research supports that location.
- Prefer visible objects, people, places, documents, rooms, tools, weather, maps, ruins, phones, letters, doors, mirrors, streets, or buildings.
- If the topic uses a real person/place/event, image cues must not imply false claims.
- Avoid copyrighted character names unless the video is factual about that character or public-domain.
- Avoid brand names unless the brand itself is essential and factual.
- Use only these image cue moods: dark, eerie, dramatic, neutral, reveal.
- When a visual cue is about a specific named subject, fallback may reduce visual specificity but must not change the subject.
- If the video topic is a specific person, character, product, brand, place, event, team, film, game, landmark, or object, mark the main-subject cues with subject_lock true.
- For subject_lock true, include the exact required subject in required_subjects and useful aliases in aliases.
- Subject-locked cues must not be replaced by category-related or generic scene footage. Use allowed_fallback_level exact_subject, subject_alias, abstract_symbolic, or text_card.
- Supporting/background cues may use subject_lock false and allowed_fallback_level generic_scene.

SFX cue rules:
- sfx_cues may be empty if sound effects would be distracting.
- Every trigger_word must appear in the narration.
- sfx_type must be short_snake_case.
- When input.sfx_catalog is present, prefer one of its id values for sfx_type. Choose by matching the catalog tags, aliases, and use_cases to the story beat.
- If no catalog item fits, use the closest simple catalog id rather than inventing an overly specific sound name.
- Use subtle, useful sounds: phone_buzz, paper_rustle, door_creak, heartbeat, static_glitch, camera_shutter, crowd_murmur.
- Do not overdo sound effects.

Caption emphasis rules:
- emphasis_words should be short words or phrases from the narration.
- Choose words that help retention.
- Prefer concrete names, numbers, reveal words, objects, and emotional turning points.

Genre handling:
- scary_stories: suspense first, no graphic gore, concrete setting, possible reveal.
- mystery_stories: clue chain, evidence object, clear reveal.
- reddit_stories: realistic social conflict, concrete proof, no overacting.
- history_facts: real anchors, dates/places only when supported, no fake legends.
- comics: comic-book stakes, panel-like visual beats, hero/villain conflict, avoid relying on movie footage.
- science_facts: simple mechanism, no unsupported certainty.
- finance/legal/medical: cautious wording, no advice beyond research.
- explainers: problem, surprising detail, simple takeaway.
- motivational: practical insight, no fake quotes or fake studies.

Quality check before final:
- Is the output JSON only?
- Does hook_line exactly match the first sentence?
- Does narration end cleanly?
- Is at least one research anchor used when research exists?
- Are there at least 5 concrete, distinct image cues?
- Are all SFX trigger words present in narration?
- Are title and hashtags safe and non-clickbait?
""".strip()


EXAMPLE_USER_INPUT_1 = """
{
  "raw_request": "Make a short about why Roman concrete lasted so long.",
  "genre_id": "history_facts",
  "platform": "youtube_shorts",
  "duration_seconds": 45,
  "target_audience": "curious students",
  "mood": "surprising",
  "genre": {
    "word_count_min": 90,
    "word_count_max": 120
  },
  "research": {
    "facts": [
      "Roman marine concrete used volcanic ash and lime.",
      "Research on ancient harbor concrete found mineral growth that helped fill cracks.",
      "Pozzuoli was known as a source of volcanic ash used by Roman builders."
    ],
    "source_snippets": [
      "Studies of Roman harbor concrete describe volcanic ash, seawater, and minerals forming over time."
    ]
  },
  "constraints": ["avoid fake facts"],
  "previous_failures": []
}
"""

EXAMPLE_ASSISTANT_OUTPUT_1 = """
{
  "title": "Why Roman Concrete Survived",
  "narration": "Roman concrete had a trick modern concrete often misses. In places near the sea, builders mixed lime with volcanic ash, including ash linked to Pozzuoli. That sounds simple, but here is the strange part. Seawater did not only damage some of these old structures. In some harbor concrete, it helped new minerals grow inside tiny cracks. So while normal concrete can slowly break apart, parts of Roman concrete could partly seal themselves over time. This does not mean every Roman wall was magic. It means their material matched the sea better than expected. The lesson is simple: sometimes durability comes from working with the environment, not fighting it.",
  "hook_line": "Roman concrete had a trick modern concrete often misses.",
  "word_count": 105,
  "estimated_duration": 45,
  "description": "How volcanic ash and seawater helped some Roman concrete survive for centuries.",
  "hashtags": ["#shorts", "#history", "#rome", "#engineering"],
  "image_cues": [
    {"keyword": "Roman harbor ruins sea", "timestamp_hint": "word_0", "mood": "dramatic"},
    {"keyword": "volcanic ash stone texture", "timestamp_hint": "word_14", "mood": "neutral"},
    {"keyword": "ancient concrete wall crack", "timestamp_hint": "word_31", "mood": "reveal"},
    {"keyword": "seawater hitting old pier", "timestamp_hint": "word_43", "mood": "dramatic"},
    {"keyword": "mineral crystals rock closeup", "timestamp_hint": "word_56", "mood": "reveal"},
    {"keyword": "Roman ruins coastline sunset", "timestamp_hint": "word_89", "mood": "dramatic"}
  ],
  "sfx_cues": [
    {"trigger_word": "sea", "sfx_type": "soft_wave_crash", "timestamp_hint": "during sea"},
    {"trigger_word": "cracks", "sfx_type": "stone_crack", "timestamp_hint": "during cracks"}
  ],
  "emphasis_words": ["Roman concrete", "volcanic ash", "seawater", "tiny cracks", "seal themselves"]
}
"""

EXAMPLE_USER_INPUT_2 = """
{
  "raw_request": "A scary story where a woman hears scratching inside her mirror.",
  "genre_id": "scary_stories",
  "platform": "youtube_shorts",
  "duration_seconds": 30,
  "target_audience": "horror story viewers",
  "mood": "dark",
  "genre": {
    "word_count_min": 65,
    "word_count_max": 85
  },
  "research": {
    "facts": [],
    "source_snippets": []
  },
  "constraints": ["no gore"],
  "previous_failures": ["image cues were too abstract"]
}
"""

EXAMPLE_ASSISTANT_OUTPUT_2 = """
{
  "title": "The Scratches Behind The Mirror",
  "narration": "Maya first heard the scratching at 2:13 a.m. It came from the bathroom mirror, slow and careful, like a nail dragging across glass. She checked the sink, the wall, even the cabinet behind it. Nothing was there. Then the scratching stopped. A foggy line appeared on the mirror from the inside. It wrote one word: move. Maya stepped back. A second later, the mirror cracked outward, and a rusted screw fell into the sink. The mirror was not haunted. Someone had been loosening it from the other side.",
  "hook_line": "Maya first heard the scratching at 2:13 a.m.",
  "word_count": 81,
  "estimated_duration": 30,
  "description": "A short horror story about a mirror, a warning, and a very real threat.",
  "hashtags": ["#shorts", "#horror", "#scarystory", "#mystery"],
  "image_cues": [
    {"keyword": "dark bathroom mirror night", "timestamp_hint": "word_0", "mood": "dark"},
    {"keyword": "scratched glass closeup", "timestamp_hint": "word_12", "mood": "eerie"},
    {"keyword": "woman checking bathroom cabinet", "timestamp_hint": "word_28", "mood": "dark"},
    {"keyword": "foggy mirror written word", "timestamp_hint": "word_43", "mood": "reveal"},
    {"keyword": "cracked mirror bathroom sink", "timestamp_hint": "word_61", "mood": "dramatic"},
    {"keyword": "rusted screw white sink", "timestamp_hint": "word_67", "mood": "reveal"}
  ],
  "sfx_cues": [
    {"trigger_word": "scratching", "sfx_type": "glass_scratch", "timestamp_hint": "during scratching"},
    {"trigger_word": "cracked", "sfx_type": "mirror_crack", "timestamp_hint": "during cracked"},
    {"trigger_word": "screw", "sfx_type": "metal_drop", "timestamp_hint": "during screw"}
  ],
  "emphasis_words": ["2:13 a.m.", "bathroom mirror", "from the inside", "move", "other side"]
}
"""


MESSAGES_BASE: list[dict[str, str]] = [
    {"role": "system", "content": SYSTEM_PROMPT},
    {"role": "user", "content": EXAMPLE_USER_INPUT_1},
    {"role": "assistant", "content": EXAMPLE_ASSISTANT_OUTPUT_1},
    {"role": "user", "content": EXAMPLE_USER_INPUT_2},
    {"role": "assistant", "content": EXAMPLE_ASSISTANT_OUTPUT_2},
]


EXPECTED_OUTPUT_KEYS = {
    "title",
    "narration",
    "hook_line",
    "word_count",
    "estimated_duration",
    "description",
    "hashtags",
    "image_cues",
    "sfx_cues",
    "emphasis_words",
}

IMAGE_CUE_KEYS = {
    "keyword",
    "timestamp_hint",
    "mood",
    "role",
    "subject_lock",
    "required_subjects",
    "aliases",
    "allowed_fallback_level",
}
LEGACY_IMAGE_CUE_KEYS = {"keyword", "timestamp_hint", "mood"}
SFX_CUE_KEYS = {"trigger_word", "sfx_type", "timestamp_hint"}
ALLOWED_IMAGE_MOODS = {"dark", "eerie", "dramatic", "neutral", "reveal"}


def messages_base() -> list[dict[str, str]]:
    return base_messages(SYSTEM_PROMPT, MESSAGES_BASE[1:])


def build_script_user_payload(
    raw_request: str,
    genre_id: str,
    platform: str = "youtube_shorts",
    duration_seconds: int = 45,
    target_audience: str = "",
    mood: str = "",
    word_count_min: int | None = None,
    word_count_max: int | None = None,
    research_facts: list[str] | None = None,
    research_source_snippets: list[str] | None = None,
    constraints: list[str] | None = None,
    previous_failures: list[str] | None = None,
) -> str:
    genre: dict[str, int] = {}
    if word_count_min is not None:
        genre["word_count_min"] = int(word_count_min)
    if word_count_max is not None:
        genre["word_count_max"] = int(word_count_max)

    payload: dict[str, Any] = {
        "raw_request": clean_text(raw_request, 900),
        "genre_id": clean_text(genre_id, 80),
        "platform": clean_text(platform, 40),
        "duration_seconds": int(duration_seconds),
        "target_audience": clean_text(target_audience, 160),
        "mood": clean_text(mood, 80),
        "genre": genre,
        "research": {
            "facts": clean_list(research_facts, item_limit=320, max_items=10),
            "source_snippets": clean_list(
                research_source_snippets,
                item_limit=420,
                max_items=8,
            ),
        },
        "constraints": clean_list(constraints, item_limit=140, max_items=10),
        "previous_failures": clean_list(previous_failures, item_limit=160, max_items=8),
    }

    text = compact_json(payload)
    if len(text) <= MAX_INPUT_CHARS:
        return text

    payload["raw_request"] = clean_text(raw_request, 600)
    payload["research"]["facts"] = clean_list(research_facts, item_limit=220, max_items=7)
    payload["research"]["source_snippets"] = clean_list(
        research_source_snippets,
        item_limit=280,
        max_items=5,
    )
    payload["constraints"] = clean_list(constraints, item_limit=100, max_items=6)
    payload["previous_failures"] = clean_list(previous_failures, item_limit=100, max_items=5)

    text = compact_json(payload)
    if len(text) <= MAX_INPUT_CHARS:
        return text

    payload["raw_request"] = clean_text(raw_request, 350)
    payload["target_audience"] = clean_text(target_audience, 80)
    payload["research"]["facts"] = clean_list(research_facts, item_limit=160, max_items=4)
    payload["research"]["source_snippets"] = clean_list(
        research_source_snippets,
        item_limit=180,
        max_items=3,
    )

    text = compact_json(payload)
    if len(text) <= MAX_INPUT_CHARS:
        return text

    return compact_json(
        {
            "raw_request": clean_text(raw_request, 220),
            "genre_id": clean_text(genre_id, 60),
            "platform": clean_text(platform, 30),
            "duration_seconds": int(duration_seconds),
            "target_audience": "",
            "mood": clean_text(mood, 50),
            "genre": genre,
            "research": {
                "facts": clean_list(research_facts, item_limit=120, max_items=2),
                "source_snippets": [],
            },
            "constraints": [],
            "previous_failures": [],
        }
    )


def messages_with_user(user_payload: str, *, include_examples: bool = True) -> list[dict[str, str]]:
    base = messages_base() if include_examples else base_messages(SYSTEM_PROMPT)
    return append_user_message(base, user_payload, MAX_INPUT_CHARS)


def messages_with_structured_user(
    raw_request: str,
    genre_id: str,
    platform: str = "youtube_shorts",
    duration_seconds: int = 45,
    target_audience: str = "",
    mood: str = "",
    word_count_min: int | None = None,
    word_count_max: int | None = None,
    research_facts: list[str] | None = None,
    research_source_snippets: list[str] | None = None,
    constraints: list[str] | None = None,
    previous_failures: list[str] | None = None,
    include_examples: bool = True,
) -> list[dict[str, str]]:
    user_payload = build_script_user_payload(
        raw_request=raw_request,
        genre_id=genre_id,
        platform=platform,
        duration_seconds=duration_seconds,
        target_audience=target_audience,
        mood=mood,
        word_count_min=word_count_min,
        word_count_max=word_count_max,
        research_facts=research_facts,
        research_source_snippets=research_source_snippets,
        constraints=constraints,
        previous_failures=previous_failures,
    )

    base = messages_base() if include_examples else base_messages(SYSTEM_PROMPT)
    return append_user_message(base, user_payload, MAX_INPUT_CHARS)


def count_spoken_words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)?", text))


def normalize_space(text: str) -> str:
    return " ".join(text.strip().split())


def first_sentence(text: str) -> str:
    text = normalize_space(text)
    match = re.search(r"^.*?[.!?](?:\s|$)", text)
    if match:
        return match.group(0).strip()
    return text


def is_snake_case(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", value))


def extract_word_bounds(user_payload: str | None) -> tuple[int | None, int | None]:
    if not user_payload:
        return None, None

    try:
        data = json.loads(user_payload)
    except json.JSONDecodeError:
        return None, None

    genre = data.get("genre", {})
    if not isinstance(genre, dict):
        genre = {}

    min_words = genre.get("word_count_min", data.get("word_count_min"))
    max_words = genre.get("word_count_max", data.get("word_count_max"))

    try:
        min_words = int(min_words) if min_words is not None else None
    except (TypeError, ValueError):
        min_words = None

    try:
        max_words = int(max_words) if max_words is not None else None
    except (TypeError, ValueError):
        max_words = None

    return min_words, max_words


def extract_json_object(response_text: str) -> str:
    text = response_text.strip()
    if text.startswith("{") and text.endswith("}"):
        return text

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise ValueError("Response does not contain a JSON object.")

    return text[start:end + 1]


def parse_script_plan_response(
    response_text: str,
    user_payload: str | None = None,
    strict_json_only: bool = True,
) -> dict[str, Any]:
    raw = response_text.strip() if strict_json_only else extract_json_object(response_text)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"SCRIPT_PLAN response is not valid JSON: {exc}") from exc

    validate_script_plan_response(data, user_payload=user_payload)
    return data


def validate_script_plan_response(
    data: dict[str, Any],
    user_payload: str | None = None,
) -> None:
    if not isinstance(data, dict):
        raise ValueError("SCRIPT_PLAN response must be a JSON object.")

    actual_keys = set(data.keys())
    if actual_keys != EXPECTED_OUTPUT_KEYS:
        raise ValueError(
            f"SCRIPT_PLAN response must contain exactly {EXPECTED_OUTPUT_KEYS}, "
            f"got {actual_keys}."
        )

    title = data["title"]
    narration = data["narration"]
    hook_line = data["hook_line"]
    word_count = data["word_count"]
    estimated_duration = data["estimated_duration"]
    description = data["description"]
    hashtags = data["hashtags"]
    image_cues = data["image_cues"]
    sfx_cues = data["sfx_cues"]
    emphasis_words = data["emphasis_words"]

    if not isinstance(title, str) or not title.strip():
        raise ValueError("title must be a non-empty string.")

    if len(title.strip()) > 60:
        raise ValueError("title must be max 60 characters.")

    if not isinstance(narration, str) or not narration.strip():
        raise ValueError("narration must be a non-empty string.")

    if not isinstance(hook_line, str) or not hook_line.strip():
        raise ValueError("hook_line must be a non-empty string.")

    detected_hook = first_sentence(narration)
    if normalize_space(hook_line) != normalize_space(detected_hook):
        raise ValueError(
            "hook_line must exactly match the first sentence of narration. "
            f"Expected: {detected_hook!r}, got: {hook_line!r}."
        )

    if not isinstance(word_count, int):
        raise ValueError("word_count must be an integer.")

    actual_word_count = count_spoken_words(narration)
    if abs(actual_word_count - word_count) > 3:
        raise ValueError(
            f"word_count is inaccurate. Declared {word_count}, actual approx {actual_word_count}."
        )

    min_words, max_words = extract_word_bounds(user_payload)

    if min_words is not None and actual_word_count < min_words:
        raise ValueError(
            f"narration is too short. Minimum {min_words}, actual {actual_word_count}."
        )

    if max_words is not None and actual_word_count > max_words:
        raise ValueError(
            f"narration is too long. Maximum {max_words}, actual {actual_word_count}."
        )

    if not isinstance(estimated_duration, int | float) or estimated_duration <= 0:
        raise ValueError("estimated_duration must be a positive number.")

    if not isinstance(description, str) or not description.strip():
        raise ValueError("description must be a non-empty string.")

    if not isinstance(hashtags, list) or len(hashtags) < 3:
        raise ValueError("hashtags must be a list with at least 3 items.")

    for tag in hashtags:
        if not isinstance(tag, str) or not re.fullmatch(r"#[A-Za-z0-9_]+", tag):
            raise ValueError(f"Invalid hashtag: {tag!r}")

    if not isinstance(image_cues, list) or len(image_cues) < 5:
        raise ValueError("image_cues must contain at least 5 items.")

    seen_keywords: set[str] = set()

    for cue in image_cues:
        if not isinstance(cue, dict):
            raise ValueError("Each image cue must be an object.")

        cue_keys = set(cue.keys())
        if cue_keys not in {IMAGE_CUE_KEYS, LEGACY_IMAGE_CUE_KEYS}:
            raise ValueError(
                f"Each image cue must contain either {IMAGE_CUE_KEYS} or legacy {LEGACY_IMAGE_CUE_KEYS}, got {cue_keys}."
            )

        keyword = cue["keyword"]
        timestamp_hint = cue["timestamp_hint"]
        mood = cue["mood"]

        if not isinstance(keyword, str) or not keyword.strip():
            raise ValueError("image_cue.keyword must be a non-empty string.")

        normalized_keyword = normalize_space(keyword).lower()
        if normalized_keyword in seen_keywords:
            raise ValueError(f"Duplicate image cue keyword: {keyword!r}")

        seen_keywords.add(normalized_keyword)

        if len(keyword.split()) < 2:
            raise ValueError(f"image cue keyword is too vague: {keyword!r}")

        if not isinstance(timestamp_hint, str) or not timestamp_hint.strip():
            raise ValueError("image_cue.timestamp_hint must be a non-empty string.")

        if mood not in ALLOWED_IMAGE_MOODS:
            raise ValueError(
                f"image_cue.mood must be one of {ALLOWED_IMAGE_MOODS}, got {mood!r}."
            )

        if cue_keys == IMAGE_CUE_KEYS:
            if not isinstance(cue["role"], str) or not cue["role"].strip():
                raise ValueError("image_cue.role must be a non-empty string.")
            if not isinstance(cue["subject_lock"], bool):
                raise ValueError("image_cue.subject_lock must be a boolean.")
            if not isinstance(cue["required_subjects"], list):
                raise ValueError("image_cue.required_subjects must be a list.")
            if not isinstance(cue["aliases"], list):
                raise ValueError("image_cue.aliases must be a list.")
            if not isinstance(cue["allowed_fallback_level"], str) or not cue["allowed_fallback_level"].strip():
                raise ValueError("image_cue.allowed_fallback_level must be a non-empty string.")
            if cue["subject_lock"] and not any(str(item).strip() for item in cue["required_subjects"]):
                raise ValueError("subject-locked image cues must include required_subjects.")

    if not isinstance(sfx_cues, list):
        raise ValueError("sfx_cues must be a list.")

    narration_lower = narration.lower()

    for cue in sfx_cues:
        if not isinstance(cue, dict):
            raise ValueError("Each sfx cue must be an object.")

        if set(cue.keys()) != SFX_CUE_KEYS:
            raise ValueError(
                f"Each sfx cue must contain exactly {SFX_CUE_KEYS}, got {set(cue.keys())}."
            )

        trigger_word = cue["trigger_word"]
        sfx_type = cue["sfx_type"]
        timestamp_hint = cue["timestamp_hint"]

        if not isinstance(trigger_word, str) or not trigger_word.strip():
            raise ValueError("sfx_cue.trigger_word must be a non-empty string.")

        if trigger_word.lower() not in narration_lower:
            raise ValueError(
                f"sfx trigger_word must appear in narration: {trigger_word!r}"
            )

        if not isinstance(sfx_type, str) or not is_snake_case(sfx_type):
            raise ValueError(f"sfx_type must be short_snake_case, got {sfx_type!r}.")

        if not isinstance(timestamp_hint, str) or not timestamp_hint.strip():
            raise ValueError("sfx_cue.timestamp_hint must be a non-empty string.")

    if not isinstance(emphasis_words, list) or not emphasis_words:
        raise ValueError("emphasis_words must be a non-empty list.")

    for item in emphasis_words:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("Each emphasis word must be a non-empty string.")


if __name__ == "__main__":
    payload = build_script_user_payload(
        raw_request="Make a short about the hidden cost of free mobile games.",
        genre_id="explainer",
        platform="youtube_shorts",
        duration_seconds=40,
        target_audience="teen gamers",
        mood="sharp and revealing",
        word_count_min=85,
        word_count_max=110,
        research_facts=[
            "Many free mobile games use ads, in-app purchases, and reward loops to earn revenue.",
            "Some games use limited-time offers to create urgency."
        ],
        research_source_snippets=[
            "Free-to-play games often monetize through ads and optional purchases rather than upfront pricing."
        ],
        constraints=["avoid sounding preachy", "needs strong retention"],
        previous_failures=["previous script was too generic"],
    )

    messages = messages_with_structured_user(
        raw_request="Make a short about the hidden cost of free mobile games.",
        genre_id="explainer",
        platform="youtube_shorts",
        duration_seconds=40,
        target_audience="teen gamers",
        mood="sharp and revealing",
        word_count_min=85,
        word_count_max=110,
        research_facts=[
            "Many free mobile games use ads, in-app purchases, and reward loops to earn revenue.",
            "Some games use limited-time offers to create urgency."
        ],
        research_source_snippets=[
            "Free-to-play games often monetize through ads and optional purchases rather than upfront pricing."
        ],
        constraints=["avoid sounding preachy", "needs strong retention"],
        previous_failures=["previous script was too generic"],
        include_examples=True,
    )

    print(render_messages_for_single_prompt(messages))
