from __future__ import annotations

import json
import random
import shutil
import subprocess
from pathlib import Path

from agents.base import BaseAgent
from agents.prompts.asset_prompts import (
    MAX_OUTPUT_TOKENS as ASSET_QUERY_MAX_OUTPUT_TOKENS,
    SYSTEM_PROMPT as ASSET_QUERY_SYSTEM_PROMPT,
    messages_with_user as asset_query_messages_with_user,
    parse_asset_query_response,
)
from agents.prompts.message_base import render_messages_for_single_prompt
from app.paths import DATA_DIR
from app.schemas import AssetBundle, GenreConfig, ImageCue, SfxCue
from modules.assets.intent_generator import build_asset_intent_profile
from modules.assets.image_fetcher import fetch_image_for_cue
from modules.assets.video_fetcher import fetch_video_for_cue


class AssetAgent(BaseAgent):
    name = "asset_agent"

    def run(
        self,
        image_cues: list[ImageCue],
        sfx_cues: list[SfxCue],
        genre: GenreConfig,
        pexels_key: str = "",
        pixabay_key: str = "",
        provider=None,
    ) -> AssetBundle:
        payload = {
            "image_cues": image_cues,
            "sfx_cues": sfx_cues,
            "genre_id": genre.genre_id,
            "has_pexels_key": bool(pexels_key),
            "has_pixabay_key": bool(pixabay_key),
            "asset_query_provider": getattr(provider, "name", "none") if provider else "none",
            "asset_query_rewrite_max_input_chars": 500,
            "asset_query_rewrite_max_output_tokens": 80,
            "asset_source_order": [
                "pexels_video",
                "pexels_image",
                "pixabay_image",
                "bing_image",
                "wikimedia_image",
                "generated_fallback",
            ],
        }
        self.log_input(payload)
        image_dir = self.run_dir / "intermediate" / "images"
        video_dir = self.run_dir / "intermediate" / "videos"
        asset_intent_profile = build_asset_intent_profile(image_cues, genre)
        image_paths: list[str] = []
        video_paths: list[str] = []
        media_paths: list[str] = []
        media_types: list[str] = []
        sources: list[str] = []
        stock_video_search_terms: list[str] = []
        for cue in image_cues:
            fetch_cue, rewrite = _rewrite_asset_query(cue, genre, provider)
            if rewrite.get("error"):
                self.event("Asset query rewrite skipped", keyword=cue.keyword, error=str(rewrite["error"])[:240])
            elif rewrite.get("query") and rewrite["query"] != cue.keyword:
                self.event("Asset query rewritten", original=cue.keyword, query=rewrite["query"], reason=rewrite.get("reason", ""))
            stock_video_search_terms.append(fetch_cue.keyword)

            self.event("Fetching video", keyword=fetch_cue.keyword, source="pexels")
            video_path, video_source = fetch_video_for_cue(
                fetch_cue,
                video_dir,
                genre,
                pexels_key=pexels_key,
                asset_intent_profile=asset_intent_profile,
            )
            if video_path:
                video_paths.append(video_path)
                media_paths.append(video_path)
                media_types.append("video")
                sources.append(f"{video_source}_video")
                frame_path = _extract_video_frame(video_path, _video_frame_path(image_dir, cue))
                if frame_path:
                    image_paths.append(frame_path)
                    self.event("Video frame ready", video_path=video_path, path=frame_path, source=video_source)
                    continue
                self.event("Video frame extraction failed; falling back to image", video_path=video_path)
                image_path, image_source = fetch_image_for_cue(
                    fetch_cue,
                    image_dir,
                    genre,
                    pexels_key=pexels_key,
                    pixabay_key=pixabay_key,
                )
                image_paths.append(image_path)
                self.event("Poster image ready", path=image_path, source=image_source)
                continue
            elif video_source:
                self.event("Video search failed; falling back to image", detail=video_source[:300])

            self.event("Fetching image", keyword=fetch_cue.keyword)
            path, source = fetch_image_for_cue(
                fetch_cue,
                image_dir,
                genre,
                pexels_key=pexels_key,
                pixabay_key=pixabay_key,
            )
            image_paths.append(path)
            media_paths.append(path)
            media_types.append("image")
            sources.append(source)
            self.event("Image ready", path=path, source=source)

        music_path = _pick_music_track()
        if music_path:
            self.event("Background music ready", path=music_path)
        bundle = AssetBundle(
            image_paths=image_paths,
            sfx_paths=[],
            music_path=music_path,
            sources=sources,
            video_paths=video_paths,
            media_paths=media_paths,
            media_types=media_types,
            stock_video_search_terms=stock_video_search_terms,
        )
        self.event(
            "Asset search terms ready",
            stock_video_search_terms=stock_video_search_terms,
            video_count=len(video_paths),
            image_count=len(image_paths),
            media_count=len(media_paths),
        )
        self.log_output(bundle)
        return bundle


def _rewrite_asset_query(cue: ImageCue, genre: GenreConfig, provider) -> tuple[ImageCue, dict[str, str]]:
    if not provider or getattr(provider, "name", "") == "offline":
        return cue, {}
    try:
        messages = asset_query_messages_with_user(
            raw_query=cue.keyword,
            genre_id=genre.genre_id,
            mood=cue.mood,
        )
        prompt = render_messages_for_single_prompt(messages[1:])
        data = provider.generate_json(
            ASSET_QUERY_SYSTEM_PROMPT,
            prompt,
            ASSET_QUERY_MAX_OUTPUT_TOKENS,
        )
        parsed = parse_asset_query_response(json.dumps(data, ensure_ascii=False) if isinstance(data, dict) else str(data))
        query = parsed["query"]
        if not query or query.strip().lower() == cue.keyword.strip().lower():
            return cue, parsed
        return ImageCue(keyword=query, timestamp_hint=cue.timestamp_hint, mood=cue.mood), parsed
    except Exception as exc:
        return cue, {"error": f"{type(exc).__name__}: {exc}"}


def _video_frame_path(image_dir: Path, cue: ImageCue) -> Path:
    import hashlib

    image_dir.mkdir(parents=True, exist_ok=True)
    safe_name = hashlib.md5(f"video:{cue.keyword}".encode("utf-8")).hexdigest()[:12]
    return image_dir / f"{safe_name}.jpg"


def _extract_video_frame(video_path: str, target: Path) -> str:
    if target.exists():
        return str(target)
    ffmpeg = shutil.which("ffmpeg")
    source = Path(video_path)
    if not ffmpeg or not source.exists():
        return ""
    target.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-ss",
            "00:00:01",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(target),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0 or not target.exists() or target.stat().st_size <= 0:
        return ""
    return str(target)


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
