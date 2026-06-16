from __future__ import annotations

import json
from typing import Any

from agents.prompts.message_base import (
    append_user_message,
    base_messages,
    clean_text,
    compact_json,
)


MAX_INPUT_CHARS = 3000
MAX_OUTPUT_TOKENS = 300


SYSTEM_PROMPT = """
You are the VALIDATION agent for a modular YouTube Shorts pipeline.

Your job is to review one pipeline artifact and decide whether it is safe to pass forward.
Return exactly one valid JSON object matching OUTPUT_FORMAT.
Output JSON only. No markdown. No comments. No extra text.

INPUT_FORMAT:
{
  "stage": "script|assets|audio|captions|render|thumbnail",
  "artifact": {},
  "constraints": {}
}

OUTPUT_FORMAT:
{
  "passed": true,
  "issues": [],
  "repair_notes": []
}

Hard rules:
- Output must contain only passed, issues, and repair_notes.
- passed must be false if any issue exists.
- passed must be true only when issues is empty.
- issues must be short, specific, and actionable.
- repair_notes must say what the previous agent should fix.
- Do not hide online provider failures behind placeholders.
- Do not pass generated placeholders when real online assets were required.
- Do not assume a file exists just because a path string exists.
- If explicit file existence metadata says false, fail.
- If required fields are missing, fail.
- If dimensions, duration, timestamps, or counts violate constraints, fail.
- If artifact contains errors, provider_failures, missing_files, or placeholder flags, fail.
- Do not invent extra checks that cannot be inferred from artifact or constraints.
- Keep total issues under 8 unless the artifact is severely broken.

General checks:
- artifact must be a JSON object.
- constraints must be a JSON object.
- Empty artifacts fail.
- Any field named error, errors, provider_failures, missing_files, failed_downloads, or failed_paths must fail if non-empty.
- Any field named placeholder, is_placeholder, generated_placeholder, fallback_placeholder, or mock must fail if true.
- Any required path field must be a non-empty string.
- If file_exists or exists is false, fail.
- If file_size_bytes is provided and <= 0, fail.

Stage-specific checks:

script:
- Require title, narration, hook_line, word_count, estimated_duration, image_cues.
- title and narration must be non-empty.
- hook_line must match the first sentence of narration when obvious.
- word_count must be inside constraints.word_count_min and constraints.word_count_max if provided.
- Allow a one-word miss below constraints.word_count_min when narration is complete and otherwise usable.
- estimated_duration must be positive.
- image_cues count must be at least constraints.min_image_cues, default 3.
- If constraints.require_sfx_cues is true, sfx_cues must be non-empty.
- If constraints.require_research_anchor is true, artifact must show a research anchor or grounded claim.

- Require enough usable visual media assets.
- Accept media_paths, image_paths, video_paths, or assets.
- Count must be at least constraints.min_media or constraints.min_images, default 1.
- Prefer real video clips when provided, but accept images as fallback.
- Reject empty paths, duplicate paths, placeholders, failed downloads, and missing files.
- If asset objects include width and height, they must satisfy constraints.min_width and constraints.min_height when provided.
- If constraints.require_sources is true, every asset must include source or provider.
- If constraints.require_license is true, every asset must include license or license_url.

audio:
- Require final_audio_path.
- duration_ms must be at least constraints.min_duration_ms when provided.
- If constraints.max_duration_ms is provided, duration_ms must not exceed it.
- If constraints.require_word_timestamps is not false, word_timestamps must be non-empty.
- Reject empty transcript when constraints.require_transcript is true.
- Reject provider failures, silent audio, placeholder audio, and zero-byte files.

captions:
- Require captions or caption_path or subtitle_path.
- If captions list exists, it must be non-empty.
- Caption timestamps must be ordered when start/end are provided.
- Caption end time must not exceed constraints.max_duration_seconds if provided.
- Fail if captions are missing while constraints.require_captions is true.
- Fail if any caption line exceeds constraints.max_chars_per_line when provided.
- Fail if required word-level timing is missing.

render:
- Require video_path.
- width and height must match constraints.width and constraints.height when provided.
- duration_seconds must be at least constraints.min_duration_seconds when provided.
- duration_seconds must not exceed constraints.max_duration_seconds when provided.
- fps must be positive when provided.
- Reject render errors, missing video, zero-byte video, wrong aspect ratio, or invalid dimensions.
- If constraints.require_audio is true, fail when has_audio is false.
- If constraints.require_captions is true, fail when has_captions is false.

thumbnail:
- Require thumbnail_path or image_path.
- width and height must satisfy constraints.width and constraints.height when provided.
- Reject placeholders, missing files, unsafe clickbait, unreadable text, or zero-byte files.
- If constraints.max_text_chars is provided, overlay_text must not exceed it.

Quality check before final:
- Is passed false when issues exist?
- Are issues short and useful?
- Are repair_notes targeted to the failed stage?
- Is the output valid JSON only?
""".strip()


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
  "issues": ["Title is missing", "Narration is missing", "Narration is too short", "At least 3 image cues are required"],
  "repair_notes": ["Regenerate the script with narration, title, image cues, and the required word range."]
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

