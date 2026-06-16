import json
from typing import Dict, List

from agents.prompts.message_base import (
    append_user_message,
    base_messages,
    clean_text,
    compact_json,
)


MAX_INPUT_CHARS = 500
MAX_OUTPUT_TOKENS = 80


SYSTEM_PROMPT = """
You are the ASSET_QUERY agent for a YouTube Shorts asset pipeline.

Your job is to rewrite a script visual cue into a stock-video-first / image-search query.

Return exactly one valid JSON object matching OUTPUT_FORMAT.
Output JSON only. No markdown, no comments, no extra text.

INPUT_FORMAT:
{
  "raw_query": "Original visual cue from the script.",
  "genre_id": "Genre id.",
  "mood": "Cue mood.",
  "failure_reason": "Why the previous search failed, if known."
}

OUTPUT_FORMAT:
{
  "query": "Professional 2-6 word stock-video/search query.",
  "reason": "Short reason for the rewrite."
}

Hard rules:
- query must be 2-6 words.
- query must describe one searchable moving visual scene when possible.
- query must use concrete visible nouns, settings, objects, actions, and emotions.
- Prefer terms that can return real Pexels-style video footage.
- reason must be one short sentence.
- Output must be valid JSON with only the keys query and reason.
- Do not include markdown, bullets, explanations, or extra fields.

Prefer:
- people + object + setting: "woman reading letter kitchen"
- object + setting + mood: "scratched mirror abandoned bedroom"
- event evidence instead of plot: "fake bank papers table"
- visible emotion with cause: "shocked woman holding phone"
- genre-specific concrete imagery.

Avoid:
- vague words: dramatic, scary, interesting, creepy, mysterious, moment, thing, scene.
- abstract plot words: betrayal, secret, truth, revenge, realization, destiny.
- search filler: stock photo, cinematic, 4k, high quality, aesthetic.
- long sentences, commas, hashtags, quotes, or camera instructions.
- copyrighted fictional character names unless the topic is factual or public-domain.
- brand names unless the brand itself is essential to the factual topic.
- graphic gore or sexual content; use safer visible evidence instead.

Rewrite strategy:
- If the cue is abstract, convert it into the most visible object or setting.
- If the cue is emotional, include a person, reaction, and cause.
- If the cue is dialogue, infer the visible situation behind the line.
- If the cue is a plot twist, show the evidence of the twist.
- If the cue is horror, use concrete signs: shadows, mirrors, doors, dolls, empty rooms, footprints.
- If the cue is mystery, use clues: letters, photos, keys, folders, maps, locked doors.
- If the cue is history, use era-specific places, artifacts, ruins, soldiers, maps, monuments.
- If the cue is Reddit/relationship drama, use documents, phones, messages, kitchen tables, bedrooms, offices.
- If the previous failure says "too abstract", make the query more object-based.
- If the previous failure says "generic portraits", add a specific object and setting.
- If the previous failure says "no results", simplify rare words into broader searchable terms.
- If the previous failure says "copyright", replace the name with a generic visual equivalent.
- If no clear visual exists, choose the most searchable genre-appropriate fallback and explain that.

Quality check before final:
- Is query 2-6 words?
- Is it a concrete stock video or image search query?
- Does it avoid vague/abstract words?
- Is the output valid JSON only?
"""


USER_INPUT_1 = """
{
  "raw_query": "she can hear you scratched mirror",
  "genre_id": "scary_stories",
  "mood": "dark",
  "failure_reason": "Too abstract for stock image search."
}
"""

ASSISTANT_OUTPUT_1 = """
{
  "query": "scratched mirror dark abandoned bedroom",
  "reason": "Uses concrete objects and setting that image APIs can match."
}
"""

USER_INPUT_2 = """
{
  "raw_query": "boyfriend exposed after fake debt papers",
  "genre_id": "reddit_stories",
  "mood": "reveal",
  "failure_reason": "Original query is story-like rather than visual."
}
"""

ASSISTANT_OUTPUT_2 = """
{
  "query": "fake bank papers kitchen counter",
  "reason": "Converts the plot event into a specific searchable object scene."
}
"""

USER_INPUT_3 = """
{
  "raw_query": "ancient empire rises from nothing",
  "genre_id": "history_facts",
  "mood": "dramatic",
  "failure_reason": "Too broad and abstract."
}
"""

ASSISTANT_OUTPUT_3 = """
{
  "query": "ancient city ruins desert",
  "reason": "Turns a broad historical idea into visible places and objects."
}
"""

USER_INPUT_4 = """
{
  "raw_query": "the moment she realizes the secret",
  "genre_id": "mystery_stories",
  "mood": "reveal",
  "failure_reason": "Emotion-only query returned generic portraits."
}
"""

ASSISTANT_OUTPUT_4 = """
{
  "query": "woman reading letter shocked",
  "reason": "Uses a concrete reveal object and clear human reaction."
}
"""

USER_INPUT_5 = """
{
  "raw_query": "he felt like spider-man watching from the ceiling",
  "genre_id": "scary_stories",
  "mood": "uneasy",
  "failure_reason": "Copyrighted character name caused bad results."
}
"""

