import json, re, time, requests
import config

PREFERRED = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile", "qwen/qwen3-32b"]
SKIP = ("whisper", "guard", "tts", "orpheus", "compound", "playai", "embed")
HEADERS = lambda: {"Authorization": f"Bearer {config.GROQ_API_KEY}"}


def _prompt(history_titles):
    avoid = "; ".join(history_titles[-60:]) or "none yet"
    return f"""You write original, laugh-out-loud COMEDY cartoon stories for a YouTube channel about: {config.CHANNEL_THEME}.
Story language: {config.LANGUAGE}. Write title, description, tags and every narration line in {config.LANGUAGE}, in natural spoken everyday language like a funny storyteller (not stiff or bookish).

Comedy rules:
- Open with a funny hook in the first line.
- Build one silly problem that keeps getting worse, with escalating mishaps, misunderstandings, wordplay and funny reactions.
- Use comic timing: setup, then punchline. Add funny sound words (धड़ाम, छपाक, etc.) and playful exaggeration.
- Finish with a big surprise twist or punchline in the last scene.
- Family-friendly humor only: no insults about people, religion, caste, looks or regions; no violence, nothing scary, no brands.

Write ONE brand-new story. Do NOT reuse these earlier titles or ideas: {avoid}

Return ONLY valid JSON (no markdown) with this exact shape:
{{
  "title": "catchy funny title under 70 characters, in {config.LANGUAGE}",
  "description": "2-3 sentence funny YouTube description in {config.LANGUAGE}",
  "tags": ["10 short search tags, mix of {config.LANGUAGE} and English"],
  "characters": "ENGLISH ONLY: one-line visual description of the main characters (species, colors, clothes, funny trait) so the art stays consistent",
  "scenes": [
    {{"narration": "2-3 short funny sentences in {config.LANGUAGE}, about 35-50 words", "image_prompt": "ENGLISH ONLY: what to draw in this scene, concrete and visual, with a funny exaggerated expression or action, no text in image"}}
  ]
}}
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
            "max_completion_tokens": 6000,
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
