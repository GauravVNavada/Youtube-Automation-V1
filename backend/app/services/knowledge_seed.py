from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Genre, GenreHook, GenreRule, VisualStyleRule


DEFAULT_GENRES = [
    {
        "id": "scary_stories",
        "display_name": "Scary Stories",
        "category": "story",
        "tone": "Slow dread with simple words, concrete real-world details, and a believable final reveal.",
        "caption_preset": "horror_red",
        "music_mood": "dark ambient",
        "hooks": ["At {time}, {subject} noticed {detail}.", "The first warning was {detail}."],
        "visual_keywords": "dark hallway, old door, phone screen, shadow figure, abandoned room, mirror",
        "negative_visual_keywords": "cartoon, anime, fantasy monster, gore, random school hallway",
    },
    {
        "id": "history_facts",
        "display_name": "History Facts",
        "category": "facts",
        "tone": "Mini documentary with names, dates, places, and one surprising real-world detail.",
        "caption_preset": "documentary_gold",
        "music_mood": "documentary pulse",
        "hooks": ["Most people do not know {fact}.", "This real place changed because of {event}."],
        "visual_keywords": "historic city street, archive photo, museum object, map close up",
        "negative_visual_keywords": "fantasy, fictional city, game art",
    },
    {
        "id": "reddit_stories",
        "display_name": "Reddit Stories",
        "category": "story",
        "tone": "Conversational, direct, believable, and easy to follow.",
        "caption_preset": "clean_pro",
        "music_mood": "light tension",
        "hooks": ["I thought {person} was joking until {detail}.", "What would you do if {problem}?"],
        "visual_keywords": "family dinner, phone message, apartment living room, tense conversation",
        "negative_visual_keywords": "celebrity, cartoon, fantasy",
    },
]


def seed_pipeline_knowledge(db: Session) -> None:
    for item in DEFAULT_GENRES:
        genre = db.get(Genre, item["id"])
        if genre is None:
            genre = Genre(id=item["id"], display_name=item["display_name"])
            db.add(genre)
        genre.category = item["category"]
        genre.tone = item["tone"]
        genre.caption_preset = item["caption_preset"]
        genre.music_mood = item["music_mood"]
        genre.is_active = True
        _ensure_hooks(db, genre.id, item["hooks"])
        _ensure_rule(db, genre.id, "tone_rule", item["tone"])
        _ensure_visual_style(db, genre.id, item)
    db.commit()


def _ensure_hooks(db: Session, genre_id: str, hooks: list[str]) -> None:
    existing = {(row.genre_id, row.template) for row in db.query(GenreHook).filter(GenreHook.genre_id == genre_id)}
    for template in hooks:
        if (genre_id, template) not in existing:
            db.add(GenreHook(genre_id=genre_id, template=template, hook_type="template"))


def _ensure_rule(db: Session, genre_id: str, rule_type: str, value: str) -> None:
    exists = (
        db.query(GenreRule)
        .filter(GenreRule.genre_id == genre_id, GenreRule.rule_type == rule_type, GenreRule.value == value)
        .first()
    )
    if exists is None:
        db.add(GenreRule(genre_id=genre_id, rule_type=rule_type, value=value, weight=1))


def _ensure_visual_style(db: Session, genre_id: str, item: dict[str, str]) -> None:
    style = db.query(VisualStyleRule).filter(VisualStyleRule.genre_id == genre_id).first()
    if style is None:
        style = VisualStyleRule(genre_id=genre_id)
        db.add(style)
    style.layout_type = "full_image"
    style.image_or_video_count = 8
    style.image_style = "realistic stock footage and photos"
    style.visual_keywords = item["visual_keywords"]
    style.negative_visual_keywords = item["negative_visual_keywords"]
    style.source_policy = "stock_video_first"
