#!/usr/bin/env python3
"""Gemini client for the comedy writer (plain REST, no extra package).

Models come from the GEMINI_MODELS environment variable (comma separated, best first), e.g.
  GEMINI_MODELS="gemini-3.8-flash,gemini-3.6-flash,gemini-3.5-flash,gemini-3.5-flash-lite,gemini-2.5-flash"
Each model is tried in order. A model that does not exist, is not allowed for your key, or keeps failing is skipped
and the next one is used. Key: GEMINI_API_KEY (or GOOGLE_API_KEY).
"""
import json
import os
import re
import sys
import time

import requests

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import log  # noqa: E402

DEFAULT_MODELS = "gemini-3.8-flash,gemini-3.6-flash,gemini-3.5-flash,gemini-3.5-flash-lite,gemini-2.5-flash"
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

_state = {"good": None, "dead": set()}


def gemini_models():
    raw = (os.environ.get("GEMINI_MODELS") or "").strip() or DEFAULT_MODELS
    return [m.strip() for m in raw.split(",") if m.strip()]


def gemini_key():
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_KEY"):
        v = (os.environ.get(name) or "").strip()
        if v:
            return v
    return ""


def gemini_available():
    return bool(gemini_key())


def parse_json(text):
    """Parse model output as JSON (also when wrapped in ``` fences or surrounded by chatter)."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except ValueError:
        i, j = text.find("{"), text.rfind("}")
        if i >= 0 and j > i:
            return json.loads(text[i:j + 1])
        raise


def _extract_text(data):
    """Visible answer text of a generateContent response ('thought' parts are skipped). None if blocked/empty."""
    cands = data.get("candidates") or []
    if not cands:
        fb = data.get("promptFeedback", {})
        log(f"[gemini] no candidates (promptFeedback: {fb})")
        return None, "NO_CANDIDATES"
    cand = cands[0]
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    return (text or None), cand.get("finishReason", "")


def gemini_chat(system, user, temperature=1.0, thinking="medium", max_tokens=16000):
    """One JSON answer from the first model that works. Returns a dict, or None if every model failed."""
    key = gemini_key()
    if not key:
        return None
    models = gemini_models()
    if _state["good"] in models:
        models = [_state["good"]] + [m for m in models if m != _state["good"]]
    for model in models:
        if model in _state["dead"]:
            continue
        use_thinking = bool(thinking)
        for attempt in range(4):
            gen = {
                # Gemini 3 models are tuned for temperature 1.0; lowering it can make them repeat themselves
                "temperature": 1.0 if model.startswith("gemini-3") else temperature,
                "maxOutputTokens": max_tokens,       # thinking tokens count toward this limit, so it is generous
                "responseMimeType": "application/json",
            }
            if use_thinking:
                gen["thinkingConfig"] = {"thinkingLevel": thinking}
            body = {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": gen,
            }
            try:
                r = requests.post(URL.format(model=model), headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                                  json=body, timeout=240)
            except requests.RequestException as e:
                log(f"[gemini] {model}: network error {type(e).__name__}")
                time.sleep(4 * (attempt + 1))
                continue
            low = r.text.lower()
            if r.status_code == 200:
                try:
                    text, finish = _extract_text(r.json())
                except ValueError:
                    text, finish = None, "BAD_RESPONSE"
                if text:
                    try:
                        out = parse_json(text)
                        if _state["good"] != model:
                            log(f"[gemini] using model {model}")
                        _state["good"] = model
                        return out
                    except ValueError:
                        log(f"[gemini] {model}: answer was not valid JSON (finish={finish}); retrying")
                        time.sleep(2)
                        continue
                log(f"[gemini] {model}: empty answer (finish={finish})")
                if finish in ("MAX_TOKENS", "SAFETY", "PROHIBITED_CONTENT", "NO_CANDIDATES", "BLOCKLIST"):
                    break                                   # retrying will not help; try the next model
                time.sleep(3)
                continue
            log(f"[gemini] {model}: HTTP {r.status_code}: {r.text[:200]}")
            if r.status_code == 400 and use_thinking and "think" in low:
                use_thinking = False                        # this model does not know thinkingLevel
                continue
            if r.status_code == 401 or (r.status_code in (400, 403) and "api key" in low):
                log("[gemini] the API key was rejected; check the GEMINI_API_KEY secret")
                return None
            if r.status_code in (400, 403, 404):
                _state["dead"].add(model)                   # unknown model / not allowed for this key
                break
            if r.status_code == 429:
                time.sleep(min(15 * (attempt + 1), 45))
                if attempt >= 2:
                    break
                continue
            if r.status_code >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            break
        log(f"[gemini] giving up on {model}, trying the next model")
    return None
