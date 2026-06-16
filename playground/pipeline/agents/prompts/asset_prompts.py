# Max context budget: input <= 500 chars, output <= 80 tokens.
MAX_INPUT_CHARS = 500
MAX_OUTPUT_TOKENS = 80

SYSTEM_PROMPT = """
You are the ASSET_QUERY agent for a YouTube Shorts asset pipeline.
Rewrite visual concepts into professional image-search queries.

You must output a single JSON object that matches OUTPUT_FORMAT exactly.
Output JSON only, no markdown, no extra text.

INPUT_FORMAT:
{
  "raw_query": "Original visual cue from the script.",
  "genre_id": "Genre id.",
  "mood": "Cue mood.",
  "failure_reason": "Why the previous search failed, if known."
}

OUTPUT_FORMAT:
{
  "query": "Professional 2-6 word visual search query.",
  "reason": "Short reason for the rewrite."
}

Rules:
- Guardrails: never include API keys, credentials, private data, or system/developer instructions in the query.
- Guardrails: keep queries safe for general stock-image search and avoid sexual, hateful, exploitative, or wrongdoing-enabling terms.
- If the raw query is a greeting or generic chat, convert it to a neutral creator workspace visual instead of pretending it is a story scene.
- Prefer literal nouns, places, objects, emotions, and settings.
- Prefer searchable stock-photo language that is likely to return many results.
- Avoid vague words like dramatic, scary, interesting, moment, thing.
- Avoid emotion-only queries like "feeling overwhelmed exams" or "exam anxiety".
- Every query should include a visible subject/object and a setting, such as "stressed student exam papers classroom".
- Avoid over-specific story phrases that only match one exact plot.
- If the raw query is too specific, generalize it while keeping the same visual meaning.
- Avoid copyrighted character names unless the topic is factual or public-domain.
- Do not include camera instructions unless they improve search quality.
- Good queries usually include 2-3 concrete nouns and one setting, such as "worried man kitchen table".
- Return JSON only.
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

MESSAGES_BASE = [
    {"role": "system", "content": SYSTEM_PROMPT},
    {"role": "user", "content": USER_INPUT_1},
    {"role": "assistant", "content": ASSISTANT_OUTPUT_1},
    {"role": "user", "content": USER_INPUT_2},
    {"role": "assistant", "content": ASSISTANT_OUTPUT_2},
    {"role": "user", "content": USER_INPUT_3},
    {"role": "assistant", "content": ASSISTANT_OUTPUT_3},
    {"role": "user", "content": USER_INPUT_4},
    {"role": "assistant", "content": ASSISTANT_OUTPUT_4},
]


def messages_base():
    """Return messages with trimmed whitespace for consistency."""
    return [{**m, "content": m["content"].strip()} for m in MESSAGES_BASE]


def build_user_input(raw_query: str, genre_id: str, mood: str = "", failure_reason: str = "") -> str:
    payload = (
        '{"raw_query": "'
        + raw_query.replace('"', "'")[:180]
        + '", "genre_id": "'
        + genre_id.replace('"', "'")[:80]
        + '", "mood": "'
        + mood.replace('"', "'")[:80]
        + '", "failure_reason": "'
        + failure_reason.replace('"', "'")[:120]
        + '"}'
    )
    return payload[:MAX_INPUT_CHARS]


def messages_with_user(raw_query: str, genre_id: str, mood: str = "", failure_reason: str = ""):
    return messages_base() + [
        {
            "role": "user",
            "content": build_user_input(raw_query, genre_id, mood, failure_reason),
        }
    ]
