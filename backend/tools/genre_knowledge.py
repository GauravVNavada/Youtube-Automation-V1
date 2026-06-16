from __future__ import annotations

import argparse
import json
import sys
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape
import xml.etree.ElementTree as ET

from sqlalchemy import inspect, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.database import Base, SessionLocal, engine, init_database  # noqa: E402
from app.models import (  # noqa: E402
    AiSuggestion,
    GenerationRun,
    Genre,
    GenreHook,
    GenreRule,
    KnowledgeImportBatch,
    ReferenceVideo,
    ScriptAnalysis,
    TopicExpansionRule,
    TopicResearchSource,
    VisualStyleRule,
)


OUTPUT_DIR = ROOT / "data" / "knowledge"
TEMPLATE_PATH = OUTPUT_DIR / "Genre_Knowledge_Import_Template.xlsx"
REAL_WORLD_SEED_PATH = OUTPUT_DIR / "Genre_Knowledge_Real_World_Seed.xlsx"
SINGLE_ENTRY_PATH = OUTPUT_DIR / "YT_Shorts_Knowledge_Single_Entry.xlsx"
BACKUP_DIR = OUTPUT_DIR / "backups"

KNOWLEDGE_MODELS = (
    KnowledgeImportBatch,
    AiSuggestion,
    GenerationRun,
    TopicResearchSource,
    TopicExpansionRule,
    VisualStyleRule,
    ScriptAnalysis,
    ReferenceVideo,
    GenreHook,
    GenreRule,
    Genre,
)


@dataclass(frozen=True)
class FieldRule:
    sheet: str
    field: str
    required: str
    data_type: str
    max_length: str
    allowed_values: str
    example: str
    notes: str


SHEETS: dict[str, list[str]] = {
    "README": ["Section", "Instruction"],
    "00_Column_Explanations": [
        "sheet",
        "column",
        "what_it_means",
        "how_to_fill",
        "required",
        "data_type",
        "max_length",
        "example",
    ],
    "01_Genres": [
        "id",
        "display_name",
        "category",
        "tone",
        "audience_size",
        "competition_level",
        "content_difficulty",
        "recommended_score",
        "default_duration_sec",
        "word_count_min",
        "word_count_max",
        "layout",
        "caption_preset",
        "voice_rate",
        "music_mood",
        "realism_mode",
        "is_active",
        "notes",
    ],
    "02_Genre_Rules": ["genre_id", "rule_type", "value", "weight", "notes"],
    "03_Genre_Hooks": ["genre_id", "hook_type", "template", "emotional_trigger", "avg_score", "notes"],
    "04_Reference_Videos": [
        "genre_id",
        "video_url",
        "channel_name",
        "channel_subscribers",
        "views",
        "likes",
        "comments",
        "upload_date",
        "duration_sec",
        "title",
        "description_first_line",
        "hashtags",
        "full_script",
        "word_count",
        "sentence_count",
        "words_per_second",
        "overall_score",
        "usable_as_few_shot",
        "notes",
    ],
    "05_Script_Analysis": [
        "video_url",
        "hook_first_sentence",
        "hook_type",
        "hook_emotional_trigger",
        "hook_speed_sec",
        "opening_words",
        "body_sentence_count",
        "has_twist_reveal",
        "twist_line",
        "ending_type",
        "last_sentence",
        "tense_used",
        "pov_person",
        "narrative_technique",
        "emotional_arc",
        "power_words",
        "emphasis_words",
        "sensory_language_used",
        "retention_hook",
        "likely_share_trigger",
        "why_it_worked",
        "what_to_improve",
    ],
    "06_Visual_Style_Rules": [
        "genre_id",
        "layout_type",
        "image_or_video_count",
        "image_change_timing",
        "transition_type",
        "image_style",
        "visual_keywords",
        "negative_visual_keywords",
        "caption_style",
        "caption_font",
        "caption_primary_color",
        "caption_highlight_color",
        "caption_position",
        "music_mood",
        "sfx_rules",
        "source_policy",
    ],
    "07_Topic_Expansion_Rules": [
        "genre_id",
        "trigger_term",
        "search_queries",
        "required_words",
        "forbidden_words",
        "realism_mode",
        "notes",
    ],
    "08_Topic_Research_Sources": [
        "topic",
        "genre_id",
        "title",
        "url",
        "source_type",
        "snippet",
        "extracted_facts",
        "credibility_score",
        "relevance_score",
    ],
    "09_Field_Rules": [
        "sheet",
        "field",
        "required",
        "data_type",
        "max_length",
        "allowed_values",
        "example",
        "notes",
    ],
    "10_Playground_Test_Topics": [
        "example_id",
        "genre_id",
        "playground_topic",
        "grounded_angle",
        "realism_mode",
        "search_queries",
        "why_good_test",
        "source_title",
        "source_url",
        "prompt_note",
    ],
}


COLUMN_MEANINGS: dict[str, dict[str, tuple[str, str]]] = {
    "README": {
        "Section": ("Instruction category.", "Do not edit unless you want to change the guide text."),
        "Instruction": ("Human-readable instruction for using the workbook.", "Read only; the importer ignores this sheet."),
    },
    "00_Column_Explanations": {
        "sheet": ("Workbook tab/table where the column appears.", "Read only."),
        "column": ("Exact column header name.", "Read only."),
        "what_it_means": ("Plain-English meaning of the field.", "Read only."),
        "how_to_fill": ("Practical instruction for the person filling data.", "Read only."),
        "required": ("Whether the importer expects this field.", "Read only."),
        "data_type": ("Expected value type.", "Read only."),
        "max_length": ("Maximum DB text length, if limited.", "Read only."),
        "example": ("Example value that will import cleanly.", "Read only."),
    },
    "01_Genres": {
        "id": ("Unique machine name for the genre.", "Use lowercase words joined by underscore, for example scary_stories."),
        "display_name": ("Human-friendly genre name shown in the app.", "Write the readable name of the genre."),
        "category": ("Broad content category.", "Use short labels like horror, education, story, tech, psychology."),
        "tone": ("Writing style and pacing rules for the AI.", "Describe the voice, mood, pacing, and specificity expected."),
        "audience_size": ("Rough size of the audience for this niche.", "Use Small, Medium, Large, or Huge."),
        "competition_level": ("How crowded the niche is.", "Use Low, Medium, High, or a similar short value."),
        "content_difficulty": ("How hard this niche is to research and produce.", "Use Easy, Medium, or Hard."),
        "recommended_score": ("Internal recommendation rating.", "Enter 0 to 5, where 5 means highly recommended."),
        "default_duration_sec": ("Default video length for this genre.", "Enter seconds, usually 30, 45, 60, or 180."),
        "word_count_min": ("Minimum narration words for this genre.", "Enter a number that fits the default duration."),
        "word_count_max": ("Maximum narration words for this genre.", "Must be greater than or equal to word_count_min."),
        "layout": ("Default video layout.", "Use values like full_image, split_screen, full_gameplay."),
        "caption_preset": ("Caption style preset used by renderer.", "Use an existing preset name like horror_red."),
        "voice_rate": ("Narration speed multiplier.", "Use decimal values like 0.88, 1.0, or 1.05."),
        "music_mood": ("Default background music mood.", "Use short mood words like eerie, subtle, documentary."),
        "realism_mode": ("How factual or fictional the script should be.", "Use fictional, fictionalized_realistic, inspired_by_real_events, documentary_style, or verified_fact_only."),
        "is_active": ("Whether this genre can be used by the app.", "Use TRUE for available genres and FALSE to hide it."),
        "notes": ("Extra internal notes about the genre.", "Write anything useful for the admin or AI maintainer."),
    },
    "02_Genre_Rules": {
        "genre_id": ("Genre this rule belongs to.", "Must match an id in 01_Genres."),
        "rule_type": ("Type of rule being added.", "Use positive_term, negative_term, required_context, banned_phrase, or tone_rule."),
        "value": ("Actual rule text.", "Write one term, phrase, or instruction per row."),
        "weight": ("Strength of this rule.", "Use positive numbers for boosts and negative numbers for penalties."),
        "notes": ("Why this rule exists.", "Optional but useful for future tuning."),
    },
    "03_Genre_Hooks": {
        "genre_id": ("Genre this hook belongs to.", "Must match an id in 01_Genres."),
        "hook_type": ("Short category name for the hook.", "Use labels like question, time_place, question_time_reference."),
        "template": ("Reusable hook pattern.", "Use placeholders like {year}, {place}, {subject}, {event}."),
        "emotional_trigger": ("Viewer emotion the hook targets.", "Use curiosity, dread, shock, justice, surprise, etc."),
        "avg_score": ("Performance estimate for this hook.", "Use 0 to 10 if known; otherwise leave blank."),
        "notes": ("Extra hook usage notes.", "Explain when this hook should be used."),
    },
    "04_Reference_Videos": {
        "genre_id": ("Genre of the watched video.", "Must match an id in 01_Genres."),
        "video_url": ("Unique URL of the reference video.", "Paste the YouTube Shorts URL."),
        "channel_name": ("Creator/channel name.", "Paste the visible channel handle or name."),
        "channel_subscribers": ("Approximate subscriber count.", "Enter a number only, for example 850000."),
        "views": ("View count at time of research.", "Enter a number only."),
        "likes": ("Like count at time of research.", "Enter a number only; leave blank if unavailable."),
        "comments": ("Comment count at time of research.", "Enter a number only; leave blank if unavailable."),
        "upload_date": ("Date the video was uploaded.", "Use YYYY-MM-DD."),
        "duration_sec": ("Video duration in seconds.", "Enter a number only."),
        "title": ("Video title.", "Paste title, keeping it short."),
        "description_first_line": ("First line of the video description.", "Paste only the first line, not the full description."),
        "hashtags": ("Hashtags used by the video.", "Enter space-separated hashtags."),
        "full_script": ("Exact spoken transcript/script.", "Paste the complete narration word-for-word."),
        "word_count": ("Number of words in full_script.", "Enter manually or leave blank to auto-calculate roughly."),
        "sentence_count": ("Number of sentences in full_script.", "Enter a number only."),
        "words_per_second": ("Pacing metric.", "word_count divided by duration_sec, as a decimal."),
        "overall_score": ("Your quality/performance score.", "Use 0 to 10 based on hook, script, pacing, visuals, audio, shareability."),
        "usable_as_few_shot": ("Whether AI should use this as an example.", "Use TRUE only for strong examples."),
        "notes": ("Anything unusual about the video.", "Write extra observations not captured elsewhere."),
    },
    "05_Script_Analysis": {
        "video_url": ("Which reference video this analysis belongs to.", "Must exactly match 04_Reference_Videos.video_url."),
        "hook_first_sentence": ("Exact first sentence of the narration.", "Copy the first sentence word-for-word."),
        "hook_type": ("Kind of hook used.", "Use labels like question, shock_statement, time_reference, confession."),
        "hook_emotional_trigger": ("Emotion created by the hook.", "Use curiosity, fear, anger, justice, surprise, empathy, etc."),
        "hook_speed_sec": ("How quickly the hook lands.", "Enter seconds from start until viewer understands the promise."),
        "opening_words": ("First few words of the narration.", "Copy the first 5 words or short opening phrase."),
        "body_sentence_count": ("Number of middle/body sentences.", "Enter a number only."),
        "has_twist_reveal": ("Whether the script has a twist or reveal.", "Use TRUE/FALSE."),
        "twist_line": ("Line where the twist/reveal happens.", "Copy the exact reveal line if present."),
        "ending_type": ("How the story ends.", "Use labels like open_ended, warning, justice, lesson, shocking_fact."),
        "last_sentence": ("Exact final sentence.", "Copy the ending sentence word-for-word."),
        "tense_used": ("Main tense of the narration.", "Use past, present, or mixed."),
        "pov_person": ("Point of view.", "Use narrator, first_person, third_person, direct_address, etc."),
        "narrative_technique": ("Story structure technique.", "Use escalating_reveal, story_arc, listicle, mystery_setup, cause_effect, etc."),
        "emotional_arc": ("Emotion path through the video.", "Write a short progression like curiosity -> dread -> shock."),
        "power_words": ("Words that make the story feel strong.", "Comma-separate words like sealed, vanished, exposed."),
        "emphasis_words": ("Words worth highlighting in captions.", "Comma-separate the key caption pop words."),
        "sensory_language_used": ("Visual/audio/physical sensory details.", "Note concrete sensory details like scratching sound, red handprint, cold hallway."),
        "retention_hook": ("Why viewers keep watching.", "Describe the open question or promise that carries the video."),
        "likely_share_trigger": ("Why people would share/comment.", "Describe the share reason, debate trigger, or relatable payoff."),
        "why_it_worked": ("Main reason this video performed well.", "Write a clear human analysis, not just keywords."),
        "what_to_improve": ("Weaknesses or changes to make it stronger.", "Write practical improvement notes."),
    },
    "06_Visual_Style_Rules": {
        "genre_id": ("Genre these visual rules belong to.", "Must match an id in 01_Genres."),
        "layout_type": ("Preferred screen layout.", "Use full_image, split_screen, full_gameplay, etc."),
        "image_or_video_count": ("Typical number of visuals in this genre.", "Enter a number."),
        "image_change_timing": ("How often visuals change.", "Use text like every 8-12 sec or every sentence."),
        "transition_type": ("Preferred visual transition.", "Use cut, dissolve, zoom, none, etc."),
        "image_style": ("Overall visual look.", "Use values like dark_moody_realistic, documentary, natural."),
        "visual_keywords": ("Good visual search words.", "Comma-separate concrete visible nouns and settings."),
        "negative_visual_keywords": ("Visuals to avoid.", "Comma-separate bad terms like cartoon, selfie, logo."),
        "caption_style": ("Caption animation/style.", "Use word_at_a_time, phrase_pop, subtitle_line, etc."),
        "caption_font": ("Preferred caption font.", "Use available font name if known."),
        "caption_primary_color": ("Main caption color.", "Use color word or hex code."),
        "caption_highlight_color": ("Emphasis caption color.", "Use color word or hex code."),
        "caption_position": ("Where captions appear.", "Use center, lower_third, top, etc."),
        "music_mood": ("Background music mood.", "Use eerie, subtle, documentary, tense, uplifting, etc."),
        "sfx_rules": ("Sound effect guidance.", "Write when to use SFX and what type."),
        "source_policy": ("Asset sourcing preference.", "Use stock_video_first, image_first, generated_image_first, etc."),
    },
    "07_Topic_Expansion_Rules": {
        "genre_id": ("Genre this topic rule belongs to.", "Must match an id in 01_Genres."),
        "trigger_term": ("User topic word that activates this rule.", "Use one important word like hallway, hospital, betrayal, roman."),
        "search_queries": ("Better research/search queries for this topic.", "Separate multiple queries with semicolons."),
        "required_words": ("Words that should appear in grounded results/script.", "Comma-separate required context words."),
        "forbidden_words": ("Words that make results irrelevant.", "Comma-separate terms to avoid."),
        "realism_mode": ("Grounding level for this topic.", "Use inspired_by_real_events, documentary_style, verified_fact_only, etc."),
        "notes": ("Extra usage notes.", "Explain when or why this expansion rule matters."),
    },
    "08_Topic_Research_Sources": {
        "topic": ("Topic seed this real-world source supports.", "Use the topic text that the generator may receive."),
        "genre_id": ("Genre this source belongs to.", "Must match an id in 01_Genres."),
        "title": ("Source title or page title.", "Use the article/page title."),
        "url": ("Source URL.", "Paste a verifiable source link."),
        "source_type": ("Kind of source.", "Use encyclopedia, article, official, study, archive, or local."),
        "snippet": ("Short source summary.", "Write a compact summary in your own words."),
        "extracted_facts": ("Facts the AI can safely use.", "Separate facts with semicolons; avoid unsupported claims."),
        "credibility_score": ("How reliable the source is.", "Use 0 to 10."),
        "relevance_score": ("How relevant it is to the topic.", "Use 0 to 10."),
    },
    "09_Field_Rules": {
        "sheet": ("Workbook tab/table where this rule applies.", "Read only."),
        "field": ("Column name the rule applies to.", "Read only."),
        "required": ("Whether the field is mandatory.", "YES means fill it before import."),
        "data_type": ("Expected type for this field.", "Use this to avoid import errors."),
        "max_length": ("Maximum text length in DB.", "Keep text under this limit when specified."),
        "allowed_values": ("Accepted values or examples.", "Choose from this list when provided."),
        "example": ("Safe example value.", "Use as a pattern."),
        "notes": ("Extra import rule details.", "Read before filling unclear fields."),
    },
    "10_Playground_Test_Topics": {
        "example_id": ("Unique id for the test topic.", "Use PT001, PT002, and so on."),
        "genre_id": ("Genre to select in the playground app.", "Must match a genre id, or add that genre before importing."),
        "playground_topic": ("Topic text to paste into the playground generator.", "Copy this into the app's topic field."),
        "grounded_angle": ("Real-world angle the AI should follow.", "Use it as user notes if the generated script drifts."),
        "realism_mode": ("How factual the output should be.", "Use documentary_style or verified_fact_only for factual topics."),
        "search_queries": ("Search phrases that can retrieve grounding context.", "Use these queries in research/discovery logic or manual testing."),
        "why_good_test": ("What this example tests in the generator.", "Read this to understand why the topic is included."),
        "source_title": ("Internet source used for the topic seed.", "Keep this as provenance."),
        "source_url": ("URL for the source.", "Keep this link so the topic can be verified later."),
        "prompt_note": ("Extra instruction to keep generation accurate.", "Paste into user notes if needed."),
    },
}


