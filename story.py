import json, re, time, requests
import config
from prompt import build_outline_prompt
from prompt2 import build_script_prompt
from prompt3 import build_director_prompt

PREFERRED = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile", "qwen/qwen3-32b"]
SKIP = ("whisper", "guard", "tts", "orpheus", "compound", "playai", "embed")
HEADERS = lambda: {"Authorization": f"Bearer {config.GROQ_API_KEY}"}


def _candidates():
    """Models to try in order; asks Groq what this key can use, so deprecations don't break the bot."""
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


def _chat(prompt, model, temperature):
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions", headers=HEADERS(), timeout=240,
        json={"model": model, "temperature": temperature, "max_completion_tokens": 9000,
              "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": "You are a comedy writer. Reply with valid JSON only."},
                           {"role": "user", "content": prompt}]})
    if r.status_code >= 400:
        raise RuntimeError(f"Groq API {r.status_code}: {r.text[:300]}")
    text = r.json()["choices"][0]["message"]["content"]
    return json.loads(re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip())


def _scenes_ok(scenes, minimum=6):
    return (isinstance(scenes, list) and len(scenes) >= minimum and
            all(s.get("narration") and s.get("image_prompt") for s in scenes))


def _step(fn, label, retries=2):
    last = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            last = e
            print(f"  {label} attempt {attempt+1} failed: {e}")
            if any(k in str(e) for k in ("model_not_found", " 404", "decommissioned")):
                break
            time.sleep(5)
    raise RuntimeError(f"{label} failed: {last}")


def generate_story(history_titles):
    last = None
    for model in _candidates():
        print("Trying model:", model)
        try:
            print("  planning episode...")
            outline = _step(lambda: _chat(build_outline_prompt(history_titles), model, 1.0), "outline")
            assert outline["title"] and len(outline["beats"]) >= 5
            print("  writing script...")
            script = _step(lambda: _chat(build_script_prompt(outline), model, 0.9), "script")
            assert _scenes_ok(script["scenes"])
            scenes = script["scenes"]
            print("  checking story logic, matching pictures to lines...")
            title, desc = outline["title"], outline["description"]
            try:
                fixed = _chat(build_director_prompt(outline, scenes), model, 0.7)
                new = fixed["scenes"]
                if _scenes_ok(new) and len(new) == len(scenes):
                    for old, nw in zip(scenes, new):
                        old["narration"], old["image_prompt"] = nw["narration"], nw["image_prompt"]
                    title = fixed.get("title") or title
                    desc = fixed.get("description") or desc
            except Exception as e:
                print("  director pass skipped:", e)
            return {"title": title, "description": desc, "tags": outline["tags"],
                    "characters": config.MAIN_CHARACTERS, "location": outline.get("location", ""),
                    "props": outline.get("props", ""),
                    "comment_question": outline.get("comment_question", ""), "scenes": scenes}
        except Exception as e:
            last = e
            print(f"  model {model} failed: {e}")
    raise RuntimeError(f"Could not generate story: {last}")
