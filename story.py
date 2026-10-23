import json, re, time, requests
import config

PREFERRED = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile", "qwen/qwen3-32b"]
SKIP = ("whisper", "guard", "tts", "orpheus", "compound", "playai", "embed")
HEADERS = lambda: {"Authorization": f"Bearer {config.GROQ_API_KEY}"}


def _prompt(history_titles):
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


def _candidates():
    """Models to try, in order. Asks Groq which models this key can use, so deprecations don't break the bot."""
    available = []
    try:
        r = requests.get("https://api.groq.com/openai/v1/models", headers=HEADERS(), timeout=30)
        if r.status_code == 200:
            available = [m["id"] for m in r.json().get("data", [])]
            print("Models available on your Groq key:", ", ".join(available))
    except Exception as e:
        print("Could not list Groq models:", e)

    wanted = ([config.GROQ_MODEL] if config.GROQ_MODEL else []) + PREFERRED
    if not available:
        return wanted
    ordered = [m for m in wanted if m in available]
    ordered += [m for m in available if m not in ordered and not any(k in m.lower() for k in SKIP)]
    return ordered or wanted


def _call(prompt, model):
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=HEADERS(),
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a children's story writer. Reply with valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 1.0,
            "max_completion_tokens": 9000,
            "response_format": {"type": "json_object"},
        },
        timeout=180,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Groq API {r.status_code}: {r.text[:300]}")
    text = r.json()["choices"][0]["message"]["content"]
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    return json.loads(text)


def generate_story(history_titles):
    last = None
    for model in _candidates():
        print("Trying model:", model)
        for attempt in range(2):
            try:
                data = _call(_prompt(history_titles), model)
                assert data["title"] and len(data["scenes"]) >= 3
                for s in data["scenes"]:
                    assert s["narration"] and s["image_prompt"]
                return data
            except Exception as e:
                last = e
                print(f"  attempt {attempt+1} failed: {e}")
                if "model_not_found" in str(e) or " 404" in str(e) or "decommissioned" in str(e):
                    break  # try next model
                time.sleep(5)
    raise RuntimeError(f"Could not generate story: {last}")