DEFAULT_ROWS: dict[str, list[list[Any]]] = {
    "README": [
        ["How to use", "Fill only the numbered sheets. Do not rename sheets or column headers."],
        ["Most important sheets", "Your researcher mainly fills 04_Reference_Videos and 05_Script_Analysis."],
        ["IDs", "genre_id must match a row in 01_Genres.id exactly, for example scary_stories."],
        ["Dates", "Use YYYY-MM-DD, for example 2026-06-16."],
        ["Numbers", "Enter only numbers in views, likes, comments, scores, counts, duration, and speed fields."],
        ["Booleans", "Use TRUE/FALSE, YES/NO, or 1/0."],
        ["Long text", "full_script, why_it_worked, and visual keyword fields can be long. Keep title fields short."],
        ["Import", "Run: python tools/genre_knowledge.py import data/knowledge/Genre_Knowledge_Import_Template.xlsx --backup --reset"],
    ],
    "01_Genres": [
        [
            "scary_stories",
            "Scary Stories",
            "horror",
            "slow dread, unsettling, realistic, specific details",
            "Huge",
            "Medium",
            "Easy",
            5,
            45,
            80,
            130,
            "full_image",
            "horror_red",
            0.88,
            "eerie",
            "inspired_by_real_events",
            "TRUE",
            "Good for real-world creepy places, unexplained reports, and witness-style stories.",
        ],
        [
            "reddit_stories",
            "Reddit Stories",
            "story",
            "conversational, dramatic, twist-based, first-person story",
            "Huge",
            "High",
            "Easy",
            3,
            60,
            120,
            180,
            "split_screen",
            "reddit_white",
            1.05,
            "subtle",
            "fictionalized_realistic",
            "TRUE",
            "Good for conflict, family drama, revenge, and satisfying reveal formats.",
        ],
        [
            "history_facts",
            "History Facts",
            "education",
            "documentary, specific dates, surprising consequence",
            "Large",
            "Low",
            "Medium",
            5,
            45,
            80,
            130,
            "full_image",
            "documentary_yellow",
            0.95,
            "documentary",
            "verified_fact_only",
            "TRUE",
            "Must be grounded in verifiable places, dates, events, or artifacts.",
        ],
        [
            "mystery_stories",
            "Mystery Stories",
            "mystery",
            "documentary mystery, clue-driven, specific evidence, unresolved payoff",
            "Large",
            "Medium",
            "Medium",
            4,
            45,
            80,
            130,
            "full_image",
            "mystery_yellow",
            0.95,
            "tense",
            "documentary_style",
            "TRUE",
            "Good for unsolved cases, strange disappearances, clues, evidence, and open-ended reveals.",
        ],
        [
            "science_facts",
            "Science Facts",
            "education",
            "clear, surprising, evidence-based, simple explanation, no fake claims",
            "Large",
            "Medium",
            "Medium",
            4,
            45,
            80,
            130,
            "full_image",
            "science_blue",
            1.0,
            "curious",
            "verified_fact_only",
            "TRUE",
            "Good for psychology studies, biology facts, space, experiments, and research-backed explainers.",
        ],
    ],
    "02_Genre_Rules": [
        ["scary_stories", "positive_term", "haunted", 20, "Useful for visual/search alignment."],
        ["scary_stories", "positive_term", "abandoned corridor", 20, "Good for hallway/hospital/school topics."],
        ["scary_stories", "negative_term", "cartoon", -60, "Avoid irrelevant generated/stock visuals."],
        ["scary_stories", "required_context", "real reported place", 40, "Keeps horror grounded in the real world."],
        ["reddit_stories", "positive_term", "realistic conversation", 20, "Grounds story visuals."],
        ["history_facts", "required_context", "verifiable date or place", 50, "Prevents fake history."],
        ["mystery_stories", "positive_term", "evidence", 20, "Keeps mystery stories clue-driven."],
        ["mystery_stories", "required_context", "named real case or documented event", 50, "Prevents generic fictional mysteries."],
        ["science_facts", "positive_term", "researchers found", 20, "Keeps science scripts evidence-based."],
        ["science_facts", "required_context", "study, experiment, organism, or verified phenomenon", 50, "Prevents fake science claims."],
    ],
    "03_Genre_Hooks": [
        ["scary_stories", "question_time_reference", "Did you know that in {year}, {place} had reports of {event}?", "curiosity", 8.5, ""],
        ["scary_stories", "time_place", "At {time}, people in {place} started hearing {sound}.", "dread", 8.0, ""],
        ["reddit_stories", "question", "What's the smartest way you tested {person}?", "curiosity", 8.5, ""],
        ["mystery_stories", "clue_question", "One detail in the {case} still does not make sense.", "curiosity", 8.5, ""],
        ["science_facts", "myth_flip", "Scientists tested {idea}, and the result was stranger than the myth.", "surprise", 8.0, ""],
    ],
    "06_Visual_Style_Rules": [
        [
            "scary_stories",
            "full_image",
            6,
            "every 8-12 sec",
            "dissolve",
            "dark_moody_realistic",
            "abandoned hallway, hospital corridor, foggy window, scratched wall, old door, shadow on wall",
            "cartoon, anime, cute, selfie, logo, medical injury closeup",
            "word_at_a_time",
            "Montserrat Black",
            "white",
            "red",
            "center",
            "eerie",
            "low bass hit at hook; sharp stinger at reveal",
            "stock_video_first",
        ],
        [
            "mystery_stories",
            "full_image",
            6,
            "every 8-12 sec",
            "cut",
            "moody_documentary",
            "old evidence photo, map with pins, abandoned location, newspaper archive, clue on table, dark corridor",
            "cartoon, party, selfie, luxury, unrelated office",
            "word_at_a_time",
            "Montserrat Black",
            "white",
            "yellow",
            "center",
            "tense",
            "soft hit at clue; low drone at reveal",
            "stock_video_first",
        ],
        [
            "science_facts",
            "full_image",
            6,
            "every 8-12 sec",
            "cut",
            "clean_science_documentary",
            "laboratory, microscope, research paper, data screen, experiment room, organism closeup",
            "cartoon, fake sci-fi, fantasy, logo, unrelated business meeting",
            "word_at_a_time",
            "Montserrat Black",
            "white",
            "blue",
            "center",
            "curious",
            "small whoosh at fact reveal; subtle click at data point",
            "stock_video_first",
        ],
    ],
    "07_Topic_Expansion_Rules": [
        [
            "scary_stories",
            "hallway",
            "real haunted hallway reports; abandoned hospital corridor ghost story; haunted hotel hallway incident; school hallway paranormal report",
            "hallway, corridor, reported, witness, place",
            "fantasy, demon king, magical portal, anime, cartoon",
            "inspired_by_real_events",
            "Use when user types vague topics like horror hallway.",
        ],
    ],
    "08_Topic_Research_Sources": [
        ["Medfield State Hospital haunted basement", "scary_stories", "Medfield State Hospital", "https://en.wikipedia.org/wiki/Medfield_State_Hospital", "encyclopedia", "Historic former psychiatric hospital in Massachusetts with public grounds, strict after-dark trespass restrictions, and local paranormal legends.", "Opened in 1892; closed in 2003; associated with local ghost stories and reported paranormal activity; police patrol and trespassing after dark is forbidden.", 7.5, 9.0],
        ["St Ignatius Hospital ghost hunters", "scary_stories", "St. Ignatius Hospital", "https://en.wikipedia.org/wiki/St._Ignatius_Hospital", "encyclopedia", "Closed hospital in Colfax, Washington, known for ghost tours and paranormal investigation interest.", "Former hospital building; associated with public ghost tours; useful for abandoned-hospital horror grounded in a named place.", 7.0, 8.5],
        ["Poveglia Island haunted hospital", "scary_stories", "List of reportedly haunted locations", "https://en.wikipedia.org/wiki/List_of_reportedly_haunted_locations", "encyclopedia", "Catalog of locations reported as haunted, including well-known sites used for folklore-style horror topics.", "Use as haunted-location source; frame claims as reports or folklore; avoid presenting paranormal claims as proven.", 6.5, 8.0],
        ["Hotel Burchianti children in the hallway", "scary_stories", "List of reportedly haunted locations", "https://en.wikipedia.org/wiki/List_of_reportedly_haunted_locations", "encyclopedia", "Reportedly haunted hotel/location list useful for hallway and hotel ghost-lore seeds.", "Use named hotel/location; frame children-in-hallway details as reports; keep narration careful and lore-based.", 6.5, 8.0],
        ["Ohio University Wilson Hall Room 428", "scary_stories", "Ghostlore", "https://en.wikipedia.org/wiki/Ghostlore", "encyclopedia", "Ghostlore overview with college and building-related folklore patterns.", "Use campus ghostlore framing; avoid claiming proof; good for dorm room, hallway, slamming-door visuals.", 6.5, 7.5],
        ["Smith College secret staircase ghost story", "scary_stories", "Ghostlore", "https://en.wikipedia.org/wiki/Ghostlore", "encyclopedia", "Ghostlore source suitable for campus secret-staircase legends and old-building folklore structure.", "Frame as college folklore; focus on a physical place such as a staircase or old house; avoid invented witnesses.", 6.5, 7.5],
        ["Dyatlov Pass tent cut from inside", "mystery_stories", "Dyatlov Pass incident", "https://en.wikipedia.org/wiki/Dyatlov_Pass_incident", "encyclopedia", "Known 1959 incident involving hikers in the Ural Mountains with long-running public mystery interest.", "Hikers died in 1959; tent and injuries became central to the mystery; avoid paranormal certainty and stick to unresolved/documented details.", 8.0, 9.5],
        ["Mary Celeste abandoned ship", "mystery_stories", "Mary Celeste", "https://en.wikipedia.org/wiki/Mary_Celeste", "encyclopedia", "Ship discovered deserted in the Atlantic in 1872 with cargo and belongings largely intact.", "Found adrift and deserted on December 4, 1872; lifeboat missing; crew never seen again; avoid fantasy explanations.", 8.0, 9.5],
        ["Lost Colony of Roanoke vanished settlement", "history_facts", "Roanoke Colony", "https://en.wikipedia.org/wiki/Roanoke_Colony", "encyclopedia", "English colony remembered for the disappearance of its colonists and the later Lost Colony mystery.", "Use Croatoan/Roanoke mystery carefully; distinguish known history from speculation; strong history-mystery seed.", 8.0, 9.0],
        ["D B Cooper vanished after hijacking", "mystery_stories", "D. B. Cooper", "https://en.wikipedia.org/wiki/D._B._Cooper", "encyclopedia", "Unidentified hijacker who parachuted from a plane and became a famous unsolved case.", "Use hijacking, parachute escape, and unresolved identity; do not name a culprit as fact.", 8.0, 9.0],
        ["Tunguska explosion flattened forest", "history_facts", "Tunguska event", "https://en.wikipedia.org/wiki/Tunguska_event", "encyclopedia", "Large 1908 explosion over Siberia often explained as an airburst from a cosmic body.", "Use 1908 Siberia explosion; emphasize scale and forest damage; avoid conspiracy framing.", 8.0, 9.0],
        ["Antikythera mechanism ancient computer", "history_facts", "Antikythera mechanism", "https://en.wikipedia.org/wiki/Antikythera_mechanism", "encyclopedia", "Ancient Greek hand-powered mechanical model used to predict astronomical positions and eclipses.", "Use artifact, gears, astronomy, ancient engineering; strong object-centered history fact.", 8.5, 9.5],
        ["Roman roads paths to empire", "history_facts", "Roman roads", "https://en.wikipedia.org/wiki/Roman_roads", "encyclopedia", "Roman road network helped military movement, administration, and trade across the empire.", "Use infrastructure consequence: soldiers, trade, messages, durable roads; avoid vague greatness claims.", 8.0, 8.5],
        ["Salem witch trials fear spread", "history_facts", "Salem witch trials", "https://en.wikipedia.org/wiki/Salem_witch_trials", "encyclopedia", "1692-1693 colonial Massachusetts witch trials and executions rooted in accusation, fear, and legal process.", "Use respectful factual framing; explain panic, accusation, and consequence without sensationalizing victims.", 8.0, 8.5],
        ["Milgram experiment obedience shock box", "science_facts", "Milgram experiment", "https://en.wikipedia.org/wiki/Milgram_experiment", "encyclopedia", "Yale obedience study where participants were instructed to administer what they believed were electric shocks.", "Use authority pressure and ethics controversy; avoid implying the shocks were real injuries.", 8.0, 9.0],
        ["Marshmallow test replication changed the lesson", "science_facts", "Stanford marshmallow experiment", "https://en.wikipedia.org/wiki/Stanford_marshmallow_experiment", "encyclopedia", "Delayed-gratification study later discussed alongside replication and context debates.", "Use original test plus later nuance; payoff should mention context and reliability, not just willpower.", 7.5, 8.5],
        ["Asch conformity experiment wrong lines", "science_facts", "Asch conformity experiments", "https://en.wikipedia.org/wiki/Asch_conformity_experiments", "encyclopedia", "Classic conformity studies about group pressure and line-judgment answers.", "Use group pressure and wrong-answer setup; strong simple visual science topic.", 8.0, 8.5],
        ["cuttlefish passed a marshmallow-style test", "science_facts", "Stanford marshmallow experiment", "https://en.wikipedia.org/wiki/Stanford_marshmallow_experiment", "encyclopedia", "Delayed-gratification framework can seed animal cognition topics when paired with specific research.", "Use as test-style framing only; verify cuttlefish details separately before making precise claims.", 6.5, 7.0],
        ["Tardigrades survive extreme conditions", "science_facts", "Tardigrade", "https://en.wikipedia.org/wiki/Tardigrade", "encyclopedia", "Microscopic animals known for surviving extreme environmental stress in a dormant state.", "Use water bear, cryptobiosis, vacuum/radiation/extreme-condition visuals; do not exaggerate immortality.", 8.0, 9.0],
        ["placebo effect fake treatment real response", "science_facts", "Placebo", "https://en.wikipedia.org/wiki/Placebo", "encyclopedia", "Placebo effect describes real perceived or measured response related to treatment context rather than active treatment.", "Use careful medical framing; do not give treatment advice; mention expectation/context rather than magic.", 8.0, 8.5],
    ],
    "10_Playground_Test_Topics": [
        ["PT001", "scary_stories", "Medfield State Hospital haunted basement", "Use the real abandoned hospital setting, reported whispers, Weeping Woman lore, and trespassing warnings.", "inspired_by_real_events", "Medfield State Hospital haunted basement; Medfield State Hospital Weeping Woman; abandoned hospital ghost reports", "Tests real-world horror without inventing a random fictional hospital.", "Medfield State Hospital", "https://en.wikipedia.org/wiki/Medfield_State_Hospital", "Keep claims framed as local legends or reports."],
        ["PT002", "scary_stories", "St Ignatius Hospital ghost hunters", "Use the closed Colfax hospital, ghost tours, and its reputation as a haunted hospital.", "inspired_by_real_events", "St Ignatius Hospital ghost tours; Colfax abandoned hospital haunted; St Ignatius Hospital Ghost Adventures", "Tests abandoned hospital topic grounding and eerie visual cues.", "St. Ignatius Hospital", "https://en.wikipedia.org/wiki/St._Ignatius_Hospital", "Avoid claiming proof of ghosts; say visitors reported."],
        ["PT003", "scary_stories", "Poveglia Island haunted hospital", "Use the Italian island's plague/quarantine and hospital/asylum folklore.", "inspired_by_real_events", "Poveglia Island haunted hospital; Poveglia asylum ghost story; haunted island Italy", "Tests real place plus horror folklore plus strong atmosphere.", "List of reportedly haunted locations", "https://en.wikipedia.org/wiki/List_of_reportedly_haunted_locations", "Frame as one of the world's most famous haunted-location legends."],
        ["PT004", "scary_stories", "Hotel Burchianti children in the hallway", "Use the Florence hotel reports of children skipping down halls and cold sensations.", "inspired_by_real_events", "Hotel Burchianti haunted children hallway; Florence haunted hotel children sounds", "Directly tests hallway horror with a named real hotel.", "List of reportedly haunted locations", "https://en.wikipedia.org/wiki/List_of_reportedly_haunted_locations", "Keep it short, eerie, and report-based."],
        ["PT005", "scary_stories", "Ohio University Wilson Hall Room 428", "Use the campus ghostlore reports of objects flying and doors slamming.", "inspired_by_real_events", "Ohio University Wilson Hall Room 428 ghost; haunted dorm door slamming; campus ghostlore", "Tests school/dorm horror without generic monsters.", "Ghostlore", "https://en.wikipedia.org/wiki/Ghostlore", "Use student-lore framing."],
        ["PT006", "scary_stories", "Smith College secret staircase ghost story", "Use Sessions House, the hidden staircase, and Revolutionary War-era ghostlore.", "inspired_by_real_events", "Smith College Sessions House secret staircase ghost; haunted campus secret staircase", "Tests old-building horror with historical detail.", "Ghostlore", "https://en.wikipedia.org/wiki/Ghostlore", "Make the staircase the central visual object."],
        ["PT007", "mystery_stories", "Dyatlov Pass tent cut from inside", "Focus on the hikers leaving their tent, hypothermia, severe injuries, and unresolved mystery framing.", "documentary_style", "Dyatlov Pass tent cut from inside; Dyatlov Pass injuries hypothermia; Dyatlov mystery facts", "Tests mystery narration grounded in known facts.", "Dyatlov Pass incident", "https://en.wikipedia.org/wiki/Dyatlov_Pass_incident", "Do not overclaim a paranormal answer."],
        ["PT008", "mystery_stories", "Mary Celeste abandoned ship", "Use the famous derelict ship mystery and missing crew setup.", "documentary_style", "Mary Celeste abandoned ship mystery; ghost ship Mary Celeste facts; derelict vessel missing crew", "Tests classic mystery structure and maritime visuals.", "History's Mysteries", "https://en.wikipedia.org/wiki/History%27s_Mysteries", "Keep focus on the unanswered question."],
        ["PT009", "history_facts", "Lost Colony of Roanoke vanished settlement", "Use the disappearance of the colony and the mystery around what happened.", "verified_fact_only", "Lost Colony of Roanoke vanished settlement; Croatoan clue; Roanoke mystery history", "Tests historical mystery with a famous real-world case.", "History's Mysteries", "https://en.wikipedia.org/wiki/History%27s_Mysteries", "Use facts and uncertainty, not fantasy."],
        ["PT010", "mystery_stories", "D B Cooper vanished after hijacking", "Use the airplane hijacking, parachute escape, and unresolved disappearance.", "documentary_style", "D B Cooper hijacking vanished parachute; D B Cooper mystery facts", "Tests modern unsolved mystery pacing.", "History's Mysteries", "https://en.wikipedia.org/wiki/History%27s_Mysteries", "Avoid naming a culprit unless sourced."],
        ["PT011", "history_facts", "Tunguska explosion flattened forest", "Use the Siberian explosion and the scale of forest damage.", "verified_fact_only", "Tunguska event flattened forest; 1908 Siberia explosion facts", "Tests science-history fact storytelling.", "Unsolved History", "https://en.wikipedia.org/wiki/Unsolved_History", "Explain the impact clearly with no conspiracy angle."],
        ["PT012", "history_facts", "Antikythera mechanism ancient computer", "Use the ancient Greek geared device and why it shocked historians.", "verified_fact_only", "Antikythera mechanism ancient computer; Greek geared device history", "Tests artifact-based historical wonder.", "History's Mysteries", "https://en.wikipedia.org/wiki/History%27s_Mysteries", "Make the object visually central."],
        ["PT013", "history_facts", "Roman roads paths to empire", "Use the Roman road network as infrastructure that helped power the empire.", "verified_fact_only", "Roman roads paths to empire; Roman road engineering facts", "Tests educational history with clear visuals.", "History's Mysteries", "https://en.wikipedia.org/wiki/History%27s_Mysteries", "Focus on consequence: movement, military, trade."],
        ["PT014", "history_facts", "Salem witch trials fear spread", "Use the trials as a cautionary history story about panic and accusation.", "verified_fact_only", "Salem witch trials accusation panic history; Salem witch trials facts", "Tests sensitive historical topic handling.", "History's Mysteries", "https://en.wikipedia.org/wiki/History%27s_Mysteries", "Stay respectful and factual."],
        ["PT015", "science_facts", "Milgram experiment obedience shock box", "Use the Yale obedience study, authority pressure, and the shocking 450-volt result claim.", "verified_fact_only", "Milgram experiment obedience 450 volts; Yale shock box psychology experiment", "Tests psychology fact script with ethical nuance.", "Milgram experiment", "https://en.wikipedia.org/wiki/Milgram_experiment", "Mention the ethical controversy."],
        ["PT016", "science_facts", "Marshmallow test replication changed the lesson", "Use the original delayed gratification setup and later replication challenges.", "verified_fact_only", "Stanford marshmallow experiment replication challenged; marshmallow test economic background", "Tests science update nuance instead of oversimplified motivation.", "Stanford marshmallow experiment", "https://en.wikipedia.org/wiki/Stanford_marshmallow_experiment", "Payoff: reliability/context mattered more than willpower alone."],
        ["PT017", "science_facts", "Asch conformity experiment wrong lines", "Use the conformity setup where people agreed with wrong answers under group pressure.", "verified_fact_only", "Asch conformity experiment line judgment; social pressure wrong answer", "Tests simple visual psychology explanation.", "Social experiment", "https://en.wikipedia.org/wiki/Social_experiment", "Use classroom/table visual cues."],
        ["PT018", "science_facts", "cuttlefish passed a marshmallow-style test", "Use the adapted delayed-gratification test in cuttlefish and future-oriented behavior.", "verified_fact_only", "cuttlefish marshmallow test delayed gratification; cuttlefish self control study", "Tests weird science with strong hook potential.", "Stanford marshmallow experiment", "https://en.wikipedia.org/wiki/Stanford_marshmallow_experiment", "Make the surprise about intelligence, not cuteness."],
        ["PT019", "science_facts", "Tardigrades survive extreme conditions", "Use the microscopic animal's survival under harsh conditions as a science short.", "verified_fact_only", "tardigrades survive extreme conditions vacuum radiation; water bear science facts", "Tests science visuals and concrete explanation.", "Tardigrade", "https://en.wikipedia.org/wiki/Tardigrade", "Use microscope and survival-condition visuals."],
        ["PT020", "science_facts", "placebo effect fake treatment real response", "Use placebo/nocebo as a grounded mind-body science fact.", "verified_fact_only", "placebo effect fake treatment real response; nocebo effect science facts", "Tests abstract science made concrete.", "Placebo", "https://en.wikipedia.org/wiki/Placebo", "Use medical-study framing carefully; do not give medical advice."],
    ],
}