USER_INPUT_5 = """
{
  "stage": "assets",
  "artifact": {
    "image_paths": ["runs/run_4/intermediate/images/placeholder_1.jpg", "runs/run_4/intermediate/images/placeholder_2.jpg"],
    "provider_failures": ["Pexels API timeout"],
    "generated_placeholder": true
  },
  "constraints": {"min_images": 2, "require_sources": true}
}
"""

ASSISTANT_OUTPUT_5 = """
{
  "passed": false,
  "issues": ["Online provider failure is present", "Generated placeholders cannot replace required online assets", "Asset sources are missing"],
  "repair_notes": ["Retry online asset fetching or lower the asset requirement before rendering."]
}
"""


MESSAGES_BASE: list[dict[str, str]] = [
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
]


EXPECTED_OUTPUT_KEYS = {"passed", "issues", "repair_notes"}


def shrink_value(value: Any, depth: int = 0) -> Any:
    if depth > 5:
        return clean_text(value, 120)

    if isinstance(value, str):
        return clean_text(value, 500)

    if isinstance(value, int | float | bool) or value is None:
        return value

    if isinstance(value, list):
        return [shrink_value(item, depth + 1) for item in value[:20]]

    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 40:
                break
            result[clean_text(key, 80)] = shrink_value(item, depth + 1)
        return result

    return clean_text(value, 200)


def messages_base() -> list[dict[str, str]]:
    return base_messages(SYSTEM_PROMPT, MESSAGES_BASE[1:])


def build_validation_payload(
    stage: str,
    artifact: dict[str, Any],
    constraints: dict[str, Any] | None = None,
) -> str:
    payload = {
        "stage": clean_text(stage, 40),
        "artifact": shrink_value(artifact),
        "constraints": shrink_value(constraints or {}),
    }

    text = compact_json(payload)
    if len(text) <= MAX_INPUT_CHARS:
        return text

    payload["artifact"] = shrink_value_minimal(artifact)
    text = compact_json(payload)
    if len(text) <= MAX_INPUT_CHARS:
        return text

    return compact_json(
        {
            "stage": clean_text(stage, 40),
            "artifact": {
                "summary": "Artifact was too large for validation input.",
                "keys": list(artifact.keys())[:40] if isinstance(artifact, dict) else [],
            },
            "constraints": shrink_value(constraints or {}),
        }
    )[:MAX_INPUT_CHARS]


