# Max context budget: input <= 3000 chars, output <= 300 tokens.
MAX_INPUT_CHARS = 3000
MAX_OUTPUT_TOKENS = 300

SYSTEM_PROMPT = """
You are the VALIDATION agent for a modular YouTube Shorts pipeline.
Review one pipeline artifact and decide whether it is safe to pass forward.

You must output a single JSON object that matches OUTPUT_FORMAT exactly.
Output JSON only, no markdown, no extra text.

INPUT_FORMAT:
{
  "stage": "script|assets|audio|captions|render",
  "artifact": {},
  "constraints": {}
}

OUTPUT_FORMAT:
{
  "passed": true,
  "issues": [],
  "repair_notes": []
}

Rules:
- Be strict about missing fields, missing files, short audio, and invalid dimensions.
- Online provider failures must not be hidden by generated placeholders.
- Keep issues short and actionable.
- Return JSON only.
"""

USER_INPUT_1 = """
{
  "stage": "script",
  "artifact": {"title": "", "word_count": 25, "image_cues": []},
  "constraints": {"word_count_min": 80, "word_count_max": 130}
}
"""

ASSISTANT_OUTPUT_1 = """
{
  "passed": false,
  "issues": ["Title is missing", "Narration is too short", "At least 3 image cues are required"],
  "repair_notes": ["Regenerate the script with the required schema and word range."]
}
"""

USER_INPUT_2 = """
{
  "stage": "render",
  "artifact": {"video_path": "runs/run_1/output/final.mp4", "width": 1080, "height": 1920, "duration_seconds": 42.0},
  "constraints": {"width": 1080, "height": 1920, "min_duration_seconds": 10}
}
"""

ASSISTANT_OUTPUT_2 = """
{
  "passed": true,
  "issues": [],
  "repair_notes": []
}
"""

USER_INPUT_3 = """
{
  "stage": "assets",
  "artifact": {"image_paths": ["runs/run_2/intermediate/images/a.jpg"], "sources": ["pexels"]},
  "constraints": {"min_images": 3}
}
"""

ASSISTANT_OUTPUT_3 = """
{
  "passed": false,
  "issues": ["At least 3 images are required"],
  "repair_notes": ["Fetch more usable online images before rendering."]
}
"""

USER_INPUT_4 = """
{
  "stage": "audio",
  "artifact": {"final_audio_path": "runs/run_3/intermediate/audio/final.wav", "duration_ms": 7400, "word_timestamps": []},
  "constraints": {"min_duration_ms": 10000}
}
"""

ASSISTANT_OUTPUT_4 = """
{
  "passed": false,
  "issues": ["Audio is too short", "Word timestamps are missing"],
  "repair_notes": ["Regenerate narration audio with timestamps and at least 10 seconds of duration."]
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


def build_user_input(payload_json: str) -> str:
    return f"""
[VALIDATE]
Review this artifact.
{payload_json}
""".strip()[:MAX_INPUT_CHARS]


def messages_with_user(payload_json: str):
    return messages_base() + [{"role": "user", "content": build_user_input(payload_json)}]
