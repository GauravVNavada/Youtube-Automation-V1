import json
from typing import Any, Dict, List

from agents.prompts.message_base import (
    append_user_message,
    base_messages,
    clean_list,
    clean_text,
    compact_json,
)


MAX_INPUT_CHARS = 1800
MAX_OUTPUT_TOKENS = 900


MASTER_AGENT_PROMPT = """
You are the MASTER_AGENT for a YouTube Shorts / short-video generation pipeline.

Your job is to plan a grounded production route across specialized agents:
research, script, asset_query, asset_fetch, audio, captions, render, and thumbnail.

You do not write the final video script.
You do not perform research yourself.
You do not generate assets, audio, captions, renders, or thumbnails.
You only decide the correct route, dependencies, handoffs, grounding level, quality gates, and fallbacks.

Return exactly one valid JSON object matching OUTPUT_FORMAT.
Output JSON only. No markdown, no comments, no extra text.

INPUT_FORMAT:
{
  "raw_request": "User's video idea or instruction.",
  "genre_id": "Video genre.",
  "platform": "youtube_shorts | instagram_reels | tiktok | unknown",
  "duration_seconds": 15,
  "target_audience": "Audience description, if known.",
  "mood": "Desired mood or style.",
  "source_policy": "auto | web_required | provided_sources_only | no_research",
  "constraints": ["Optional production constraints."],
  "available_agents": ["Optional list of usable agents."],
  "previous_failures": ["Optional prior pipeline failures."]
}

OUTPUT_FORMAT:
{
  "route_id": "short_snake_case_route_name",
  "intent": "One-sentence interpretation of the video goal.",
  "assumptions": ["Important assumptions made due to missing input."],
  "grounding_level": "none | light | strict",
  "risk_flags": ["Potential factual, safety, copyright, or production risks."],
  "agent_order": ["Ordered agent names to run."],
  "handoffs": [
    {
      "agent": "agent_name",
      "goal": "Specific task for this agent.",
      "input_focus": ["What this agent should pay attention to."],
      "output_needed": ["Concrete output expected from this agent."],
      "blocking": true
    }
  ],
  "quality_gates": ["Checks that must pass before final render."],
  "fallbacks": ["What to do if key agents fail or return weak output."]
}

Hard rules:
- Output must be valid JSON with only the keys in OUTPUT_FORMAT.
- agent_order must only contain agents that should actually run.
- handoffs must follow the same order as agent_order.
- Every agent in agent_order must have exactly one handoff.
- Do not invent facts, citations, statistics, dates, quotes, or sources.
- Do not include the final script, captions, thumbnail text, or asset queries unless routing requires a brief example.
- Prefer concrete, executable instructions over vague planning.
- If input is underspecified, make reasonable assumptions and list them.
- If an agent is unavailable, skip it and add a fallback or risk flag.
- If factual accuracy matters, research must run before script.
- If claims are current, medical, legal, financial, political, scientific, or historical, use strict grounding.
- If the video is fictional, personal, or purely emotional, grounding may be none or light.
- If source_policy is web_required, grounding_level must be strict and research must run.
- If source_policy is provided_sources_only, research must verify only supplied material.
- If source_policy is no_research, do not add research unless safety requires refusing/flagging the route.
- If previous failures mention weak assets, include asset_query repair and asset_fetch fallback.
- If previous failures mention pacing, include script timing and render pacing checks.
- If previous failures mention captions, include caption readability checks.
- If previous failures mention copyright, avoid branded/copyrighted visuals unless factual and necessary.

Agent responsibilities:
- research: collect and verify facts, source ids, dates, claim boundaries, and uncertainty.
- script: create hook, beats, narration, retention structure, and factual claim mapping.
- asset_query: convert each visual beat into searchable visual queries.
- asset_fetch: retrieve/select assets matching the asset queries and licensing constraints.
- audio: choose voice/music/SFX direction based on mood, pacing, and platform.
- captions: create readable short-form captions with emphasis timing.
- render: assemble timeline, cuts, motion, safe zones, aspect ratio, and export settings.
- thumbnail: create click-worthy but accurate thumbnail concept.

Grounding rules:
- none: no factual verification needed; useful for fictional or generic emotional content.
- light: basic fact/context check useful but not central.
- strict: every important factual claim needs source-backed verification before scripting.

Quality gates should cover:
- factual grounding where needed.
- script duration fit.
- visual availability.
- audio-caption sync.
- platform safe zones.
- copyright/licensing risk.
- final render completeness.

Fallback strategy:
- If research is weak, narrow the claim scope or convert to a non-factual angle.
- If assets are weak, simplify visuals into searchable objects/settings.
- If the script is too long, reduce beats before render.
- If audio is unavailable, continue with voice + captions only.
- If thumbnail is risky/clickbait, make it more literal and accurate.
"""


