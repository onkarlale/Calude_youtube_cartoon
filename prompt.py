import config
from themes import pick


def build_outline_prompt(history_titles):
    avoid = "; ".join(history_titles[-60:]) or "none yet"
    setting, style, cast = pick()
    return f"""You are a head writer for a hit animated COMEDY channel for a general audience (teens and adults love it, kids can watch too). Channel style: {config.CHANNEL_THEME}.
Story language: {config.LANGUAGE}. Plan ONE brand-new episode with original characters only (never copy existing cartoons).

This episode: setting = {setting}. Comedy engine = {style}. Cast = {cast}.

A great episode has:
- Two memorable characters with opposite personalities, each with a funny flaw.
- One clear, silly goal and a heroes' plan that backfires.
- A running gag that returns 3 times and gets bigger each time.
- Escalation: every beat is worse or funnier than the last. Smart, relatable, observational jokes and wordplay, never childish baby talk.
- A surprising twist ending with a final punchline.
- Clean, advertiser-friendly humor: no profanity, nothing sexual, no insults about people, religion, caste or looks, no real violence, no brands.

Do NOT reuse these earlier titles or ideas: {avoid}

Return ONLY valid JSON, exactly this shape:
{{
  "title": "catchy funny title under 70 characters, in {config.LANGUAGE}",
  "description": "2-3 sentence funny YouTube description in {config.LANGUAGE}",
  "tags": ["10 short search tags, mix of {config.LANGUAGE} and English"],
  "characters": "ENGLISH ONLY: both main characters with exact visual details (colors, clothes, features), consistent and easy to redraw",
  "character_a": "name of the first character (deep, slow voice)",
  "character_b": "name of the second character (high, squeaky voice)",
  "running_gag": "the repeating joke",
  "beats": ["exactly {config.NUM_SCENES} short beats in order; the last one is the twist and punchline"]
}}"""
