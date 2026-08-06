from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


ROUTE_INTENTS = {"generate_video", "edit_video", "chat", "ask_clarifying_question", "save_preference"}


@dataclass
class StyleProfile:
    sample_index: int
    style_id: str
    label: str
    script_angle: str
    pacing: str
    visual_style: str
    audio_style: str
    caption_style: str
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ParameterPatch:
    target_agent: str = ""
    settings_patch: dict[str, Any] = field(default_factory=dict)
    agent_instructions: dict[str, str] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RouteDecision:
    intent: str
    topic: str = ""
    genre: str = ""
    notes: str = ""
    reply_text: str = ""
    needs_clarification: bool = False
    target_agent: str = ""
    parent_job_id: str = ""
    source_prompt: str = ""
    settings_patch: dict[str, Any] = field(default_factory=dict)
    agent_instructions: dict[str, str] = field(default_factory=dict)
    style_profile: dict[str, Any] = field(default_factory=dict)
    planned_agents: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_route_decision(value: dict[str, Any], fallback_genre: str) -> RouteDecision:
    intent = str(value.get("intent") or "").strip().lower()
    if intent not in ROUTE_INTENTS:
        intent = "ask_clarifying_question"
    needs_clarification = bool(value.get("needs_clarification") or intent == "ask_clarifying_question")
    return RouteDecision(
        intent=intent,
        topic=str(value.get("topic") or value.get("source_prompt") or "").strip(),
        genre=str(value.get("genre") or fallback_genre).strip() or fallback_genre,
        notes=str(value.get("notes") or "").strip(),
        reply_text=str(value.get("reply_text") or "").strip(),
        needs_clarification=needs_clarification,
        target_agent=str(value.get("target_agent") or "").strip(),
        parent_job_id=str(value.get("parent_job_id") or "").strip(),
        source_prompt=str(value.get("source_prompt") or value.get("topic") or "").strip(),
        settings_patch=dict(value.get("settings_patch") or {}),
        agent_instructions=dict(value.get("agent_instructions") or {}),
        style_profile=dict(value.get("style_profile") or {}),
        reason=str(value.get("reason") or "").strip(),
    )


def merge_agent_instructions(*items: dict[str, str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for item in items:
        for key, value in (item or {}).items():
            text = str(value or "").strip()
            if not text:
                continue
            merged[key] = f"{merged[key]}\n{text}".strip() if key in merged else text
    return merged

