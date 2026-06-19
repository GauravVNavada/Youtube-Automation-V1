from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "backend", ROOT / "final_pipeline"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from desktop_pipeline.master_agent import MasterAgent
from desktop_pipeline import master_agent, parameter_agent, style_sampler_agent
from desktop_pipeline.message_base import render_messages_for_single_prompt
from desktop_pipeline.parameter_agent import map_parameter_request
from desktop_pipeline.style_sampler_agent import build_style_profiles
from backend.app.services.pipeline_runner import PipelineRunner


class FakeProvider:
    def __init__(self, payload=None, error: Exception | None = None):
        self.payload = payload or {}
        self.error = error

    def generate_json(self, *_args):
        if self.error:
            raise self.error
        return self.payload


class DesktopPipelineTests(unittest.TestCase):
    def test_style_sampler_returns_three_unique_profiles(self) -> None:
        provider = FakeProvider(
            {
                "styles": [
                    {
                        "label": "Slow Mystery",
                        "script_angle": "Start with the missing clue.",
                        "pacing": "slow",
                        "visual_style": "dark closeups",
                        "audio_style": "quiet",
                        "caption_style": "clean",
                    },
                    {
                        "label": "Fast Reveal",
                        "script_angle": "Start at the chase.",
                        "pacing": "fast",
                        "visual_style": "motion shots",
                        "audio_style": "urgent",
                        "caption_style": "bold",
                    },
                    {
                        "label": "Evidence Trail",
                        "script_angle": "Start with proof.",
                        "pacing": "measured",
                        "visual_style": "documents and objects",
                        "audio_style": "calm",
                        "caption_style": "readable",
                    },
                ]
            }
        )
        profiles = build_style_profiles("school hallway chase", "scary_stories", provider=provider)
        self.assertEqual(len(profiles), 3)
        self.assertEqual(len({profile.style_id for profile in profiles}), 3)
        self.assertTrue(all(profile.sample_index in {1, 2, 3} for profile in profiles))

    def test_desktop_agents_expose_message_examples(self) -> None:
        for module in (master_agent, style_sampler_agent, parameter_agent):
            messages = module.messages_base()
            rendered = render_messages_for_single_prompt(messages)
            self.assertGreaterEqual(len(messages), 3)
            self.assertIn("SYSTEM:", rendered)
            self.assertIn("ASSISTANT:", rendered)

    def test_parameter_agent_maps_common_edit_requests(self) -> None:
        current = {"voice_speed": 1.0, "caption_words": 4, "image_count": 8, "music_volume": 0.18}
        self.assertLess(map_parameter_request("the audio speed is a lot", current).settings_patch["voice_speed"], 1.0)
        self.assertEqual(map_parameter_request("images are not good", current).target_agent, "asset_agent")
        self.assertLess(map_parameter_request("captions have too many words", current).settings_patch["caption_words"], 4)
        self.assertLess(map_parameter_request("music is too loud", current).settings_patch["music_volume"], 0.18)

    def test_master_agent_clarifies_when_gemini_route_fails(self) -> None:
        decision = MasterAgent(provider=FakeProvider(error=RuntimeError("503")), require_provider=True).decide(
            "make a video about roman concrete",
            {"genre_id": "history_facts"},
        )
        self.assertEqual(decision.intent, "ask_clarifying_question")
        self.assertTrue(decision.needs_clarification)

    def test_master_agent_creates_child_edit_from_latest_job(self) -> None:
        latest_job = {
            "id": "job-1",
            "topic": "Thor fights the Avengers",
            "genre": "scary_stories",
            "settings": {"voice_speed": 1.0, "source_prompt": "Thor fights the Avengers"},
        }
        provider = FakeProvider(
            {
                "intent": "edit_video",
                "topic": "Thor fights the Avengers",
                "genre": "scary_stories",
                "needs_clarification": False,
                "target_agent": "audio_agent",
                "settings_patch": {},
            }
        )
        decision = MasterAgent(provider=provider, require_provider=True).decide(
            "audio is too fast",
            {"genre_id": "scary_stories", "latest_job": latest_job},
        )
        self.assertEqual(decision.intent, "edit_video")
        self.assertEqual(decision.parent_job_id, "job-1")
        self.assertEqual(decision.target_agent, "audio_agent")
        self.assertLess(decision.settings_patch["voice_speed"], 1.0)

    def test_pipeline_runner_passes_desktop_settings(self) -> None:
        import backend.app.services.pipeline_runner as runner_module

        captured = {}
        old_run = runner_module.subprocess.run

        def fake_run(cmd, **_kwargs):
            captured["cmd"] = cmd
            return SimpleNamespace(returncode=0, stdout="[run] /tmp/run\nFinal video: /tmp/out.mp4\n", stderr="")

        try:
            runner_module.subprocess.run = fake_run
            PipelineRunner(backend_dir=ROOT / "backend").run(
                topic="school hallway chase sample 1",
                genre="scary_stories",
                duration=30,
                notes="style notes",
                settings={
                    "source_prompt": "school hallway chase",
                    "voice_speed": 0.88,
                    "caption_words": 3,
                    "image_count": 10,
                    "music_volume": 0.12,
                    "style_profile": {"label": "Slow Mystery"},
                    "agent_instructions": {"asset_agent": "replace weak images"},
                },
            )
        finally:
            runner_module.subprocess.run = old_run

        joined = " ".join(captured["cmd"])
        self.assertIn("--source-prompt school hallway chase", joined)
        self.assertIn("--voice-speed 0.88", joined)
        self.assertIn("--caption-words 3", joined)
        self.assertIn("--image-count 10", joined)
        self.assertIn("--music-volume 0.12", joined)
        self.assertIn("--style-profile-json", joined)
        self.assertIn("--agent-instructions-json", joined)


if __name__ == "__main__":
    unittest.main()
