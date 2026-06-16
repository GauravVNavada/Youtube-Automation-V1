from __future__ import annotations

import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from agents.base import BaseAgent
from app.paths import DATA_DIR
from app.schemas import AssetBundle, GenreConfig, ImageCue, SfxCue
from modules.assets.image_fetcher import fetch_image_for_cue
from modules.assets.intent import profile_to_dict
from modules.assets.intent_generator import generate_asset_intent_profile
from modules.assets.video_fetcher import fetch_video_for_cue
from modules.visuals.style_router import should_skip_stock_video, visual_style_to_dict


class AssetAgent(BaseAgent):
    name = "asset_agent"

    def run(
        self,
        image_cues: list[ImageCue],
        sfx_cues: list[SfxCue],
        genre: GenreConfig,
        pexels_key: str = "",
        pixabay_key: str = "",
        visual_style: dict | None = None,
        asset_intent_profile: dict | None = None,
        intent_provider=None,
        topic: str = "",
        growth_context: dict | None = None,
    ) -> AssetBundle:
        visual_style_payload = visual_style_to_dict(visual_style)
        if intent_provider:
            self.provenance(
                "Preparing AI-assisted asset intent analysis",
                mode="hybrid",
                provider=getattr(intent_provider, "name", "unknown"),
                genre_id=genre.genre_id,
            )
        else:
            self.provenance(
                "Preparing deterministic asset intent analysis",
                mode="deterministic",
                genre_id=genre.genre_id,
            )
        asset_intent_payload = self._resolve_asset_intent_profile(
            provider=intent_provider,
            genre=genre,
            topic=topic,
            image_cues=image_cues,
            growth_context=growth_context or {},
            visual_style=visual_style_payload,
            fallback_profile=asset_intent_profile,
        )
        skip_stock_video = should_skip_stock_video(visual_style_payload)
        payload = {
            "image_cues": image_cues,
            "sfx_cues": sfx_cues,
            "genre_id": genre.genre_id,
            "has_pexels_key": bool(pexels_key),
            "has_pixabay_key": bool(pixabay_key),
            "visual_style": visual_style_payload,
            "asset_intent_profile": asset_intent_payload,
            "skip_stock_video": skip_stock_video,
            "asset_query_rewrite_max_input_chars": 500,
            "asset_query_rewrite_max_output_tokens": 80,
        }
        self.log_input(payload)
        image_dir = self.run_dir / "intermediate" / "images"
        video_dir = self.run_dir / "intermediate" / "videos"
        paths: list[str] = [""] * len(image_cues)
        sources: list[str] = [""] * len(image_cues)
        video_paths: list[str] = [""] * len(image_cues)
        video_sources: list[str] = [""] * len(image_cues)
        max_workers = min(4, max(1, len(image_cues)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {}
            for index, cue in enumerate(image_cues):
                self.provenance(
                    "Fetching image",
                    mode="deterministic",
                    keyword=cue.keyword,
                    index=index,
                    method="free-source search and local cache scoring",
                )
                future = executor.submit(
                    fetch_image_for_cue,
                    cue,
                    image_dir,
                    genre,
                    pexels_key,
                    pixabay_key,
                    visual_style_payload,
                    asset_intent_payload,
                )
                future_map[future] = (index, cue)

            for future in as_completed(future_map):
                index, cue = future_map[future]
                path, source = future.result()
                paths[index] = path
                sources[index] = source
                self.provenance(
                    "Image ready",
                    mode="deterministic",
                    path=path,
                    source=source,
                    keyword=cue.keyword,
                    index=index,
                )

        if pexels_key and not skip_stock_video:
            video_workers = min(3, max(1, len(image_cues)))
            with ThreadPoolExecutor(max_workers=video_workers) as executor:
                future_map = {}
                for index, cue in enumerate(image_cues):
                    self.provenance(
                        "Fetching stock video",
                        mode="deterministic",
                        keyword=cue.keyword,
                        index=index,
                        method="Pexels API search when a free key is configured",
                    )
                    future = executor.submit(
                        fetch_video_for_cue,
                        cue,
                        video_dir,
                        genre,
                        pexels_key,
                        asset_intent_payload,
                    )
                    future_map[future] = (index, cue)

                for future in as_completed(future_map):
                    index, cue = future_map[future]
                    try:
                        path, source = future.result()
                    except Exception as exc:
                        self.provenance(
                            "Stock video unavailable; using image fallback",
                            mode="fallback",
                            keyword=cue.keyword,
                            index=index,
                            reason=str(exc),
                        )
                        continue
                    video_paths[index] = path
                    video_sources[index] = source
                    self.provenance(
                        "Stock video ready",
                        mode="deterministic",
                        path=path,
                        source=source,
                        keyword=cue.keyword,
                        index=index,
                    )
        elif pexels_key and skip_stock_video:
            self.provenance(
                "Stock video skipped for visual style",
                mode="deterministic",
                render_style=visual_style_payload.get("render_style"),
                asset_strategy=visual_style_payload.get("asset_strategy"),
            )

        duplicate_count = self._remove_duplicate_videos(video_paths, video_sources)
        if duplicate_count:
            self.provenance(
                "Duplicate stock videos replaced with image fallbacks",
                mode="fallback",
                duplicate_count=duplicate_count,
            )

        music_path = _pick_music_track()
        if music_path:
            self.provenance("Background music ready", mode="deterministic", path=music_path)
        bundle = AssetBundle(
            image_paths=paths,
            sfx_paths=[],
            music_path=music_path,
            sources=sources,
            video_paths=video_paths,
            video_sources=video_sources,
            visual_style=str(visual_style_payload.get("render_style") or "natural"),
            asset_strategy=str(visual_style_payload.get("asset_strategy") or "hybrid_video"),
        )
        self.log_output(bundle)
        return bundle

    def _remove_duplicate_videos(self, video_paths: list[str], video_sources: list[str]) -> int:
        seen: set[str] = set()
        duplicate_count = 0
        for index, path in enumerate(video_paths):
            if not path:
                continue
            key = _video_identity(path, video_sources[index] if index < len(video_sources) else "")
            if key in seen:
                video_paths[index] = ""
                if index < len(video_sources):
                    video_sources[index] = "image_fallback_duplicate_video"
                duplicate_count += 1
                continue
            seen.add(key)
        return duplicate_count

    def _resolve_asset_intent_profile(
        self,
        *,
        provider,
        genre: GenreConfig,
        topic: str,
        image_cues: list[ImageCue],
        growth_context: dict,
        visual_style: dict,
        fallback_profile: dict | None,
    ) -> dict:
        if fallback_profile:
            self.provenance(
                "Using supplied asset intent profile",
                mode="deterministic",
                genre_id=genre.genre_id,
            )
            return profile_to_dict(fallback_profile, genre)
        if provider:
            try:
                profile = generate_asset_intent_profile(
                    provider,
                    genre=genre,
                    topic=topic,
                    image_cues=image_cues,
                    growth_context=growth_context,
                    visual_style=visual_style,
                )
                self.provenance(
                    "Generated dynamic asset intent profile",
                    mode="ai",
                    provider=getattr(provider, "name", "unknown"),
                    positive_terms=profile.get("positive_terms", [])[:6],
                    required_context=profile.get("required_context", [])[:4],
                )
                return profile
            except Exception as exc:
                self.provenance(
                    "Dynamic asset intent profile failed; using inferred fallback",
                    mode="fallback",
                    reason=str(exc),
                )
        self.provenance(
            "Using inferred deterministic asset intent profile",
            mode="deterministic",
            genre_id=genre.genre_id,
        )
        return profile_to_dict(None, genre)


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


def _video_identity(path: str, source: str) -> str:
    if source and source != "cache":
        return source.split("?", 1)[0]
    resolved = Path(path)
    try:
        return f"{resolved.resolve()}:{resolved.stat().st_size}"
    except OSError:
        return str(resolved)