EXAMPLE_USER_INPUT_1 = """
{
  "raw_request": "Make a 45 second short about why Roman concrete lasted so long.",
  "genre_id": "history_facts",
  "platform": "youtube_shorts",
  "duration_seconds": 45,
  "target_audience": "curious students",
  "mood": "surprising",
  "source_policy": "auto",
  "constraints": ["avoid fake facts"],
  "available_agents": [],
  "previous_failures": []
}
"""

EXAMPLE_ASSISTANT_OUTPUT_1 = """
{
  "route_id": "strict_history_fact_route",
  "intent": "Create a fact-grounded short explaining the durability of Roman concrete.",
  "assumptions": ["The video should prioritize accuracy over speculation.", "A 45 second duration allows roughly 5 to 7 narration beats."],
  "grounding_level": "strict",
  "risk_flags": ["Historical science claims may be oversimplified.", "Dates and material explanations need source verification."],
  "agent_order": ["research", "script", "asset_query", "asset_fetch", "audio", "captions", "render", "thumbnail"],
  "handoffs": [
    {
      "agent": "research",
      "goal": "Verify the main explanation for Roman concrete durability using reliable sources.",
      "input_focus": ["Roman concrete", "volcanic ash", "seawater", "mineral formation", "uncertainty"],
      "output_needed": ["verified claims", "source ids", "claim limitations", "suggested narrative angle"],
      "blocking": true
    },
    {
      "agent": "script",
      "goal": "Write a 45 second script with source-mapped factual claims and a strong hook.",
      "input_focus": ["verified research only", "simple explanation", "retention beats"],
      "output_needed": ["timed narration beats", "claim-source mapping", "visual beat list"],
      "blocking": true
    },
    {
      "agent": "asset_query",
      "goal": "Turn each visual beat into concrete image-search queries.",
      "input_focus": ["ancient ruins", "Roman harbor", "volcanic ash", "concrete texture"],
      "output_needed": ["2-6 word visual queries per beat"],
      "blocking": true
    },
    {
      "agent": "asset_fetch",
      "goal": "Select usable assets that match the visual queries and avoid misleading visuals.",
      "input_focus": ["licensing", "historical relevance", "visual clarity"],
      "output_needed": ["selected assets", "backup assets", "asset ids"],
      "blocking": true
    },
    {
      "agent": "audio",
      "goal": "Choose educational but energetic voice, music, and subtle sound direction.",
      "input_focus": ["curious mood", "45 second pacing", "non-distracting music"],
      "output_needed": ["voice direction", "music direction", "SFX notes"],
      "blocking": false
    },
    {
      "agent": "captions",
      "goal": "Create readable captions emphasizing key terms without clutter.",
      "input_focus": ["short lines", "technical terms", "mobile readability"],
      "output_needed": ["caption text", "emphasis words", "timing guidance"],
      "blocking": true
    },
    {
      "agent": "render",
      "goal": "Assemble the final vertical video with correct pacing and safe zones.",
      "input_focus": ["9:16 layout", "asset timing", "caption safe zones", "45 second duration"],
      "output_needed": ["render plan", "timeline", "export settings"],
      "blocking": true
    },
    {
      "agent": "thumbnail",
      "goal": "Create an accurate thumbnail concept that teases the durability mystery.",
      "input_focus": ["Roman ruins", "concrete texture", "curiosity gap without false claims"],
      "output_needed": ["thumbnail concept", "short overlay text", "risk notes"],
      "blocking": false
    }
  ],
  "quality_gates": ["Every factual claim has a source id.", "Script fits 45 seconds.", "Assets do not imply false historical specifics.", "Captions are readable on mobile.", "Render uses 9:16 safe zones.", "Thumbnail is accurate and not clickbait."],
  "fallbacks": ["If research is inconclusive, frame the video as the leading scientific explanation.", "If Roman-specific assets are weak, use ruins and concrete texture visuals.", "If the script is too long, remove one supporting example before render."]
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
  "source_policy": "no_research",
  "constraints": ["no gore"],
  "available_agents": [],
  "previous_failures": ["asset search returned generic portraits"]
}
"""

