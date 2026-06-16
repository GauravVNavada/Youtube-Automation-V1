from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from agents.base import BaseAgent
from agents.validation_agent import ValidationAgent
from app.schemas import AssetBundle, AudioBundle, CaptionBundle, GenreConfig, ImageCue, ResearchSource, ScriptOutput, WordTimestamp
from modules.assets.asset_index import record_image_asset, restore_cached_image
from modules.assets.intent import build_asset_intent, reject_for_intent, score_intent_alignment
from modules.assets.image_fetcher import _query_variants, _search_jobs
from modules.assets.intent import infer_genre_intent_profile, profile_from_mapping, profile_to_dict
from modules.assets.intent_generator import generate_asset_intent_profile
from modules.assets.image_scoring import ImageResult
from modules.assets.image_services import _extract_bing_mediaurl_results, _extract_bing_murl_results
from modules.audio.edge_tts import _edge_rate
from modules.discovery.engine import discover_topics
from modules.discovery.research import build_research_brief
from modules.discovery.sources import SearchResult
from modules.niches.profiles import fallback_niche_profile, load_niche_profile
from modules.render.plan import write_render_plan
from modules.scripts.generator import script_from_mapping, validate_script_json_shape
from modules.scripts.structure import polish_script_ending, validate_narrative_structure
from modules.thumbnails.renderer import create_thumbnail_set
from modules.visuals.style_router import (
    apply_visual_style_to_cues,
    apply_visual_style_to_script,
    build_visual_style_plan,
)


def _genre() -> GenreConfig:
    return GenreConfig(
        genre_id="scary_stories",
        display_name="Scary Stories",
        word_count_min=40,
        word_count_max=70,
        tone="slow dread",
        layout="full_image",
        caption_preset="horror_red",
        voice_rate=0.9,
        music_mood="eerie",
        hook_patterns=["At {time}, {subject} noticed {detail}."],
        banned_phrases=[],
    )


def _genre_id(genre_id: str, display: str | None = None) -> GenreConfig:
    return GenreConfig(
        genre_id=genre_id,
        display_name=display or genre_id.replace("_", " ").title(),
        word_count_min=40,
        word_count_max=70,
        tone="clear, relevant, genre-matched",
        layout="full_image",
        caption_preset="clean_pro",
        voice_rate=1.0,
        music_mood="neutral",
        hook_patterns=[],
        banned_phrases=[],
    )


def test_agent_provenance_logs_execution_mode(tmp_path: Path) -> None:
    agent = BaseAgent(tmp_path)
    agent.provenance("LLM step", mode="ai", provider="fake")

    event = json.loads((tmp_path / "logs" / "base_agent" / "events.log").read_text(encoding="utf-8").strip())
    assert event["execution_mode"] == "ai"
    assert event["ai_used"] is True
    assert event["deterministic"] is False
    assert event["provider"] == "fake"


def test_niche_profile_loading_and_fallback(tmp_path: Path) -> None:
    genre = _genre()
    profile_dir = tmp_path / "niche_profiles"
    profile_dir.mkdir()
    (profile_dir / "scary_stories.json").write_text(
        '{"genre_id":"scary_stories","display_name":"Scary","hook_templates":["Hook {detail}"],'
        '"tone_rules":["Tense"],"title_words":["secret"],"thumbnail_text_rules":["short"],'
        '"visual_keywords":["dark door"],"hashtag_hints":["#scary"]}',
        encoding="utf-8",
    )

    loaded = load_niche_profile(genre, data_dir=tmp_path)
    assert loaded.hook_templates == ["Hook {detail}"]
    assert loaded.visual_keywords == ["dark door"]

    fallback = fallback_niche_profile(genre)
    assert fallback.genre_id == "scary_stories"
    assert fallback.hook_templates


def test_discovery_scoring_with_mocked_sources(monkeypatch) -> None:
    genre = _genre()
    profile = fallback_niche_profile(genre)

    def fake_duckduckgo(query: str, max_results: int = 5):
        return [SearchResult("Hidden hospital door clue", "https://example.test", "A hallway door became the key detail.", "duckduckgo")]

    monkeypatch.setattr("modules.discovery.engine.search_duckduckgo", fake_duckduckgo)
    monkeypatch.setattr("modules.discovery.engine.search_reddit", lambda *args, **kwargs: [])
    monkeypatch.setattr("modules.discovery.engine.search_wikimedia", lambda *args, **kwargs: [])

    output = discover_topics("haunted hospital", genre, [], profile)
    assert output.selected_topic.startswith("haunted hospital")
    assert output.candidates[0].source == "duckduckgo"
    assert output.source_errors == []


