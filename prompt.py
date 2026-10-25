import config
from themes import pick
from trends import get_trends


def build_outline_prompt(history_titles):
    avoid = "; ".join(history_titles[-60:]) or "none yet"
    setting, style, _ = pick()
    trends = get_trends()
    trend_text = (
        f"Trending searches in India right now: {', '.join(trends)}. If one can become a safe, funny episode, build it "
        "around its general theme or mood only (a cricket final becomes cricket-mad neighbours). Never mention real people, "
        "news events, brands or tragedies; skip politics, religion, crime and disasters. If none fits, use the default setting."
    ) if trends else ""
    return f"""You are the head writer of a viral animated COMEDY channel for a general audience (teens and adults love it, kids can watch too). Channel style: {config.CHANNEL_THEME}.
Story language: {config.LANGUAGE}. Plan ONE brand-new episode.

The two recurring stars (same looks and personalities in every episode):
{config.CAST_BIO}
Default setting: {setting}. Comedy engine: {style}. {trend_text}
{config.FORMAT_RULES}

A great episode has: one clear silly goal, a plan that backfires, a running gag that returns 3 times and grows, escalation in every beat, relatable observational jokes and wordplay (never baby talk), and a surprising twist ending with a final punchline. Clean, advertiser-friendly humor: no profanity, nothing sexual, no insults about people, religion, caste or looks, no real violence, no brands.

CONSISTENCY RULES (the story, the pictures and the voices must all match):
- The whole episode happens in ONE place (or a very small number of closely related places) so the pictures stay consistent.
- Every beat is concrete and visual: say WHO ({config.NAME_A} and/or {config.NAME_B}) does WHAT, with which object, so it can be drawn and spoken exactly.
- Each beat follows directly from the previous one (cause and effect), and the title, description and tags must describe THIS story, not a generic one.

Title rules: 35-60 characters, relatable or curiosity hook that makes people want to watch, ending with one fitting emoji.
Do NOT reuse these earlier titles or ideas: {avoid}

Return ONLY valid JSON, exactly this shape:
{{
  "title": "title in {config.LANGUAGE}",
  "description": "2-3 sentence funny YouTube description in {config.LANGUAGE}, describing this exact story",
  "tags": ["10 short search tags, mix of {config.LANGUAGE} and English"],
  "comment_question": "one fun either-or vote or relatable question for viewers, in {config.LANGUAGE}, max 14 words, about this story, that makes them want to comment",
  "location_visual": "ENGLISH ONLY: where the episode takes place plus 3-4 key props that stay the same in every picture (one sentence, no characters)",
  "running_gag": "the repeating joke",
  "gag_visual": "ENGLISH ONLY: what the running gag looks like in a picture (the object or action that repeats)",
  "beats": ["exactly {config.NUM_SCENES - 1} short story beats in order; the last one is the twist and punchline"]
}}"""
