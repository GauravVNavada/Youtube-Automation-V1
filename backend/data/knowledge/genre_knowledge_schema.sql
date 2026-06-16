-- Normalized genre knowledge schema for AI Shorts generation.
-- The application creates these tables through SQLAlchemy models in app/models.py.

CREATE TABLE genres (
    id VARCHAR(80) PRIMARY KEY,
    display_name VARCHAR(120) NOT NULL,
    category VARCHAR(80) NOT NULL DEFAULT '',
    tone TEXT NOT NULL DEFAULT '',
    audience_size VARCHAR(40) NOT NULL DEFAULT '',
    competition_level VARCHAR(40) NOT NULL DEFAULT '',
    content_difficulty VARCHAR(40) NOT NULL DEFAULT '',
    recommended_score INTEGER NOT NULL DEFAULT 0,
    default_duration_sec INTEGER NOT NULL DEFAULT 45,
    word_count_min INTEGER NOT NULL DEFAULT 80,
    word_count_max INTEGER NOT NULL DEFAULT 130,
    layout VARCHAR(80) NOT NULL DEFAULT 'full_image',
    caption_preset VARCHAR(80) NOT NULL DEFAULT 'default',
    voice_rate FLOAT NOT NULL DEFAULT 1.0,
    music_mood VARCHAR(80) NOT NULL DEFAULT '',
    realism_mode VARCHAR(60) NOT NULL DEFAULT 'inspired_by_real_events',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE TABLE genre_rules (
    id INTEGER PRIMARY KEY,
    genre_id VARCHAR(80) NOT NULL REFERENCES genres(id),
    rule_type VARCHAR(60) NOT NULL,
    value VARCHAR(300) NOT NULL,
    weight INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    UNIQUE (genre_id, rule_type, value)
);

CREATE TABLE genre_hooks (
    id INTEGER PRIMARY KEY,
    genre_id VARCHAR(80) NOT NULL REFERENCES genres(id),
    hook_type VARCHAR(80) NOT NULL DEFAULT '',
    template VARCHAR(500) NOT NULL,
    emotional_trigger VARCHAR(80) NOT NULL DEFAULT '',
    avg_score FLOAT NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE TABLE reference_videos (
    id INTEGER PRIMARY KEY,
    genre_id VARCHAR(80) NOT NULL REFERENCES genres(id),
    video_url VARCHAR(500) UNIQUE NOT NULL,
    channel_name VARCHAR(120) NOT NULL DEFAULT '',
    channel_subscribers INTEGER NOT NULL DEFAULT 0,
    views INTEGER NOT NULL DEFAULT 0,
    likes INTEGER NOT NULL DEFAULT 0,
    comments INTEGER NOT NULL DEFAULT 0,
    upload_date DATE,
    duration_sec INTEGER NOT NULL DEFAULT 0,
    title VARCHAR(160) NOT NULL DEFAULT '',
    description_first_line VARCHAR(300) NOT NULL DEFAULT '',
    hashtags VARCHAR(500) NOT NULL DEFAULT '',
    full_script TEXT NOT NULL DEFAULT '',
    word_count INTEGER NOT NULL DEFAULT 0,
    sentence_count INTEGER NOT NULL DEFAULT 0,
    words_per_second FLOAT NOT NULL DEFAULT 0,
    overall_score FLOAT NOT NULL DEFAULT 0,
    usable_as_few_shot BOOLEAN NOT NULL DEFAULT FALSE,
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE TABLE script_analysis (
    id INTEGER PRIMARY KEY,
    reference_video_id INTEGER UNIQUE NOT NULL REFERENCES reference_videos(id),
    hook_first_sentence VARCHAR(500) NOT NULL DEFAULT '',
    hook_type VARCHAR(80) NOT NULL DEFAULT '',
    hook_emotional_trigger VARCHAR(80) NOT NULL DEFAULT '',
    hook_speed_sec FLOAT NOT NULL DEFAULT 0,
    opening_words VARCHAR(200) NOT NULL DEFAULT '',
    body_sentence_count INTEGER NOT NULL DEFAULT 0,
    has_twist_reveal BOOLEAN NOT NULL DEFAULT FALSE,
    twist_line VARCHAR(700) NOT NULL DEFAULT '',
    ending_type VARCHAR(80) NOT NULL DEFAULT '',
    last_sentence VARCHAR(500) NOT NULL DEFAULT '',
    tense_used VARCHAR(60) NOT NULL DEFAULT '',
    pov_person VARCHAR(60) NOT NULL DEFAULT '',
    narrative_technique VARCHAR(120) NOT NULL DEFAULT '',
    emotional_arc VARCHAR(300) NOT NULL DEFAULT '',
    power_words VARCHAR(700) NOT NULL DEFAULT '',
    emphasis_words VARCHAR(700) NOT NULL DEFAULT '',
    sensory_language_used TEXT NOT NULL DEFAULT '',
    retention_hook VARCHAR(500) NOT NULL DEFAULT '',
    likely_share_trigger VARCHAR(500) NOT NULL DEFAULT '',
    why_it_worked TEXT NOT NULL DEFAULT '',
    what_to_improve TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE TABLE visual_style_rules (
    id INTEGER PRIMARY KEY,
    genre_id VARCHAR(80) UNIQUE NOT NULL REFERENCES genres(id),
    layout_type VARCHAR(80) NOT NULL DEFAULT '',
    image_or_video_count INTEGER NOT NULL DEFAULT 0,
    image_change_timing VARCHAR(120) NOT NULL DEFAULT '',
    transition_type VARCHAR(80) NOT NULL DEFAULT '',
    image_style VARCHAR(160) NOT NULL DEFAULT '',
    visual_keywords TEXT NOT NULL DEFAULT '',
    negative_visual_keywords TEXT NOT NULL DEFAULT '',
    caption_style VARCHAR(120) NOT NULL DEFAULT '',
    caption_font VARCHAR(120) NOT NULL DEFAULT '',
    caption_primary_color VARCHAR(80) NOT NULL DEFAULT '',
    caption_highlight_color VARCHAR(80) NOT NULL DEFAULT '',
    caption_position VARCHAR(80) NOT NULL DEFAULT '',
    music_mood VARCHAR(80) NOT NULL DEFAULT '',
    sfx_rules TEXT NOT NULL DEFAULT '',
    source_policy VARCHAR(80) NOT NULL DEFAULT 'stock_video_first',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE TABLE topic_expansion_rules (
    id INTEGER PRIMARY KEY,
    genre_id VARCHAR(80) NOT NULL REFERENCES genres(id),
    trigger_term VARCHAR(120) NOT NULL,
    search_queries TEXT NOT NULL,
    required_words VARCHAR(700) NOT NULL DEFAULT '',
    forbidden_words VARCHAR(700) NOT NULL DEFAULT '',
    realism_mode VARCHAR(60) NOT NULL DEFAULT 'inspired_by_real_events',
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    UNIQUE (genre_id, trigger_term)
);

CREATE TABLE topic_research_sources (
    id INTEGER PRIMARY KEY,
    topic VARCHAR(300) NOT NULL,
    genre_id VARCHAR(80) NOT NULL REFERENCES genres(id),
    title VARCHAR(300) NOT NULL DEFAULT '',
    url VARCHAR(700) NOT NULL DEFAULT '',
    source_type VARCHAR(80) NOT NULL DEFAULT '',
    snippet TEXT NOT NULL DEFAULT '',
    extracted_facts TEXT NOT NULL DEFAULT '',
    credibility_score FLOAT NOT NULL DEFAULT 0,
    relevance_score FLOAT NOT NULL DEFAULT 0,
    fetched_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE TABLE generation_runs (
    id INTEGER PRIMARY KEY,
    user_topic VARCHAR(300) NOT NULL,
    selected_genre_id VARCHAR(80) NOT NULL REFERENCES genres(id),
    selected_angle VARCHAR(300) NOT NULL DEFAULT '',
    research_brief TEXT NOT NULL DEFAULT '',
    generated_title VARCHAR(160) NOT NULL DEFAULT '',
    generated_script TEXT NOT NULL DEFAULT '',
    relevance_score FLOAT NOT NULL DEFAULT 0,
    factual_grounding_score FLOAT NOT NULL DEFAULT 0,
    status VARCHAR(60) NOT NULL DEFAULT 'created',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE TABLE ai_suggestions (
    id INTEGER PRIMARY KEY,
    target_table VARCHAR(80) NOT NULL,
    target_id VARCHAR(120) NOT NULL DEFAULT '',
    suggestion_type VARCHAR(80) NOT NULL DEFAULT '',
    old_value TEXT NOT NULL DEFAULT '',
    suggested_value TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    confidence FLOAT NOT NULL DEFAULT 0,
    status VARCHAR(40) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE TABLE knowledge_import_batches (
    id INTEGER PRIMARY KEY,
    source_file VARCHAR(500) NOT NULL DEFAULT '',
    row_counts JSON NOT NULL DEFAULT '{}',
    errors JSON NOT NULL DEFAULT '[]',
    imported_at TIMESTAMP WITH TIME ZONE NOT NULL
);