def test_research_brief_when_web_disabled() -> None:
    genre = _genre()
    profile = fallback_niche_profile(genre)
    discovery = discover_topics("haunted hospital", genre, [], profile, web_enabled=False)

    research = build_research_brief("haunted hospital", genre, discovery, profile, web_enabled=False)
    assert research.brief
    assert research.facts
    assert all(isinstance(source, ResearchSource) for source in research.source_snippets)


def test_thumbnail_generation_outputs_both_sizes(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    Image.new("RGB", (800, 1200), "#334455").save(source)
    profile = fallback_niche_profile(_genre())

    output = create_thumbnail_set(
        video_path="",
        image_paths=[str(source)],
        output_dir=tmp_path / "thumbs",
        title="The Door Opened Alone",
        hook_line="At midnight, the door opened alone.",
        profile=profile,
        selected_angle="midnight door clue",
        facts=["A door clue anchors the scene."],
    )

    assert Image.open(output.shorts_cover_path).size == (1080, 1920)
    assert Image.open(output.youtube_thumbnail_path).size == (1280, 720)
    assert output.text_lines


def test_edge_tts_rate_mapping_and_validation_acceptance(tmp_path: Path) -> None:
    assert _edge_rate(1.0) == "+0%"
    assert _edge_rate(1.2) == "+20%"
    assert _edge_rate(0.8) == "-20%"

    audio_path = tmp_path / "final_audio.wav"
    audio_path.write_bytes(b"0" * 2048)
    audio = AudioBundle(
        narration_path=str(audio_path),
        final_audio_path=str(audio_path),
        duration_ms=12000,
        word_timestamps=[WordTimestamp("hello", 0, 500)],
        provider="edge_tts",
        alignment_source="whisper",
    )
    result = ValidationAgent(tmp_path).validate_audio(audio)
    assert result.passed


def test_bing_image_parsers_are_no_key() -> None:
    html = (
        "mediaurl=https%3A%2F%2Fexample.com%2Fone.jpg&amp;x=1 expw=900 x exph=1200 "
        "&quot;murl&quot;:&quot;https:\\/\\/example.com\\/two.png&quot;"
    )
    media = _extract_bing_mediaurl_results(html)
    murls = _extract_bing_murl_results(html)
    assert media[0][0] == "https://example.com/one.jpg"
    assert media[0][1:] == (900, 1200)
    assert murls == ["https://example.com/two.png"]


def test_asset_index_records_and_restores_cached_images(tmp_path: Path, monkeypatch) -> None:
    import modules.assets.asset_index as asset_index

    monkeypatch.setattr(asset_index, "INDEX_PATH", tmp_path / "asset_index.json")
    monkeypatch.setattr(asset_index, "CACHE_DIR", tmp_path / "cache")
    source = tmp_path / "source.jpg"
    Image.new("RGB", (80, 80), "#223344").save(source, quality=95)
    if source.stat().st_size < 1024:
        source.write_bytes(source.read_bytes() + b"0" * 2048)

    record_image_asset("dark hallway", "bing", "https://example.com/image.jpg", source)
    target = tmp_path / "run" / "image.jpg"
    restored = restore_cached_image("dark hallway", target)
    assert restored is not None
    assert Path(restored[0]).exists()
    assert restored[1] == "asset_cache:bing"


def test_visual_style_plan_sanitizes_superhero_ip() -> None:
    plan = build_visual_style_plan("Avengers Iron Man fighting all other Avengers", "scary_stories")

    assert plan.mode == "illustration"
    assert plan.asset_strategy == "image_first"
    assert plan.render_style == "comic_book"
    assert "iron man" not in plan.sanitized_topic.lower()
    assert "avengers" not in plan.sanitized_topic.lower()

    cues = apply_visual_style_to_cues(
        [ImageCue("Iron Man fighting Avengers in destroyed city", "word_0", "dramatic")],
        plan,
    )
    assert "comic book illustration" in cues[0].keyword
    assert "iron man" not in cues[0].keyword.lower()
    assert "avengers" not in cues[0].keyword.lower()


def test_visual_style_sanitizes_script_output() -> None:
    plan = build_visual_style_plan("Iron Man versus Avengers comic fight", "scary_stories")
    script = ScriptOutput(
        title="Iron Man Fights The Avengers",
        narration="Iron Man turns against the Avengers in a city battle.",
        hook_line="Iron Man turns against the Avengers in a city battle.",
        word_count=9,
        estimated_duration=30,
        description="Iron Man and the Avengers battle.",
        hashtags=["#IronMan", "#Avengers"],
        image_cues=[ImageCue("Iron Man Avengers battle city", "word_0", "dramatic")],
        sfx_cues=[],
        emphasis_words=["Iron Man", "Avengers"],
    )

    sanitized = apply_visual_style_to_script(script, plan)
    joined = " ".join([sanitized.title, sanitized.narration, sanitized.description, " ".join(sanitized.hashtags)])
    assert "iron man" not in joined.lower()
    assert "avengers" not in joined.lower()
    assert "armored tech hero" in sanitized.narration.lower()
    assert "comic book illustration" in sanitized.image_cues[0].keyword


def test_stylized_search_plan_skips_pexels_video_style_sources() -> None:
    genre = _genre()
    plan = build_visual_style_plan("Avengers Iron Man comic battle", genre.genre_id)
    queries = _query_variants("Iron Man Avengers battle city", genre, plan)
    jobs = _search_jobs(queries, "pexels-key", "pixabay-key", plan)

    assert queries
    assert all("iron man" not in query.lower() for query in queries)
    assert all("avengers" not in query.lower() for query in queries)
    assert any("comic book illustration" in query for query in queries)
    assert not any(source == "pexels" for source, *_ in jobs)
    assert any(source == "pixabay" for source, *_ in jobs)


def test_scary_asset_intent_rewrites_handprint_to_horror_context() -> None:
    genre = _genre()
    queries = _query_variants("red handprint on wall", genre)

    assert queries[0] == "bloody handprint on dark wall horror"
    assert any("horror" in query for query in queries[:4])
    assert all("child" not in query.lower() for query in queries[:4])
    assert all("pain" not in query.lower() for query in queries[:4])


def test_scary_asset_intent_penalizes_child_pain_handprint_results() -> None:
    genre = _genre()
    cue = ImageCue("red handprint on wall", "word_0", "dark")
    intent = build_asset_intent(cue, genre)
    horror = ImageResult(
        url="https://example.com/bloody-handprint-dark-wall-horror.jpg",
        source="bing",
        width=1200,
        height=1600,
        description="bloody handprint on dark wall horror",
    )
    child_pain = ImageResult(
        url="https://example.com/child-hand-pain-clinic.jpg",
        source="pexels",
        width=1200,
        height=1600,
        description="child hand pain doctor clinic",
    )

    assert reject_for_intent(child_pain, "bloody handprint on dark wall horror", intent)
    assert not reject_for_intent(horror, "bloody handprint on dark wall horror", intent)
    assert score_intent_alignment(horror, "bloody handprint on dark wall horror", intent) > 0
    assert score_intent_alignment(child_pain, "bloody handprint on dark wall horror", intent) < 0


def test_asset_intent_rewrites_across_core_genres() -> None:
    cases = [
        ("mystery_stories", "voicemail on phone", "phone voicemail screen mystery clue"),
        ("history_facts", "roman road under modern traffic", "roman ruins ancient history documentary"),
        ("science_facts", "brain cells firing", "human brain neuron model science laboratory"),
        ("relationship_stories", "boyfriend text message", "phone message screen relationship drama"),
        ("reddit_stories", "father finds fake debt papers", "tense family conversation living room"),
        ("motivational_stories", "student failure before exam", "determined person working late motivational"),
    ]

    for genre_id, cue, expected in cases:
        queries = _query_variants(cue, _genre_id(genre_id))
        assert queries[0] == expected


def test_asset_intent_penalizes_cross_genre_mismatches() -> None:
    history_intent = build_asset_intent(ImageCue("roman road artifact", "word_0", "neutral"), _genre_id("history_facts"))
    office = ImageResult(
        url="https://example.com/modern-office-business-selfie.jpg",
        source="pexels",
        width=1200,
        height=1600,
        description="modern business office selfie",
    )
    ruins = ImageResult(
        url="https://example.com/ancient-roman-ruins-documentary.jpg",
        source="wikimedia",
        width=1200,
        height=1600,
        description="ancient roman ruins historic documentary",
    )
    assert reject_for_intent(office, "roman ruins ancient history documentary", history_intent)
    assert not reject_for_intent(ruins, "roman ruins ancient history documentary", history_intent)
    assert score_intent_alignment(ruins, "roman ruins ancient history documentary", history_intent) > 0
    assert score_intent_alignment(office, "roman ruins ancient history documentary", history_intent) < 0

    relationship_intent = build_asset_intent(ImageCue("couple tense conversation", "word_0", "dramatic"), _genre_id("relationship_stories"))
    horror = ImageResult(
        url="https://example.com/blood-monster-horror-room.jpg",
        source="bing",
        width=1200,
        height=1600,
        description="blood monster horror room",
    )
    couple = ImageResult(
        url="https://example.com/couple-conversation-living-room.jpg",
        source="pexels",
        width=1200,
        height=1600,
        description="couple realistic relationship conversation living room",
    )
    assert reject_for_intent(horror, "couple tense conversation living room", relationship_intent)
    assert not reject_for_intent(couple, "couple tense conversation living room", relationship_intent)
    assert score_intent_alignment(couple, "couple tense conversation living room", relationship_intent) > 0
    assert score_intent_alignment(horror, "couple tense conversation living room", relationship_intent) < 0


def test_unknown_genre_infers_profile_from_live_genre_metadata() -> None:
    genre = _genre_id("cozy_baking", "Cozy Baking")
    genre = GenreConfig(
        genre_id=genre.genre_id,
        display_name=genre.display_name,
        word_count_min=genre.word_count_min,
        word_count_max=genre.word_count_max,
        tone="warm bakery recipe soothing sourdough pastry kitchen",
        layout=genre.layout,
        caption_preset=genre.caption_preset,
        voice_rate=genre.voice_rate,
        music_mood="soft",
        hook_patterns=["The mistake every baker makes with {detail}"],
        banned_phrases=[],
    )

    profile = infer_genre_intent_profile(genre)
    payload = profile_to_dict(profile)
    queries = _query_variants("sourdough starter jar", genre, asset_intent_profile=payload)

    assert "bakery" in payload["positive_terms"] or "sourdough" in payload["positive_terms"]
    assert "sourdough starter jar" in queries[0]
    assert any("bakery" in query or "sourdough" in query for query in queries)


def test_ai_generated_asset_intent_profile_overrides_fallback() -> None:
    class FakeProvider:
        name = "fake"

        def generate_json(self, system_prompt: str, user_prompt: str, max_output_tokens: int):
            return {
                "positive_terms": ["bakery", "sourdough", "warm kitchen", "flour", "oven"],
                "negative_terms": ["horror", "blood", "office", "gym"],
                "required_context": ["bakery", "warm kitchen"],
                "query_expansions": ["cozy bakery", "warm kitchen"],
                "rewrites": [
                    {"triggers": ["starter", "sourdough"], "replacement": "sourdough starter jar cozy bakery kitchen"}
                ],
                "reject_rules": [
                    {"triggers": ["sourdough", "bread"], "bad_terms": ["horror", "blood", "office"]}
                ],
            }

    genre = _genre_id("cozy_baking", "Cozy Baking")
    profile = generate_asset_intent_profile(
        FakeProvider(),
        genre=genre,
        topic="sourdough starter mistake",
        image_cues=[ImageCue("starter jar", "word_0", "warm")],
        growth_context={},
        visual_style={},
    )
    queries = _query_variants("starter jar", genre, asset_intent_profile=profile)

    assert queries[0] == "sourdough starter jar cozy bakery kitchen"
    assert "bakery" in profile["positive_terms"]


def test_script_sections_parse_and_validate_clear_ending() -> None:
    data = {
        "title": "This Road Is Older Than You Think",
        "narration": (
            "Every day, cars roll over a road whose first stones were placed almost two thousand years ago. "
            "The Romans built it for soldiers and messages that had to cross the empire fast. "
            "That is why the past can still be under your tires today."
        ),
        "hook_line": "Every day, cars roll over a road whose first stones were placed almost two thousand years ago.",
        "script_sections": [
            {
                "name": "header",
                "purpose": "Hook with the hidden modern connection.",
                "narration": "Every day, cars roll over a road whose first stones were placed almost two thousand years ago.",
            },
            {
                "name": "mid",
                "purpose": "Give the relevant context.",
                "narration": "The Romans built it for soldiers and messages that had to cross the empire fast.",
            },
            {
                "name": "footer",
                "purpose": "Explain why it matters now.",
                "narration": "That is why the past can still be under your tires today.",
            },
        ],
        "word_count": 35,
        "estimated_duration": 30,
        "description": "A short history fact.",
        "hashtags": ["#shorts", "#history"],
        "image_cues": [
            {"keyword": "ancient roman road stones", "timestamp_hint": "word_0", "mood": "dramatic"},
            {"keyword": "modern traffic city street", "timestamp_hint": "word_8", "mood": "neutral"},
            {"keyword": "roman soldiers stone road", "timestamp_hint": "word_16", "mood": "dramatic"},
            {"keyword": "old stone road closeup", "timestamp_hint": "word_24", "mood": "reveal"},
            {"keyword": "city road under traffic", "timestamp_hint": "word_30", "mood": "reveal"},
            {"keyword": "ancient road modern city", "timestamp_hint": "word_34", "mood": "reveal"},
        ],
        "sfx_cues": [],
        "emphasis_words": ["two thousand", "today"],
    }

    validate_script_json_shape(data)
    script = script_from_mapping(data, provider="test", requested_duration=30)
    assert [section.name for section in script.script_sections] == ["header", "mid", "footer"]
    assert validate_narrative_structure(script, "history_facts") == []


def test_bad_ending_is_detected_and_polished() -> None:
    script = ScriptOutput(
        title="The Signal",
        narration="The signal came from the basement. I followed it downstairs. Then it stopped.",
        hook_line="The signal came from the basement.",
        word_count=13,
        estimated_duration=30,
        description="A short mystery.",
        hashtags=["#shorts"],
        image_cues=[ImageCue("phone signal basement stairs", "word_0", "dramatic")],
        sfx_cues=[],
    )

    issues = validate_narrative_structure(script, "mystery_stories")
    assert any("direct stop" in issue or "abrupt" in issue for issue in issues)

    polished = polish_script_ending(script, "mystery_stories", max_words=40)
    assert "direct stop" not in " ".join(validate_narrative_structure(polished, "mystery_stories")).lower()
    assert polished.narration.endswith(".")
    assert [section.name for section in polished.script_sections] == ["header", "mid", "footer"]


def test_render_plan_artifact(tmp_path: Path) -> None:
    image_path = tmp_path / "image.jpg"
    video_path = tmp_path / "clip.mp4"
    audio_path = tmp_path / "audio.wav"
    caption_path = tmp_path / "captions.ass"
    for path in (image_path, video_path, audio_path, caption_path):
        path.write_bytes(b"0" * 2048)
    plan_path = tmp_path / "render_plan.json"
    output_path = tmp_path / "final.mp4"

    result_path = write_render_plan(
        assets=AssetBundle(
            image_paths=[str(image_path)],
            video_paths=[str(video_path)],
            video_sources=["pexels"],
            sfx_paths=[],
            music_path=None,
            sources=["bing"],
            visual_style="comic_book",
            asset_strategy="image_first",
        ),
        audio=AudioBundle(
            narration_path=str(audio_path),
            final_audio_path=str(audio_path),
            duration_ms=15000,
            word_timestamps=[WordTimestamp("hello", 0, 500)],
            provider="edge_tts",
            alignment_source="whisper",
        ),
        captions=CaptionBundle(
            srt_path=str(caption_path),
            ass_path=str(caption_path),
            phrase_count=1,
            word_count=1,
        ),
        output_path=output_path,
        plan_path=plan_path,
        music_volume=0.18,
        render_style="comic_book",
    )
    assert Path(result_path).exists()
    text = plan_path.read_text(encoding="utf-8")
    assert '"renderer": "ffmpeg"' in text
    assert '"render_style": "comic_book"' in text
    assert '"asset_strategy": "image_first"' in text
    assert '"provider": "edge_tts"' in text
