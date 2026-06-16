from __future__ import annotations

import re

from app.schemas import ImageCue, NicheProfile, VisualStylePlan


PROTECTED_REPLACEMENTS = (
    ("marvel comics", "superhero comic universe"),
    ("dc comics", "superhero comic universe"),
)


def build_visual_style_plan(profile: NicheProfile | None = None, source_policy: str = "stock_video_first") -> VisualStylePlan:
    profile = profile or NicheProfile(genre_id="", display_name="")
    return VisualStylePlan(
        source_policy=source_policy,
        visual_keywords=profile.visual_keywords,
        negative_visual_keywords=profile.negative_visual_keywords,
        protected_terms=[item[0] for item in PROTECTED_REPLACEMENTS],
        style_notes=profile.tone_rules[:3],
    )


def coerce_visual_style_plan(value) -> VisualStylePlan:
    if isinstance(value, VisualStylePlan):
        return value
    if isinstance(value, dict):
        return VisualStylePlan(
            source_policy=str(value.get("source_policy") or "stock_video_first"),
            visual_keywords=[str(x) for x in value.get("visual_keywords", [])],
            negative_visual_keywords=[str(x) for x in value.get("negative_visual_keywords", [])],
            protected_terms=[str(x) for x in value.get("protected_terms", [])],
            style_notes=[str(x) for x in value.get("style_notes", [])],
        )
    return VisualStylePlan()


def visual_style_to_dict(plan: VisualStylePlan) -> dict:
    return {
        "source_policy": plan.source_policy,
        "visual_keywords": plan.visual_keywords,
        "negative_visual_keywords": plan.negative_visual_keywords,
        "protected_terms": plan.protected_terms,
        "style_notes": plan.style_notes,
    }


def apply_visual_style_to_script(script, plan: VisualStylePlan):
    script.image_cues = apply_visual_style_to_cues(script.image_cues, plan)
    return script


def apply_visual_style_to_cues(cues: list[ImageCue], plan: VisualStylePlan) -> list[ImageCue]:
    return [ImageCue(stylized_asset_keyword(cue.keyword, plan), cue.timestamp_hint, cue.mood) for cue in cues]


def stylized_query_variants(keyword: str, plan: VisualStylePlan) -> list[str]:
    base = stylized_asset_keyword(keyword, plan)
    variants = [base, f"{base} realistic stock footage", f"{base} vertical video"]
    for hint in plan.visual_keywords[:3]:
        variants.append(f"{base} {hint}")
    return list(dict.fromkeys([item.strip() for item in variants if item.strip()]))


def stylized_asset_keyword(keyword: str, plan: VisualStylePlan) -> str:
    text = sanitize_text(keyword)
    for old, new in PROTECTED_REPLACEMENTS:
        text = re.sub(re.escape(old), new, text, flags=re.I)
    for bad in plan.negative_visual_keywords:
        text = re.sub(rf"\b{re.escape(bad.lower())}\b", " ", text.lower())
    return " ".join(text.split())


def should_skip_stock_video(keyword: str, plan: VisualStylePlan) -> bool:
    return plan.source_policy == "image_only" or any(term.lower() in keyword.lower() for term in plan.negative_visual_keywords)


def sanitize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()
