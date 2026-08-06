from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "backend", ROOT / "final_pipeline"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from desktop_pipeline.master_agent import MasterAgent
from desktop_pipeline import master_agent, parameter_agent, style_sampler_agent
from desktop_pipeline.message_base import render_messages_for_single_prompt
from desktop_pipeline.parameter_agent import map_parameter_request
from desktop_pipeline.style_sampler_agent import build_style_profiles
from app.schemas import SfxCue, ValidationResult, WordTimestamp
from agents.asset_agent import _resolve_sfx
from agents.music_agent import _sfx_placements
from backend.app.services.pipeline_runner import PipelineRunner
from backend.app.routers import playground
from main import ResumeContext, run_validated_stage


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
        script_patch = map_parameter_request("the script does not look good, it feels random", current)
        self.assertEqual(script_patch.target_agent, "script_agent")
        self.assertIn("script_agent", script_patch.agent_instructions)

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

    def test_master_agent_preserves_latest_topic_for_script_feedback(self) -> None:
        latest_job = {
            "id": "job-2",
            "topic": "Spider-Man Brand New Day",
            "genre": "comics",
            "settings": {"source_prompt": "Spider-Man Brand New Day"},
        }
        provider = FakeProvider(
            {
                "intent": "generate_video",
                "topic": "the script does not look good",
                "genre": "comics",
                "needs_clarification": False,
                "settings_patch": {},
                "agent_instructions": {},
            }
        )
        decision = MasterAgent(provider=provider, require_provider=True).decide(
            "the script does not look good, it feels random",
            {"genre_id": "comics", "latest_job": latest_job},
        )
        self.assertEqual(decision.intent, "edit_video")
        self.assertEqual(decision.parent_job_id, "job-2")
        self.assertEqual(decision.topic, "Spider-Man Brand New Day")
        self.assertEqual(decision.source_prompt, "Spider-Man Brand New Day")
        self.assertIn("script_agent", decision.agent_instructions)

    def test_playground_followup_uses_parent_prompt_and_script_context(self) -> None:
        parent_id = "parent-run-1"
        with tempfile.TemporaryDirectory() as tmp:
            parent_run = {
                "schema_version": playground.RUN_SCHEMA_VERSION,
                "id": parent_id,
                "user_message": "Spider-Man Brand New Day",
                "effective_message": "Spider-Man Brand New Day",
                "raw_user_message": "make a video on Spider-Man Brand New Day",
                "genre_id": "comics",
                "duration": 30,
                "status": "succeeded",
                "stages": [
                    {
                        "id": "script_agent",
                        "output_json": {
                            "title": "Old Script",
                            "narration": "Spider-Man opens with a random scene that does not connect well.",
                        },
                    }
                ],
            }
            Path(tmp, f"{parent_id}.json").write_text(json.dumps(parent_run), encoding="utf-8")
            with patch.dict(os.environ, {"PLAYGROUND_RUNS_DIR": tmp}):
                route = playground._playground_route(
                    playground.PlaygroundRunCreate(
                        message="the script doesnt look good, it is unusual and random",
                        genre_id="comics",
                        parent_run_id=parent_id,
                        chat_history=[{"role": "user", "content": "make a video on Spider-Man Brand New Day"}],
                    )
                )

        self.assertTrue(route["is_followup"])
        self.assertEqual(route["effective_message"], "Spider-Man Brand New Day")
        self.assertEqual(route["target_agent"], "script_agent")
        self.assertIn("script_agent", route["agent_instructions"])
        self.assertIn("PREVIOUS SCRIPT CONTEXT ONLY", route["notes"])
        self.assertIn("Do not copy this failed wording", route["notes"])

    def test_playground_stage_rerun_forces_selected_agent(self) -> None:
        parent_id = "parent-run-render"
        with tempfile.TemporaryDirectory() as tmp:
            parent_run = {
                "schema_version": playground.RUN_SCHEMA_VERSION,
                "id": parent_id,
                "user_message": "School hallway story",
                "effective_message": "School hallway story",
                "raw_user_message": "make a video on School hallway story",
                "genre_id": "scary_stories",
                "duration": 30,
                "status": "succeeded",
                "stages": [],
            }
            Path(tmp, f"{parent_id}.json").write_text(json.dumps(parent_run), encoding="utf-8")
            with patch.dict(os.environ, {"PLAYGROUND_RUNS_DIR": tmp}):
                route = playground._playground_route(
                    playground.PlaygroundRunCreate(
                        message="Rerun the Render Agent node for the existing video.",
                        genre_id="scary_stories",
                        parent_run_id=parent_id,
                        rerun_stage_id="render_agent",
                        forced_agent_instructions={"render_agent": "Rerun render only; preserve other decisions."},
                    )
                )

        self.assertTrue(route["is_followup"])
        self.assertEqual(route["effective_message"], "School hallway story")
        self.assertEqual(route["target_agent"], "render_agent")
        self.assertEqual(route["rerun_stage_id"], "render_agent")
        self.assertIn("render_agent", route["agent_instructions"])

    def test_playground_music_rerun_targets_music_agent_with_uploaded_track(self) -> None:
        parent_id = "parent-run-music"
        with tempfile.TemporaryDirectory() as runs_tmp, tempfile.TemporaryDirectory() as data_tmp:
            music_dir = Path(data_tmp) / "assets" / "music" / "uploads"
            music_dir.mkdir(parents=True)
            music_file = music_dir / "bed.mp3"
            music_file.write_bytes(b"fake-audio")
            parent_run = {
                "schema_version": playground.RUN_SCHEMA_VERSION,
                "id": parent_id,
                "user_message": "School hallway story",
                "effective_message": "School hallway story",
                "raw_user_message": "make a video on School hallway story",
                "genre_id": "scary_stories",
                "duration": 30,
                "status": "succeeded",
                "stages": [],
            }
            Path(runs_tmp, f"{parent_id}.json").write_text(json.dumps(parent_run), encoding="utf-8")
            with patch.dict(os.environ, {"PLAYGROUND_RUNS_DIR": runs_tmp, "PLAYGROUND_PIPELINE_DATA_DIR": data_tmp}):
                route = playground._playground_route(
                    playground.PlaygroundRunCreate(
                        message="Playground controls rerun: Music Agent",
                        genre_id="scary_stories",
                        parent_run_id=parent_id,
                        rerun_stage_id="music_agent",
                        music_path=str(music_file),
                        settings_patch={"music_volume": 0.18},
                    )
                )

        self.assertTrue(route["is_followup"])
        self.assertEqual(route["target_agent"], "music_agent")
        self.assertEqual(route["rerun_stage_id"], "music_agent")
        self.assertEqual(route["music_path"], str(music_file.resolve()))
        self.assertEqual(route["settings_patch"]["music_volume"], 0.18)

    def test_asset_agent_resolves_sfx_from_local_library(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sfx_dir = Path(tmp) / "assets" / "sfx"
            sfx_dir.mkdir(parents=True)
            whoosh = sfx_dir / "simple-whoosh-382724.mp3"
            whoosh.write_bytes(b"fake")

            with patch.dict(os.environ, {"MODULARSHORTS_DB_SFX_CATALOG": "0"}), patch("agents.asset_agent.DATA_DIR", Path(tmp)):
                paths, trace = _resolve_sfx([SfxCue(trigger_word="fight", sfx_type="fast_whoosh")])

        self.assertEqual(paths, [str(whoosh)])
        self.assertEqual(trace[0]["status"], "matched")
        self.assertIn("whoosh", trace[0]["strategy"])
        self.assertEqual(trace[0]["sfx_id"], "simple_whoosh")

    def test_asset_agent_resolves_script_sfx_aliases_from_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sfx_dir = Path(tmp) / "assets" / "sfx"
            sfx_dir.mkdir(parents=True)
            smash = sfx_dir / "impact-cinematic-boom-05-352465.mp3"
            growl = sfx_dir / "bass-impact-327529.mp3"
            smash.write_bytes(b"fake")
            growl.write_bytes(b"fake")

            with patch.dict(os.environ, {"MODULARSHORTS_DB_SFX_CATALOG": "0"}), patch("agents.asset_agent.DATA_DIR", Path(tmp)):
                paths, trace = _resolve_sfx(
                    [
                        SfxCue(trigger_word="smash", sfx_type="concrete_smash"),
                        SfxCue(trigger_word="rage", sfx_type="deep_growl"),
                    ]
                )

        self.assertEqual(paths, [str(smash.resolve()), str(growl.resolve())])
        self.assertEqual([item["status"] for item in trace], ["matched", "matched"])
        self.assertEqual([item["sfx_id"] for item in trace], ["impact_cinematic_boom", "bass_impact"])

    def test_music_agent_places_sfx_before_trigger_word(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sfx = Path(tmp) / "impact.mp3"
            sfx.write_bytes(b"fake")
            placements = _sfx_placements(
                [str(sfx)],
                [SfxCue(trigger_word="door", sfx_type="impact", timestamp_hint="during word")],
                [
                    WordTimestamp("The", 0, 200),
                    WordTimestamp("door", 1000, 1300),
                ],
                5000,
            )

        self.assertEqual(placements[0]["trigger_ms"], 1000)
        self.assertEqual(placements[0]["position_ms"], 800)
        self.assertEqual(placements[0]["strategy"], "trigger_word")

    def test_playground_rerun_settings_are_cleaned_for_render_controls(self) -> None:
        parent_id = "parent-run-render-settings"
        with tempfile.TemporaryDirectory() as tmp:
            parent_run = {
                "schema_version": playground.RUN_SCHEMA_VERSION,
                "id": parent_id,
                "user_message": "School hallway story",
                "effective_message": "School hallway story",
                "raw_user_message": "make a video on School hallway story",
                "genre_id": "scary_stories",
                "duration": 30,
                "status": "succeeded",
                "settings": {"music_volume": 0.2, "transition_style": "slide"},
                "stages": [],
            }
            Path(tmp, f"{parent_id}.json").write_text(json.dumps(parent_run), encoding="utf-8")
            with patch.dict(os.environ, {"PLAYGROUND_RUNS_DIR": tmp}):
                route = playground._playground_route(
                    playground.PlaygroundRunCreate(
                        message="Playground controls rerun: Render Agent",
                        genre_id="scary_stories",
                        parent_run_id=parent_id,
                        rerun_stage_id="render_agent",
                        settings_patch={
                            "visual_motion": False,
                            "transition_style": "wipe",
                            "transition_seconds": 2.0,
                            "zoom_variant": "out",
                            "music_volume": 0.99,
                        },
                    )
                )

        self.assertEqual(route["settings_patch"]["visual_motion"], False)
        self.assertEqual(route["settings_patch"]["transition_style"], "wipe")
        self.assertEqual(route["settings_patch"]["transition_seconds"], 1.2)
        self.assertEqual(route["settings_patch"]["zoom_variant"], "center_out")
        self.assertEqual(route["settings_patch"]["music_volume"], 0.8)

    def test_resume_context_for_render_reuses_upstream_and_runs_downstream(self) -> None:
        with tempfile.TemporaryDirectory() as parent_tmp, tempfile.TemporaryDirectory() as child_tmp:
            parent = Path(parent_tmp)
            child = Path(child_tmp)
            asset_log = parent / "logs" / "asset_agent"
            music_log = parent / "logs" / "music_agent"
            render_log = parent / "logs" / "render_agent"
            asset_log.mkdir(parents=True)
            music_log.mkdir(parents=True)
            render_log.mkdir(parents=True)
            parent_media = parent / "media" / "a.jpg"
            parent_media.parent.mkdir(parents=True)
            parent_media.write_bytes(b"fake")
            parent_audio = parent / "intermediate" / "audio" / "final_audio.wav"
            parent_audio.parent.mkdir(parents=True)
            parent_audio.write_bytes(b"fake-audio")
            old_container_path = f"/app/data/playground/runs/_pipeline_outputs/{parent.name}/media/a.jpg"
            old_audio_path = f"/app/data/playground/runs/_pipeline_outputs/{parent.name}/intermediate/audio/final_audio.wav"
            (asset_log / "input.json").write_text("{}", encoding="utf-8")
            (asset_log / "output.json").write_text(
                json.dumps(
                    {
                        "image_paths": [old_container_path],
                        "sfx_paths": [],
                        "music_path": None,
                        "sources": ["parent"],
                        "video_paths": [],
                        "media_paths": [old_container_path],
                        "media_types": ["image"],
                        "media_durations_ms": [3000],
                    }
                ),
                encoding="utf-8",
            )
            (music_log / "output.json").write_text(
                json.dumps(
                    {
                        "input_audio_path": old_audio_path,
                        "final_audio_path": old_audio_path,
                        "music_path": None,
                        "duration_ms": 30000,
                        "music_volume": 0.0,
                        "mixed": False,
                        "status": "skipped",
                        "skipped_reason": "No uploaded music selected",
                        "mean_volume_db": -18.5,
                    }
                ),
                encoding="utf-8",
            )
            (render_log / "output.json").write_text(
                json.dumps({"video_path": "/tmp/old.mp4", "width": 1080, "height": 1920, "duration_seconds": 30}),
                encoding="utf-8",
            )

            resume = ResumeContext(parent, "render_agent", child)
            self.assertFalse(resume.should_run("asset_agent"))
            self.assertTrue(resume.should_run("render_agent"))
            self.assertTrue(resume.should_run("thumbnail_agent"))
            resume.prepare_reused_logs()

            self.assertTrue((child / "logs" / "asset_agent" / "output.json").exists())
            self.assertTrue((child / "logs" / "music_agent" / "output.json").exists())
            self.assertFalse((child / "logs" / "render_agent").exists())
            assets = resume.assets()
            self.assertEqual(assets.media_paths, [str(parent_media)])
            self.assertEqual(assets.media_durations_ms, [3000])
            music = resume.music(
                SimpleNamespace(
                    final_audio_path=str(parent_audio),
                    duration_ms=30000,
                    mean_volume_db=None,
                    max_volume_db=None,
                    longest_silence_seconds=None,
                )
            )
            self.assertEqual(music.final_audio_path, str(parent_audio))
            self.assertFalse(music.mixed)
            self.assertEqual(music.status, "skipped")
            self.assertEqual(music.mean_volume_db, -18.5)

    def test_playground_final_output_uses_reused_render_video_when_new_output_missing(self) -> None:
        run = {
            "status": "succeeded",
            "pipeline_run_dir": "/tmp/missing-new-run",
            "stdout_path": "/tmp/stdout.log",
            "returncode": 0,
            "stages": [
                {"id": "render_agent", "output_json": {"video_path": "/tmp/parent-final.mp4"}},
                {"id": "thumbnail_agent", "output_json": {}},
                {"id": "final_output", "output_json": {}},
            ],
        }

        final = playground._final_output_json(run)

        self.assertEqual(final["video_path"], "/tmp/parent-final.mp4")

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

    def test_validated_stage_returns_validator_feedback_to_producer(self) -> None:
        calls: list[list[str]] = []
        events: list[dict] = []

        def producer(feedback):
            calls.append(list(feedback))
            return {"attempt": len(calls)}

        def validate(artifact):
            if artifact["attempt"] == 1:
                return ValidationResult(False, ["Title is missing"], ["Regenerate with a title"])
            return ValidationResult(True, [], [])

        artifact, check = run_validated_stage(
            errors=SimpleNamespace(record=lambda **_kwargs: None),
            validator=SimpleNamespace(event=lambda _message, **fields: events.append(fields)),
            producer_stage="script_agent",
            validation_stage="validate_script",
            producer_fn=producer,
            validator_fn=validate,
        )

        self.assertTrue(check.passed)
        self.assertEqual(artifact["attempt"], 2)
        self.assertEqual(calls[0], [])
        self.assertIn("Regenerate with a title", calls[1])
        self.assertEqual(events[0]["target_agent"], "script_agent")


if __name__ == "__main__":
    unittest.main()