FIELD_RULES = [
    FieldRule("01_Genres", "id", "YES", "text", "80", "lowercase letters/numbers/underscore", "scary_stories", "Primary key. Never change after videos reference it."),
    FieldRule("01_Genres", "display_name", "YES", "text", "120", "", "Scary Stories", ""),
    FieldRule("01_Genres", "recommended_score", "NO", "number", "", "0-5", "5", ""),
    FieldRule("01_Genres", "default_duration_sec", "NO", "integer", "", "10-180", "45", ""),
    FieldRule("01_Genres", "word_count_min", "NO", "integer", "", "1-1000", "80", ""),
    FieldRule("01_Genres", "word_count_max", "NO", "integer", "", "1-1000", "130", "Must be >= word_count_min."),
    FieldRule("01_Genres", "voice_rate", "NO", "decimal", "", "0.5-2.0", "0.88", ""),
    FieldRule("01_Genres", "realism_mode", "NO", "text", "60", "fictional; fictionalized_realistic; inspired_by_real_events; documentary_style; verified_fact_only", "inspired_by_real_events", ""),
    FieldRule("01_Genres", "is_active", "NO", "boolean", "", "TRUE/FALSE", "TRUE", ""),
    FieldRule("02_Genre_Rules", "genre_id", "YES", "text", "80", "must exist in 01_Genres.id", "scary_stories", ""),
    FieldRule("02_Genre_Rules", "rule_type", "YES", "text", "60", "positive_term; negative_term; required_context; banned_phrase; tone_rule", "positive_term", ""),
    FieldRule("02_Genre_Rules", "value", "YES", "text", "300", "", "abandoned hallway", ""),
    FieldRule("02_Genre_Rules", "weight", "NO", "integer", "", "-100 to 100", "20", ""),
    FieldRule("03_Genre_Hooks", "template", "YES", "text", "500", "", "At {time}, {subject} moved by itself.", "Use placeholders inside curly braces."),
    FieldRule("04_Reference_Videos", "genre_id", "YES", "text", "80", "must exist in 01_Genres.id", "scary_stories", ""),
    FieldRule("04_Reference_Videos", "video_url", "YES", "text", "500", "unique", "https://youtube.com/shorts/abc", ""),
    FieldRule("04_Reference_Videos", "channel_name", "NO", "text", "120", "", "@DarkFactsDaily", ""),
    FieldRule("04_Reference_Videos", "views", "NO", "integer", "", "0 or higher", "14200000", ""),
    FieldRule("04_Reference_Videos", "upload_date", "NO", "date", "", "YYYY-MM-DD", "2026-06-16", ""),
    FieldRule("04_Reference_Videos", "title", "NO", "text", "160", "", "This Family Found A Sealed Room", ""),
    FieldRule("04_Reference_Videos", "hashtags", "NO", "text", "500", "", "#shorts #scary", ""),
    FieldRule("04_Reference_Videos", "full_script", "YES", "long text", "unlimited", "", "Paste exact transcript here", "Most important field."),
    FieldRule("04_Reference_Videos", "overall_score", "NO", "decimal", "", "0-10", "9", ""),
    FieldRule("04_Reference_Videos", "usable_as_few_shot", "NO", "boolean", "", "TRUE/FALSE", "TRUE", ""),
    FieldRule("05_Script_Analysis", "video_url", "YES", "text", "500", "must exist in 04_Reference_Videos.video_url", "https://youtube.com/shorts/abc", "Used instead of database id so humans can fill it."),
    FieldRule("05_Script_Analysis", "hook_first_sentence", "YES", "text", "500", "", "Did you know that in 1973...", ""),
    FieldRule("05_Script_Analysis", "has_twist_reveal", "NO", "boolean", "", "TRUE/FALSE", "TRUE", ""),
    FieldRule("05_Script_Analysis", "why_it_worked", "YES", "long text", "unlimited", "", "Escalating reveals and specific details.", "Very important for AI learning."),
    FieldRule("05_Script_Analysis", "what_to_improve", "NO", "long text", "unlimited", "", "Start faster.", ""),
    FieldRule("06_Visual_Style_Rules", "genre_id", "YES", "text", "80", "must exist in 01_Genres.id", "scary_stories", ""),
    FieldRule("06_Visual_Style_Rules", "visual_keywords", "NO", "long text", "unlimited", "comma-separated", "abandoned hallway, foggy window", ""),
    FieldRule("06_Visual_Style_Rules", "negative_visual_keywords", "NO", "long text", "unlimited", "comma-separated", "cartoon, logo, selfie", ""),
    FieldRule("07_Topic_Expansion_Rules", "trigger_term", "YES", "text", "120", "", "hallway", "When this word appears in user topic, add better research queries."),
    FieldRule("07_Topic_Expansion_Rules", "search_queries", "YES", "long text", "unlimited", "semicolon-separated", "real haunted hallway reports; haunted hotel hallway incident", ""),
    FieldRule("08_Topic_Research_Sources", "topic", "YES", "text", "300", "", "Mary Celeste abandoned ship", ""),
    FieldRule("08_Topic_Research_Sources", "genre_id", "YES", "text", "80", "must exist in 01_Genres.id", "mystery_stories", ""),
    FieldRule("08_Topic_Research_Sources", "title", "NO", "text", "300", "", "Mary Celeste", ""),
    FieldRule("08_Topic_Research_Sources", "url", "YES", "text", "700", "valid URL recommended", "https://en.wikipedia.org/wiki/Mary_Celeste", ""),
    FieldRule("08_Topic_Research_Sources", "source_type", "NO", "text", "80", "encyclopedia; article; official; study; archive; local", "encyclopedia", ""),
    FieldRule("08_Topic_Research_Sources", "snippet", "NO", "long text", "unlimited", "", "Ship discovered deserted in the Atlantic in 1872.", ""),
    FieldRule("08_Topic_Research_Sources", "extracted_facts", "NO", "long text", "unlimited", "semicolon-separated", "Found deserted; lifeboat missing; crew never seen again", ""),
    FieldRule("08_Topic_Research_Sources", "credibility_score", "NO", "decimal", "", "0-10", "8", ""),
    FieldRule("08_Topic_Research_Sources", "relevance_score", "NO", "decimal", "", "0-10", "9", ""),
]


