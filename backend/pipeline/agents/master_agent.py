from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


MIN_DURATION_SECONDS = 10
MAX_DURATION_SECONDS = 180
MIN_VOICE_SPEED = 0.65
MAX_VOICE_SPEED = 1.4

DEFAULT_GENERATION_SETTINGS: dict[str, Any] = {
    "duration": 30,
    "voice_speed": 1.0,
    "caption_words": 4,
    "image_count": 8,
    "music_volume": 0.18,
    "schedule": "now",
}

_DURATION_RE = re.compile(r"\b([1-9]\d{0,2})\s*(?:second|seconds|sec|secs|s)\b", re.IGNORECASE)
_VOICE_SPEED_RE = re.compile(
    r"\b(?:voice\s*speed|speaking\s*rate|speed)\s*(?:is|=|:)?\s*(0\.\d+|1(?:\.\d+)?|1\.4)\s*x?\b",
    re.IGNORECASE,
)
_CAPTION_WORDS_RE = re.compile(r"\b(?:caption\s*words|words\s*per\s*caption)\s*(?:is|=|:)?\s*([1-9]\d?)\b", re.IGNORECASE)
_IMAGE_COUNT_RE = re.compile(r"\b([1-9]\d?)\s*(?:images|frames|visuals|photos)\b", re.IGNORECASE)
_MUSIC_VOLUME_RE = re.compile(r"\b(?:music\s*volume|bgm\s*volume)\s*(?:is|=|:)?\s*(0(?:\.\d+)?|0?\.?\d+)\b", re.IGNORECASE)


@dataclass(frozen=True)
class MasterDecision:
    intent: str
    assistant_message: str
    topic: str = ""
    genre: str = "scary_stories"
    duration: int = 30
    notes: str = ""
    settings: dict[str, Any] | None = None
    parent_job_id: str = ""
    planned_agents: list[dict[str, Any]] | None = None
    constraints: dict[str, Any] | None = None
    agent_contracts: list[dict[str, Any]] | None = None
    ai_master_decision: dict[str, Any] | None = None


@dataclass(frozen=True)
class MasterContext:
    onboarding_complete: bool = False
    genre_id: str = "scary_stories"
    user_intent: str = ""
    preferred_script: str = ""
    calibration_notes: str = ""
    preferred_settings: dict[str, Any] | None = None
    latest_generation_topic: str = ""
    latest_generation_job_id: str = ""
    latest_generation_settings: dict[str, Any] | None = None
    feedback_notes: list[str] | None = None


