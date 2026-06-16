from __future__ import annotations

from app.services.master_agent import decide_next_action


class MasterAgent:
    def run(self, message: str, fallback_genre: str = "scary_stories") -> dict:
        return decide_next_action(message, fallback_genre)