EXAMPLE_ASSISTANT_OUTPUT_2 = """
{
  "route_id": "fiction_horror_story_route",
  "intent": "Create a fictional 30 second horror short centered on scratching sounds from a mirror.",
  "assumptions": ["The story is fictional and does not need factual research.", "The horror should rely on suspense rather than gore."],
  "grounding_level": "none",
  "risk_flags": ["Asset searches may become generic without concrete objects.", "Horror tone should avoid graphic gore."],
  "agent_order": ["script", "asset_query", "asset_fetch", "audio", "captions", "render", "thumbnail"],
  "handoffs": [
    {
      "agent": "script",
      "goal": "Write a compact 30 second suspense story with a strong final reveal.",
      "input_focus": ["mirror scratching", "woman alone", "dark room", "no gore"],
      "output_needed": ["timed narration beats", "visual beat list", "ending reveal"],
      "blocking": true
    },
    {
      "agent": "asset_query",
      "goal": "Rewrite each beat into object-based horror image searches.",
      "input_focus": ["scratched mirror", "dark bedroom", "shadow figure", "empty hallway"],
      "output_needed": ["2-6 word concrete asset queries", "backup queries"],
      "blocking": true
    },
    {
      "agent": "asset_fetch",
      "goal": "Find dark, object-focused assets instead of generic portraits.",
      "input_focus": ["mirror", "scratches", "bedroom", "shadows", "no gore"],
      "output_needed": ["selected assets", "backup assets", "licensing notes"],
      "blocking": true
    },
    {
      "agent": "audio",
      "goal": "Create suspense with quiet ambience and scratching sound cues.",
      "input_focus": ["dark mood", "scratching SFX", "slow tension"],
      "output_needed": ["voice direction", "music direction", "SFX timestamps"],
      "blocking": false
    },
    {
      "agent": "captions",
      "goal": "Create minimal captions that preserve suspense and readability.",
      "input_focus": ["short lines", "delayed reveal", "mobile readability"],
      "output_needed": ["caption text", "timing guidance"],
      "blocking": true
    },
    {
      "agent": "render",
      "goal": "Assemble a vertical suspense edit with slow zooms and reveal timing.",
      "input_focus": ["9:16 layout", "dark visuals", "caption safe zones", "30 second duration"],
      "output_needed": ["render plan", "timeline", "export settings"],
      "blocking": true
    },
    {
      "agent": "thumbnail",
      "goal": "Create a simple horror thumbnail centered on a scratched mirror.",
      "input_focus": ["scratched mirror", "dark bedroom", "short text", "no gore"],
      "output_needed": ["thumbnail concept", "overlay text", "risk notes"],
      "blocking": false
    }
  ],
  "quality_gates": ["Script fits 30 seconds.", "Assets focus on concrete horror objects.", "No graphic gore appears in visuals or thumbnail.", "Captions do not cover key mirror details.", "Audio cues align with scratching moments."],
  "fallbacks": ["If mirror assets are weak, use cracked glass or dark bathroom mirror visuals.", "If audio SFX is unavailable, emphasize silence and caption timing.", "If pacing feels slow, reduce setup and reach the mirror reveal earlier."]
}
"""