class MasterAgent:
    """GenAI-backed global orchestrator for chat and video generation routing."""

    name = "master_agent"

    def __init__(self, ai_client: Any | None = None):
        self.ai_client = ai_client

    def decide(self, message: str, history: list[Any], context: MasterContext | None = None) -> MasterDecision:
        context = context or MasterContext()
        if self.ai_client:
            try:
                return self._decide_with_ai(message, history, context)
            except Exception as exc:
                logger.warning("AI master decision failed; falling back to deterministic route: %s", exc)
        return self._decide_with_rules(message, history, context)

    def _decide_with_ai(self, message: str, history: list[Any], context: MasterContext) -> MasterDecision:
        normalized = message.strip()
        lower = normalized.lower()
        base_genre = self._extract_genre(lower, history, context)
        base_settings = self._extract_settings(normalized, history, context)
        ai = self.ai_client.decide(
            message=normalized,
            history=history,
            context=context,
            base_genre=base_genre,
            base_settings=base_settings,
        )
        intent = str(ai.get("intent") or "chat").strip()
        assistant_message = str(ai.get("assistant_message") or "").strip()
        if intent in {"chat", "ask_clarifying_question", "save_preference"}:
            return MasterDecision(
                intent=intent,
                assistant_message=assistant_message or self._generic_reply(lower, context),
                ai_master_decision=ai,
            )

        is_change_request = bool(ai.get("is_change_request")) or self._looks_like_change_request(lower)
        if is_change_request and not context.onboarding_complete:
            return MasterDecision(
                intent="ask_clarifying_question",
                assistant_message=(
                    "I can make those changes after we lock one style sample. "
                    "Please finish the initial 3-sample calibration first, then I will generate one updated video."
                ),
                ai_master_decision=ai,
            )

        genre = str(ai.get("genre") or base_genre).strip() or base_genre
        ai_settings = ai.get("settings") if isinstance(ai.get("settings"), dict) else {}
        settings = normalize_generation_settings({**base_settings, **ai_settings}, text=normalized, prefer_text=True)
        duration = int(settings["duration"])
        topic = str(ai.get("topic") or "").strip()
        if not topic:
            topic = self._extract_topic(normalized, context, is_change_request=is_change_request)
        if is_change_request:
            topic = topic or context.latest_generation_topic or context.user_intent or normalized
        if len(topic.split()) < 3:
            return MasterDecision(
                intent="ask_clarifying_question",
                assistant_message=(
                    assistant_message
                    or "I can generate it, but I need one clear topic detail first. For example: a haunted hospital in Japan."
                ),
                ai_master_decision=ai,
            )

        constraints = generation_constraints(settings, genre_id=genre, duration=duration)
        contracts = build_agent_contracts(settings, genre_id=genre, duration=duration)
        notes = self._build_notes(
            history,
            context,
            normalized,
            is_change_request=is_change_request,
            constraints=constraints,
            contracts=contracts,
            ai_decision=ai,
        )
        label = "updated" if is_change_request else "new"
        return MasterDecision(
            intent="generate_video",
            topic=topic,
            genre=genre,
            duration=duration,
            notes=notes,
            settings=settings,
            parent_job_id=context.latest_generation_job_id if is_change_request else "",
            planned_agents=contracts,
            constraints=constraints,
            agent_contracts=contracts,
            ai_master_decision=ai,
            assistant_message=self._build_generation_reply(
                label,
                duration,
                genre,
                topic,
                constraints,
                contracts,
                ai_message=assistant_message,
            ),
        )

    def _decide_with_rules(self, message: str, history: list[Any], context: MasterContext) -> MasterDecision:
        normalized = message.strip()
        lower = normalized.lower()
        if self._is_generic_chat(lower):
            return MasterDecision(intent="chat", assistant_message=self._generic_reply(lower, context))

        is_generation_request = self._looks_like_generation_request(lower)
        is_change_request = self._looks_like_change_request(lower)
        if is_generation_request or is_change_request:
            if is_change_request and not context.onboarding_complete:
                return MasterDecision(
                    intent="ask_clarifying_question",
                    assistant_message=(
                        "I can make those changes after we lock one style sample. "
                        "Please finish the initial 3-sample calibration first, then I will generate one updated video."
                    ),
                )

            genre = self._extract_genre(lower, history, context)
            settings = self._extract_settings(normalized, history, context)
            duration = int(settings["duration"])
            topic = self._extract_topic(normalized, context, is_change_request=is_change_request)
            if len(topic.split()) < 3:
                return MasterDecision(
                    intent="ask_clarifying_question",
                    assistant_message=(
                        "I can generate it, but I need one clear topic detail first. "
                        "For example: 'a haunted hospital in Japan' or 'a Reddit story about a tenant hearing letters inside the wall.'"
                    ),
                )
            constraints = generation_constraints(settings, genre_id=genre, duration=duration)
            contracts = build_agent_contracts(settings, genre_id=genre, duration=duration)
            notes = self._build_notes(
                history,
                context,
                normalized,
                is_change_request=is_change_request,
                constraints=constraints,
                contracts=contracts,
            )
            label = "updated" if is_change_request else "new"
            return MasterDecision(
                intent="generate_video",
                topic=topic,
                genre=genre,
                duration=duration,
                notes=notes,
                settings=settings,
                parent_job_id=context.latest_generation_job_id if is_change_request else "",
                planned_agents=contracts,
                constraints=constraints,
                agent_contracts=contracts,
                assistant_message=self._build_generation_reply(label, duration, genre, topic, constraints, contracts),
            )

        return MasterDecision(
            intent="chat",
            assistant_message=(
                "Tell me the short you want to create, including genre and duration if you have a preference. "
                "For example: generate a 30 second scary story about a lighthouse. "
                "You can also say things like 'make the voice slower and use 12 visual cues' after choosing a style."
            ),
        )

    def _is_generic_chat(self, lower: str) -> bool:
        cleaned = re.sub(r"[^a-z\s]", "", lower).strip()
        if self._looks_like_generation_request(cleaned) or self._looks_like_change_request(cleaned):
            return False
        generic = {
            "hi",
            "hello",
            "hey",
            "how are you",
            "what are you doing",
            "what can you do",
            "who are you",
            "thanks",
            "thank you",
        }
        return cleaned in generic or cleaned.startswith(("hi ", "hello ", "hey "))

    def _generic_reply(self, lower: str, context: MasterContext) -> str:
        if "what are you doing" in lower or "what can you do" in lower:
            if context.onboarding_complete:
                return "I am ready to turn your chosen style into one final video. Tell me the topic or changes, like 'make the voice slower and add more visual variety.'"
            return "I am helping you set up the creator pipeline. First we choose a genre, generate 3 style samples, then you pick one style."
        if "how are you" in lower:
            return "I am good and ready to help. Tell me the video idea or the changes you want, and I will route it properly."
        return "Hi. I can help generate one final short after the initial style calibration, or adjust voice, captions, visuals, pacing, and music."

    def _looks_like_generation_request(self, lower: str) -> bool:
        triggers = ("generate", "make", "create", "render", "video", "short", "youtube")
        return any(trigger in lower for trigger in triggers)

    def _looks_like_change_request(self, lower: str) -> bool:
        change_words = (
            "change", "adjust", "modify", "update", "redo", "regenerate", "make it", "make the",
            "slower", "faster", "more images", "more frames", "more visuals", "less music", "louder", "quieter",
            "captions", "caption", "voice", "audio", "music", "pacing", "speed",
        )
        return any(word in lower for word in change_words)

    def _extract_topic(self, message: str, context: MasterContext, is_change_request: bool = False) -> str:
        if is_change_request:
            return context.latest_generation_topic or context.user_intent or message.strip()
        cleaned = re.sub(r"\b(generate|make|create|render)\b", "", message, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(i\s+want|i\s+need|can\s+you|please|plz)\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(a|an)?\s*(youtube)?\s*(short|video)\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b([1-9]\d{0,2})\s*(second|seconds|sec|secs|s)\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(scary|horror|reddit|story|stories)\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^\s*(a|an)\s+(on|about|for)\s+", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^\s*(on|about|for)\s+", "", cleaned, flags=re.IGNORECASE)
        topic = " ".join(cleaned.replace(":", " ").split())
        return topic or context.latest_generation_topic or context.user_intent or message.strip()

    def _extract_duration(self, lower: str, history: list[Any]) -> int:
        duration = extract_duration_seconds(lower)
        if duration is not None:
            return duration
        for previous in reversed(history):
            duration = extract_duration_seconds(str(getattr(previous, "content", "")))
            if duration is not None:
                return duration
        return 30

    def _extract_settings(self, message: str, history: list[Any], context: MasterContext) -> dict[str, Any]:
        text = "\n".join([str(getattr(item, "content", "")) for item in history[-4:]] + [message])
        base = context.latest_generation_settings or context.preferred_settings or {}
        settings = normalize_generation_settings(base, text=text, prefer_text=True)
        settings["duration"] = self._extract_duration(message.lower(), history)
        if extract_duration_seconds(message) is None and base.get("duration"):
            settings["duration"] = int(base["duration"])
        return settings

    def _extract_genre(self, lower: str, history: list[Any], context: MasterContext) -> str:
        if "reddit" in lower:
            return "reddit_stories"
        if any(word in lower for word in ("scary", "horror", "ghost", "haunted")):
            return "scary_stories"
        if context.genre_id:
            return context.genre_id
        for previous in reversed(history):
            previous_lower = str(getattr(previous, "content", "")).lower()
            if "reddit" in previous_lower:
                return "reddit_stories"
            if any(word in previous_lower for word in ("scary", "horror", "ghost", "haunted")):
                return "scary_stories"
        return "scary_stories"

    def _build_generation_reply(
        self,
        label: str,
        duration: int,
        genre: str,
        topic: str,
        constraints: dict[str, Any],
        contracts: list[dict[str, Any]],
        ai_message: str = "",
    ) -> str:
        route = compact_agent_route(contracts)
        word_range = constraints["narration_word_count"]
        opening = (
            f"AI master decision: {ai_message}\n\n"
            if ai_message and not ai_message.lower().startswith("i queued")
            else ""
        )
        return (
            opening
            +
            f"I queued one {label} {duration}s {genre.replace('_', ' ')} video for: {topic}.\n\n"
            "Master route locked these hard constraints: "
            f"{word_range['min']}-{word_range['max']} spoken words, "
            f"{constraints['image_count']} visual cues, voice speed {constraints['voice_speed_multiplier']}x, "
            f"{constraints['caption_words_per_phrase']} words per caption, music volume {constraints['music_volume']}.\n\n"
            "Agent plan:\n"
            f"{route}"
        )

    def _build_notes(
        self,
        history: list[Any],
        context: MasterContext,
        current_request: str,
        is_change_request: bool = False,
        constraints: dict[str, Any] | None = None,
        contracts: list[dict[str, Any]] | None = None,
        ai_decision: dict[str, Any] | None = None,
    ) -> str:
        user_messages = [str(getattr(msg, "content", "")) for msg in history[-6:] if getattr(msg, "role", "") == "user"]
        parts = [
            "Guardrails: generate only safe, production-ready short-video content. Do not include private secrets, API keys, hateful content, sexual content involving minors, or instructions for wrongdoing.",
            "Use simple, easy English and natural spoken pacing.",
        ]
        if context.user_intent:
            parts.append(f"Original user intent: {context.user_intent}")
        if context.calibration_notes:
            parts.append(f"Selected style notes: {context.calibration_notes}")
        if context.preferred_script:
            parts.append(f"Reference selected sample script: {context.preferred_script[:700]}")
        if is_change_request:
            parts.append(f"Apply this user change request: {current_request}")
        if context.feedback_notes:
            parts.append("Avoid these previous mistakes:")
            parts.extend(f"- {item}" for item in context.feedback_notes[:5])
        if user_messages:
            parts.append("Recent chat context:")
            parts.extend(user_messages[-4:])
        if constraints:
            parts.append(f"Master constraints JSON: {json.dumps(constraints, ensure_ascii=True)}")
        if contracts:
            parts.append("Agent contracts summary:")
            parts.append(compact_agent_route(contracts))
        if ai_decision:
            safe_decision = dict(ai_decision)
            safe_decision.pop("assistant_message", None)
            parts.append(f"AI master decision JSON: {json.dumps(safe_decision, ensure_ascii=True)[:5000]}")
        return "\n".join(part for part in parts if str(part).strip())


