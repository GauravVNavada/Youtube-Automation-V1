from __future__ import annotations

import json
import re
from typing import Any

from desktop_pipeline.message_base import base_messages, compact_json, system_prompt_with_examples
from desktop_pipeline.route_models import StyleProfile


SYSTEM_PROMPT = """You create calibration style profiles for a short-video generation app.
Return strict JSON only. Create exactly 3 different styles for the same user prompt and genre.
Keep the genre fixed. Do not write the final script. Make the script angle, pacing, visuals,
audio tone, and caption style clearly different across all 3 samples."""


EXAMPLES = [
    {
        "role": "user",
        "content": compact_json(
            {
                "user_prompt": "school hallway where a guy is running from demons",
                "genre_id": "scary_stories",
                "genre_tone": "slow dread, unsettling, cinematic, specific details",
            }
        ),
    },
    {
        "role": "assistant",
        "content": compact_json(
            {
                "styles": [
                    {
                        "label": "Cinematic Slow Build",
                        "script_angle": "Open with the empty hallway and reveal the chase through sound before showing the runner.",
                        "pacing": "Slow first beat, then tightening cuts.",
                        "visual_style": "Dark school corridors, lockers, fluorescent lights, running feet, shadow at the end of hall.",
                        "audio_style": "Low voice with pauses, distant footsteps, tension bed.",
                        "caption_style": "Clean active-word captions with red emphasis on reveal words.",
                        "notes": "Keep it grounded and avoid gore.",
                    },
                    {
                        "label": "Fast Panic Cut",
                        "script_angle": "Start mid-chase and explain the danger through quick concrete details.",
                        "pacing": "Fast hook and fast visual changes.",
                        "visual_style": "Motion blur hallway shots, door handles, emergency lights, closeups of panic.",
                        "audio_style": "Urgent narration and louder breath/footstep moments.",
                        "caption_style": "Bold short captions with punchy highlighted words.",
                        "notes": "Prioritize speed and clarity.",
                    },
                    {
                        "label": "Evidence Reveal",
                        "script_angle": "Treat the chase as something proven by a security camera detail.",
                        "pacing": "Measured clue-to-reveal structure.",
                        "visual_style": "Security camera view, hallway signs, timestamp, door window, empty corridor after reveal.",
                        "audio_style": "Calm narration with a stronger final line.",
                        "caption_style": "Readable captions highlighting times and evidence.",
                        "notes": "Make the ending feel like proof, not fantasy.",
                    },
                ]
            }
        ),
    },
]


def messages_base() -> list[dict[str, str]]:
    return base_messages(SYSTEM_PROMPT, EXAMPLES)


def build_style_profiles(
    user_prompt: str,
    genre_id: str,
    genre_tone: str = "",
    provider: Any | None = None,
) -> list[StyleProfile]:
    if provider is not None:
        try:
            data = provider.generate_json(
                system_prompt_with_examples(SYSTEM_PROMPT, EXAMPLES),
                json.dumps(
                    {
                        "user_prompt": user_prompt,
                        "genre_id": genre_id,
                        "genre_tone": genre_tone,
                        "required_output": {
                            "styles": [
                                {
                                    "label": "short human label",
                                    "script_angle": "how this sample tells the same idea differently",
                                    "pacing": "slow/medium/fast and why",
                                    "visual_style": "asset/search style",
                                    "audio_style": "voice/music direction",
                                    "caption_style": "caption direction",
                                    "notes": "one sentence instruction for the generation agents",
                                }
                            ]
                        },
                    },
                    ensure_ascii=True,
                ),
                1200,
            )
            profiles = _profiles_from_llm(data, genre_id)
            if len(profiles) == 3 and len({item.style_id for item in profiles}) == 3:
                return profiles
        except Exception:
            pass
    return default_style_profiles(user_prompt, genre_id, genre_tone)


def default_style_profiles(user_prompt: str, genre_id: str, genre_tone: str = "") -> list[StyleProfile]:
    base = _topic_terms(user_prompt)
    tone = genre_tone or genre_id.replace("_", " ")
    templates = [
        (
            "cinematic_slow_build",
            "Cinematic Slow Build",
            f"Open with one specific image from {base}, then build toward the key reveal.",
            "Slow start, medium middle, sharp ending.",
            f"Cinematic closeups, grounded locations, and subject-locked visuals for {base}.",
            "Controlled voice with short pauses before reveals.",
            "Clean active-word captions with restrained emphasis.",
        ),
        (
            "fast_conflict_cut",
            "Fast Conflict Cut",
            f"Start at the conflict in {base}, then explain only the details needed to follow it.",
            "Fast hook, quick visual changes, no long setup.",
            f"Action-heavy visuals, reaction shots, and concrete objects tied to {base}.",
            "Slightly more urgent voice and tighter pauses.",
            "Bold captions with punchy highlighted words.",
        ),
        (
            "evidence_reveal",
            "Evidence Reveal",
            f"Frame {base} around evidence, clues, or visible proof before the final point.",
            "Measured pacing with a clear clue-to-reveal structure.",
            f"Documents, screens, objects, places, and evidence-focused visuals for {base}.",
            "Calm narration with a stronger final reveal.",
            "Readable captions that highlight names, times, and evidence.",
        ),
    ]
    return [
        StyleProfile(
            sample_index=index,
            style_id=style_id,
            label=label,
            script_angle=angle,
            pacing=pacing,
            visual_style=visual,
            audio_style=audio,
            caption_style=caption,
            notes=f"Keep the genre as {tone}. {angle} {visual}",
        )
        for index, (style_id, label, angle, pacing, visual, audio, caption) in enumerate(templates, start=1)
    ]


def style_profile_to_notes(profile: dict[str, Any] | StyleProfile | None) -> str:
    if profile is None:
        return ""
    data = profile.to_dict() if isinstance(profile, StyleProfile) else dict(profile)
    parts = [
        data.get("label"),
        data.get("script_angle"),
        data.get("pacing"),
        data.get("visual_style"),
        data.get("audio_style"),
        data.get("caption_style"),
        data.get("notes"),
    ]
    return " | ".join(str(part).strip() for part in parts if str(part or "").strip())


def _profiles_from_llm(data: dict[str, Any], genre_id: str) -> list[StyleProfile]:
    rows = data.get("styles") if isinstance(data.get("styles"), list) else []
    profiles = []
    for index, item in enumerate(rows[:3], start=1):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or f"Style {index}").strip()
        style_id = _slug(label) or f"style_{index}"
        profiles.append(
            StyleProfile(
                sample_index=index,
                style_id=style_id,
                label=label,
                script_angle=str(item.get("script_angle") or "").strip(),
                pacing=str(item.get("pacing") or "").strip(),
                visual_style=str(item.get("visual_style") or "").strip(),
                audio_style=str(item.get("audio_style") or "").strip(),
                caption_style=str(item.get("caption_style") or "").strip(),
                notes=str(item.get("notes") or f"Keep genre fixed as {genre_id}.").strip(),
            )
        )
    return profiles


def _slug(text: str) -> str:
    return "_".join(re.findall(r"[a-z0-9]+", text.lower()))[:60]


def _topic_terms(text: str) -> str:
    terms = [item for item in re.findall(r"[a-zA-Z0-9]+", text) if len(item) > 2]
    return " ".join(terms[:8]) or "the selected idea"