SINGLE_ENTRY_HEADERS = [
    "row_type",
    "import_action",
    "genre_id",
    "genre",
    "display_name",
    "sub_genre",
    "category",
    "tone",
    "audience_size",
    "competition_level",
    "content_difficulty",
    "recommended_score",
    "default_duration_sec",
    "word_count_min",
    "word_count_max",
    "layout",
    "caption_preset",
    "voice_rate",
    "music_mood",
    "realism_mode",
    "is_active",
    "video_url",
    "channel_name",
    "channel_subscribers",
    "views",
    "likes",
    "comments",
    "upload_date",
    "duration_sec",
    "day_of_week",
    "post_time",
    "video_title",
    "title_length",
    "title_has_emoji",
    "title_has_hashtags",
    "hashtags_used",
    "description_first_line",
    "full_transcript",
    "word_count",
    "sentence_count",
    "words_per_second",
    "hook_first_sentence",
    "hook_type",
    "hook_template",
    "hook_emotional_trigger",
    "hook_speed_sec",
    "opening_5_words",
    "body_sentence_count",
    "twist_present",
    "twist_line",
    "ending_type",
    "last_sentence",
    "tense_used",
    "pov_person",
    "rhetorical_questions_count",
    "power_words",
    "emphasis_words",
    "narrative_technique",
    "emotional_arc",
    "numbers_stats_present",
    "direct_address_present",
    "banned_phrases_found",
    "avg_sentence_length",
    "shortest_sentence",
    "longest_sentence",
    "short_long_ratio",
    "sentence_length_pattern",
    "info_density",
    "surprise_twist_count",
    "cta_present",
    "cta_placement",
    "repetition_callback",
    "sensory_language_used",
    "voice_gender",
    "voice_tone",
    "speaking_speed",
    "pause_after_hook_ms",
    "pause_before_reveal_ms",
    "other_notable_pauses",
    "words_spoken_louder_slower",
    "layout_type",
    "face_visible",
    "image_count",
    "image_or_video_count",
    "image_change_timing",
    "transition_type",
    "image_style",
    "visual_keywords",
    "negative_visual_keywords",
    "image_descriptions",
    "ken_burns_effect",
    "images_match_words",
    "gameplay_type",
    "gameplay_position",
    "color_grading",
    "text_overlays",
    "caption_style",
    "caption_font",
    "caption_primary_color",
    "caption_highlight_color",
    "caption_position",
    "caption_border_glow",
    "words_per_caption_pop",
    "background_music_present",
    "music_volume_level",
    "music_fades",
    "music_changes_mid_video",
    "sound_effects_present",
    "sfx_at_hook",
    "sfx_at_reveal",
    "sfx_at_ending",
    "other_sfx_notes",
    "sfx_rules",
    "audio_clarity",
    "like_view_ratio",
    "comment_view_ratio",
    "estimated_save_share_level",
    "why_would_someone_share",
    "rewatch_value",
    "controversy_debate_potential",
    "trend_alignment",
    "first_frame_scroll_stop",
    "first_frame_motion",
    "would_you_stop_scrolling",
    "top_comment_theme",
    "comment_sentiment",
    "comments_add_stories",
    "creator_replies_in_comments",
    "likely_share_trigger",
    "retention_hook",
    "where_would_you_stop_watching",
    "thumbnail_style",
    "thumbnail_text",
    "thumbnail_colors",
    "score_hook",
    "score_script",
    "score_pacing",
    "score_visual",
    "score_audio",
    "score_shareability",
    "score_overall",
    "why_it_worked",
    "what_to_improve",
    "usable_as_few_shot_example",
    "additional_notes",
    "processed_time",
    "automation_confidence",
    "rule_type",
    "rule_value",
    "rule_weight",
    "trigger_term",
    "search_queries",
    "required_words",
    "forbidden_words",
    "source_topic",
    "source_title",
    "source_url",
    "source_type",
    "source_snippet",
    "extracted_facts",
    "credibility_score",
    "relevance_score",
]


SINGLE_ENTRY_EXAMPLE_ROW = [
    "reference_video",
    "upsert",
    "scary_stories",
    "Scary Stories",
    "Scary Stories",
    "haunted places",
    "horror",
    "slow dread, realistic, specific details",
    "Huge",
    "Medium",
    "Easy",
    5,
    45,
    80,
    130,
    "full_image",
    "horror_red",
    0.88,
    "eerie",
    "inspired_by_real_events",
    "TRUE",
    "https://youtube.com/shorts/example",
    "@ExampleChannel",
    850000,
    14200000,
    620000,
    8400,
    "2026-06-16",
    52,
    "Tuesday",
    "21:30",
    "This Family Found A Sealed Room",
    52,
    "TRUE",
    "FALSE",
    "#shorts #scary #horror",
    "Would you stay?",
    "Paste full transcript here.",
    108,
    7,
    2.08,
    "Did you know that in 1973, a family bought their dream home?",
    "question_time_reference",
    "Did you know that in {year}, {place} had reports of {event}?",
    "curiosity",
    4.5,
    "Did you know that in",
    4,
    "TRUE",
    "she can hear you",
    "open_ended",
    "And the house? It's still for sale.",
    "past",
    "narrator",
    0,
    "sealed, scratched, hear",
    "sealed, 40 years, still for sale",
    "escalating_reveal",
    "curiosity -> unease -> dread -> shock",
    "TRUE",
    "FALSE",
    "none",
    15.4,
    "The bed was still made.",
    "Long setup sentence here.",
    "3:4",
    "long_then_short_punch",
    "1.0",
    2,
    "FALSE",
    "",
    "still repeated as callback",
    "visual: bed, toys, scratched wall; auditory: hear",
    "male",
    "deep_authoritative",
    "slow",
    600,
    800,
    "After reveal line",
    "sealed, scratched",
    "full_image",
    "FALSE",
    5,
    5,
    "every 8-12 sec",
    "dissolve",
    "dark_moody_realistic",
    "abandoned hallway, old house, scratched wall",
    "cartoon, selfie, logo",
    "Old house exterior; brick wall; abandoned bedroom",
    "TRUE",
    "perfectly_synced",
    "minecraft_parkour",
    "bottom_half",
    "cold_desaturated",
    "none",
    "word_at_a_time",
    "Montserrat Black",
    "white",
    "red",
    "center",
    "black border and red glow",
    "2-3",
    "TRUE",
    "barely_audible",
    "TRUE",
    "FALSE",
    "TRUE",
    "subtle low bass hit",
    "sharp horror stinger",
    "deep drone",
    "faint scratching sound",
    "low bass at hook; stinger at reveal",
    "crystal_clear",
    4.36,
    0.05,
    "high",
    "The twist makes people tag friends.",
    "medium",
    "low",
    "evergreen",
    "TRUE",
    "TRUE",
    "TRUE",
    "people sharing similar stories",
    "engaged_scared",
    "TRUE",
    "TRUE",
    "the twist phrase",
    "each sentence reveals more",
    "nowhere",
    "dark_atmospheric",
    "SEALED ROOM",
    "dark blue + red",
    9,
    9,
    9,
    8,
    8,
    9,
    9,
    "Escalating reveals, concrete details, strong open ending.",
    "Could start faster.",
    "TRUE",
    "Good template for discovery horror.",
    "",
    0.92,
    "required_context",
    "real reported place",
    40,
    "hallway",
    "real haunted hallway reports; haunted hotel hallway incident",
    "hallway, corridor, reported, witness",
    "fantasy, anime, cartoon",
    "Medfield State Hospital haunted basement",
    "Medfield State Hospital",
    "https://en.wikipedia.org/wiki/Medfield_State_Hospital",
    "encyclopedia",
    "Historic former psychiatric hospital with local legends.",
    "Opened 1892; closed 2003; associated with local ghost stories.",
    7.5,
    9.0,
]


