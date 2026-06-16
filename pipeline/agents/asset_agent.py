from __future__ import annotations

import random
from pathlib import Path

from agents.base import BaseAgent
from app.paths import DATA_DIR
from app.schemas import AssetBundle, GenreConfig, ImageCue, SfxCue
from modules.assets.image_fetcher import fetch_image_for_cue


class AssetAgent(BaseAgent):
    name = "asset_agent"

    def run(
        self,
        image_cues: list[ImageCue],
        sfx_cues: list[SfxCue],
        genre: GenreConfig,
        pexels_key: str = "",
        pixabay_key: str = "",
    ) -> AssetBundle:
        payload = {
            "image_cues": image_cues,
            "sfx_cues": sfx_cues,
            "genre_id": genre.genre_id,
            "has_pexels_key": bool(pexels_key),
            "has_pixabay_key": bool(pixabay_key),
            "asset_query_rewrite_max_input_chars": 500,
            "asset_query_rewrite_max_output_tokens": 80,
        }
        self.log_input(payload)
        image_dir = self.run_dir / "intermediate" / "images"
        paths: list[str] = []
        sources: list[str] = []
        for cue in image_cues:
            self.event("Fetching image", keyword=cue.keyword)
            path, source = fetch_image_for_cue(
                cue,
                image_dir,
                genre,
                pexels_key=pexels_key,
                pixabay_key=pixabay_key,
            )
            paths.append(path)
            sources.append(source)
            self.event("Image ready", path=path, source=source)

        music_path = _pick_music_track()
        if music_path:
            self.event("Background music ready", path=music_path)
        bundle = AssetBundle(
            image_paths=paths,
            sfx_paths=[],
            music_path=music_path,
            sources=sources,
        )
        self.log_output(bundle)
        return bundle


def _pick_music_track() -> str | None:
    music_dir = DATA_DIR / "assets" / "music"
    if not music_dir.exists():
        return None
    tracks: list[Path] = []
    for pattern in ("*.mp3", "*.MP3", "*.wav", "*.WAV", "*.m4a", "*.M4A"):
        tracks.extend(music_dir.glob(pattern))
    if not tracks:
        return None
    return str(random.choice(sorted(tracks)))