def normalize_generation_settings(
    settings: dict[str, Any] | None = None,
    text: str = "",
    prefer_text: bool = False,
) -> dict[str, Any]:
    """Normalize user-facing generation controls into safe pipeline limits."""
    normalized = dict(DEFAULT_GENERATION_SETTINGS)
    normalized.update({key: value for key, value in (settings or {}).items() if value is not None})

    parsed_duration = extract_duration_seconds(text)
    if parsed_duration is not None and prefer_text:
        normalized["duration"] = parsed_duration

    parsed_voice_speed = _extract_float(_VOICE_SPEED_RE, text)
    if parsed_voice_speed is not None and prefer_text:
        normalized["voice_speed"] = parsed_voice_speed

    caption_words = _extract_int(_CAPTION_WORDS_RE, text)
    if caption_words is not None and prefer_text:
        normalized["caption_words"] = caption_words

    image_count = _extract_int(_IMAGE_COUNT_RE, text)
    if image_count is not None and prefer_text:
        normalized["image_count"] = image_count

    music_volume = _extract_float(_MUSIC_VOLUME_RE, text)
    if music_volume is not None and prefer_text:
        normalized["music_volume"] = music_volume

    if prefer_text:
        lowered = text.lower()
        if parsed_voice_speed is None and any(word in lowered for word in ("slower voice", "slow voice", "speak slower")):
            normalized["voice_speed"] = 0.9
        if parsed_voice_speed is None and any(word in lowered for word in ("faster voice", "fast voice", "speak faster")):
            normalized["voice_speed"] = 1.1

    normalized["duration"] = _clamp_int(normalized.get("duration"), MIN_DURATION_SECONDS, MAX_DURATION_SECONDS, DEFAULT_GENERATION_SETTINGS["duration"])
    normalized["voice_speed"] = _clamp_float(normalized.get("voice_speed"), MIN_VOICE_SPEED, MAX_VOICE_SPEED, DEFAULT_GENERATION_SETTINGS["voice_speed"])
    normalized["caption_words"] = _clamp_int(normalized.get("caption_words"), 1, 10, DEFAULT_GENERATION_SETTINGS["caption_words"])
    normalized["image_count"] = _clamp_int(normalized.get("image_count"), 3, 24, DEFAULT_GENERATION_SETTINGS["image_count"])
    normalized["music_volume"] = _clamp_float(normalized.get("music_volume"), 0.0, 0.8, DEFAULT_GENERATION_SETTINGS["music_volume"])
    normalized["schedule"] = str(normalized.get("schedule") or "now")
    return normalized