SINGLE_ENTRY_MEANING_ROW = [
    "column_meaning: tells importer what this row represents; real data can be reference_video, genre_rule, genre_hook, visual_rule, topic_source, or topic_expansion.",
    "What to do with this row during import, usually upsert to create or update existing data.",
    "Stable machine id for the genre. Use lowercase letters, numbers, and underscores.",
    "Human genre name from the BDA sheet, usually same idea as display_name.",
    "Readable genre name shown to admins and prompts.",
    "More specific niche inside the genre, such as haunted places or family betrayal.",
    "Broad content family, such as horror, mystery, history, science, or story.",
    "Writing style and emotional feel the AI should copy for this genre.",
    "Estimated audience size for the niche: Small, Medium, Large, or Huge.",
    "How crowded the niche is on Shorts: Low, Medium, or High.",
    "How hard the niche is to research and produce correctly.",
    "Internal rating from 0 to 5 for how strongly we should recommend this genre.",
    "Default target duration for generated videos in seconds.",
    "Minimum narration word count that usually fits this genre and duration.",
    "Maximum narration word count that usually fits this genre and duration.",
    "Default video composition, such as full_image, split_screen, or full_gameplay.",
    "Caption preset name the renderer should use for this genre.",
    "Narration speed multiplier. Lower feels slower and darker; higher feels faster.",
    "Default background music mood for this genre.",
    "How factual the AI should be: fictional, inspired_by_real_events, documentary_style, or verified_fact_only.",
    "Whether this genre is active and available for generation.",
    "YouTube Shorts URL for the reference video being analyzed.",
    "Creator or channel name for the reference Short.",
    "Subscriber count at the time your researcher watched the video.",
    "View count at the time your researcher recorded the video.",
    "Like count at the time your researcher recorded the video.",
    "Comment count at the time your researcher recorded the video.",
    "Date the video was uploaded. Use YYYY-MM-DD if known.",
    "Actual video length in seconds.",
    "Day of week when the video was posted, if known.",
    "Upload time of day, if visible or known.",
    "Exact visible title of the reference video.",
    "Character count of the title, useful for title pattern analysis.",
    "Whether the title contains emoji.",
    "Whether the title contains hashtags.",
    "Hashtags used in the title or description.",
    "First line of the video description, if useful.",
    "Full spoken transcript or script from the Short.",
    "Number of words in the transcript.",
    "Number of sentences in the transcript.",
    "Pacing metric: word_count divided by duration_sec.",
    "Exact first sentence spoken in the video.",
    "Type of opening hook, such as question, shock_statement, or time_place.",
    "Reusable pattern behind the hook, with placeholders if possible.",
    "Emotion the hook creates, such as curiosity, fear, anger, surprise, or empathy.",
    "Seconds until the hook promise becomes clear.",
    "The first five words spoken, useful for pattern matching.",
    "Number of middle/body sentences after the hook and before the ending.",
    "Whether the video contains a twist, reveal, or reversal.",
    "Exact line where the twist or reveal happens.",
    "How the video ends, such as open_ended, warning, lesson, justice, or shocking_fact.",
    "Exact last sentence of the narration.",
    "Main narration tense: past, present, or mixed.",
    "Point of view: narrator, first_person, third_person, direct_address, etc.",
    "Number of rhetorical questions used in the script.",
    "Strong emotional or high-impact words used in the script.",
    "Words that captions or voice should emphasize.",
    "Storytelling structure, such as escalating_reveal, listicle, mystery_setup, or cause_effect.",
    "Emotional journey of the viewer across the script.",
    "Whether the script uses numbers, dates, money, percentages, or stats.",
    "Whether the script speaks directly to the viewer using you/your.",
    "Any weak, overused, unsafe, or banned phrases found in the script.",
    "Average sentence length in words.",
    "Shortest sentence in the script.",
    "Longest sentence in the script.",
    "Relationship between short and long sentences, used to measure rhythm.",
    "Overall sentence rhythm pattern, such as short_punchy or long_then_short_punch.",
    "How much information is packed into the script; higher means denser.",
    "Number of separate surprise beats or twist moments.",
    "Whether the video asks viewers to like, comment, follow, or share.",
    "Where the call to action appears: start, middle, end, pinned comment, or none.",
    "A phrase, image, or idea repeated later for payoff.",
    "Concrete sensory details: what viewers can see, hear, feel, or imagine.",
    "Voice gender or vocal style if noticeable.",
    "Voice mood, such as deep_authoritative, whispered, excited, calm, or documentary.",
    "Human description of narration speed: slow, medium, fast, or very_fast.",
    "Pause length after the hook in milliseconds.",
    "Pause length before the reveal in milliseconds.",
    "Any other important pauses and where they happen.",
    "Words intentionally spoken louder, slower, or with special emphasis.",
    "Actual layout used in the reference video.",
    "Whether a human face is visible in the video.",
    "BDA-compatible count of images or visual scenes used.",
    "Normalized count of images, clips, or major visual changes.",
    "How often images or video scenes change.",
    "Transition style between visuals, such as cut, dissolve, zoom, or swipe.",
    "Overall image look, such as dark_moody_realistic or clean_documentary.",
    "Good visual search/generation keywords for this video or genre.",
    "Visual terms to avoid because they make results irrelevant or low quality.",
    "Short description of the actual images or scenes used.",
    "Whether slow zoom/pan movement is applied to still images.",
    "How well visuals match the spoken words.",
    "Gameplay type if gameplay footage is used, otherwise none.",
    "Where gameplay appears, such as bottom_half, background, or none.",
    "Color treatment, such as cold_desaturated, warm, high_contrast, or natural.",
    "Any non-caption text shown on screen.",
    "Caption animation format, such as word_at_a_time, phrase_pop, or subtitle_line.",
    "Caption font used or closest match.",
    "Main caption text color.",
    "Caption highlight/emphasis color.",
    "Where captions appear on screen.",
    "Caption outline, border, shadow, or glow style.",
    "How many words appear per caption pop.",
    "Whether background music is present.",
    "How loud the music feels compared with the voice.",
    "Whether music fades in or out.",
    "Whether the music changes during the Short.",
    "Whether sound effects are used.",
    "Sound effect used at or immediately after the hook.",
    "Sound effect used at the reveal or twist.",
    "Sound effect used at the ending.",
    "Other useful sound effect notes.",
    "Reusable sound effect rule for this genre or style.",
    "How clear the voice/audio mix is.",
    "Likes divided by views, used as an engagement signal.",
    "Comments divided by views, used as a discussion signal.",
    "Estimated save/share strength: low, medium, high, or very_high.",
    "Human reason a viewer would share the video.",
    "How likely people are to rewatch: low, medium, high.",
    "Whether the topic can create debate or disagreement.",
    "Whether the video matches a current or evergreen Shorts trend.",
    "Whether the first frame is strong enough to stop scrolling.",
    "Whether something moves or changes in the first frame.",
    "Your honest answer: would you personally stop scrolling for this first second.",
    "Main theme seen in the top comments.",
    "Overall comment mood: positive, negative, scared, curious, angry, mixed, etc.",
    "Whether commenters add their own stories or experiences.",
    "Whether the creator replies to comments.",
    "Main thing that would make viewers share or tag someone.",
    "Open question or promise that keeps viewers watching.",
    "Point where a normal viewer might lose interest.",
    "Thumbnail or cover-frame style if visible.",
    "Words shown on the thumbnail or cover frame.",
    "Dominant thumbnail or cover-frame colors.",
    "Score from 0 to 10 for the hook strength.",
    "Score from 0 to 10 for the script quality.",
    "Score from 0 to 10 for pacing.",
    "Score from 0 to 10 for visuals.",
    "Score from 0 to 10 for audio and sound design.",
    "Score from 0 to 10 for shareability.",
    "Overall score from 0 to 10.",
    "Human explanation of why the video worked.",
    "Specific changes that could make the video better.",
    "Whether this is good enough for the AI to learn from as an example.",
    "Extra notes that do not fit elsewhere.",
    "When the row was processed by automation, if automation was used.",
    "Confidence score for automated extraction, from 0 to 1.",
    "Type of genre rule, such as positive_term, negative_term, required_context, banned_phrase, or tone_rule.",
    "Actual rule text the AI should follow or avoid.",
    "Strength of the rule. Positive boosts; negative penalizes.",
    "User topic word that activates topic expansion, such as hallway or hospital.",
    "Better research/search queries to ground vague user topics in real-world examples.",
    "Words that should appear in grounded results or the final direction.",
    "Words that should be avoided because they lead to irrelevant output.",
    "Topic seed supported by the source.",
    "Title of the article, page, study, or source.",
    "URL proving or supporting the source.",
    "Kind of source: encyclopedia, article, official, study, archive, local, or video.",
    "Short human summary of what the source says.",
    "Facts the AI can safely use, separated by semicolons.",
    "Reliability score from 0 to 10.",
    "How relevant the source is to the topic, from 0 to 10.",
]


BDA_VIDEO_ANALYSIS_HEADERS = [
    "Video URL",
    "Genre",
    "Sub Genre",
    "Channel Name",
    "Channel Subscribers",
    "Views",
    "Likes",
    "Comments",
    "Upload Date",
    "Duration Sec",
    "Day of Week",
    "Post Time",
    "Video Title",
    "Title Length",
    "Title Has Emoji",
    "Title Has Hashtags",
    "Hashtags Used",
    "Category",
    "Full Transcript",
    "Word Count",
    "Sentence Count",
    "Words Per Second",
    "Hook First Sentence",
    "Hook Type",
    "Hook Emotional Trigger",
    "Hook Speed Sec",
    "Opening 5 Words",
    "Body Sentence Count",
    "Twist Present",
    "Twist Line",
    "Ending Type",
    "Last Sentence",
    "Tense Used",
    "POV Person",
    "Rhetorical Questions Count",
    "Power Words",
    "Emphasis Words",
    "Narrative Technique",
    "Emotional Arc",
    "Numbers Stats Present",
    "Direct Address Present",
    "Banned Phrases Found",
    "Avg Sentence Length",
    "Shortest Sentence",
    "Longest Sentence",
    "Short Long Ratio",
    "Sentence Length Pattern",
    "Info Density",
    "Surprise Twist Count",
    "CTA Present",
    "CTA Placement",
    "Repetition Callback",
    "Sensory Language Used",
    "Voice Gender",
    "Voice Tone",
    "Speaking Speed",
    "Pause After Hook Ms",
    "Pause Before Reveal Ms",
    "Other Notable Pauses",
    "Words Spoken Louder Slower",
    "Layout Type",
    "Face Visible",
    "Image Count",
    "Image Change Timing",
    "Transition Type",
    "Image Style",
    "Ken Burns Effect",
    "Images Match Words",
    "Gameplay Type",
    "Gameplay Position",
    "Color Grading",
    "Text Overlays",
    "Caption Style",
    "Caption Font",
    "Caption Primary Color",
    "Caption Highlight Color",
    "Caption Position",
    "Caption Border Glow",
    "Words Per Caption Pop",
    "Background Music Present",
    "Music Mood",
    "Music Volume Level",
    "Music Fades",
    "Music Changes Mid Video",
    "Sound Effects Present",
    "SFX At Hook",
    "SFX At Reveal",
    "SFX At Ending",
    "Other SFX Notes",
    "Audio Clarity",
    "Like View Ratio",
    "Comment View Ratio",
    "Estimated Save Share Level",
    "Why Would Someone Share",
    "Rewatch Value",
    "Controversy Debate Potential",
    "Trend Alignment",
    "First Frame Scroll Stop",
    "First Frame Motion",
    "Would You Stop Scrolling",
    "Top Comment Theme",
    "Comment Sentiment",
    "Comments Add Stories",
    "Creator Replies In Comments",
    "Likely Share Trigger",
    "Retention Hook",
    "Where Would You Stop Watching",
    "Thumbnail Style",
    "Thumbnail Text",
    "Thumbnail Colors",
    "Score Hook",
    "Score Script",
    "Score Pacing",
    "Score Visual",
    "Score Audio",
    "Score Shareability",
    "Score Overall",
    "Why It Worked",
    "What To Improve",
    "Usable As Few Shot Example",
    "Additional Notes",
    "Processed Time",
    "Automation Confidence",
]


BDA_VIDEO_EXAMPLES = {
    "Video URL": "https://youtube.com/shorts/example",
    "Genre": "Scary Stories",
    "Sub Genre": "Haunted places",
    "Channel Name": "@ExampleChannel",
    "Channel Subscribers": 850000,
    "Views": 14200000,
    "Likes": 620000,
    "Comments": 8400,
    "Upload Date": "2026-06-16",
    "Duration Sec": 52,
    "Day of Week": "Tuesday",
    "Post Time": "21:30",
    "Video Title": "This Family Found A Sealed Room",
    "Title Length": 31,
    "Title Has Emoji": "FALSE",
    "Title Has Hashtags": "FALSE",
    "Hashtags Used": "#shorts #scary #horror",
    "Category": "Horror",
    "Full Transcript": "Did you know that in 1973, a family bought their dream home and found one bedroom sealed from the inside?",
    "Word Count": 108,
    "Sentence Count": 7,
    "Words Per Second": 2.08,
    "Hook First Sentence": "Did you know that in 1973, a family bought their dream home?",
    "Hook Type": "Question with time reference",
    "Hook Emotional Trigger": "Curiosity",
    "Hook Speed Sec": 4.5,
    "Opening 5 Words": "Did you know that in",
    "Body Sentence Count": 4,
    "Twist Present": "TRUE",
    "Twist Line": "Then they found scratches on the inside of the wall.",
    "Ending Type": "Open ended",
    "Last Sentence": "And the house is still for sale.",
    "Tense Used": "Past",
    "POV Person": "Narrator",
    "Rhetorical Questions Count": 1,
    "Power Words": "sealed, scratched, vanished",
    "Emphasis Words": "sealed room, 40 years, still for sale",
    "Narrative Technique": "Escalating reveal",
    "Emotional Arc": "curiosity -> unease -> dread -> shock",
    "Numbers Stats Present": "TRUE",
    "Direct Address Present": "FALSE",
    "Banned Phrases Found": "none",
    "Avg Sentence Length": 15.4,
    "Shortest Sentence": "Nobody opened it.",
    "Longest Sentence": "The family later learned the room had been sealed for almost forty years.",
    "Short Long Ratio": "3:4",
    "Sentence Length Pattern": "Long setup, short punch lines",
    "Info Density": "Medium",
    "Surprise Twist Count": 2,
    "CTA Present": "FALSE",
    "CTA Placement": "none",
    "Repetition Callback": "sealed room repeated at ending",
    "Sensory Language Used": "scratching sound, cold hallway, dust on the bed",
    "Voice Gender": "Male",
    "Voice Tone": "Deep, serious",
    "Speaking Speed": "Slow",
    "Pause After Hook Ms": 600,
    "Pause Before Reveal Ms": 800,
    "Other Notable Pauses": "Short pause after the twist line",
    "Words Spoken Louder Slower": "sealed, scratched",
    "Layout Type": "Full image",
    "Face Visible": "FALSE",
    "Image Count": 5,
    "Image Change Timing": "Every 8-12 sec",
    "Transition Type": "Dissolve",
    "Image Style": "Dark realistic",
    "Ken Burns Effect": "TRUE",
    "Images Match Words": "Mostly yes",
    "Gameplay Type": "none",
    "Gameplay Position": "none",
    "Color Grading": "Cold desaturated",
    "Text Overlays": "none",
    "Caption Style": "Word at a time",
    "Caption Font": "Montserrat Black",
    "Caption Primary Color": "White",
    "Caption Highlight Color": "Red",
    "Caption Position": "Center",
    "Caption Border Glow": "Black border, red glow",
    "Words Per Caption Pop": "2-3",
    "Background Music Present": "TRUE",
    "Music Mood": "Eerie",
    "Music Volume Level": "Low",
    "Music Fades": "TRUE",
    "Music Changes Mid Video": "FALSE",
    "Sound Effects Present": "TRUE",
    "SFX At Hook": "Low bass hit",
    "SFX At Reveal": "Sharp stinger",
    "SFX At Ending": "Deep drone",
    "Other SFX Notes": "Faint scratching sound near reveal",
    "Audio Clarity": "Clear",
    "Like View Ratio": 4.36,
    "Comment View Ratio": 0.05,
    "Estimated Save Share Level": "High",
    "Why Would Someone Share": "The twist makes people tag friends.",
    "Rewatch Value": "Medium",
    "Controversy Debate Potential": "Low",
    "Trend Alignment": "Evergreen",
    "First Frame Scroll Stop": "TRUE",
    "First Frame Motion": "TRUE",
    "Would You Stop Scrolling": "TRUE",
    "Top Comment Theme": "People sharing similar stories",
    "Comment Sentiment": "Scared but engaged",
    "Comments Add Stories": "TRUE",
    "Creator Replies In Comments": "TRUE",
    "Likely Share Trigger": "The ending twist",
    "Retention Hook": "Each sentence reveals a new detail.",
    "Where Would You Stop Watching": "Nowhere",
    "Thumbnail Style": "Dark atmospheric frame",
    "Thumbnail Text": "SEALED ROOM",
    "Thumbnail Colors": "Dark blue and red",
    "Score Hook": 9,
    "Score Script": 9,
    "Score Pacing": 9,
    "Score Visual": 8,
    "Score Audio": 8,
    "Score Shareability": 9,
    "Score Overall": 9,
    "Why It Worked": "The video uses a fast hook, concrete details, and a strong open ending.",
    "What To Improve": "Start the first visual with the sealed door instead of the house exterior.",
    "Usable As Few Shot Example": "TRUE",
    "Additional Notes": "Good template for realistic discovery horror.",
    "Processed Time": "",
    "Automation Confidence": "",
}


