#!/usr/bin/env python3
"""Two-pass Groq comedy writer (draft, then punch-up). Writes build/script.json.

  python scripts/write_script.py            # real run (needs build/topic.json + GROQ key)
  python scripts/write_script.py --sample   # no API: writes a short sample script for smoke tests
"""
import argparse
import json
import os
import re
import sys
import time

import requests

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import BUILD, ROOT, fail, load_config, log  # noqa: E402

API = "https://api.groq.com/openai/v1/chat/completions"

BANNED = [
    "modi", "bjp", "congress party", "kejriwal", "rahul gandhi", "yogi", "hindu", "muslim", "islam",
    "christian", "sikh", "dalit", "brahmin", "caste",
    "मोदी", "भाजपा", "कांग्रेस", "केजरीवाल", "हिंदू", "हिन्दू", "मुस्लिम", "इस्लाम", "ईसाई", "सिख", "दलित", "ब्राह्मण", "जाति",
]

SCHEMA = """Return ONLY valid JSON:
{
  "segments": [
    {"text": "what Raj says out loud in one breath", "role": "setup|punch|aside", "pause_after_ms": 300}
  ]
}
- role "setup": 1 or 2 short spoken sentences that build the moment (max 22 words).
- role "punch": the joke line. At most 14 words. The surprising word comes LAST. The room laughs after it.
- role "aside": a quick side remark to the room, a crowd-work question, a self-interruption or a reaction ("Seriously?").
- 22 to 30 segments in total. About one third of them are punch lines.
- Only words Raj SAYS. No stage directions, no brackets, no asterisks, no emojis, no labels like "Raj:"."""

SAMPLE = {
    "title": "Smoke test video",
    "description": "Pipeline smoke test.",
    "tags": ["test"],
    "thumb_text": "SMOKE TEST",
    "segments": [
        {"text": "नमस्ते दोस्तों, आज मैं आपको अपनी सुबह के बारे में बताने आया हूँ।", "role": "setup", "pause_after_ms": 300},
        {"text": "मेरा अलार्म सुबह छह बजे बजता है, और मैं उसे ऐसे बंद करता हूँ जैसे वो मेरा पुराना कर्ज़ा माँग रहा हो।", "role": "punch", "pause_after_ms": 1200},
        {"text": "फिर मम्मी आती हैं और कहती हैं, बेटा उठ जा, शर्मा जी का बेटा कब का जिम से आ गया।", "role": "setup", "pause_after_ms": 300},
        {"text": "अरे मम्मी, शर्मा जी के बेटे ने तो रात में सोना ही छोड़ दिया है, मैं क्यों उसकी बराबरी करूँ?", "role": "punch", "pause_after_ms": 1200},
        {"text": "खैर, मैं ऑफिस पहुँचता हूँ और मैनेजर बोलता है, बस पाँच मिनट की क्विक मीटिंग है।", "role": "setup", "pause_after_ms": 300},
        {"text": "वो पाँच मिनट इतने लंबे होते हैं कि उसमें मेरी ईएमआई की तीन किस्तें कट जाती हैं।", "role": "punch", "pause_after_ms": 1200},
    ],
}


def groq_key():
    k = os.environ.get("GROQ_API_KEY_CLAUDE") or os.environ.get("GROQ_API_KEY")
    if not k:
        fail("Set GROQ_API_KEY_CLAUDE (or GROQ_API_KEY).")
    return k


PREFERRED = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile", "moonshotai/kimi-k2-instruct-0905",
             "qwen/qwen3-32b", "llama-3.1-8b-instant"]
SKIP = ("whisper", "guard", "tts", "orpheus", "prompt-guard", "safeguard", "compound", "embed", "distil")
_state = {"candidates": None, "model": None}


def _candidates(first):
    """Preference order: config model, known good models, then anything else Groq lists for this key."""
    if _state["candidates"] is None:
        listed = []
        try:
            r = requests.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {groq_key()}"}, timeout=30)
            if r.status_code == 200:
                listed = [m["id"] for m in r.json().get("data", []) if not any(x in m["id"].lower() for x in SKIP)]
                log(f"[writer] models available to your key: {listed}")
        except Exception as e:  # noqa: BLE001
            log(f"[writer] could not list models: {e}")
        order = [first] + PREFERRED
        cands = [m for m in order if (not listed or m in listed)] + [m for m in listed if m not in order]
        seen, out = set(), []
        for m in cands + ([first] if not listed else []):
            if m and m not in seen:
                seen.add(m)
                out.append(m)
        _state["candidates"] = out
        log(f"[writer] model order: {out}")
    return _state["candidates"]