def extract_duration_seconds(text: str) -> int | None:
    """Extract an explicit duration from natural text."""
    match = _DURATION_RE.search(text or "")
    if not match:
        return None
    return _clamp_int(match.group(1), MIN_DURATION_SECONDS, MAX_DURATION_SECONDS, DEFAULT_GENERATION_SETTINGS["duration"])


def generation_constraints(
    settings: dict[str, Any] | None = None,
    *,
    genre_id: str = "scary_stories",
    duration: int | None = None,
) -> dict[str, Any]:
    """Build hard route constraints for downstream agents."""
    base = dict(settings or {})
    if duration is not None:
        base["duration"] = duration
    normalized = normalize_generation_settings(base)
    seconds = int(normalized["duration"])
    min_words = max(18, int(seconds * 1.75))
    max_words = max(min_words + 8, int(seconds * 2.55))
    if seconds < 30:
        max_words += 5
    target_max_words = max(min_words, max_words - _word_safety_margin(seconds))
    target_words = max(min_words, int((min_words + target_max_words) / 2))
    image_count = max(int(normalized["image_count"]), _minimum_image_cues(seconds))
    return {
        "genre_id": genre_id,
        "duration_seconds": seconds,
        "narration_word_count": {"min": min_words, "max": max_words},
        "script_target_word_count": target_words,
        "script_target_word_count_max": target_max_words,
        "script_word_safety_margin": max_words - target_max_words,
        "image_count": image_count,
        "voice_speed_multiplier": float(normalized["voice_speed"]),
        "caption_words_per_phrase": int(normalized["caption_words"]),
        "music_volume": float(normalized["music_volume"]),
        "schedule": str(normalized["schedule"]),
        "language": "layman English for a 12-year-old, short spoken sentences, common words, clear cause-and-effect",
        "script_format": "strict JSON object only; no markdown, comments, trailing commas, or extra text",
        "growth_policy": "discover a niche-specific angle and research brief before script generation; continue with local fallbacks if free web sources fail",
        "asset_policy": "prefer online stock video b-roll when keys exist; keep free/no-key image fallbacks for every cue; every cue must name visible nouns plus setting/context",
        "audio_policy": "prefer Google TTS when configured; otherwise use EdgeTTS with Whisper word alignment",
        "repair_policy": "script must pass deterministic self-check and validation before assets/audio/captions/render start; weak endings, missing alert beats, and hard words must be repaired",
    }


