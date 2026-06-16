from __future__ import annotations

from typing import Any


def extract_generation_request(message: str, fallback_genre: str = "scary_stories") -> dict[str, Any]:
    text = " ".join(message.split())
    lower = text.lower()
    intent = "generate_video"
    if any(word in lower for word in ("hello", "hi", "what can you")) and len(lower.split()) < 8:
        intent = "chat"
    genre = fallback_genre
    if "history" in lower:
        genre = "history_facts"
    elif "reddit" in lower or "storytime" in lower:
        genre = "reddit_stories"
    elif "scary" in lower or "horror" in lower or "haunted" in lower:
        genre = "scary_stories"
    return {
        "intent": intent,
        "topic": text,
        "genre": genre,
        "notes": "",
        "needs_clarification": len([w for w in lower.split() if len(w) > 2]) < 3,
    }
