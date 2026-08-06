from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agents.render_agent import RenderAgent
from app.schemas import AssetBundle, AudioBundle, CaptionBundle, TimedVisualCue, WordTimestamp


def main() -> int:
    parser = argparse.ArgumentParser(description="Rerender from saved pipeline artifacts.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--assets-json", required=True)
    parser.add_argument("--audio-json", required=True)
    parser.add_argument("--captions-json", required=True)
    parser.add_argument("--music-volume", type=float, default=0.12)
    parser.add_argument("--visual-motion", choices=["on", "off"], default="on")
    parser.add_argument("--transition-style", choices=["slide", "fade", "wipe", "cut"], default="slide")
    parser.add_argument("--transition-seconds", type=float, default=0.45)
    parser.add_argument("--zoom-variant", choices=["mixed", "center_in", "center_out", "still"], default="mixed")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    assets = _asset_bundle(_read_json(Path(args.assets_json)))
    audio = _audio_bundle(_read_json(Path(args.audio_json)))
    captions = _caption_bundle(_read_json(Path(args.captions_json)))

    print(f"[run] {run_dir}")
    print("[8/10] Rendering video...")
    result = RenderAgent(run_dir).run(
        assets,
        audio,
        captions,
        music_volume=args.music_volume,
        visual_motion=args.visual_motion == "on",
        transition_style=args.transition_style,
        transition_seconds=args.transition_seconds,
        zoom_variant=args.zoom_variant,
    )
    print("[10/10] Complete.")
    print(f"Final video: {result.video_path}")
    return 0


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected object JSON at {path}")
    return data


def _asset_bundle(data: dict[str, Any]) -> AssetBundle:
    return AssetBundle(
        image_paths=_strings(data.get("image_paths")),
        sfx_paths=_strings(data.get("sfx_paths")),
        music_path=_optional_string(data.get("music_path")),
        sources=_strings(data.get("sources")),
        sfx_asset_ids=_strings(data.get("sfx_asset_ids")),
        sfx_asset_names=_strings(data.get("sfx_asset_names")),
        video_paths=_strings(data.get("video_paths")),
        media_paths=_strings(data.get("media_paths")),
        media_types=_strings(data.get("media_types")),
        stock_video_search_terms=_strings(data.get("stock_video_search_terms")),
        subject_lock_issues=_strings(data.get("subject_lock_issues")),
        asset_selection_trace=list(data.get("asset_selection_trace") or []),
        asset_trace_path=str(data.get("asset_trace_path") or ""),
        media_start_ms=_ints(data.get("media_start_ms")),
        media_end_ms=_ints(data.get("media_end_ms")),
        media_durations_ms=_ints(data.get("media_durations_ms")),
        timed_visual_cues=[
            TimedVisualCue(**cue)
            for cue in data.get("timed_visual_cues", [])
            if isinstance(cue, dict)
        ],
        timed_visual_cues_path=str(data.get("timed_visual_cues_path") or ""),
    )


def _audio_bundle(data: dict[str, Any]) -> AudioBundle:
    return AudioBundle(
        narration_path=str(data.get("narration_path") or ""),
        final_audio_path=str(data.get("final_audio_path") or ""),
        duration_ms=int(data.get("duration_ms") or 0),
        word_timestamps=[
            WordTimestamp(**word)
            for word in data.get("word_timestamps", [])
            if isinstance(word, dict)
        ],
        provider=str(data.get("provider") or "unknown"),
        mean_volume_db=data.get("mean_volume_db"),
        max_volume_db=data.get("max_volume_db"),
        longest_silence_seconds=data.get("longest_silence_seconds"),
        alignment_source=str(data.get("alignment_source") or "unknown"),
    )


def _caption_bundle(data: dict[str, Any]) -> CaptionBundle:
    return CaptionBundle(
        srt_path=str(data.get("srt_path") or ""),
        ass_path=str(data.get("ass_path") or ""),
        phrase_count=int(data.get("phrase_count") or 0),
        word_count=int(data.get("word_count") or 0),
    )


def _strings(value: Any) -> list[str]:
    return [str(item) for item in value or [] if str(item or "")]


def _ints(value: Any) -> list[int]:
    output: list[int] = []
    for item in value or []:
        try:
            output.append(int(item))
        except (TypeError, ValueError):
            continue
    return output


def _optional_string(value: Any) -> str | None:
    text = str(value or "")
    return text or None


if __name__ == "__main__":
    raise SystemExit(main())