ASSISTANT_OUTPUT_5 = """
{
  "query": "shadow figure ceiling bedroom",
  "reason": "Replaces copyrighted reference with a concrete horror visual."
}
"""

USER_INPUT_6 = """
{
  "raw_query": "she finally understands the betrayal",
  "genre_id": "reddit_stories",
  "mood": "reveal",
  "failure_reason": "Abstract emotion returned generic face images."
}
"""

ASSISTANT_OUTPUT_6 = """
{
  "query": "woman reading phone shocked",
  "reason": "Turns the abstract reveal into a visible reaction with an object."
}
"""


MESSAGES_BASE: List[Dict[str, str]] = [
    {"role": "system", "content": SYSTEM_PROMPT},
    {"role": "user", "content": USER_INPUT_1},
    {"role": "assistant", "content": ASSISTANT_OUTPUT_1},
    {"role": "user", "content": USER_INPUT_2},
    {"role": "assistant", "content": ASSISTANT_OUTPUT_2},
    {"role": "user", "content": USER_INPUT_3},
    {"role": "assistant", "content": ASSISTANT_OUTPUT_3},
    {"role": "user", "content": USER_INPUT_4},
    {"role": "assistant", "content": ASSISTANT_OUTPUT_4},
    {"role": "user", "content": USER_INPUT_5},
    {"role": "assistant", "content": ASSISTANT_OUTPUT_5},
    {"role": "user", "content": USER_INPUT_6},
    {"role": "assistant", "content": ASSISTANT_OUTPUT_6},
]


def messages_base() -> List[Dict[str, str]]:
    """
    Return base few-shot messages with trimmed whitespace for consistency.
    """
    return base_messages(SYSTEM_PROMPT, MESSAGES_BASE[1:])


def build_user_input(
    raw_query: str,
    genre_id: str,
    mood: str = "",
    failure_reason: str = "",
) -> str:
    """
    Build the final compact JSON user message.

    Uses json.dumps instead of manual string concatenation so quotes,
    backslashes, emojis, and newlines are safely escaped.
    """
    payload = {
        "raw_query": clean_text(raw_query, 180),
        "genre_id": clean_text(genre_id, 80),
        "mood": clean_text(mood, 60),
        "failure_reason": clean_text(failure_reason, 120),
    }

    text = compact_json(payload)

    if len(text) <= MAX_INPUT_CHARS:
        return text

    # First reduce lower-priority fields.
    payload["failure_reason"] = clean_text(failure_reason, 60)
    payload["mood"] = clean_text(mood, 40)

    text = compact_json(payload)
    if len(text) <= MAX_INPUT_CHARS:
        return text

    # Then progressively reduce raw_query while preserving valid JSON.
    while len(payload["raw_query"]) > 40:
        payload["raw_query"] = payload["raw_query"][:-20].strip()
        text = compact_json(payload)
        if len(text) <= MAX_INPUT_CHARS:
            return text

    # Final fallback should almost never be needed, but keeps output valid JSON.
    payload["raw_query"] = clean_text(payload["raw_query"], 40)
    payload["genre_id"] = clean_text(payload["genre_id"], 40)
    payload["mood"] = clean_text(payload["mood"], 20)
    payload["failure_reason"] = clean_text(payload["failure_reason"], 40)

    text = compact_json(payload)

    if len(text) <= MAX_INPUT_CHARS:
        return text

    # Last-resort minimal valid payload.
    return json.dumps(
        {
            "raw_query": clean_text(raw_query, 30),
            "genre_id": clean_text(genre_id, 20),
            "mood": "",
            "failure_reason": "",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def messages_with_user(
    raw_query: str,
    genre_id: str,
    mood: str = "",
    failure_reason: str = "",
) -> List[Dict[str, str]]:
    """
    Return complete message list ready to send to the model.
    """
    return append_user_message(
        messages_base(),
        build_user_input(
            raw_query=raw_query,
            genre_id=genre_id,
            mood=mood,
            failure_reason=failure_reason,
        ),
        MAX_INPUT_CHARS,
    )


def parse_asset_query_response(response_text: str) -> Dict[str, str]:
    """
    Parse and lightly validate the model response.

    Raises ValueError if the response does not match the expected schema.
    """
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model response is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Model response must be a JSON object.")

    expected_keys = {"query", "reason"}
    actual_keys = set(data.keys())

    if actual_keys != expected_keys:
        raise ValueError(
            f"Model response must contain only keys {expected_keys}, got {actual_keys}."
        )

    query = data.get("query")
    reason = data.get("reason")

    if not isinstance(query, str) or not query.strip():
        raise ValueError("Field 'query' must be a non-empty string.")

    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Field 'reason' must be a non-empty string.")

    word_count = len(query.split())
    if word_count < 2 or word_count > 6:
        raise ValueError(f"Field 'query' must be 2-6 words, got {word_count}.")

    return {
        "query": query.strip(),
        "reason": reason.strip(),
    }


if __name__ == "__main__":
    # Example usage.
    messages = messages_with_user(
        raw_query="he found the hidden camera in her room",
        genre_id="reddit_stories",
        mood="reveal",
        failure_reason="Original query was too plot-like.",
    )

    print(json.dumps(messages, indent=2, ensure_ascii=False))
