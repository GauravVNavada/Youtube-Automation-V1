from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "final_pipeline"
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))

from agents.asset_agent import AssetAgent
import agents.audio_agent as audio_module
from agents.audio_agent import AudioAgent
from agents.validation_agent import ValidationAgent
from app.schemas import GenreConfig, ImageCue, ScriptOutput, TimedVisualCue, WordTimestamp
from main import combine_topic_and_angle, duration_from_topic, strip_duration_instruction
from modules.scripts.generator import build_user_prompt, generate_script, script_from_mapping, validate_script_originality, validate_script_relevance
from modules.assets.candidates import AssetCandidate
from modules.assets.fallback_image import create_fallback_image
from modules.assets.image_scoring import ImageResult
from modules.assets.subject_lock import infer_subject_lock
from modules.assets.video_services import VideoResult
from modules.captions.ass_builder import build_ass
from modules.audio.alignment import _map_whisper_timestamps_to_script
from modules.audio.humanizer import _build_excess_pause_cuts
from modules.render.ffmpeg_builder import build_image_slideshow_command, build_media_timeline_command
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


class SequenceGeminiProvider:
    name = "gemini"

    def __init__(self, payloads: list[dict]):
        self.payloads = list(payloads)

    def generate_json(self, *_args):
        if not self.payloads:
            raise AssertionError("No fake Gemini payloads left")
        return self.payloads.pop(0)


