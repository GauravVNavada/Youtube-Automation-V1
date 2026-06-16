from __future__ import annotations

from app.schemas import GenreConfig, ImageCue
from modules.assets.intent import build_asset_intent


def build_asset_intent_profile(cues: list[ImageCue], genre: GenreConfig) -> dict:
    required = []
    for cue in cues:
        required.extend(build_asset_intent(cue, genre).get("required_terms", [])[:2])
    return {
        "required_terms": list(dict.fromkeys(required))[:12],
        "negative_terms": ["cartoon", "anime", "illustration"],
        "visual_style": "realistic stock footage",
    }
