from __future__ import annotations

import json
from typing import Any

from desktop_pipeline.message_base import base_messages, compact_json, system_prompt_with_examples
from desktop_pipeline.parameter_agent import looks_like_edit_request, map_parameter_request
from desktop_pipeline.route_models import RouteDecision, merge_agent_instructions, normalize_route_decision


SYSTEM_PROMPT = """You are the MASTER_AGENT for an Electron short-video desktop app.
You read the current chat history, selected calibration style, latest video job, settings,
and user message. Decide whether to generate a new video, remake the selected/latest video
with parameter changes, ask a clarification, save a preference, or chat briefly.

Return strict JSON only with:
intent: generate_video | edit_video | ask_clarifying_question | save_preference | chat
topic: concrete video topic or source prompt
genre: genre id, keep the selected genre unless user explicitly asks otherwise
needs_clarification: boolean
target_agent: audio_agent | asset_agent | caption_agent | script_agent | render_agent | empty
settings_patch: object with only changed settings
agent_instructions: object keyed by target agent name
notes: concise generation/repair notes
reply_text: short user-facing response
reason: concise routing reason

Rules:
- After calibration, edit requests like "audio is too fast" should become edit_video for the latest job.
- Do not queue vague prompts. Ask for one concrete detail.
- Keep the selected style and genre unless the user clearly asks to change them.
- Do not create scripts, assets, captions, or final video content here."""


EXAMPLES = [
    {
        "role": "user",
        "content": compact_json(
            {
                "message": "make a video about a school hallway chase",
                "selected_genre": "scary_stories",
                "latest_job": {},
                "selected_calibration": {"style_profile": {"label": "Cinematic Slow Build"}},
            }
        ),
    },
    {
        "role": "assistant",
        "content": compact_json(
            {
                "intent": "generate_video",
                "topic": "school hallway chase",
                "genre": "scary_stories",
                "needs_clarification": False,
                "target_agent": "",
                "settings_patch": {},
                "agent_instructions": {},
                "notes": "Use the selected calibrated style.",
                "reply_text": "I queued one video for: school hallway chase",
                "reason": "Concrete new topic after calibration.",
            }
        ),
    },
    {
        "role": "user",
        "content": compact_json(
            {
                "message": "audio is too fast and images are not good",
                "selected_genre": "scary_stories",
                "latest_job": {
                    "id": "job-123",
                    "topic": "school hallway chase",
                    "settings": {"voice_speed": 1.0, "image_count": 8, "source_prompt": "school hallway chase"},
                },
            }
        ),
    },
    {
        "role": "assistant",
        "content": compact_json(
            {
                "intent": "edit_video",
                "topic": "school hallway chase",
                "genre": "scary_stories",
                "needs_clarification": False,
                "target_agent": "audio_agent",
                "settings_patch": {"voice_speed": 0.88, "image_count": 10},
                "agent_instructions": {"asset_agent": "Replace weak or repeated visuals with subject-matched assets."},
                "notes": "Remake one child video from the latest job.",
                "reply_text": "I queued a single updated version using the selected style.",
                "reason": "User requested parameter and asset fixes to the latest video.",
            }
        ),
    },
]


def messages_base() -> list[dict[str, str]]:
    return base_messages(SYSTEM_PROMPT, EXAMPLES)


