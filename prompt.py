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

Title rules: 35-60 characters, relatable or curiosity hook that makes people want to watch, ending with one fitting emoji.
Do NOT reuse these earlier titles or ideas: {avoid}

Return ONLY valid JSON, exactly this shape:
{{
  "title": "title in {config.LANGUAGE}",
  "description": "2-3 sentence funny YouTube description in {config.LANGUAGE}",
  "tags": ["10 short search tags, mix of {config.LANGUAGE} and English"],
  "comment_question": "one fun either-or vote or relatable question for viewers, in {config.LANGUAGE}, max 14 words, that makes them want to comment",
  "running_gag": "the repeating joke",
  "beats": ["exactly {config.NUM_SCENES - 1} short story beats in order; the last one is the twist and punchline"]
}}"""
