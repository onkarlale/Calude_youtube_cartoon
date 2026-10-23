import json, re, time, requests
import config

def _prompt(history_titles):
    avoid = "; ".join(history_titles[-60:]) or "none yet"
    return f"""You write original, kid-safe stories for a YouTube channel about: {config.CHANNEL_THEME}.
Language: {config.LANGUAGE}.

Write ONE brand-new story with a clear beginning, middle, end and a gentle moral.
Do NOT reuse these earlier titles or ideas: {avoid}

Return ONLY valid JSON (no markdown) with this exact shape:
{{
  "title": "catchy title under 70 characters",
  "description": "2-3 sentence YouTube description",
  "tags": ["10 short tags"],
  "characters": "one-line visual description of the main characters (species, colors, clothes) used to keep art consistent",
  "scenes": [
    {{"narration": "2-3 simple sentences, about 35-50 words", "image_prompt": "what to draw in this scene, concrete and visual, no text in image"}}
  ]
}}
Use exactly {config.NUM_SCENES} scenes. Keep language simple and warm. No violence, no scary content, no brands."""

def _call(prompt):
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
        json={
            "model": config.GROQ_MODEL,
            "messages": [
                {"role": "system", "content": "You are a children's story writer. Reply with valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 1.0,
            "response_format": {"type": "json_object"},
        },
        timeout=120,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Groq API {r.status_code}: {r.text[:300]}")
    text = r.json()["choices"][0]["message"]["content"]
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    return json.loads(text)

def generate_story(history_titles):
    last = None
    for attempt in range(3):
        try:
            data = _call(_prompt(history_titles))
            assert data["title"] and len(data["scenes"]) >= 3
            for s in data["scenes"]:
                assert s["narration"] and s["image_prompt"]
            return data
        except Exception as e:
            last = e
            print(f"Story attempt {attempt+1} failed: {e}")
            time.sleep(5)
    raise RuntimeError(f"Could not generate story: {last}")
