from __future__ import annotations

from app.services.master_llm import extract_generation_request


def decide_next_action(message: str, fallback_genre: str = "scary_stories") -> dict:
    return extract_generation_request(message, fallback_genre)