class MasterAgent:
    def __init__(self, provider: Any | None = None, require_provider: bool = True) -> None:
        self.provider = provider
        self.require_provider = require_provider

    def decide(self, message: str, context: dict[str, Any]) -> RouteDecision:
        fallback_genre = str(context.get("genre_id") or "scary_stories")
        latest_job = context.get("latest_job") or {}
        current_settings = dict(latest_job.get("settings") or context.get("settings") or {})
        parameter_patch = map_parameter_request(message, current_settings)

        if self.provider is None and self.require_provider:
            return self._clarify(
                fallback_genre,
                "Gemini is required for the desktop master agent. Configure a Gemini key before routing this request.",
            )

        if self.provider is None:
            decision = self._rule_decision(message, context, parameter_patch)
        else:
            try:
                data = self.provider.generate_json(
                    system_prompt_with_examples(SYSTEM_PROMPT, EXAMPLES),
                    json.dumps(_route_payload(message, context), ensure_ascii=True),
                    1000,
                )
                decision = normalize_route_decision(data, fallback_genre)
            except Exception as exc:
                return self._clarify(
                    fallback_genre,
                    f"I could not safely route that request with Gemini: {str(exc)[:180]}",
                )

        if parameter_patch.settings_patch or parameter_patch.agent_instructions:
            if latest_job:
                decision.intent = "edit_video"
                decision.parent_job_id = str(latest_job.get("id") or "")
                decision.topic = str(latest_job.get("topic") or decision.topic or message).strip()
                decision.source_prompt = str(
                    (latest_job.get("settings") or {}).get("source_prompt")
                    or latest_job.get("topic")
                    or decision.source_prompt
                    or decision.topic
                ).strip()
                decision.target_agent = parameter_patch.target_agent or decision.target_agent
                decision.settings_patch = {**decision.settings_patch, **parameter_patch.settings_patch}
                decision.agent_instructions = merge_agent_instructions(
                    decision.agent_instructions,
                    parameter_patch.agent_instructions,
                )
                decision.reason = parameter_patch.reason or decision.reason
                decision.needs_clarification = False
            else:
                return self._clarify(fallback_genre, "Tell me which video to change, or generate one first.")

        if decision.intent == "edit_video" and not latest_job and not decision.parent_job_id:
            return self._clarify(fallback_genre, "I need an existing video before I can remake it.")

        if decision.intent == "generate_video" and not _has_concrete_topic(decision.topic or decision.source_prompt or message):
            return self._clarify(fallback_genre, "Tell me one concrete subject, place, person, event, or scene for the video.")

        if decision.intent == "edit_video" and not decision.source_prompt:
            decision.source_prompt = str(latest_job.get("topic") or decision.topic or message).strip()

        if decision.intent == "generate_video" and not decision.source_prompt:
            decision.source_prompt = decision.topic or message

        if not decision.reply_text:
            decision.reply_text = _default_reply(decision)
        return decision

    def _rule_decision(self, message: str, context: dict[str, Any], parameter_patch) -> RouteDecision:
        latest_job = context.get("latest_job") or {}
        genre = str(context.get("genre_id") or "scary_stories")
        if latest_job and (parameter_patch.settings_patch or looks_like_edit_request(message)):
            return RouteDecision(
                intent="edit_video",
                topic=str(latest_job.get("topic") or "").strip(),
                genre=genre,
                source_prompt=str((latest_job.get("settings") or {}).get("source_prompt") or latest_job.get("topic") or "").strip(),
                parent_job_id=str(latest_job.get("id") or ""),
                target_agent=parameter_patch.target_agent,
                settings_patch=parameter_patch.settings_patch,
                agent_instructions=parameter_patch.agent_instructions,
                reason=parameter_patch.reason,
            )
        return RouteDecision(intent="generate_video", topic=message.strip(), genre=genre, source_prompt=message.strip())

    @staticmethod
    def _clarify(genre: str, message: str) -> RouteDecision:
        return RouteDecision(
            intent="ask_clarifying_question",
            genre=genre,
            needs_clarification=True,
            reply_text=message,
            reason="clarification required",
        )


def _route_payload(message: str, context: dict[str, Any]) -> dict[str, Any]:
    return {
        "message": message,
        "selected_genre": context.get("genre_id") or "scary_stories",
        "user_intent": context.get("user_intent") or "",
        "selected_calibration": context.get("calibration") or {},
        "latest_job": context.get("latest_job") or {},
        "recent_feedback": context.get("feedback") or [],
        "chat_history": (context.get("chat_history") or [])[-12:],
    }


def _has_concrete_topic(text: str) -> bool:
    useful = [word for word in str(text or "").split() if len(word.strip(".,!?")) > 2]
    return len(useful) >= 3


def _default_reply(decision: RouteDecision) -> str:
    if decision.intent == "edit_video":
        return "I queued a single updated version using the selected style."
    if decision.intent == "generate_video":
        return f"I queued one video for: {decision.topic or decision.source_prompt}"
    if decision.intent == "save_preference":
        return "I saved that preference for the next generation."
    if decision.intent == "chat":
        return "Tell me the video idea or the change you want."
    return "Tell me one more concrete detail for the video."
