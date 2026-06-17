from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "final_pipeline"
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))

from agents.asset_agent import AssetAgent
from app.schemas import GenreConfig, ImageCue, ScriptOutput, TimedVisualCue, WordTimestamp
from main import combine_topic_and_angle, duration_from_topic, strip_duration_instruction
from modules.scripts.generator import build_user_prompt, generate_script
from modules.assets.candidates import AssetCandidate
from modules.assets.image_scoring import ImageResult
from modules.assets.video_services import VideoResult
from modules.captions.ass_builder import build_ass
from modules.render.ffmpeg_builder import build_media_timeline_command
from modules.visuals.timed_cues import generate_timed_visual_cues, merge_caption_phrases_for_visuals


def _genre() -> GenreConfig:
    return GenreConfig(
        genre_id="scary_stories",
        display_name="Scary Stories",
        word_count_min=40,
        word_count_max=130,
        tone="tense",
        layout="shorts",
        caption_preset="default",
        voice_rate=1.0,
        music_mood="dark",
    )


def _script() -> ScriptOutput:
    return ScriptOutput(
        title="Iron Man Faces The Avengers",
        narration="Iron Man enters the room. The Avengers move closer. The fight begins.",
        hook_line="Iron Man enters the room.",
        word_count=12,
        estimated_duration=8,
        description="",
        hashtags=[],
        image_cues=[ImageCue("Iron Man battle", "word_0", subject_lock=True, required_subjects=["Iron Man"])],
        sfx_cues=[],
    )


def _words(count: int = 18, step_ms: int = 400) -> list[WordTimestamp]:
    output = []
    for index in range(count):
        output.append(WordTimestamp(word=f"word{index}", start_ms=index * step_ms, end_ms=index * step_ms + 300))
    return output


class BadProvider:
    name = "bad_provider"

    def generate_json(self, *_args):
        raise ValueError("Unterminated string starting at line 3")


class FakeGeminiProvider:
    name = "gemini"

    def __init__(self, payload: dict):
        self.payload = payload

    def generate_json(self, *_args):
        return self.payload


def _script_payload(title: str, narration: str, image_base: str) -> dict:
    return {
        "title": title,
        "narration": narration,
        "hook_line": narration.split(".")[0].strip() + ".",
        "word_count": len(narration.split()),
        "estimated_duration": 30,
        "description": f"A short about {title}.",
        "hashtags": ["#shorts", "#story", "#video"],
        "image_cues": [
            {"keyword": f"{image_base} wide shot", "timestamp_hint": "word_0", "mood": "dramatic"},
            {"keyword": f"{image_base} close up", "timestamp_hint": "word_15", "mood": "dark"},
            {"keyword": f"{image_base} hallway action", "timestamp_hint": "word_30", "mood": "eerie"},
            {"keyword": f"{image_base} locked door", "timestamp_hint": "word_45", "mood": "reveal"},
            {"keyword": f"{image_base} final scene", "timestamp_hint": "word_60", "mood": "dramatic"},
        ],
        "sfx_cues": [],
        "emphasis_words": [],
    }