def build_agent_contracts(
    settings: dict[str, Any] | None = None,
    *,
    genre_id: str = "scary_stories",
    duration: int | None = None,
) -> list[dict[str, Any]]:
    """Describe each agent's task, inputs, outputs, and constraints."""
    constraints = generation_constraints(settings, genre_id=genre_id, duration=duration)
    return [
        _contract(
            "master_agent",
            "Master",
            "Understands the chat, locks route constraints, and decides which agents should run.",
            ["message", "chat_history", "profile", "settings"],
            ["intent", "topic", "genre", "constraints", "planned_agents"],
            [
                "Ask a clarifying question if the topic is not clear enough.",
                "Lock duration, image count, voice speed, caption density, and music volume before queueing.",
                "Never pass secrets into prompts or logs.",
            ],
        ),
        _contract(
            "topic_discovery_agent",
            "Discovery",
            "Finds free/no-key topic angles and local niche guidance before script writing.",
            ["topic", "genre", "reference_scripts", "niche_profile"],
            ["selected_topic", "selected_angle", "candidates", "niche_profile", "title_hints"],
            [
                "Use no-key web signals and local references only.",
                "If web calls fail, continue with genre/profile/reference fallbacks.",
                "Prefer angles with clear stakes, novelty, and visual potential.",
            ],
        ),
        _contract(
            "research_agent",
            "Research",
            "Builds a short source-backed brief for the selected angle without blocking generation.",
            ["selected_topic", "selected_angle", "genre", "free_sources"],
            ["brief", "facts", "source_snippets", "search_queries"],
            [
                "Use free/no-key sources only and log failures as non-fatal events.",
                "Keep facts short enough to guide a Shorts script.",
                "Never require research success before script generation.",
            ],
        ),
        _contract(
            "script_agent",
            "Script",
            "Writes the strict JSON script plan: narration, hook, title, metadata, image cues, SFX cues, and emphasis words.",
            ["topic", "genre", "duration", "reference_scripts", "user_notes", "growth_context"],
            ["title", "narration", "hook_line", "image_cues", "sfx_cues", "emphasis_words"],
            [
                f"Hard max is {constraints['narration_word_count']['max']} words; target {constraints['script_target_word_count']} words and never exceed {constraints['script_target_word_count_max']} words.",
                f"Create at least {constraints['image_count']} meaningful visual cues.",
                "Apply niche hook/style guidance and research facts without overloading the narration.",
                "Return valid JSON only and keep the narration in layman English with short, common words.",
            ],
        ),
        _contract(
            "validation_agent",
            "Validation",
            "Checks each stage output and blocks downstream work until required constraints pass.",
            ["stage_output", "constraints"],
            ["passed", "issues", "repair_notes"],
            [
                "Script validation failure must trigger script auto-repair before assets begin.",
                "Audio must contain Google TTS or EdgeTTS narration, Whisper word timestamps, and no long silent gaps.",
                "Render must be 1080x1920 MP4 with a playable audio stream.",
            ],
        ),
        _contract(
            "asset_agent",
            "Assets",
            "Turns visual and SFX cues into stock video clips and free image fallbacks for the renderer.",
            ["image_cues", "sfx_cues", "image_provider_keys"],
            ["video_paths", "image_paths", "sfx_paths", "music_path", "sources"],
            [
                "Prefer Pexels stock videos when available and keep Pexels, Pixabay, Openverse, Wikimedia, or Bing image fallbacks for resilience.",
                f"Produce enough visual media to satisfy image_count={constraints['image_count']}.",
                "Search concrete cue variants in parallel and preserve final scene order.",
            ],
        ),
        _contract(
            "audio_agent",
            "Voice",
            "Creates real narrator speech and aligned word timestamps for captions.",
            ["narration", "word_count", "duration", "voice_speed_multiplier", "google_tts_credentials", "edge_tts_voice"],
            ["narration_path", "final_audio_path", "word_timestamps", "audio_health"],
            [
                "Use Google TTS when configured; fall back to EdgeTTS when credentials are missing or Google TTS fails.",
                f"Apply voice_speed_multiplier={constraints['voice_speed_multiplier']}.",
                "Protect first-word audio with a pre-word guard and keep sentence pauses natural.",
            ],
        ),
        _contract(
            "caption_agent",
            "Captions",
            "Builds SRT and ASS captions from word-level audio timing.",
            ["word_timestamps", "caption_preset", "emphasis_words", "words_per_caption"],
            ["srt_path", "ass_path", "phrase_count"],
            [
                f"Use around {constraints['caption_words_per_phrase']} words per caption phrase.",
                "Never invent timing; captions must come from actual word timestamps.",
                "Keep punctuation breaks readable without skipping the first word of a sentence.",
            ],
        ),
        _contract(
            "render_agent",
            "Render",
            "Composes stock video clips, image fallbacks, captions, narration, and music into the final vertical MP4.",
            ["assets", "audio", "captions", "music_volume"],
            ["video_path", "width", "height", "duration_seconds"],
            [
                "Render 1080x1920 vertical video.",
                f"Use background music volume={constraints['music_volume']}.",
                "Write a render_plan.json artifact describing clip order and fallbacks.",
                "Final MP4 must include a playable narration audio stream.",
            ],
        ),
        _contract(
            "thumbnail_agent",
            "Thumbnail",
            "Creates free deterministic Shorts cover and YouTube thumbnail images after render.",
            ["video_path", "image_paths", "title", "hook_line", "niche_profile"],
            ["shorts_cover_path", "youtube_thumbnail_path", "source_image_path", "text_lines"],
            [
                "Generate a 1080x1920 Shorts cover and a 1280x720 YouTube thumbnail.",
                "Prefer a frame from the rendered video and fall back to fetched images.",
                "Use local Pillow templates with safe font fallback; no paid image generation.",
            ],
        ),
    ]