BDA_COLUMN_MEANINGS = {
    "Video URL": "The exact Shorts link for the video being analyzed.",
    "Genre": "The broad genre label the researcher sees, such as horror, history, mystery, science, or Reddit story.",
    "Sub Genre": "A narrower topic inside the genre, such as haunted hospital, ship mystery, betrayal story, or psychology fact.",
    "Channel Name": "The creator or channel handle that posted the Short.",
    "Channel Subscribers": "The subscriber count visible when the researcher watched the video.",
    "Views": "The visible view count when the researcher recorded the row.",
    "Likes": "The visible like count when available.",
    "Comments": "The visible comment count when available.",
    "Upload Date": "The date the Short was uploaded.",
    "Duration Sec": "Total video duration in seconds.",
    "Day of Week": "The weekday of upload if visible or calculated from the upload date.",
    "Post Time": "The upload time if visible or known.",
    "Video Title": "The exact title shown on YouTube.",
    "Title Length": "Number of characters in the video title.",
    "Title Has Emoji": "Whether the title contains any emoji.",
    "Title Has Hashtags": "Whether hashtags appear in the title itself.",
    "Hashtags Used": "Hashtags found in the title or description.",
    "Category": "The content category or bucket used by the researcher.",
    "Full Transcript": "The full spoken script, written as accurately as possible.",
    "Word Count": "Total number of words in the transcript.",
    "Sentence Count": "Total number of sentences in the transcript.",
    "Words Per Second": "Script pacing: word count divided by duration seconds.",
    "Hook First Sentence": "The first sentence spoken in the video.",
    "Hook Type": "The style of the opening hook, described in normal words.",
    "Hook Emotional Trigger": "The emotion the hook creates in the viewer.",
    "Hook Speed Sec": "How many seconds it takes for the viewer to understand the promise of the video.",
    "Opening 5 Words": "The first five spoken words.",
    "Body Sentence Count": "Number of middle sentences after the hook and before the ending.",
    "Twist Present": "Whether the video has a twist, reveal, reversal, or unexpected fact.",
    "Twist Line": "The exact line where the twist or reveal happens.",
    "Ending Type": "How the video ends, such as question, warning, lesson, cliffhanger, or shocking fact.",
    "Last Sentence": "The final sentence spoken in the video.",
    "Tense Used": "Main tense of the narration: past, present, or mixed.",
    "POV Person": "Point of view used by the narration.",
    "Rhetorical Questions Count": "Number of questions asked for effect, not because the creator expects an answer.",
    "Power Words": "Strong words that make the story feel urgent, scary, emotional, or surprising.",
    "Emphasis Words": "Words that are emphasized by voice, captions, timing, or repetition.",
    "Narrative Technique": "The storytelling method used to keep attention.",
    "Emotional Arc": "How the viewer's emotion changes from start to end.",
    "Numbers Stats Present": "Whether the script uses numbers, dates, money, percentages, or statistics.",
    "Direct Address Present": "Whether the script talks directly to the viewer using words like you or your.",
    "Banned Phrases Found": "Any weak, repeated, misleading, or unwanted phrases noticed in the script.",
    "Avg Sentence Length": "Average number of words per sentence.",
    "Shortest Sentence": "The shortest sentence in the transcript.",
    "Longest Sentence": "The longest sentence in the transcript.",
    "Short Long Ratio": "A simple summary of how many short sentences versus long sentences the script uses.",
    "Sentence Length Pattern": "The rhythm of sentence lengths across the script.",
    "Info Density": "How much useful information is packed into each sentence.",
    "Surprise Twist Count": "Number of separate surprise or reveal moments.",
    "CTA Present": "Whether the creator asks viewers to like, comment, follow, subscribe, save, or share.",
    "CTA Placement": "Where the call to action appears.",
    "Repetition Callback": "A word, phrase, or idea that returns later for payoff.",
    "Sensory Language Used": "Details that describe what the viewer can see, hear, feel, or imagine.",
    "Voice Gender": "Perceived voice type if obvious.",
    "Voice Tone": "The emotional quality of the voice.",
    "Speaking Speed": "Whether the narration feels slow, medium, fast, or very fast.",
    "Pause After Hook Ms": "Approximate pause after the hook in milliseconds.",
    "Pause Before Reveal Ms": "Approximate pause before the twist or reveal in milliseconds.",
    "Other Notable Pauses": "Other pauses that affect tension or clarity.",
    "Words Spoken Louder Slower": "Words that are spoken with stronger or slower emphasis.",
    "Layout Type": "How the video is visually arranged on screen.",
    "Face Visible": "Whether a person's face is visible.",
    "Image Count": "Number of images, clips, or major visual scenes used.",
    "Image Change Timing": "How often the visuals change.",
    "Transition Type": "How the video moves from one visual to the next.",
    "Image Style": "The overall style of the visuals.",
    "Ken Burns Effect": "Whether still images slowly zoom or pan.",
    "Images Match Words": "How well the visuals match what is being said.",
    "Gameplay Type": "Type of gameplay shown, if any.",
    "Gameplay Position": "Where gameplay appears on the screen.",
    "Color Grading": "The color mood or treatment of the visuals.",
    "Text Overlays": "Any non-caption text shown on screen.",
    "Caption Style": "How the spoken words are displayed as captions.",
    "Caption Font": "The caption font or closest visible style.",
    "Caption Primary Color": "Main caption color.",
    "Caption Highlight Color": "Color used for emphasized caption words.",
    "Caption Position": "Where captions appear on screen.",
    "Caption Border Glow": "Caption outline, shadow, border, or glow style.",
    "Words Per Caption Pop": "How many words appear at once in the caption animation.",
    "Background Music Present": "Whether music plays behind the voice.",
    "Music Mood": "The mood created by the music.",
    "Music Volume Level": "How loud the music is compared to the voice.",
    "Music Fades": "Whether the music fades in or out.",
    "Music Changes Mid Video": "Whether the music changes during the Short.",
    "Sound Effects Present": "Whether sound effects are used.",
    "SFX At Hook": "Sound effect used at the opening hook.",
    "SFX At Reveal": "Sound effect used at the twist or reveal.",
    "SFX At Ending": "Sound effect used near the ending.",
    "Other SFX Notes": "Any other important sound effect observations.",
    "Audio Clarity": "How clear and understandable the audio is.",
    "Like View Ratio": "Likes compared with views, usually likes divided by views as a percent.",
    "Comment View Ratio": "Comments compared with views, usually comments divided by views as a percent.",
    "Estimated Save Share Level": "Researcher's estimate of how likely people are to save or share.",
    "Why Would Someone Share": "The human reason a viewer might share or tag someone.",
    "Rewatch Value": "How likely viewers are to watch again.",
    "Controversy Debate Potential": "Whether the topic can trigger debate or disagreement.",
    "Trend Alignment": "Whether the video fits a current trend, evergreen trend, or neither.",
    "First Frame Scroll Stop": "Whether the first frame is strong enough to stop a viewer from scrolling.",
    "First Frame Motion": "Whether something moves immediately in the first frame.",
    "Would You Stop Scrolling": "The researcher's honest judgment on whether they would stop for this video.",
    "Top Comment Theme": "The main pattern or topic in the top comments.",
    "Comment Sentiment": "Overall mood of comments.",
    "Comments Add Stories": "Whether viewers add their own stories or examples in comments.",
    "Creator Replies In Comments": "Whether the creator replies to comments.",
    "Likely Share Trigger": "The exact thing most likely to make viewers share.",
    "Retention Hook": "The open question or promise that keeps people watching.",
    "Where Would You Stop Watching": "The point where the researcher thinks viewers may drop off.",
    "Thumbnail Style": "The style of the cover frame or thumbnail.",
    "Thumbnail Text": "Text visible on the thumbnail or cover frame.",
    "Thumbnail Colors": "Dominant colors in the thumbnail or cover frame.",
    "Score Hook": "Researcher's 0 to 10 score for the hook.",
    "Score Script": "Researcher's 0 to 10 score for the script.",
    "Score Pacing": "Researcher's 0 to 10 score for pacing.",
    "Score Visual": "Researcher's 0 to 10 score for visuals.",
    "Score Audio": "Researcher's 0 to 10 score for audio.",
    "Score Shareability": "Researcher's 0 to 10 score for shareability.",
    "Score Overall": "Overall 0 to 10 score for the Short.",
    "Why It Worked": "Plain-English explanation of why the video performed or felt strong.",
    "What To Improve": "Specific changes that could make the video better.",
    "Usable As Few Shot Example": "Whether this video is good enough for the AI to imitate later.",
    "Additional Notes": "Anything useful that does not fit another column.",
    "Processed Time": "Timestamp if a tool processed the row later. Human researcher can leave blank.",
    "Automation Confidence": "Confidence score if automation extracts fields later. Human researcher can leave blank.",
}


def _bda_video_example_row() -> list[Any]:
    return [BDA_VIDEO_EXAMPLES.get(header, "") for header in BDA_VIDEO_ANALYSIS_HEADERS]


def _bda_column_meaning_rows() -> list[list[Any]]:
    rows = [["column", "what_it_means", "example", "how_to_fill", "data_type"]]
    for header in BDA_VIDEO_ANALYSIS_HEADERS:
        rows.append(
            [
                header,
                BDA_COLUMN_MEANINGS.get(header, f"Observed value for {header}."),
                BDA_VIDEO_EXAMPLES.get(header, ""),
                _bda_how_to_fill(header),
                _bda_data_type(header),
            ]
        )
    return rows


def _bda_how_to_fill(header: str) -> str:
    if header in {"Video URL", "Channel Name", "Video Title", "Full Transcript", "Hook First Sentence", "Twist Line", "Last Sentence"}:
        return "Copy this from the video as accurately as possible."
    if header in {"Views", "Likes", "Comments", "Channel Subscribers", "Duration Sec", "Word Count", "Sentence Count", "Image Count"}:
        return "Enter numbers only. Leave blank if unavailable."
    if header.startswith("Score "):
        return "Enter a score from 0 to 10."
    if header.endswith("Present") or header.startswith("Title Has") or header in {
        "Twist Present",
        "Face Visible",
        "Ken Burns Effect",
        "Background Music Present",
        "Music Fades",
        "Music Changes Mid Video",
        "Sound Effects Present",
        "First Frame Scroll Stop",
        "First Frame Motion",
        "Would You Stop Scrolling",
        "Comments Add Stories",
        "Creator Replies In Comments",
        "Usable As Few Shot Example",
    }:
        return "Use TRUE or FALSE."
    if header == "Upload Date":
        return "Use YYYY-MM-DD if possible."
    if header in {"Post Time"}:
        return "Use HH:MM if known; otherwise leave blank."
    if "Ratio" in header or "Speed Sec" in header or header.endswith("Ms") or header == "Automation Confidence":
        return "Enter a numeric value only."
    return "Write a short human observation from watching the video."


def _bda_data_type(header: str) -> str:
    if header == "Upload Date":
        return "date"
    if header == "Post Time":
        return "time"
    if header in {"Video URL"}:
        return "url"
    if header in {"Views", "Likes", "Comments", "Channel Subscribers", "Duration Sec", "Word Count", "Sentence Count", "Image Count", "Title Length", "Body Sentence Count", "Rhetorical Questions Count", "Surprise Twist Count"} or header.startswith("Score "):
        return "integer"
    if "Ratio" in header or "Speed Sec" in header or "Words Per Second" == header or header.endswith("Ms") or header == "Automation Confidence" or header == "Avg Sentence Length":
        return "decimal"
    if header.endswith("Present") or header.startswith("Title Has") or header in {
        "Twist Present",
        "Face Visible",
        "Ken Burns Effect",
        "Background Music Present",
        "Music Fades",
        "Music Changes Mid Video",
        "Sound Effects Present",
        "First Frame Scroll Stop",
        "First Frame Motion",
        "Would You Stop Scrolling",
        "Comments Add Stories",
        "Creator Replies In Comments",
        "Usable As Few Shot Example",
    }:
        return "boolean"
    return "text"


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage genre knowledge Excel templates and DB imports.")
    sub = parser.add_subparsers(dest="command", required=True)

    template = sub.add_parser("template", help="Create a fillable XLSX template.")
    template.add_argument("--output", default=str(TEMPLATE_PATH))

    examples = sub.add_parser("examples", help="Create a prefilled real-world seed XLSX.")
    examples.add_argument("--output", default=str(REAL_WORLD_SEED_PATH))

    single = sub.add_parser("single-sheet", help="Create one wide data-entry sheet for future scraping.")
    single.add_argument("--output", default=str(SINGLE_ENTRY_PATH))

    backup = sub.add_parser("backup", help="Back up database tables to JSON.")
    backup.add_argument("--output", default="")

    export = sub.add_parser("export", help="Export current normalized knowledge tables to XLSX.")
    export.add_argument("--output", default=str(OUTPUT_DIR / "Genre_Knowledge_DB_Export.xlsx"))

    reset = sub.add_parser("reset", help="Clear normalized genre knowledge tables.")
    reset.add_argument("--backup", action="store_true")

    import_cmd = sub.add_parser("import", help="Import a filled XLSX workbook.")
    import_cmd.add_argument("xlsx_path")
    import_cmd.add_argument("--backup", action="store_true")
    import_cmd.add_argument("--reset", action="store_true")

    args = parser.parse_args()
    if args.command == "template":
        create_template(Path(args.output))
    elif args.command == "examples":
        create_template(Path(args.output))
    elif args.command == "single-sheet":
        create_single_entry_workbook(Path(args.output))
    elif args.command == "backup":
        print(backup_database(Path(args.output) if args.output else None))
    elif args.command == "export":
        init_database()
        print(export_knowledge_workbook(Path(args.output)))
    elif args.command == "reset":
        init_database()
        if args.backup:
            print(backup_database())
        reset_knowledge_tables()
    elif args.command == "import":
        init_database()
        if args.backup:
            print(backup_database())
        if args.reset:
            reset_knowledge_tables()
        import_workbook(Path(args.xlsx_path))