class TimedVisualCueTests(unittest.TestCase):
    def test_caption_chunks_merge_into_non_overlapping_visual_windows(self) -> None:
        words = [
            WordTimestamp("First", 0, 300),
            WordTimestamp("long", 400, 700),
            WordTimestamp("natural", 800, 1100),
            WordTimestamp("sentence.", 1200, 1500),
            WordTimestamp("Second", 2400, 2700),
            WordTimestamp("pause", 2800, 3100),
            WordTimestamp("continues", 3200, 3500),
            WordTimestamp("and", 3600, 3900),
            WordTimestamp("ends.", 4000, 4300),
        ]
        cues = merge_caption_phrases_for_visuals(words, duration_ms=5000)
        self.assertGreaterEqual(len(cues), 2)
        for index, cue in enumerate(cues):
            self.assertLess(cue["start_ms"], cue["end_ms"])
            if index + 1 < len(cues):
                self.assertLessEqual(cue["end_ms"], cues[index + 1]["start_ms"])
        self.assertIn("First long natural sentence.", cues[0]["text"])

    def test_malformed_batch_rewrite_falls_back_per_slot_and_keeps_subject_lock(self) -> None:
        cues, meta = generate_timed_visual_cues(
            script=_script(),
            words=_words(),
            genre=_genre(),
            duration_ms=7600,
            topic="Iron Man fighting the Avengers",
            provider=BadProvider(),
        )
        self.assertTrue(cues)
        self.assertTrue(meta["rewrite_error"])
        self.assertTrue(all(cue.subject_lock for cue in cues))
        self.assertTrue(all("iron man" in cue.search_query.lower() for cue in cues))

    def test_thor_prompt_duration_typo_uses_gemini_subject_script(self) -> None:
        prompt = "can u make a video on thor from avengers fighting with all other avengers, duration of 60 secons"
        cleaned = strip_duration_instruction(prompt)
        self.assertEqual(duration_from_topic(prompt), 60)
        self.assertNotIn("duration", cleaned.lower())
        narration = (
            "Thor lands in the middle of the broken street. The Avengers close in from every side, but he is not trying to destroy them. "
            "The first strike throws sparks across the pavement, and Thor realizes the team is moving like someone is controlling them. "
            "He blocks the shield, dodges the blast, and follows the signal instead of chasing a win. "
            "When the Avengers rush together, Thor takes the hit long enough to break the control. "
            "The fight ends when the team understands the enemy was never Thor."
        )
        script = generate_script(FakeGeminiProvider(_script_payload("Thor Versus The Avengers", narration, "Thor Avengers battle")), cleaned, _genre(), 60, [])
        self.assertEqual(script.provider, "gemini")
        self.assertEqual(script.estimated_duration, 60)
        self.assertIn("Thor", script.title)
        self.assertIn("Thor", script.narration)
        self.assertIn("Avengers", script.narration)
        self.assertNotIn("normal short video idea", script.narration)

    def test_duration_strip_removes_keep_duration_clause(self) -> None:
        prompt = "make a video on a school hallway where there is a guy running from daemons, keep duration for 30 seconds"
        cleaned = strip_duration_instruction(prompt)
        self.assertEqual(duration_from_topic(prompt), 30)
        self.assertEqual(cleaned, "make a video on a school hallway where there is a guy running from daemons")

    def test_unrelated_discovery_angle_is_not_combined_into_topic(self) -> None:
        topic = "make a video on a school hallway where there is a guy running from demons"
        self.assertEqual(combine_topic_and_angle(topic, "Make a short about why Roman concrete lasted so long"), topic)
        self.assertEqual(
            combine_topic_and_angle(topic, "school hallway locked exit chase"),
            f"{topic} - school hallway locked exit chase",
        )

    def test_script_prompt_keeps_final_user_json_valid_under_large_context(self) -> None:
        references = [
            {
                "title": "Why Roman Concrete Survived",
                "script": "Roman concrete volcanic ash seawater mineral cracks. " * 120,
                "overall_score": 999,
            }
        ]
        prompt = build_user_prompt(
            "make a video on a school hallway where there is a guy running from daemons",
            _genre(),
            30,
            references,
            growth_context={
                "facts": ["Roman concrete used volcanic ash. " * 80],
                "source_snippets": [{"title": "Roman concrete", "snippet": "volcanic ash " * 100, "source": "local_reference"}],
            },
        )
        last_user = prompt.rsplit("USER:", 1)[-1]
        start = last_user.find("{")
        payload, _ = json.JSONDecoder().raw_decode(last_user[start:])
        self.assertIn("school hallway", payload["raw_request"])
        self.assertNotIn("Why Roman Concrete", json.dumps(payload))

    def test_bad_gemini_does_not_use_local_script_fallback(self) -> None:
        references = [
            {
                "title": "Why Roman Concrete Survived",
                "script": "Roman concrete volcanic ash seawater mineral cracks. " * 80,
                "overall_score": 999,
            }
        ]
        with self.assertRaisesRegex(RuntimeError, "Local script fallback is disabled"):
            generate_script(
                BadProvider(),
                "make a video on a school hallway where there is a guy running from daemons",
                _genre(),
                30,
                references,
            )

    def test_timed_visual_lock_uses_topic_not_sentence_start_words(self) -> None:
        generic_script = ScriptOutput(
            title="This Story",
            narration="At first, it sounds like a normal short video idea. Then the warning appears.",
            hook_line="At first, it sounds like a normal short video idea.",
            word_count=12,
            estimated_duration=30,
            description="",
            hashtags=[],
            image_cues=[],
            sfx_cues=[],
        )
        cues, _meta = generate_timed_visual_cues(
            script=generic_script,
            words=_words(),
            genre=_genre(),
            duration_ms=7600,
            topic="thor from avengers fighting other avengers",
            provider=None,
        )
        self.assertTrue(cues)
        self.assertTrue(all(cue.required_subjects == ["Thor"] for cue in cues))
        self.assertTrue(all(cue.required_subjects != ["At"] for cue in cues))

    def test_duplicate_pexels_video_url_is_skipped(self) -> None:
        import agents.asset_agent as asset_module

        old_video_search = asset_module.search_video_candidates
        old_image_search = asset_module.search_image_candidates
        old_video_download = asset_module.download_video_candidate
        old_image_download = asset_module.download_image_candidate
        try:
            with tempfile.TemporaryDirectory() as tmp:
                run_dir = Path(tmp)
                clip = run_dir / "clip.mp4"
                clip.write_bytes(b"not-a-real-video")

                def fake_video_search(cue, genre, pexels_key="", asset_intent_profile=None, diagnostics=None):
                    return [
                        AssetCandidate("video", "pexels", "https://videos.pexels.com/same.mp4", 100, title="same"),
                    ]

                def fake_image_search(cue, genre, pexels_key="", pixabay_key="", unsplash_key="", diagnostics=None):
                    return [
                        AssetCandidate("image", "pexels", f"https://images.pexels.com/{cue.keyword}.jpg", 50, description=cue.keyword),
                    ]

                def fake_video_download(candidate, cue, video_dir, diagnostics=None):
                    if diagnostics is not None:
                        diagnostics.append({"source": candidate.source, "stage": "video_download", "status": "selected", "url": candidate.url, "path": str(clip)})
                    return str(clip)

                def fake_image_download(candidate, cue, image_dir, diagnostics=None):
                    image_dir.mkdir(parents=True, exist_ok=True)
                    path = image_dir / f"{cue.keyword.replace(' ', '_')}.jpg"
                    path.write_bytes(b"fake-image")
                    if diagnostics is not None:
                        diagnostics.append({"source": candidate.source, "stage": "image_download", "status": "selected", "url": candidate.url, "path": str(path)})
                    return str(path)

                asset_module.search_video_candidates = fake_video_search
                asset_module.search_image_candidates = fake_image_search
                asset_module.download_video_candidate = fake_video_download
                asset_module.download_image_candidate = fake_image_download

                cues = [
                    TimedVisualCue(0, 3000, "one", "Iron Man battle", subject_lock=True, required_subjects=["Iron Man"]),
                    TimedVisualCue(3000, 6000, "two", "Iron Man battle", subject_lock=True, required_subjects=["Iron Man"]),
                ]
                bundle = AssetAgent(run_dir).run(
                    [ImageCue("Iron Man battle", "word_0")],
                    [],
                    _genre(),
                    pexels_key="key",
                    timed_visual_cues=cues,
                )
                self.assertEqual(bundle.media_types, ["video", "image"])
                self.assertEqual(len(bundle.media_durations_ms), 2)
                self.assertTrue(any(sample.get("reason") for sample in bundle.asset_selection_trace[1]["rejected_samples"]))
        finally:
            asset_module.search_video_candidates = old_video_search
            asset_module.search_image_candidates = old_image_search
            asset_module.download_video_candidate = old_video_download
            asset_module.download_image_candidate = old_image_download

    def test_selected_image_url_is_not_reused_for_next_interval(self) -> None:
        import agents.asset_agent as asset_module

        old_video_search = asset_module.search_video_candidates
        old_image_search = asset_module.search_image_candidates
        old_image_download = asset_module.download_image_candidate
        try:
            with tempfile.TemporaryDirectory() as tmp:
                run_dir = Path(tmp)

                def fake_video_search(*_args, **_kwargs):
                    return []

                def fake_image_search(cue, genre, pexels_key="", pixabay_key="", unsplash_key="", diagnostics=None):
                    return [
                        AssetCandidate("image", "duckduckgo", "https://images.example.com/reused.jpg", 100, description="same top image"),
                        AssetCandidate("image", "duckduckgo", f"https://images.example.com/{cue.timestamp_hint}.jpg", 50, description="unique fallback image"),
                    ]

                def fake_image_download(candidate, cue, image_dir, diagnostics=None):
                    image_dir.mkdir(parents=True, exist_ok=True)
                    name = "reused.jpg" if "reused" in candidate.url else f"{cue.timestamp_hint}.jpg"
                    path = image_dir / name
                    path.write_bytes(b"fake-image")
                    if diagnostics is not None:
                        diagnostics.append({"source": candidate.source, "stage": "image_download", "status": "selected", "url": candidate.url, "path": str(path)})
                    return str(path)

                asset_module.search_video_candidates = fake_video_search
                asset_module.search_image_candidates = fake_image_search
                asset_module.download_image_candidate = fake_image_download
                cues = [
                    TimedVisualCue(0, 3000, "one", "first cue"),
                    TimedVisualCue(3000, 6000, "two", "second cue"),
                ]
                bundle = AssetAgent(run_dir).run([ImageCue("fallback", "word_0")], [], _genre(), timed_visual_cues=cues)
                self.assertEqual(bundle.media_types, ["image", "image"])
                self.assertNotEqual(bundle.asset_selection_trace[0]["selected_url"], bundle.asset_selection_trace[1]["selected_url"])
                self.assertTrue(any(sample.get("reason") == "same asset URL already selected in this run" for sample in bundle.asset_selection_trace[1]["rejected_samples"]))
        finally:
            asset_module.search_video_candidates = old_video_search
            asset_module.search_image_candidates = old_image_search
            asset_module.download_image_candidate = old_image_download

    def test_duckduckgo_video_is_checked_before_pexels(self) -> None:
        import modules.assets.video_fetcher as video_module

        old_duck = video_module.search_duckduckgo_videos
        old_pexels = video_module.search_pexels_videos
        old_download = video_module.download_video
        try:
            with tempfile.TemporaryDirectory() as tmp:
                video_dir = Path(tmp)

                def fake_duck(query, max_results=8):
                    return [VideoResult(url="https://cdn.example.com/thor.mp4", title=f"{query} direct clip", source="duckduckgo", width=1080, height=1920, duration=4)]

                def fake_pexels(query, api_key, max_results=8):
                    return [VideoResult(url="https://cdn.example.com/pexels.mp4", title="unrelated cooking clip", source="pexels", width=720, height=1280, duration=4)]

                def fake_download(url, target):
                    target.write_bytes(b"fake-video")
                    return str(target)

                video_module.search_duckduckgo_videos = fake_duck
                video_module.search_pexels_videos = fake_pexels
                video_module.download_video = fake_download
                diagnostics = []
                path, source = video_module.fetch_video_for_cue(ImageCue("Thor battle street", "word_0"), video_dir, _genre(), pexels_key="key", diagnostics=diagnostics)
                self.assertEqual(source, "duckduckgo")
                self.assertTrue(Path(path).exists())
                self.assertTrue(any(item.get("source") == "duckduckgo" for item in diagnostics))
        finally:
            video_module.search_duckduckgo_videos = old_duck
            video_module.search_pexels_videos = old_pexels
            video_module.download_video = old_download

    def test_duckduckgo_image_is_checked_before_other_image_sources(self) -> None:
        import modules.assets.image_fetcher as image_module

        old_duck = image_module.search_duckduckgo_images
        old_download = image_module.download_image
        try:
            with tempfile.TemporaryDirectory() as tmp:
                image_dir = Path(tmp)

                def fake_duck(query, max_results=8):
                    return [ImageResult(url="https://images.example.com/thor.jpg", source="duckduckgo", width=1200, height=1600, description=f"{query} photo")]

                def fake_download(url, target):
                    target.write_bytes(b"fake-image")
                    return str(target)

                image_module.search_duckduckgo_images = fake_duck
                image_module.download_image = fake_download
                diagnostics = []
                path, source = image_module.fetch_image_for_cue(ImageCue("Thor battle street", "word_0"), image_dir, _genre(), diagnostics=diagnostics)
                self.assertEqual(source, "duckduckgo")
                self.assertTrue(Path(path).exists())
                self.assertTrue(any(item.get("source") == "duckduckgo" for item in diagnostics))
        finally:
            image_module.search_duckduckgo_images = old_duck
            image_module.download_image = old_download

    def test_render_command_uses_per_segment_durations(self) -> None:
        cmd = build_media_timeline_command(
            ffmpeg="ffmpeg",
            media_paths=["a.jpg", "b.mp4"],
            media_types=["image", "video"],
            audio_path="voice.wav",
            ass_caption_path="captions.ass",
            output_path="out.mp4",
            duration_seconds=6.0,
            media_durations_ms=[2500, 3500],
        )
        joined = " ".join(cmd)
        self.assertIn("-t 2.50", joined)
        self.assertIn("-t 3.50", joined)
        self.assertIn("zoompan=", joined)
        self.assertIn("gblur=sigma=28", joined)
        self.assertIn("overlay=(W-w)/2:(H-h)/2", joined)
        self.assertIn("fade=t=out", joined)
        self.assertIn("trim=duration=2.50,setpts=PTS-STARTPTS", joined)
        self.assertIn("concat=n=2:v=1:a=0", joined)
        self.assertNotIn("xfade=", joined)
        self.assertIn("-t 6.000", joined)

    def test_image_timeline_segments_are_trimmed_after_zoompan(self) -> None:
        cmd = build_media_timeline_command(
            ffmpeg="ffmpeg",
            media_paths=["a.jpg", "b.jpg", "c.jpg"],
            media_types=["image", "image", "image"],
            audio_path="voice.wav",
            ass_caption_path="captions.ass",
            output_path="out.mp4",
            duration_seconds=9.0,
            media_durations_ms=[2500, 3500, 3000],
        )
        joined = " ".join(cmd)
        self.assertEqual(joined.count("zoompan="), 3)
        self.assertEqual(joined.count("gblur=sigma=28"), 3)
        self.assertEqual(joined.count("overlay=(W-w)/2:(H-h)/2"), 3)
        self.assertIn("fade=t=in:st=0", joined)
        self.assertIn("fade=t=out", joined)
        self.assertIn("trim=duration=2.50,setpts=PTS-STARTPTS", joined)
        self.assertIn("trim=duration=3.50,setpts=PTS-STARTPTS", joined)
        self.assertIn("trim=duration=3.00,setpts=PTS-STARTPTS", joined)
        self.assertIn("concat=n=3:v=1:a=0", joined)

    def test_ass_captions_highlight_active_words_with_safe_margins(self) -> None:
        words = [
            WordTimestamp("Thor", 0, 250),
            WordTimestamp("raises", 260, 520),
            WordTimestamp("the", 530, 700),
            WordTimestamp("hammer", 710, 960),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path, phrase_count = build_ass(words, Path(temp_dir) / "captions.ass", preset="clean_pro", emphasis_words=["hammer"])
            content = Path(path).read_text(encoding="utf-8")

        self.assertEqual(phrase_count, 1)
        self.assertIn("Style: Default,Roboto Bold", content)
        self.assertIn(",60,60,250,1", content)
        self.assertEqual(content.count("Dialogue:"), 4)
        self.assertIn(r"\pos(540,1450)", content)
        self.assertIn(r"\fad(60,90)", content)
        self.assertIn(r"\fscx120\fscy120", content)
        self.assertIn("THOR RAISES THE", content)

    def test_ass_captions_wrap_to_two_lines_and_cap_screen_words(self) -> None:
        words = [
            WordTimestamp("ancient", 0, 200),
            WordTimestamp("roman", 210, 410),
            WordTimestamp("concrete", 420, 620),
            WordTimestamp("survived", 630, 830),
            WordTimestamp("because", 840, 1040),
            WordTimestamp("seawater", 1050, 1250),
            WordTimestamp("formed", 1260, 1460),
            WordTimestamp("crystals", 1470, 1670),
            WordTimestamp("slowly", 1680, 1880),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path, _ = build_ass(words, Path(temp_dir) / "captions.ass", preset="classic_white")
            content = Path(path).read_text(encoding="utf-8")

        first_dialogue = next(line for line in content.splitlines() if line.startswith("Dialogue:"))
        caption_text = first_dialogue.rsplit(",,", 1)[-1]
        self.assertEqual(caption_text.count(r"\N"), 1)
        self.assertNotIn("SLOWLY", caption_text)
        self.assertIn(r"\fs76", first_dialogue)


if __name__ == "__main__":
    unittest.main()