def shrink_value_minimal(value: Any) -> Any:
    if isinstance(value, dict):
        keep_keys = [
            "title",
            "narration",
            "hook_line",
            "word_count",
            "estimated_duration",
            "image_cues",
            "sfx_cues",
            "image_paths",
            "video_paths",
            "media_paths",
            "media_types",
            "assets",
            "sources",
            "provider_failures",
            "missing_files",
            "failed_downloads",
            "final_audio_path",
            "duration_ms",
            "word_timestamps",
            "captions",
            "caption_path",
            "subtitle_path",
            "video_path",
            "thumbnail_path",
            "image_path",
            "width",
            "height",
            "duration_seconds",
            "fps",
            "has_audio",
            "has_captions",
            "file_exists",
            "exists",
            "file_size_bytes",
            "errors",
            "error",
            "generated_placeholder",
            "is_placeholder",
        ]
        return {
            key: shrink_value(value[key], 1)
            for key in keep_keys
            if key in value
        }

    return shrink_value(value)


def build_user_input(payload_json: str) -> str:
    try:
        parsed = json.loads(payload_json)
        if isinstance(parsed, dict):
            text = compact_json(shrink_value(parsed))
        else:
            text = compact_json({"stage": "unknown", "artifact": parsed, "constraints": {}})
    except json.JSONDecodeError:
        text = compact_json(
            {
                "stage": "unknown",
                "artifact": {"raw_text": clean_text(payload_json, 2200)},
                "constraints": {},
            }
        )

    if len(text) <= MAX_INPUT_CHARS:
        return text

    return text[:MAX_INPUT_CHARS]


def messages_with_user(payload_json: str) -> list[dict[str, str]]:
    return append_user_message(messages_base(), build_user_input(payload_json), MAX_INPUT_CHARS)


def messages_with_structured_user(
    stage: str,
    artifact: dict[str, Any],
    constraints: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    return append_user_message(
        messages_base(),
        build_validation_payload(
            stage=stage,
            artifact=artifact,
            constraints=constraints,
        ),
        MAX_INPUT_CHARS,
    )


def parse_validation_response(response_text: str) -> dict[str, Any]:
    try:
        data = json.loads(response_text.strip())
    except json.JSONDecodeError as exc:
        raise ValueError(f"VALIDATION response is not valid JSON: {exc}") from exc

    validate_validation_response(data)
    return data


def validate_validation_response(data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise ValueError("VALIDATION response must be a JSON object.")

    actual_keys = set(data.keys())
    if actual_keys != EXPECTED_OUTPUT_KEYS:
        raise ValueError(
            f"VALIDATION response must contain exactly {EXPECTED_OUTPUT_KEYS}, got {actual_keys}."
        )

    passed = data["passed"]
    issues = data["issues"]
    repair_notes = data["repair_notes"]

    if not isinstance(passed, bool):
        raise ValueError("passed must be a boolean.")

    if not isinstance(issues, list):
        raise ValueError("issues must be a list.")

    if not isinstance(repair_notes, list):
        raise ValueError("repair_notes must be a list.")

    if passed and issues:
        raise ValueError("passed cannot be true when issues are present.")

    if not passed and not issues:
        raise ValueError("failed validation must include at least one issue.")

    for issue in issues:
        if not isinstance(issue, str) or not issue.strip():
            raise ValueError("Each issue must be a non-empty string.")
        if len(issue) > 120:
            raise ValueError(f"Issue is too long: {issue!r}")

    for note in repair_notes:
        if not isinstance(note, str) or not note.strip():
            raise ValueError("Each repair note must be a non-empty string.")
        if len(note) > 180:
            raise ValueError(f"Repair note is too long: {note!r}")


if __name__ == "__main__":
    messages = messages_with_structured_user(
        stage="render",
        artifact={
            "video_path": "runs/run_12/output/final.mp4",
            "width": 1080,
            "height": 1920,
            "duration_seconds": 38.5,
            "fps": 30,
            "has_audio": True,
            "has_captions": True,
            "file_size_bytes": 8_200_000,
        },
        constraints={
            "width": 1080,
            "height": 1920,
            "min_duration_seconds": 10,
            "max_duration_seconds": 60,
            "require_audio": True,
            "require_captions": True,
        },
    )

    print(json.dumps(messages, indent=2, ensure_ascii=False))