MESSAGES_BASE: List[Dict[str, str]] = [
    {"role": "system", "content": MASTER_AGENT_PROMPT},
    {"role": "user", "content": EXAMPLE_USER_INPUT_1},
    {"role": "assistant", "content": EXAMPLE_ASSISTANT_OUTPUT_1},
    {"role": "user", "content": EXAMPLE_USER_INPUT_2},
    {"role": "assistant", "content": EXAMPLE_ASSISTANT_OUTPUT_2},
]


EXPECTED_OUTPUT_KEYS = {
    "route_id",
    "intent",
    "assumptions",
    "grounding_level",
    "risk_flags",
    "agent_order",
    "handoffs",
    "quality_gates",
    "fallbacks",
}

GROUNDING_LEVELS = {"none", "light", "strict"}

DEFAULT_AVAILABLE_AGENTS = [
    "research",
    "script",
    "asset_query",
    "asset_fetch",
    "audio",
    "captions",
    "render",
    "thumbnail",
]


def messages_base() -> List[Dict[str, str]]:
    return base_messages(MASTER_AGENT_PROMPT, MESSAGES_BASE[1:])


def build_master_user_input(
    raw_request: str,
    genre_id: str,
    platform: str = "youtube_shorts",
    duration_seconds: int = 30,
    target_audience: str = "",
    mood: str = "",
    source_policy: str = "auto",
    constraints: List[str] | None = None,
    available_agents: List[str] | None = None,
    previous_failures: List[str] | None = None,
) -> str:
    payload: Dict[str, Any] = {
        "raw_request": clean_text(raw_request, 500),
        "genre_id": clean_text(genre_id, 80),
        "platform": clean_text(platform, 40),
        "duration_seconds": int(duration_seconds),
        "target_audience": clean_text(target_audience, 120),
        "mood": clean_text(mood, 80),
        "source_policy": clean_text(source_policy, 40),
        "constraints": clean_list(constraints, item_limit=120, max_items=8),
        "available_agents": clean_list(available_agents, item_limit=40, max_items=12),
        "previous_failures": clean_list(previous_failures, item_limit=140, max_items=6),
    }

    text = compact_json(payload)
    if len(text) <= MAX_INPUT_CHARS:
        return text

    payload["raw_request"] = clean_text(raw_request, 320)
    payload["target_audience"] = clean_text(target_audience, 80)
    payload["constraints"] = clean_list(constraints, item_limit=80, max_items=5)
    payload["previous_failures"] = clean_list(previous_failures, item_limit=90, max_items=4)

    text = compact_json(payload)
    if len(text) <= MAX_INPUT_CHARS:
        return text

    payload["raw_request"] = clean_text(raw_request, 220)
    payload["constraints"] = clean_list(constraints, item_limit=60, max_items=3)
    payload["previous_failures"] = clean_list(previous_failures, item_limit=60, max_items=3)

    text = compact_json(payload)
    if len(text) <= MAX_INPUT_CHARS:
        return text

    return compact_json(
        {
            "raw_request": clean_text(raw_request, 160),
            "genre_id": clean_text(genre_id, 50),
            "platform": clean_text(platform, 30),
            "duration_seconds": int(duration_seconds),
            "target_audience": "",
            "mood": clean_text(mood, 40),
            "source_policy": clean_text(source_policy, 30),
            "constraints": [],
            "available_agents": clean_list(available_agents, item_limit=30, max_items=8),
            "previous_failures": [],
        }
    )