def _parse_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except ValueError:
        i, j = text.find("{"), text.rfind("}")
        if i >= 0 and j > i:
            return json.loads(text[i:j + 1])
        raise


def chat(model, system, user, temperature):
    cands = [_state["model"]] if _state["model"] else _candidates(model)
    ci = 0
    use_json_mode = True
    for attempt in range(12):
        m = cands[min(ci, len(cands) - 1)]
        body = {
            "model": m,
            "temperature": temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if use_json_mode:
            body["response_format"] = {"type": "json_object"}
        if "gpt-oss" in m:
            body["reasoning_effort"] = "low"          # keep the thinking short so the joke text is not cut off
            body["max_completion_tokens"] = 8000
        try:
            r = requests.post(API, headers={"Authorization": f"Bearer {groq_key()}"}, json=body, timeout=180)
        except requests.RequestException as e:
            log(f"[writer] network error: {e}")
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 200:
            try:
                out = _parse_json(r.json()["choices"][0]["message"]["content"])
                _state["model"] = m
                return out
            except Exception as e:  # noqa: BLE001
                log(f"[writer] model {m} returned unusable JSON ({e}); retrying")
                time.sleep(3)
                continue
        log(f"[writer] Groq HTTP {r.status_code} on {m}: {r.text[:200]}")
        low = r.text.lower()
        if r.status_code in (400, 404) and ("model" in low and ("not exist" in low or "decommission" in low or "not found" in low or "access" in low)):
            ci += 1
            if ci >= len(cands):
                break
            log(f"[writer] switching model to {cands[ci]}")
            continue
        if r.status_code == 400 and use_json_mode and "response_format" in low:
            use_json_mode = False
            continue
        time.sleep(5 * (attempt + 1))
    fail("Groq API kept failing (no usable model). Check the GROQ_API_KEY_CLAUDE secret and your Groq console.")


def count_words(script):
    return sum(len(s["text"].split()) for s in script["segments"])


def banned_hit(script):
    blob = json.dumps(script, ensure_ascii=False).lower()
    return [b for b in BANNED if b in blob]


def normalize(script, cfg):
    min_laugh = cfg["timing"]["min_laugh_pause_ms"]
    segs = []
    for s in script.get("segments", []):
        text = re.sub(r"\s+", " ", str(s.get("text", ""))).strip()
        if not text:
            continue
        role = s.get("role", "setup")
        if role not in ("setup", "punch", "aside"):
            role = "setup"
        pause = int(s.get("pause_after_ms") or 0)
        if role == "punch":
            pause, laugh = max(pause, min_laugh), True
        elif role == "setup":
            pause, laugh = min(max(pause, 200), 450), False
        else:
            pause, laugh = min(max(pause, 250), 450), False
        segs.append({"text": text, "role": role, "pause_after_ms": pause, "laugh": laugh})
    script["segments"] = segs
    return script


STORY_MARKERS = [
    "एक बार", "एक दिन", "कहानी", "ek baar", "ek din", "kahani", "once upon", "let me tell you a story",
    "तो हुआ यह कि", "to hua yeh ki", "सीख", "moral", "इस कहानी",
]
ADDRESS = ["आप", "aap", "भाई", "bhai", "यार", "yaar", "दोस्तों", "dosto", "सब", "हाथ", "बोलो", "सच बोलूँ", "सच बोलूं", "hai na", "है ना", "है न"]


def style_problems(script):
    """Reject sets that read like a story. Returns a list of problems (empty = sounds like live stand-up)."""
    segs = script.get("segments", [])
    if not segs:
        return []
    texts = [s["text"] for s in segs]
    blob = " ".join(texts).lower()
    problems = []
    marks = [m for m in STORY_MARKERS if m.lower() in blob]
    if marks:
        problems.append(f"it sounds like a story being read (found {marks}); perform it live instead, in the present tense")
    addr = sum(1 for t in texts if any(a.lower() in t.lower() for a in ADDRESS))
    if addr < 7:
        problems.append(f"only {addr} lines talk directly to the audience; at least 8 lines must address the room (aap log, bhai, yaar, dosto, hai na)")
    q = blob.count("?")
    if q < 5:
        problems.append(f"only {q} questions; add at least 5 questions to the room or self-interruptions")
    longest = max(len(t.split()) for t in texts)
    if longest > 30:
        problems.append(f"a line has {longest} words; no line may exceed 26 words")
    punch = sum(1 for s in segs if s["role"] == "punch") / len(segs)
    if punch < 0.25:
        problems.append("too few punch lines; at least a quarter of the lines must be punch lines")
    return problems


def build_prompts(cfg, topic, recent):
    character = (ROOT / "assets/character.md").read_text(encoding="utf-8")
    lo, hi = cfg["script"]["min_words"], cfg["script"]["max_words"]
    system = (
        "You are the head writer AND live-show director for Raj, a stand-up comedian performing in a small comedy "
        "club in front of a packed, laughing crowd. You write ONLY what Raj says out loud on stage. This is a "
        "LIVE PERFORMANCE, not a story, not an essay, not narration. If it could be read as a short story, it is wrong.\n\n"
        "LIVE-PERFORMANCE RULES (follow every one):\n"
        "1. TALK TO THE ROOM. In at least 8 lines address the audience directly: aap log, bhai, yaar, dosto, hai na?, "
        "sach bolun?, haath uthao. Raj can see the front row and reacts to them.\n"
        "2. PRESENT TENSE, IN THE MOMENT. Say \"Main office pahunchta hoon aur Gupta sir bolte hain...\" not \"ek din main office gaya "
        "aur...\". NEVER use story openers or morals: no \"ek baar\", \"ek din\", \"kahani\", \"once upon\", \"toh hua yeh ki\", no lesson at the end.\n"
        "3. ACT IT OUT, DO NOT DESCRIBE IT. Put short dialogue in the mouths of Mummy, Papa, Gupta sir, Sharma ji ka beta "
        "(\"Mummy bolti hain, 'beta, shaadi kab?'\") and let Raj react in the next line.\n"
        "4. CROWD WORK, 2 or 3 times: ask the room a quick question, then answer for them or react to an imagined reply "
        "(\"Haath uthao jinke ghar mein... haan, front row wale uncle, aap bhi?\"). Never wait for a real answer.\n"
        "5. RHYTHM. Setup: one or two short sentences. Punch: 14 words or fewer, the surprising word LAST. Mix tiny lines "
        "(\"Seriously?\", \"Nahi nahi, ruko.\") with longer ones. Interrupt yourself. Never two long lines in a row.\n"
        "6. ESCALATE. Each bit is bigger and weirder than the last. Use rule of three with a twist. One callback to the "
        "opening inside the set and one callback in the closer.\n"
        "7. SPECIFIC BEATS GENERIC. Exact amounts, times, relatives by name, brand types, a precise object. Numbers as words.\n"
        "8. SPOKEN HINGLISH. Hindi in Devanagari, English words in Latin script as Indians really say them. Light fillers "
        "(matlab, yaar, arre) but not in every line.\n"
        "9. COLD OPEN. Start with the joke, not a greeting speech. No \"Namaste doston, aaj main aapko batane wala hoon\". "
        "End on the biggest laugh, then one tiny sign-off aside (8 words max, for example \"Main Raj, aap sab ka shukriya, good night!\").\n"
        "10. NEVER write stage directions, brackets, asterisks, emojis, hashtags or speaker labels. Only spoken words.\n"
        "Output JSON only.\n\n"
        f"CHARACTER BIBLE:\n{character}"
    )
    avoid = "\n".join(f"- {r}" for r in recent) or "- (none yet)"
    draft = (
        f"Write ONE live stand-up set for Raj, performed to the room tonight.\n"
        f"TOPIC: {topic['topic']}  (kind: {topic['kind']}; if it is news, use it only as a light spark and pivot to "
        f"everyday life; never mention politics, religion, tragedy)\n"
        f"FORMAT FOR TONIGHT: {topic['format']}\n"
        f"SHAPE: cold-open hook (2 lines) -> bit 1 (setup, punch, tag) -> crowd-work moment -> bit 2 (escalates, "
        f"act-out with two voices) -> callback to the hook -> bit 3 (the biggest, with a tag) -> closer that calls back "
        f"to bit 1 -> tiny sign-off.\n"
        f"LENGTH: {lo} to {hi} words in total across all segments.\n"
        f"AVOID reusing these recent titles/openings:\n{avoid}\n\n{SCHEMA}"
    )
    return system, draft


def punch_up_prompt(cfg, draft_json):
    lo, hi = cfg["script"]["min_words"], cfg["script"]["max_words"]
    return (
        "You are the script doctor. Rewrite this draft so it performs like a LIVE stand-up set, then punch it up.\n"
        "LIVE PASS (most important):\n"
        "- Turn every piece of narration into in-the-moment performance: present tense, acted-out dialogue, direct address.\n"
        "- Delete story openers, summaries, explanations of jokes and any moral.\n"
        "- At least 8 lines speak straight to the audience. At least 5 questions to the room or self-interruptions.\n"
        "- Two or three crowd-work moments where Raj reacts to an imagined front-row reaction.\n"
        "PUNCH-UP PASS:\n"
        "- Cut filler and any line that is not funny. Shorter sentences. Punch lines 14 words or fewer.\n"
        "- The surprising word goes at the very END of each punch line.\n"
        "- Use specifics (a number, a brand type, a named relative) instead of generic words.\n"
        "- Rule of three with a twist, escalation, one callback to the opening, and a closer that calls back to bit 1.\n"
        "- Add a quick tag joke after the two best punch lines.\n"
        "- The first line must hook within 5 seconds. The last real line is the biggest laugh, then a tiny sign-off aside.\n"
        f"- Keep it between {lo} and {hi} words. Keep 22 to 30 segments and the same JSON shape.\n"
        "- Also add: \"title\" (max 70 chars, Hinglish, curiosity-driven, no clickbait lies), "
        "\"description\" (2 short lines, Hinglish), \"tags\" (8 to 12 short strings), "
        "\"thumb_text\" (max 4 words, Latin script, ALL CAPS, punchy).\n\n"
        f"DRAFT:\n{json.dumps(draft_json, ensure_ascii=False)}\n\n{SCHEMA}\n"
        "Plus the extra keys title, description, tags, thumb_text in the same JSON object."
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    args = ap.parse_args()
    cfg = load_config()

    if args.sample:
        script = normalize(json.loads(json.dumps(SAMPLE)), cfg)
        (BUILD / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")
        (BUILD / "topic.json").write_text(json.dumps({"topic": "smoke test", "kind": "sample", "format": "sample"}), encoding="utf-8")
        log("[writer] sample script written")
        return

    topic = json.loads((BUILD / "topic.json").read_text(encoding="utf-8"))
    used = json.loads((ROOT / "used_topics.json").read_text(encoding="utf-8"))
    recent = [f"{u.get('title', '')} | {u.get('opener', '')}" for u in used[-10:] if u.get("title")]
    system, draft_prompt = build_prompts(cfg, topic, recent)
    model = cfg["script"]["model"]
    lo, hi = cfg["script"]["min_words"], cfg["script"]["max_words"]

    feedback = ""
    for attempt in range(1, 5):
        log(f"[writer] attempt {attempt}: draft")
        draft = chat(model, system, draft_prompt + feedback, 0.95)
        log("[writer] punch-up")
        final = chat(model, system, punch_up_prompt(cfg, draft), 0.7)
        final = normalize(final, cfg)
        words, hits = count_words(final), banned_hit(final)
        log(f"[writer] words={words} segments={len(final['segments'])} banned={hits}")
        problems = []
        if not final["segments"]:
            problems.append("no segments")
        if words < lo - 30 or words > hi + 40:
            problems.append(f"word count {words} is outside {lo}-{hi}")
        if hits:
            problems.append(f"remove these forbidden words/topics: {hits}")
        style = style_problems(final)
        if style:
            log(f"[writer] style check: {style}")
            if attempt < 4:
                problems.extend(style)
            else:
                log("[writer] last attempt: accepting despite style warnings")
        if not problems:
            break
        feedback = "\n\nPREVIOUS ATTEMPT WAS REJECTED: " + "; ".join(problems) + ". Fix this."
    else:
        fail("Could not get an acceptable script after 4 attempts.")

    final["title"] = (final.get("title") or topic["topic"])[:95]
    final["description"] = final.get("description") or ""
    final["tags"] = [str(t)[:30] for t in (final.get("tags") or [])][:12]
    final["thumb_text"] = (final.get("thumb_text") or "NEW SET")[:28]
    final["_meta"] = {"topic": topic["topic"], "kind": topic["kind"], "format": topic["format"], "words": words}
    (BUILD / "script.json").write_text(json.dumps(final, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"[writer] title: {final['title']}")


if __name__ == "__main__":
    main()