def compact_agent_route(contracts: list[dict[str, Any]]) -> str:
    """Return a short route explanation for user-facing master replies."""
    lines = []
    for contract in contracts:
        constraints = "; ".join(contract["constraints"][:2])
        lines.append(f"{contract['label']}: {contract['description']} Key constraints: {constraints}")
    return "\n".join(lines)


def _contract(
    name: str,
    label: str,
    description: str,
    input_params: list[str],
    output_params: list[str],
    constraints: list[str],
) -> dict[str, Any]:
    return {
        "name": name,
        "label": label,
        "description": description,
        "input_params": [_param(item) for item in input_params],
        "output_params": [_param(item) for item in output_params],
        "constraints": constraints,
    }


def _param(name: str) -> dict[str, str]:
    return {"name": name, "type": "runtime", "description": f"{name} passed by the master route"}


def _extract_int(pattern: re.Pattern[str], text: str) -> int | None:
    match = pattern.search(text or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _extract_float(pattern: re.Pattern[str], text: str) -> float | None:
    match = pattern.search(text or "")
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _clamp_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = fallback
    return max(minimum, min(maximum, number))


def _clamp_float(value: Any, minimum: float, maximum: float, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = fallback
    return round(max(minimum, min(maximum, number)), 3)


def _minimum_image_cues(duration: int) -> int:
    if duration >= 120:
        return 18
    if duration >= 90:
        return 14
    if duration >= 60:
        return 10
    if duration >= 45:
        return 8
    return 6


def _word_safety_margin(duration: int) -> int:
    if duration < 30:
        return 5
    if duration < 60:
        return 8
    return 12