def messages_with_user(
    raw_request: str,
    genre_id: str,
    platform: str = "youtube_shorts",
    duration_seconds: int = 30,
    target_audience: str = "",
    mood: str = "",
    source_policy: str = "auto",
    constraints: List[str] | None = None,
    available_agents: List[str] | None = None,
    previous_failures: List[str] | None = None,
) -> List[Dict[str, str]]:
    return append_user_message(
        messages_base(),
        build_master_user_input(
            raw_request=raw_request,
            genre_id=genre_id,
            platform=platform,
            duration_seconds=duration_seconds,
            target_audience=target_audience,
            mood=mood,
            source_policy=source_policy,
            constraints=constraints,
            available_agents=available_agents,
            previous_failures=previous_failures,
        ),
        MAX_INPUT_CHARS,
    )


def parse_master_agent_response(response_text: str) -> Dict[str, Any]:
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Master agent response is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Master agent response must be a JSON object.")

    actual_keys = set(data.keys())
    if actual_keys != EXPECTED_OUTPUT_KEYS:
        raise ValueError(
            f"Master agent response must contain exactly {EXPECTED_OUTPUT_KEYS}, got {actual_keys}."
        )

    if not isinstance(data["route_id"], str) or not data["route_id"].strip():
        raise ValueError("route_id must be a non-empty string.")

    if not isinstance(data["intent"], str) or not data["intent"].strip():
        raise ValueError("intent must be a non-empty string.")

    if data["grounding_level"] not in GROUNDING_LEVELS:
        raise ValueError(f"grounding_level must be one of {GROUNDING_LEVELS}.")

    for key in ["assumptions", "risk_flags", "agent_order", "quality_gates", "fallbacks"]:
        if not isinstance(data[key], list):
            raise ValueError(f"{key} must be a list.")

    if not isinstance(data["handoffs"], list):
        raise ValueError("handoffs must be a list.")

    agent_order = data["agent_order"]
    handoffs = data["handoffs"]

    if not all(isinstance(agent, str) and agent.strip() for agent in agent_order):
        raise ValueError("agent_order must contain non-empty strings.")

    if len(agent_order) != len(handoffs):
        raise ValueError("Each agent in agent_order must have exactly one handoff.")

    seen_agents = set()

    for index, handoff in enumerate(handoffs):
        if not isinstance(handoff, dict):
            raise ValueError("Each handoff must be a JSON object.")

        expected_handoff_keys = {
            "agent",
            "goal",
            "input_focus",
            "output_needed",
            "blocking",
        }

        if set(handoff.keys()) != expected_handoff_keys:
            raise ValueError(
                f"Handoff must contain exactly {expected_handoff_keys}, got {set(handoff.keys())}."
            )

        agent = handoff["agent"]

        if agent != agent_order[index]:
            raise ValueError("handoffs must follow the same order as agent_order.")

        if agent in seen_agents:
            raise ValueError(f"Duplicate handoff for agent: {agent}")

        seen_agents.add(agent)

        if not isinstance(handoff["goal"], str) or not handoff["goal"].strip():
            raise ValueError(f"Handoff goal for {agent} must be a non-empty string.")

        if not isinstance(handoff["input_focus"], list):
            raise ValueError(f"Handoff input_focus for {agent} must be a list.")

        if not isinstance(handoff["output_needed"], list):
            raise ValueError(f"Handoff output_needed for {agent} must be a list.")

        if not isinstance(handoff["blocking"], bool):
            raise ValueError(f"Handoff blocking for {agent} must be a boolean.")

    return data


if __name__ == "__main__":
    messages = messages_with_user(
        raw_request="Make a short about the hidden cost of free mobile games.",
        genre_id="explainer",
        platform="youtube_shorts",
        duration_seconds=40,
        target_audience="teen gamers",
        mood="sharp and revealing",
        source_policy="auto",
        constraints=["avoid sounding preachy", "needs strong retention"],
        previous_failures=["previous script was too generic"],
    )

    print(json.dumps(messages, indent=2, ensure_ascii=False))
