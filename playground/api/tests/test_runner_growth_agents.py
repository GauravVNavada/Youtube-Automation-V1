from __future__ import annotations

from app.runner import AGENTS, _artifact_agent, combine_execution_modes, decide_route, default_execution_mode_for_agent


def test_growth_agents_are_in_route_order() -> None:
    assert AGENTS == [
        "master_agent",
        "topic_discovery_agent",
        "research_agent",
        "script_agent",
        "validation_agent",
        "asset_agent",
        "audio_agent",
        "caption_agent",
        "render_agent",
        "thumbnail_agent",
    ]


def test_route_contracts_include_growth_agents() -> None:
    route = decide_route("make a 30 sec scary story about a haunted hospital")
    contract_names = [contract["name"] for contract in route["agent_contracts"]]
    assert "topic_discovery_agent" in contract_names
    assert "research_agent" in contract_names
    assert "thumbnail_agent" in contract_names


def test_thumbnail_artifacts_map_to_thumbnail_agent() -> None:
    assert _artifact_agent("output/thumbnails/shorts_cover.jpg") == "thumbnail_agent"
    assert _artifact_agent("logs/thumbnail_agent/output.json") == "thumbnail_agent"


def test_agent_execution_mode_defaults_and_combining() -> None:
    assert default_execution_mode_for_agent("script_agent") == "ai"
    assert default_execution_mode_for_agent("asset_agent") == "hybrid"
    assert default_execution_mode_for_agent("render_agent") == "deterministic"
    assert combine_execution_modes("ai", "deterministic") == "hybrid"
    assert combine_execution_modes("deterministic", "fallback") == "fallback"
