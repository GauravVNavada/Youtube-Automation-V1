from __future__ import annotations

from app.schemas import GenreConfig, ImageCue
from modules.assets.intent import build_asset_intent, genre_visual_profile


def build_asset_intent_profile(cues: list[ImageCue], genre: GenreConfig) -> dict:
    required = []
    visual_profile = genre_visual_profile(genre)
    for cue in cues:
        required.extend(build_asset_intent(cue, genre).get("required_terms", [])[:2])
    return {
        "required_terms": list(dict.fromkeys(required))[:12],
        "preferred_terms": list(visual_profile.get("preferred_terms", [])),
        "negative_terms": list(visual_profile.get("negative_terms", ["cartoon", "anime", "illustration"])),
        "visual_style": str(visual_profile.get("visual_style", "realistic stock footage")),
    }