class CapturingSequenceGeminiProvider(SequenceGeminiProvider):
    def __init__(self, payloads: list[dict]):
        super().__init__(payloads)
        self.prompts: list[str] = []

    def generate_json(self, _system, prompt, *_args):
        self.prompts.append(prompt)
        return super().generate_json(_system, prompt, *_args)


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
    def test_whisper_alignment_restores_script_words_with_exact_match(self) -> None:
        mapped = _map_whisper_timestamps_to_script(
            [
                WordTimestamp("Iron", 100, 250),
                WordTimestamp("Man", 260, 420),
                WordTimestamp("waited", 430, 700),
            ],
            "Iron Man waited.",
            1000,
        )

        self.assertEqual([word.word for word in mapped], ["Iron", "Man", "waited."])
        self.assertEqual([(word.start_ms, word.end_ms) for word in mapped], [(100, 250), (260, 420), (430, 700)])

    def test_whisper_alignment_distributes_merged_words_over_script_words(self) -> None:
        mapped = _map_whisper_timestamps_to_script(
            [
                WordTimestamp("I", 0, 120),
                WordTimestamp("don't", 130, 430),
                WordTimestamp("know", 440, 700),
            ],
            "I do not know.",
            900,
        )

        self.assertEqual([word.word for word in mapped], ["I", "do", "not", "know."])
        self.assertEqual((mapped[1].start_ms, mapped[2].end_ms), (130, 430))
        self.assertLess(mapped[1].end_ms, mapped[2].end_ms)

    def test_whisper_alignment_interpolates_skipped_script_words(self) -> None:
        mapped = _map_whisper_timestamps_to_script(
            [
                WordTimestamp("The", 0, 120),
                WordTimestamp("door", 300, 520),
            ],
            "The red door.",
            700,
        )

        self.assertEqual([word.word for word in mapped], ["The", "red", "door."])
        self.assertGreaterEqual(mapped[1].start_ms, mapped[0].end_ms)
        self.assertLessEqual(mapped[1].end_ms, mapped[2].start_ms)

    def test_audio_humanizer_does_not_trim_inside_unpunctuated_speech(self) -> None:
        cuts = _build_excess_pause_cuts(
            [
                WordTimestamp("This", 0, 120),
                WordTimestamp("gap", 700, 900),
                WordTimestamp("stays.", 1600, 1900),
                WordTimestamp("But", 3000, 3200),
            ],
            source_duration_ms=3600,
        )

        self.assertEqual(cuts, [(2550, 3000)])

    def test_audio_agent_uses_default_tts_speed_until_user_changes_it(self) -> None:
        captured_rates = []

        def fake_google_tts(_text, output_path, _credentials, speaking_rate=None):
            captured_rates.append(speaking_rate)
            Path(output_path).write_bytes(b"fake wav")
            return str(output_path)

        def fake_copy(_source, target):
            Path(target).write_bytes(b"fake wav")

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("agents.audio_agent.synthesize_google_tts", side_effect=fake_google_tts),
                patch("agents.audio_agent.probe_audio_duration_ms", return_value=10000),
                patch("agents.audio_agent.AudioAgent._word_timestamps", return_value=([WordTimestamp("Hello", 0, 400)], "estimated")),
                patch("agents.audio_agent._convert_or_copy_audio", side_effect=fake_copy),
                patch("agents.audio_agent._insert_sentence_gaps", return_value=(0, [WordTimestamp("Hello", 0, 400)])),
                patch("agents.audio_agent._prepend_silence", return_value=False),
                patch("agents.audio_agent.analyze_audio_quality", return_value=SimpleNamespace(mean_volume_db=-20.0, max_volume_db=-3.0, longest_silence_seconds=0.0)),
            ):
                AudioAgent(Path(tmp)).run("Hello world.", 2, 60, _genre(), google_tts_credentials="/tmp/google.json")
                AudioAgent(Path(tmp)).run("Hello world.", 2, 60, _genre(), google_tts_credentials="/tmp/google.json", voice_speed_multiplier=0.88)

        self.assertEqual(captured_rates, [None, 0.88])

    def test_audio_agent_does_not_add_default_synthetic_pauses(self) -> None:
        self.assertEqual(audio_module.INITIAL_AUDIO_SILENCE_MS, 0)
        self.assertEqual(audio_module.SENTENCE_AUDIO_GAP_MS, 0)

    def test_script_mapping_cleans_tts_quote_artifacts(self) -> None:
        script = script_from_mapping(
            {
                "title": "Spider-Man Brand New Day",
                "narration": "This starts with '' a broken beat. But 'Brand New Day' isn't just a label. It says \"Peter changes\" now.",
                "hook_line": "This starts with '' a broken beat.",
                "image_cues": [
                    {"keyword": "Spider-Man comic city action", "timestamp_hint": "word_0"},
                    {"keyword": "Spider-Man city skyline comic", "timestamp_hint": "word_12"},
                    {"keyword": "Spider-Man mask close up", "timestamp_hint": "word_24"},
                    {"keyword": "Spider-Man comic cover table", "timestamp_hint": "word_36"},
                    {"keyword": "Spider-Man final swing city", "timestamp_hint": "word_48"},
                ],
            },
            provider="test",
            topic="spider man brand new day",
        )

        self.assertNotIn("''", script.narration)
        self.assertNotIn("'Brand New Day'", script.narration)
        self.assertNotIn('"Peter changes"', script.narration)
        self.assertIn("Brand New Day", script.narration)
        self.assertIn("isn't", script.narration)
        self.assertEqual(script.hook_line, "This starts with a broken beat.")

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

    def test_validation_agent_accepts_normalized_spider_man_date_topic(self) -> None:
        narration = (
            "Spider-Man felt different at the start of 2020 because the hero was being pulled in two directions. "
            "On one side, fans wanted the familiar mask, the jokes, and the city swinging above traffic. "
            "On the other side, the story needed a reason to feel new. "
            "But the date should not become the hero; it should become the pressure around him. "
            "That is why the January angle works for a short. "
            "It gives the video a clear moment in time without pretending the date is the entire subject. "
            "The point is simple: Spider-Man lasts because every new chapter can change the pressure while keeping the responsibility."
        )
        provider = SequenceGeminiProvider(
            [
                _script_payload("Spider-Man In January 2020", narration, "Spider-Man comic city"),
                {"passed": True, "issues": []},
            ]
        )
        script = generate_script(
            provider,
            "spider man january 2020",
            _genre(),
            45,
            [
                {
                    "title": "Comic Hero Choice",
                    "script": "The strongest hero in the panel is not always the one throwing the punch. Start with the city falling apart behind them.",
                    "overall_score": 99,
                }
            ],
        )
        self.assertEqual(script.provider, "gemini")
        self.assertIn("Spider-Man", script.narration)
        with tempfile.TemporaryDirectory() as tmp:
            result = ValidationAgent(Path(tmp)).validate_script_output(
                script,
                _genre(),
                provider=provider,
                topic="spider man january 2020",
                reference_scripts=[],
            )
        self.assertTrue(result.passed)

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
        doctor_topic = "make a video speaking on different powers of doctor strange(avengers hero)"
        self.assertEqual(
            combine_topic_and_angle(doctor_topic, f"{doctor_topic} - black knight dane whitman"),
            doctor_topic,
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

    def test_instruction_fragment_with_number_is_not_named_subject(self) -> None:
        lock = infer_subject_lock("i want a 1 minute short about a comic hero choice")
        self.assertFalse(lock.enabled)

    def test_doctor_strange_subject_lock_wins_over_avengers_context(self) -> None:
        lock = infer_subject_lock("make a video speaking on different powers of doctor strange(avengers hero)")
        self.assertTrue(lock.enabled)
        self.assertEqual(lock.subject, "Doctor Strange")
        self.assertIn("Stephen Strange", lock.aliases)

    def test_named_subject_prompt_retries_without_copying_few_shot_example(self) -> None:
        copied_mirror = {
            "title": "The Scratches Behind The Mirror",
            "narration": (
                "Maya first heard the scratching at 2:13 a.m. It came from the bathroom mirror, slow and careful, like a nail dragging across glass. "
                "She checked the sink, the wall, even the cabinet behind it. Nothing was there. Then the scratching stopped. "
                "A foggy line appeared on the mirror from the inside. It wrote one word: move. Maya stepped back. "
                "A second later, the mirror cracked outward, and a rusted screw fell into the sink. The mirror was not haunted. "
                "Someone had been loosening it from the other side."
            ),
            "hook_line": "Maya first heard the scratching at 2:13 a.m.",
            "word_count": 81,
            "estimated_duration": 30,
            "description": "A short horror story about a mirror.",
            "hashtags": ["#shorts", "#horror"],
            "image_cues": [
                {"keyword": "dark bathroom mirror night", "timestamp_hint": "word_0", "mood": "dark"},
                {"keyword": "scratched glass closeup", "timestamp_hint": "word_12", "mood": "eerie"},
                {"keyword": "woman checking bathroom cabinet", "timestamp_hint": "word_28", "mood": "dark"},
                {"keyword": "foggy mirror written word", "timestamp_hint": "word_43", "mood": "reveal"},
                {"keyword": "cracked mirror bathroom sink", "timestamp_hint": "word_61", "mood": "dramatic"},
            ],
            "sfx_cues": [],
            "emphasis_words": [],
        }
        good_narration = (
            "Doctor Strange is dangerous because his powers are choices, not just glowing tricks. "
            "First, portals let him turn distance into a weapon, moving allies or enemies in one blink. "
            "Then his shields buy time when a fight should already be lost. "
            "But the wild part is the mirror dimension, where the battlefield itself can bend around him. "
            "Add astral projection, spell knowledge, and quick thinking, and the point becomes clear. "
            "Doctor Strange wins when he controls the rules of the scene."
        )
        provider = CapturingSequenceGeminiProvider(
            [
                copied_mirror,
                _script_payload("Doctor Strange Power Rules", good_narration, "Doctor Strange magic portal"),
            ]
        )

        script = generate_script(
            provider,
            "make a video speaking on different powers of doctor strange(avengers hero)",
            _genre(),
            60,
            [],
        )

        self.assertIn("Doctor Strange", script.narration)
        self.assertNotIn("One real anchor here is", script.narration)
        self.assertEqual(len(provider.prompts), 2)
        self.assertNotIn("The Scratches Behind The Mirror", "\n".join(provider.prompts))

    def test_script_relevance_accepts_spider_man_hyphenation(self) -> None:
        script = ScriptOutput(
            title="Spider-Man Brand New Day",
            narration="Spider-Man faces a Brand New Day with new pressure and responsibility.",
            hook_line="Spider-Man faces a Brand New Day with new pressure and responsibility.",
            word_count=11,
            estimated_duration=30,
            description="A comic short about Spider-Man and Brand New Day.",
            hashtags=[],
            image_cues=[],
            sfx_cues=[],
        )
        issues = validate_script_relevance(script, "video on spiderman brand new day, his next new movie")
        self.assertEqual(issues, [])

    def test_script_relevance_does_not_require_weak_topic_words(self) -> None:
        script = ScriptOutput(
            title="Why Spider-Man Still Works",
            narration="Spider-Man works because power never removes his everyday pressure.",
            hook_line="Spider-Man works because power never removes his everyday pressure.",
            word_count=9,
            estimated_duration=30,
            description="A comic short about Spider-Man.",
            hashtags=[],
            image_cues=[],
            sfx_cues=[],
        )
        issues = validate_script_relevance(script, "video on spiderman brand new day, his next new movie")
        self.assertEqual(issues, [])

    def test_script_originality_rejects_copied_reference_script(self) -> None:
        copied = (
            "The strongest hero in the panel is not always the one throwing the punch. "
            "Start with the city falling apart behind them. "
            "A villain offers the easy win: save one person, abandon the rest, and walk away called a hero. "
            "That is where the comic gets interesting."
        )
        script = ScriptOutput(
            title="Copied Comic Beat",
            narration=copied,
            hook_line="The strongest hero in the panel is not always the one throwing the punch.",
            word_count=35,
            estimated_duration=30,
            description="",
            hashtags=[],
            image_cues=[],
            sfx_cues=[],
        )
        issues = validate_script_originality(script, [{"title": "Comic Hero Choice", "script": copied}])
        self.assertTrue(issues)
        self.assertIn("copies too much", issues[0])

    def test_script_originality_allows_fresh_script_with_same_genre_shape(self) -> None:
        reference = (
            "The strongest hero in the panel is not always the one throwing the punch. "
            "Start with the city falling apart behind them. "
            "A villain offers the easy win: save one person, abandon the rest, and walk away called a hero. "
            "That is where the comic gets interesting. "
            "The costume matters less than the choice."
        )
        fresh = (
            "Spider-Man works because the mask never makes the choice simple. "
            "Start with Peter hearing two alarms at once: one from the city, one from home. "
            "The villain wants him to chase the loud disaster while someone smaller gets forgotten. "
            "That pressure is the real comic-book engine. "
            "The final swing matters because he chooses responsibility when nobody is clapping."
        )
        script = ScriptOutput(
            title="Why Spider-Man Still Works",
            narration=fresh,
            hook_line="Spider-Man works because the mask never makes the choice simple.",
            word_count=len(fresh.split()),
            estimated_duration=30,
            description="",
            hashtags=[],
            image_cues=[],
            sfx_cues=[],
        )
        issues = validate_script_originality(script, [{"title": "Comic Hero Choice", "script": reference}])
        self.assertEqual(issues, [])

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
                    return create_fallback_image("thor", target)

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

    def test_corrupt_downloaded_image_falls_back_before_render(self) -> None:
        import modules.assets.image_fetcher as image_module

        old_duck = image_module.search_duckduckgo_images
        old_download = image_module.download_image
        try:
            with tempfile.TemporaryDirectory() as tmp:
                image_dir = Path(tmp)

                def fake_duck(query, max_results=8):
                    return [ImageResult(url="https://images.example.com/bad.jpg", source="duckduckgo", width=1200, height=1600, description=f"{query} photo")]

                def fake_download(url, target):
                    target.write_bytes(b"not-a-real-image")
                    return str(target)

                image_module.search_duckduckgo_images = fake_duck
                image_module.download_image = fake_download
                diagnostics = []
                path, source = image_module.fetch_image_for_cue(ImageCue("bad image", "word_0"), image_dir, _genre(), diagnostics=diagnostics)
                self.assertEqual(source, "generated_fallback")
                self.assertTrue(Path(path).exists())
                self.assertTrue(any(item.get("status") == "error" for item in diagnostics))
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
        self.assertIn("-t 2.95", joined)
        self.assertIn("-t 3.50", joined)
        self.assertIn("zoompan=", joined)
        self.assertIn("force_original_aspect_ratio=increase:flags=lanczos", joined)
        self.assertIn("force_original_aspect_ratio=decrease:flags=lanczos", joined)
        self.assertIn("gblur=sigma=24", joined)
        self.assertIn("overlay=(W-w)/2:(H-h)/2", joined)
        self.assertIn("trim=end_frame=1,setpts=PTS-STARTPTS[comp0]", joined)
        self.assertIn("[comp0]zoompan=", joined)
        self.assertIn("s=2160x3840:fps=30", joined)
        self.assertIn("scale=1080:1920:flags=lanczos,setsar=1,format=yuv420p[v0]", joined)
        self.assertIn("x='trunc((iw-iw/zoom)/4)*2':y='trunc((ih-ih/zoom)/4)*2'", joined)
        self.assertNotIn("zoom+", joined)
        self.assertNotIn("iw/2-(iw/zoom/2)", joined)
        self.assertNotIn("fade=t=", joined)
        self.assertIn("trim=duration=2.95,setpts=PTS-STARTPTS", joined)
        self.assertIn("xfade=transition=slideleft:duration=0.45:offset=2.50", joined)
        self.assertNotIn("concat=n=2:v=1:a=0", joined)
        self.assertIn("-f image2 -loop 1 -t 2.95 -i a.jpg", joined)
        self.assertIn("alimiter=limit=0.89", joined)
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
        self.assertEqual(joined.count("force_original_aspect_ratio=increase:flags=lanczos"), 3)
        self.assertEqual(joined.count("force_original_aspect_ratio=decrease:flags=lanczos"), 3)
        self.assertEqual(joined.count("gblur=sigma=24"), 3)
        self.assertEqual(joined.count("overlay=(W-w)/2:(H-h)/2"), 3)
        self.assertEqual(joined.count("trim=end_frame=1,setpts=PTS-STARTPTS[comp"), 3)
        self.assertEqual(joined.count("xfade=transition="), 2)
        self.assertIn("xfade=transition=slideleft:duration=0.45:offset=2.50", joined)
        self.assertIn("xfade=transition=slideright:duration=0.45:offset=6.00", joined)
        self.assertIn("z='min(1.2200,1+(1.2200-1)*on/87)'", joined)
        self.assertIn("z='max(1,1.1800-(1.1800-1)*on/117)'", joined)
        self.assertIn("x='trunc((iw-iw/zoom)/4)*2':y='trunc((ih-ih/zoom)/4)*2'", joined)
        self.assertNotIn("zoom+", joined)
        self.assertNotIn("iw/2-(iw/zoom/2)", joined)
        self.assertNotIn("fade=t=", joined)
        self.assertIn("trim=duration=2.95,setpts=PTS-STARTPTS", joined)
        self.assertIn("trim=duration=3.95,setpts=PTS-STARTPTS", joined)
        self.assertIn("trim=duration=3.00,setpts=PTS-STARTPTS", joined)
        self.assertNotIn("concat=n=3:v=1:a=0", joined)

    def test_image_slideshow_uses_quick_slide_transitions(self) -> None:
        cmd = build_image_slideshow_command(
            ffmpeg="ffmpeg",
            image_paths=["a.jpg", "b.jpg", "c.jpg"],
            audio_path="voice.wav",
            ass_caption_path="captions.ass",
            output_path="out.mp4",
            duration_seconds=9.0,
        )
        joined = " ".join(cmd)
        self.assertIn("xfade=transition=slideleft:duration=0.45:offset=3.00", joined)
        self.assertIn("xfade=transition=slideright:duration=0.45:offset=6.00", joined)
        self.assertNotIn("concat=n=3:v=1:a=0", joined)
        self.assertNotIn("fade=t=", joined)

    def test_media_timeline_without_explicit_durations_uses_quick_slide_transitions(self) -> None:
        cmd = build_media_timeline_command(
            ffmpeg="ffmpeg",
            media_paths=["a.jpg", "b.jpg"],
            media_types=["image", "image"],
            audio_path="voice.wav",
            ass_caption_path="captions.ass",
            output_path="out.mp4",
            duration_seconds=6.0,
        )
        joined = " ".join(cmd)
        self.assertIn("xfade=transition=slideleft:duration=0.45:offset=3.00", joined)
        self.assertNotIn("concat=n=2:v=1:a=0", joined)
        self.assertNotIn("fade=t=", joined)

    def test_render_command_supports_centered_zoom_variants_and_transition_options(self) -> None:
        fade_cmd = build_image_slideshow_command(
            ffmpeg="ffmpeg",
            image_paths=["a.jpg", "b.jpg"],
            audio_path="voice.wav",
            ass_caption_path="captions.ass",
            output_path="out.mp4",
            duration_seconds=6.0,
            visual_motion=False,
            transition_style="fade",
            transition_seconds=0.6,
            zoom_variant="still",
        )
        fade_joined = " ".join(fade_cmd)
        self.assertIn("zoompan=z='1':x='trunc((iw-iw/zoom)/4)*2':y='trunc((ih-ih/zoom)/4)*2'", fade_joined)
        self.assertIn("xfade=transition=fade:duration=0.60:offset=3.00", fade_joined)

        cut_cmd = build_image_slideshow_command(
            ffmpeg="ffmpeg",
            image_paths=["a.jpg", "b.jpg"],
            audio_path="voice.wav",
            ass_caption_path="captions.ass",
            output_path="out.mp4",
            duration_seconds=6.0,
            transition_style="cut",
        )
        cut_joined = " ".join(cut_cmd)
        self.assertIn("concat=n=2:v=1:a=0", cut_joined)
        self.assertNotIn("xfade=transition=", cut_joined)

    def test_still_zoom_variants_use_frame_indexed_stable_motion(self) -> None:
        cases = [
            ("center_in", "z='min(1.2500,1+(1.2500-1)*on/89)'"),
            ("center_out", "z='max(1,1.2500-(1.2500-1)*on/89)'"),
            ("still", "z='1'"),
        ]
        for variant, expected in cases:
            cmd = build_image_slideshow_command(
                ffmpeg="ffmpeg",
                image_paths=["a.jpg"],
                audio_path="voice.wav",
                ass_caption_path="captions.ass",
                output_path="out.mp4",
                duration_seconds=3.0,
                zoom_variant=variant,
            )
            joined = " ".join(cmd)
            self.assertIn(expected, joined)
            self.assertIn("s=2160x3840:fps=30", joined)
            self.assertIn("x='trunc((iw-iw/zoom)/4)*2':y='trunc((ih-ih/zoom)/4)*2'", joined)
            self.assertNotIn("zoom+", joined)
            self.assertNotIn("iw/2-(iw/zoom/2)", joined)

        mixed_cmd = build_image_slideshow_command(
            ffmpeg="ffmpeg",
            image_paths=["a.jpg", "b.jpg"],
            audio_path="voice.wav",
            ass_caption_path="captions.ass",
            output_path="out.mp4",
            duration_seconds=6.0,
            zoom_variant="mixed",
        )
        mixed_joined = " ".join(mixed_cmd)
        self.assertIn("z='min(1.2500,1+(1.2500-1)*on/102)'", mixed_joined)
        self.assertIn("z='max(1,1.2500-(1.2500-1)*on/89)'", mixed_joined)

    def test_render_command_keeps_narration_dominant_when_mixing_music(self) -> None:
        cmd = build_image_slideshow_command(
            ffmpeg="ffmpeg",
            image_paths=["a.jpg"],
            audio_path="voice.wav",
            ass_caption_path="captions.ass",
            output_path="out.mp4",
            duration_seconds=6.0,
            music_path=str(ROOT / "README.md"),
            music_volume=0.9,
        )
        joined = " ".join(cmd)
        self.assertIn("-f image2 -loop 1", joined)
        self.assertIn("volume=0.8", joined)
        self.assertIn("amix=inputs=2:duration=first:dropout_transition=0:normalize=0", joined)
        self.assertIn("alimiter=limit=0.89", joined)

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
        self.assertNotIn(r"\fad(", content)
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