def create_template(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows_by_sheet = {name: [headers] + DEFAULT_ROWS.get(name, []) for name, headers in SHEETS.items()}
    rows_by_sheet["00_Column_Explanations"] = [SHEETS["00_Column_Explanations"]] + _column_explanation_rows()
    rows_by_sheet["09_Field_Rules"] = [SHEETS["09_Field_Rules"]] + _field_rule_rows()
    _write_xlsx(path, rows_by_sheet)
    print(path)


def _column_explanation_rows() -> list[list[str]]:
    rules_by_field = {(rule.sheet, rule.field): rule for rule in FIELD_RULES}
    rows: list[list[str]] = []
    for sheet, columns in SHEETS.items():
        for column in columns:
            meaning, how_to_fill = COLUMN_MEANINGS.get(sheet, {}).get(
                column,
                ("Workbook field used by the importer.", "Fill according to 09_Field_Rules."),
            )
            rule = rules_by_field.get((sheet, column))
            rows.append(
                [
                    sheet,
                    column,
                    meaning,
                    how_to_fill,
                    rule.required if rule else "NO",
                    rule.data_type if rule else "text",
                    rule.max_length if rule else "",
                    rule.example if rule else "",
                ]
            )
    return rows


def create_single_entry_workbook(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows_by_sheet = {
        "Video_Analysis": [BDA_VIDEO_ANALYSIS_HEADERS, _bda_video_example_row()],
        "Column_Meanings": _bda_column_meaning_rows(),
    }
    _write_xlsx(path, rows_by_sheet)
    print(path)


def export_knowledge_workbook(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    try:
        rows_by_sheet: dict[str, list[list[Any]]] = {
            "README": [SHEETS["README"]] + DEFAULT_ROWS["README"],
            "00_Column_Explanations": [SHEETS["00_Column_Explanations"]] + _column_explanation_rows(),
            "01_Genres": [SHEETS["01_Genres"]] + [
                [
                    genre.id,
                    genre.display_name,
                    genre.category,
                    genre.tone,
                    genre.audience_size,
                    genre.competition_level,
                    genre.content_difficulty,
                    genre.recommended_score,
                    genre.default_duration_sec,
                    genre.word_count_min,
                    genre.word_count_max,
                    genre.layout,
                    genre.caption_preset,
                    genre.voice_rate,
                    genre.music_mood,
                    genre.realism_mode,
                    "TRUE" if genre.is_active else "FALSE",
                    genre.notes,
                ]
                for genre in db.query(Genre).order_by(Genre.id)
            ],
            "02_Genre_Rules": [SHEETS["02_Genre_Rules"]] + [
                [rule.genre_id, rule.rule_type, rule.value, rule.weight, rule.notes]
                for rule in db.query(GenreRule).order_by(GenreRule.genre_id, GenreRule.rule_type, GenreRule.value)
            ],
            "03_Genre_Hooks": [SHEETS["03_Genre_Hooks"]] + [
                [hook.genre_id, hook.hook_type, hook.template, hook.emotional_trigger, hook.avg_score, hook.notes]
                for hook in db.query(GenreHook).order_by(GenreHook.genre_id, GenreHook.id)
            ],
            "04_Reference_Videos": [SHEETS["04_Reference_Videos"]] + [
                [
                    ref.genre_id,
                    ref.video_url,
                    ref.channel_name,
                    ref.channel_subscribers,
                    ref.views,
                    ref.likes,
                    ref.comments,
                    ref.upload_date.isoformat() if ref.upload_date else "",
                    ref.duration_sec,
                    ref.title,
                    ref.description_first_line,
                    ref.hashtags,
                    ref.full_script,
                    ref.word_count,
                    ref.sentence_count,
                    ref.words_per_second,
                    ref.overall_score,
                    "TRUE" if ref.usable_as_few_shot else "FALSE",
                    ref.notes,
                ]
                for ref in db.query(ReferenceVideo).order_by(ReferenceVideo.genre_id, ReferenceVideo.id)
            ],
            "05_Script_Analysis": [SHEETS["05_Script_Analysis"]] + [
                [
                    analysis.reference_video.video_url if analysis.reference_video else "",
                    analysis.hook_first_sentence,
                    analysis.hook_type,
                    analysis.hook_emotional_trigger,
                    analysis.hook_speed_sec,
                    analysis.opening_words,
                    analysis.body_sentence_count,
                    "TRUE" if analysis.has_twist_reveal else "FALSE",
                    analysis.twist_line,
                    analysis.ending_type,
                    analysis.last_sentence,
                    analysis.tense_used,
                    analysis.pov_person,
                    analysis.narrative_technique,
                    analysis.emotional_arc,
                    analysis.power_words,
                    analysis.emphasis_words,
                    analysis.sensory_language_used,
                    analysis.retention_hook,
                    analysis.likely_share_trigger,
                    analysis.why_it_worked,
                    analysis.what_to_improve,
                ]
                for analysis in db.query(ScriptAnalysis).join(ReferenceVideo).order_by(ReferenceVideo.genre_id, ScriptAnalysis.id)
            ],
            "06_Visual_Style_Rules": [SHEETS["06_Visual_Style_Rules"]] + [
                [
                    visual.genre_id,
                    visual.layout_type,
                    visual.image_or_video_count,
                    visual.image_change_timing,
                    visual.transition_type,
                    visual.image_style,
                    visual.visual_keywords,
                    visual.negative_visual_keywords,
                    visual.caption_style,
                    visual.caption_font,
                    visual.caption_primary_color,
                    visual.caption_highlight_color,
                    visual.caption_position,
                    visual.music_mood,
                    visual.sfx_rules,
                    visual.source_policy,
                ]
                for visual in db.query(VisualStyleRule).order_by(VisualStyleRule.genre_id)
            ],
            "07_Topic_Expansion_Rules": [SHEETS["07_Topic_Expansion_Rules"]] + [
                [
                    rule.genre_id,
                    rule.trigger_term,
                    rule.search_queries,
                    rule.required_words,
                    rule.forbidden_words,
                    rule.realism_mode,
                    rule.notes,
                ]
                for rule in db.query(TopicExpansionRule).order_by(TopicExpansionRule.genre_id, TopicExpansionRule.trigger_term)
            ],
            "08_Topic_Research_Sources": [SHEETS["08_Topic_Research_Sources"]] + [
                [
                    source.topic,
                    source.genre_id,
                    source.title,
                    source.url,
                    source.source_type,
                    source.snippet,
                    source.extracted_facts,
                    source.credibility_score,
                    source.relevance_score,
                ]
                for source in db.query(TopicResearchSource).order_by(TopicResearchSource.genre_id, TopicResearchSource.topic, TopicResearchSource.id)
            ],
            "09_Field_Rules": [SHEETS["09_Field_Rules"]] + _field_rule_rows(),
            "10_Playground_Test_Topics": [SHEETS["10_Playground_Test_Topics"]] + DEFAULT_ROWS["10_Playground_Test_Topics"],
        }
    finally:
        db.close()
    _write_xlsx(path, rows_by_sheet)
    return path


def _field_rule_rows() -> list[list[str]]:
    return [
        [
            rule.sheet,
            rule.field,
            rule.required,
            rule.data_type,
            rule.max_length,
            rule.allowed_values,
            rule.example,
            rule.notes,
        ]
        for rule in FIELD_RULES
    ]


def backup_database(output: Path | None = None) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if output is None:
        output = BACKUP_DIR / f"database_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    inspector = inspect(engine)
    backup: dict[str, Any] = {"created_at": datetime.utcnow().isoformat() + "Z", "tables": {}}
    with engine.connect() as conn:
        for table_name in inspector.get_table_names():
            rows = [dict(row._mapping) for row in conn.execute(text(f'SELECT * FROM "{table_name}"'))]
            backup["tables"][table_name] = _json_safe(rows)
    output.write_text(json.dumps(backup, indent=2, ensure_ascii=False), encoding="utf-8")
    return output


def reset_knowledge_tables() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        for model in KNOWLEDGE_MODELS:
            db.query(model).delete()
        db.commit()
    finally:
        db.close()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS knowledge_records"))
    print("Cleared normalized genre knowledge tables and dropped legacy knowledge_records if present.")


def import_workbook(path: Path) -> dict[str, int]:
    workbook = _read_xlsx(path)
    db = SessionLocal()
    errors: list[str] = []
    counts: dict[str, int] = {}
    try:
        counts["genres"] = _import_genres(db, workbook.get("01_Genres", []), errors)
        db.flush()
        counts["genre_rules"] = _import_genre_rules(db, workbook.get("02_Genre_Rules", []), errors)
        counts["genre_hooks"] = _import_genre_hooks(db, workbook.get("03_Genre_Hooks", []), errors)
        counts["reference_videos"] = _import_reference_videos(db, workbook.get("04_Reference_Videos", []), errors)
        db.flush()
        counts["script_analysis"] = _import_script_analysis(db, workbook.get("05_Script_Analysis", []), errors)
        counts["visual_style_rules"] = _import_visual_style_rules(db, workbook.get("06_Visual_Style_Rules", []), errors)
        counts["topic_expansion_rules"] = _import_topic_expansion_rules(db, workbook.get("07_Topic_Expansion_Rules", []), errors)
        counts["topic_research_sources"] = _import_topic_research_sources(db, workbook.get("08_Topic_Research_Sources", []), errors)
        db.add(KnowledgeImportBatch(source_file=str(path), row_counts=counts, errors=errors))
        if errors:
            db.rollback()
            raise ValueError("Import failed:\n" + "\n".join(errors[:50]))
        db.commit()
    finally:
        db.close()
    print(json.dumps(counts, indent=2))
    return counts


def _import_genres(db, rows: list[dict[str, str]], errors: list[str]) -> int:
    count = 0
    for row_num, row in enumerate(rows, start=2):
        genre_id = _text(row.get("id"), 80)
        if not genre_id:
            continue
        _require_pattern("01_Genres", row_num, "id", genre_id, errors, allowed_chars=True)
        genre = db.get(Genre, genre_id) or Genre(id=genre_id, display_name="")
        genre.display_name = _required_text("01_Genres", row_num, "display_name", row.get("display_name"), 120, errors)
        genre.category = _text(row.get("category"), 80)
        genre.tone = _text(row.get("tone"))
        genre.audience_size = _text(row.get("audience_size"), 40)
        genre.competition_level = _text(row.get("competition_level"), 40)
        genre.content_difficulty = _text(row.get("content_difficulty"), 40)
        genre.recommended_score = _int(row.get("recommended_score"), 0, "01_Genres", row_num, "recommended_score", errors)
        genre.default_duration_sec = _int(row.get("default_duration_sec"), 45, "01_Genres", row_num, "default_duration_sec", errors)
        genre.word_count_min = _int(row.get("word_count_min"), 80, "01_Genres", row_num, "word_count_min", errors)
        genre.word_count_max = _int(row.get("word_count_max"), 130, "01_Genres", row_num, "word_count_max", errors)
        if genre.word_count_max < genre.word_count_min:
            errors.append(f"01_Genres row {row_num}: word_count_max must be >= word_count_min.")
        genre.layout = _text(row.get("layout"), 80)
        genre.caption_preset = _text(row.get("caption_preset"), 80)
        genre.voice_rate = _float(row.get("voice_rate"), 1.0, "01_Genres", row_num, "voice_rate", errors)
        genre.music_mood = _text(row.get("music_mood"), 80)
        genre.realism_mode = _text(row.get("realism_mode"), 60) or "inspired_by_real_events"
        genre.is_active = _bool(row.get("is_active"), True)
        genre.notes = _text(row.get("notes"))
        db.merge(genre)
        count += 1
    return count


def _import_genre_rules(db, rows: list[dict[str, str]], errors: list[str]) -> int:
    count = 0
    for row_num, row in enumerate(rows, start=2):
        genre_id = _text(row.get("genre_id"), 80)
        value = _text(row.get("value"), 300)
        rule_type = _text(row.get("rule_type"), 60)
        if not any((genre_id, value, rule_type)):
            continue
        _require_genre(db, "02_Genre_Rules", row_num, genre_id, errors)
        if not value or not rule_type:
            errors.append(f"02_Genre_Rules row {row_num}: rule_type and value are required.")
            continue
        existing = db.query(GenreRule).filter_by(genre_id=genre_id, rule_type=rule_type, value=value).one_or_none()
        rule = existing or GenreRule(genre_id=genre_id, rule_type=rule_type, value=value)
        rule.weight = _int(row.get("weight"), 0, "02_Genre_Rules", row_num, "weight", errors)
        rule.notes = _text(row.get("notes"))
        db.add(rule)
        count += 1
    return count


def _import_genre_hooks(db, rows: list[dict[str, str]], errors: list[str]) -> int:
    count = 0
    for row_num, row in enumerate(rows, start=2):
        genre_id = _text(row.get("genre_id"), 80)
        template = _text(row.get("template"), 500)
        if not any((genre_id, template)):
            continue
        _require_genre(db, "03_Genre_Hooks", row_num, genre_id, errors)
        if not template:
            errors.append(f"03_Genre_Hooks row {row_num}: template is required.")
            continue
        hook = GenreHook(
            genre_id=genre_id,
            hook_type=_text(row.get("hook_type"), 80),
            template=template,
            emotional_trigger=_text(row.get("emotional_trigger"), 80),
            avg_score=_float(row.get("avg_score"), 0.0, "03_Genre_Hooks", row_num, "avg_score", errors),
            notes=_text(row.get("notes")),
        )
        db.add(hook)
        count += 1
    return count


def _import_reference_videos(db, rows: list[dict[str, str]], errors: list[str]) -> int:
    count = 0
    for row_num, row in enumerate(rows, start=2):
        genre_id = _text(row.get("genre_id"), 80)
        url = _text(row.get("video_url"), 500)
        if not any((genre_id, url, row.get("full_script"))):
            continue
        _require_genre(db, "04_Reference_Videos", row_num, genre_id, errors)
        if not url:
            errors.append(f"04_Reference_Videos row {row_num}: video_url is required.")
            continue
        ref = db.query(ReferenceVideo).filter_by(video_url=url).one_or_none() or ReferenceVideo(genre_id=genre_id, video_url=url)
        ref.genre_id = genre_id
        ref.channel_name = _text(row.get("channel_name"), 120)
        ref.channel_subscribers = _int(row.get("channel_subscribers"), 0, "04_Reference_Videos", row_num, "channel_subscribers", errors)
        ref.views = _int(row.get("views"), 0, "04_Reference_Videos", row_num, "views", errors)
        ref.likes = _int(row.get("likes"), 0, "04_Reference_Videos", row_num, "likes", errors)
        ref.comments = _int(row.get("comments"), 0, "04_Reference_Videos", row_num, "comments", errors)
        ref.upload_date = _date(row.get("upload_date"), "04_Reference_Videos", row_num, "upload_date", errors)
        ref.duration_sec = _int(row.get("duration_sec"), 0, "04_Reference_Videos", row_num, "duration_sec", errors)
        ref.title = _text(row.get("title"), 160)
        ref.description_first_line = _text(row.get("description_first_line"), 300)
        ref.hashtags = _text(row.get("hashtags"), 500)
        ref.full_script = _required_text("04_Reference_Videos", row_num, "full_script", row.get("full_script"), None, errors)
        ref.word_count = _int(row.get("word_count"), len(ref.full_script.split()), "04_Reference_Videos", row_num, "word_count", errors)
        ref.sentence_count = _int(row.get("sentence_count"), 0, "04_Reference_Videos", row_num, "sentence_count", errors)
        ref.words_per_second = _float(row.get("words_per_second"), 0.0, "04_Reference_Videos", row_num, "words_per_second", errors)
        ref.overall_score = _float(row.get("overall_score"), 0.0, "04_Reference_Videos", row_num, "overall_score", errors)
        ref.usable_as_few_shot = _bool(row.get("usable_as_few_shot"), False)
        ref.notes = _text(row.get("notes"))
        db.add(ref)
        count += 1
    db.flush()
    return count


def _import_script_analysis(db, rows: list[dict[str, str]], errors: list[str]) -> int:
    count = 0
    for row_num, row in enumerate(rows, start=2):
        url = _text(row.get("video_url"), 500)
        if not any(row.values()):
            continue
        ref = db.query(ReferenceVideo).filter_by(video_url=url).one_or_none()
        if not ref:
            errors.append(f"05_Script_Analysis row {row_num}: video_url must match 04_Reference_Videos.video_url.")
            continue
        analysis = db.query(ScriptAnalysis).filter_by(reference_video_id=ref.id).one_or_none() or ScriptAnalysis(reference_video_id=ref.id)
        for field, limit in (
            ("hook_first_sentence", 500),
            ("hook_type", 80),
            ("hook_emotional_trigger", 80),
            ("opening_words", 200),
            ("twist_line", 700),
            ("ending_type", 80),
            ("last_sentence", 500),
            ("tense_used", 60),
            ("pov_person", 60),
            ("narrative_technique", 120),
            ("emotional_arc", 300),
            ("power_words", 700),
            ("emphasis_words", 700),
            ("retention_hook", 500),
            ("likely_share_trigger", 500),
        ):
            setattr(analysis, field, _text(row.get(field), limit))
        analysis.hook_speed_sec = _float(row.get("hook_speed_sec"), 0.0, "05_Script_Analysis", row_num, "hook_speed_sec", errors)
        analysis.body_sentence_count = _int(row.get("body_sentence_count"), 0, "05_Script_Analysis", row_num, "body_sentence_count", errors)
        analysis.has_twist_reveal = _bool(row.get("has_twist_reveal"), False)
        analysis.sensory_language_used = _text(row.get("sensory_language_used"))
        analysis.why_it_worked = _required_text("05_Script_Analysis", row_num, "why_it_worked", row.get("why_it_worked"), None, errors)
        analysis.what_to_improve = _text(row.get("what_to_improve"))
        db.add(analysis)
        count += 1
    return count


def _import_visual_style_rules(db, rows: list[dict[str, str]], errors: list[str]) -> int:
    count = 0
    for row_num, row in enumerate(rows, start=2):
        genre_id = _text(row.get("genre_id"), 80)
        if not genre_id:
            continue
        _require_genre(db, "06_Visual_Style_Rules", row_num, genre_id, errors)
        visual = db.query(VisualStyleRule).filter_by(genre_id=genre_id).one_or_none() or VisualStyleRule(genre_id=genre_id)
        visual.layout_type = _text(row.get("layout_type"), 80)
        visual.image_or_video_count = _int(row.get("image_or_video_count"), 0, "06_Visual_Style_Rules", row_num, "image_or_video_count", errors)
        visual.image_change_timing = _text(row.get("image_change_timing"), 120)
        visual.transition_type = _text(row.get("transition_type"), 80)
        visual.image_style = _text(row.get("image_style"), 160)
        visual.visual_keywords = _text(row.get("visual_keywords"))
        visual.negative_visual_keywords = _text(row.get("negative_visual_keywords"))
        visual.caption_style = _text(row.get("caption_style"), 120)
        visual.caption_font = _text(row.get("caption_font"), 120)
        visual.caption_primary_color = _text(row.get("caption_primary_color"), 80)
        visual.caption_highlight_color = _text(row.get("caption_highlight_color"), 80)
        visual.caption_position = _text(row.get("caption_position"), 80)
        visual.music_mood = _text(row.get("music_mood"), 80)
        visual.sfx_rules = _text(row.get("sfx_rules"))
        visual.source_policy = _text(row.get("source_policy"), 80) or "stock_video_first"
        db.add(visual)
        count += 1
    return count


def _import_topic_expansion_rules(db, rows: list[dict[str, str]], errors: list[str]) -> int:
    count = 0
    for row_num, row in enumerate(rows, start=2):
        genre_id = _text(row.get("genre_id"), 80)
        trigger = _text(row.get("trigger_term"), 120)
        if not any((genre_id, trigger)):
            continue
        _require_genre(db, "07_Topic_Expansion_Rules", row_num, genre_id, errors)
        if not trigger:
            errors.append(f"07_Topic_Expansion_Rules row {row_num}: trigger_term is required.")
            continue
        rule = db.query(TopicExpansionRule).filter_by(genre_id=genre_id, trigger_term=trigger).one_or_none() or TopicExpansionRule(genre_id=genre_id, trigger_term=trigger, search_queries="")
        rule.search_queries = _required_text("07_Topic_Expansion_Rules", row_num, "search_queries", row.get("search_queries"), None, errors)
        rule.required_words = _text(row.get("required_words"), 700)
        rule.forbidden_words = _text(row.get("forbidden_words"), 700)
        rule.realism_mode = _text(row.get("realism_mode"), 60) or "inspired_by_real_events"
        rule.notes = _text(row.get("notes"))
        db.add(rule)
        count += 1
    return count


def _import_topic_research_sources(db, rows: list[dict[str, str]], errors: list[str]) -> int:
    count = 0
    for row_num, row in enumerate(rows, start=2):
        topic = _text(row.get("topic"), 300)
        genre_id = _text(row.get("genre_id"), 80)
        url = _text(row.get("url"), 700)
        if not any((topic, genre_id, url)):
            continue
        _require_genre(db, "08_Topic_Research_Sources", row_num, genre_id, errors)
        if not topic or not url:
            errors.append(f"08_Topic_Research_Sources row {row_num}: topic and url are required.")
            continue
        existing = (
            db.query(TopicResearchSource)
            .filter_by(topic=topic, genre_id=genre_id, url=url)
            .one_or_none()
        )
        source = existing or TopicResearchSource(topic=topic, genre_id=genre_id)
        source.title = _text(row.get("title"), 300)
        source.url = url
        source.source_type = _text(row.get("source_type"), 80)
        source.snippet = _text(row.get("snippet"))
        source.extracted_facts = _text(row.get("extracted_facts"))
        source.credibility_score = _float(row.get("credibility_score"), 0.0, "08_Topic_Research_Sources", row_num, "credibility_score", errors)
        source.relevance_score = _float(row.get("relevance_score"), 0.0, "08_Topic_Research_Sources", row_num, "relevance_score", errors)
        db.add(source)
        count += 1
    return count


def _require_genre(db, sheet: str, row_num: int, genre_id: str, errors: list[str]) -> None:
    if not genre_id:
        errors.append(f"{sheet} row {row_num}: genre_id is required.")
    elif db.get(Genre, genre_id) is None:
        errors.append(f"{sheet} row {row_num}: genre_id '{genre_id}' does not exist in 01_Genres.")


def _required_text(sheet: str, row_num: int, field: str, value: Any, limit: int | None, errors: list[str]) -> str:
    text_value = _text(value, limit)
    if not text_value:
        errors.append(f"{sheet} row {row_num}: {field} is required.")
    return text_value


def _require_pattern(sheet: str, row_num: int, field: str, value: str, errors: list[str], allowed_chars: bool = False) -> None:
    if allowed_chars and not value.replace("_", "").replace("-", "").isalnum():
        errors.append(f"{sheet} row {row_num}: {field} can only use letters, numbers, hyphen, and underscore.")


def _text(value: Any, limit: int | None = None) -> str:
    if value is None:
        return ""
    text_value = str(value).strip()
    if limit is not None:
        return text_value[:limit]
    return text_value


def _int(value: Any, fallback: int, sheet: str, row_num: int, field: str, errors: list[str]) -> int:
    if value in (None, ""):
        return fallback
    try:
        parsed = int(float(str(value).replace(",", "")))
    except ValueError:
        errors.append(f"{sheet} row {row_num}: {field} must be a number.")
        return fallback
    if parsed < 0 and field not in {"weight"}:
        errors.append(f"{sheet} row {row_num}: {field} cannot be negative.")
    return parsed


def _float(value: Any, fallback: float, sheet: str, row_num: int, field: str, errors: list[str]) -> float:
    if value in (None, ""):
        return fallback
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        errors.append(f"{sheet} row {row_num}: {field} must be a number.")
        return fallback


def _bool(value: Any, fallback: bool) -> bool:
    if value in (None, ""):
        return fallback
    return str(value).strip().lower() in {"true", "yes", "y", "1"}


def _date(value: Any, sheet: str, row_num: int, field: str, errors: list[str]) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        errors.append(f"{sheet} row {row_num}: {field} must be YYYY-MM-DD.")
        return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _write_xlsx(path: Path, sheets: dict[str, list[list[Any]]]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _content_types(len(sheets)))
        z.writestr("_rels/.rels", _root_rels())
        z.writestr("xl/workbook.xml", _workbook_xml(list(sheets)))
        z.writestr("xl/_rels/workbook.xml.rels", _workbook_rels(len(sheets)))
        z.writestr("xl/styles.xml", _styles_xml())
        for index, (name, rows) in enumerate(sheets.items(), start=1):
            z.writestr(f"xl/worksheets/sheet{index}.xml", _sheet_xml(rows))


def _sheet_xml(rows: list[list[Any]]) -> str:
    max_cols = max((len(row) for row in rows), default=1)
    cols = "".join(f'<col min="{i}" max="{i}" width="{40 if i > 2 else 24}" customWidth="1"/>' for i in range(1, max_cols + 1))
    body = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row, start=1):
            style = ' s="1"' if r == 1 else ""
            cells.append(f'<c r="{_col(c)}{r}" t="inlineStr"{style}><is><t>{escape(str(value))}</t></is></c>')
        body.append(f'<row r="{r}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<cols>{cols}</cols>"
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f'<sheetData>{"".join(body)}</sheetData>'
        "</worksheet>"
    )


def _content_types(sheet_count: int) -> str:
    sheets = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, sheet_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        f"{sheets}</Types>"
    )


def _root_rels() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )


def _workbook_xml(sheet_names: list[str]) -> str:
    sheets = "".join(
        f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
        for i, name in enumerate(sheet_names, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheets}</sheets></workbook>"
    )


def _workbook_rels(sheet_count: int) -> str:
    rels = "".join(
        f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, sheet_count + 1)
    )
    rels += f'<Relationship Id="rId{sheet_count + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{rels}</Relationships>"
    )


def _styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/><color rgb="FFFFFFFF"/></font></fonts>'
        '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/><bgColor indexed="64"/></patternFill></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>'
        "</styleSheet>"
    )


def _read_xlsx(path: Path) -> dict[str, list[dict[str, str]]]:
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as z:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        relmap = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
        result: dict[str, list[dict[str, str]]] = {}
        for sheet in wb.findall("a:sheets/a:sheet", ns):
            name = sheet.attrib["name"]
            rid = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
            target = relmap[rid]
            xml = ET.fromstring(z.read("xl/" + target))
            raw_rows: list[list[str]] = []
            for row in xml.findall(".//a:sheetData/a:row", ns):
                values: dict[int, str] = {}
                for cell in row.findall("a:c", ns):
                    ref = cell.attrib.get("r", "A1")
                    col = _col_index("".join(ch for ch in ref if ch.isalpha()))
                    value = ""
                    if cell.attrib.get("t") == "inlineStr":
                        value = "".join(t.text or "" for t in cell.findall(".//a:t", ns))
                    else:
                        node = cell.find("a:v", ns)
                        value = node.text if node is not None else ""
                    values[col] = value
                raw_rows.append([values.get(i, "") for i in range(1, max(values.keys(), default=0) + 1)])
            if not raw_rows:
                continue
            headers = [header.strip() for header in raw_rows[0]]
            records = []
            for row in raw_rows[1:]:
                record = {header: row[index].strip() if index < len(row) else "" for index, header in enumerate(headers)}
                if any(record.values()):
                    records.append(record)
            result[name] = records
        return result


def _col(index: int) -> str:
    letters = ""
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _col_index(col: str) -> int:
    value = 0
    for char in col:
        value = value * 26 + ord(char.upper()) - 64
    return value


if __name__ == "__main__":
    main()
