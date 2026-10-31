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

REQUEST_TIMEOUT = 100      # seconds to wait for ONE answer; a model that hangs longer is skipped
CALL_DEADLINE = 480        # seconds in total for one gemini_chat() call across all models
_state = {"good": None, "dead": set(), "slow": []}


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
        log(f"[gemini] no candidates (promptFeedback: {data.get('promptFeedback', {})})")
        return None, "NO_CANDIDATES"
    cand = cands[0]
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    return (text or None), cand.get("finishReason", "")


def _ask(model, key, system, user, temperature, thinking, max_tokens):
    """Try ONE model, quickly. Returns ('ok', data) | ('busy', None) | ('dead', None) | ('stop', None)."""
    use_thinking = bool(thinking)
    transient = 0
    for _ in range(5):
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
                              json=body, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            log(f"[gemini] {model}: {type(e).__name__} after {REQUEST_TIMEOUT}s; skipping this model for now")
            return "busy", None                  # a hanging model will usually hang again: go to the next one
        low = r.text.lower()
        if r.status_code == 200:
            try:
                text, finish = _extract_text(r.json())
            except ValueError:
                text, finish = None, "BAD_RESPONSE"
            if text:
                try:
                    return "ok", parse_json(text)
                except ValueError:
                    log(f"[gemini] {model}: answer was not valid JSON (finish={finish})")
                    transient += 1
                    if transient >= 2:
                        return "busy", None
                    continue
            log(f"[gemini] {model}: empty answer (finish={finish})")
            return ("dead" if finish in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST") else "busy"), None
        log(f"[gemini] {model}: HTTP {r.status_code}: {r.text[:160].strip()}")
        if r.status_code == 400 and use_thinking and "think" in low:
            use_thinking = False                 # this model does not know thinkingLevel
            continue
        if r.status_code == 401 or (r.status_code in (400, 403) and "api key" in low):
            log("[gemini] the API key was rejected; check the GEMINI_API_KEY secret")
            return "stop", None
        if r.status_code in (400, 403, 404):
            return "dead", None                  # unknown model / not allowed for this key
        if r.status_code == 429 or r.status_code >= 500:
            transient += 1
            if transient >= 2:
                return "busy", None
            time.sleep(4)                        # one short retry, then the next model
            continue
        return "busy", None
    return "busy", None


def gemini_chat(system, user, temperature=1.0, thinking="medium", max_tokens=16000):
    """One JSON answer from the first model that works. Returns a dict, or None if every model failed.
    A busy or slow model is skipped after one quick retry, so a bad day on one model never blocks the run."""
    key = gemini_key()
    if not key:
        return None
    t0 = time.time()
    for rnd in range(2):
        models = [m for m in gemini_models() if m not in _state["dead"]]
        # the model that worked last time first; models that were slow this run go to the back
        models.sort(key=lambda m: (m in _state["slow"], m != _state["good"]))
        for model in models:
            if time.time() - t0 > CALL_DEADLINE:
                log(f"[gemini] stopping after {CALL_DEADLINE}s without an answer")
                return None
            status, data = _ask(model, key, system, user, temperature, thinking, max_tokens)
            if status == "ok":
                if _state["good"] != model:
                    log(f"[gemini] using model {model}")
                _state["good"] = model
                if model in _state["slow"]:
                    _state["slow"].remove(model)
                return data
            if status == "stop":
                return None
            if status == "dead":
                _state["dead"].add(model)
            elif model not in _state["slow"]:
                _state["slow"].append(model)
            log(f"[gemini] moving on from {model}")
        if rnd == 0 and any(m not in _state["dead"] for m in gemini_models()):
            log("[gemini] every model was busy; waiting 20 s and trying them all once more")
            time.sleep(20)
    return None
