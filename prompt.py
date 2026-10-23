import config


def build_prompt(history_titles):
    avoid = "; ".join(history_titles[-60:]) or "none yet"
    return f"""You write original, laugh-out-loud SLAPSTICK COMEDY cartoon stories (fast, energetic, chase-and-mishap style) for a YouTube channel about: {config.CHANNEL_THEME}.
Story language: {config.LANGUAGE}. Write title, description, tags and every narration line in {config.LANGUAGE}, in natural spoken everyday language like a funny storyteller (not stiff or bookish).

Comedy rules:
- Open with a funny hook in the very first line.
- One silly goal or chase that keeps getting worse: escalating mishaps, near-misses, misunderstandings, funny reactions. Pace it like a cartoon: something new happens in EVERY scene.
- Use comic timing: setup, then punchline. Add funny sound words (धड़ाम, छपाक, बूम, etc.) and playful exaggeration.
- Finish with a big surprise twist or punchline in the last scene.
- Family-friendly humor only: no insults about people, religion, caste, looks or regions; no real violence, nothing scary, no brands. Do not copy any existing cartoon characters (original characters only).

Write ONE brand-new story. Do NOT reuse these earlier titles or ideas: {avoid}

Return ONLY valid JSON (no markdown) with this exact shape:
{{
  "title": "catchy funny title under 70 characters, in {config.LANGUAGE}",
  "description": "2-3 sentence funny YouTube description in {config.LANGUAGE}",
  "tags": ["10 short search tags, mix of {config.LANGUAGE} and English"],
  "characters": "ENGLISH ONLY: one-line visual description of the 1-2 main characters (species, exact colors, clothes, funny trait) so the art stays consistent",
  "scenes": [
    {{
      "narration": "1-2 SHORT funny sentences in {config.LANGUAGE}, about 15-28 words",
      "image_prompt": "ENGLISH ONLY: one clear action moment, characters fully visible in a dynamic pose with a funny exaggerated expression, simple background, no text in image",
      "motion": "one of: zoom_in, zoom_out, pan_left, pan_right, pan_up, pan_down, shake, punch",
      "sfx": "one of: whoosh, boing, crash, pop, none"
    }}
  ]
}}
Motion guide: use shake for crashes and explosions, punch for sudden surprises and the final punchline, pan_left/pan_right for chases, zoom_in for suspense, zoom_out for reveals. Sfx guide: crash with shake, whoosh for fast movement, boing for bouncing or stretching, pop for small surprises. Use sfx "none" on about half the scenes.
Use exactly {config.NUM_SCENES} scenes. The characters and image_prompt fields must be in English because the image model only understands English."""
