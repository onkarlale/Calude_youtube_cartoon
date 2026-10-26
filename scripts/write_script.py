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
    {"text": "one or two spoken sentences", "role": "setup|punch|aside", "pause_after_ms": 300}
  ]
}
- role "punch": the line ends with the funniest word LAST (the audience laughs after it).
- role "setup": builds the situation. role "aside": quick muttered side remark.
- Each segment is spoken in one breath: at most 25 words."""

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


def chat(model, system, user, temperature):
    for attempt in range(4):
        r = requests.post(
            API,
            headers={"Authorization": f"Bearer {groq_key()}"},
            json={
                "model": model,
                "temperature": temperature,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            },
            timeout=120,
        )
        if r.status_code == 200:
            return json.loads(r.json()["choices"][0]["message"]["content"])
        log(f"[writer] Groq HTTP {r.status_code}: {r.text[:200]}")
        time.sleep(5 * (attempt + 1))
    fail("Groq API kept failing.")


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


def build_prompts(cfg, topic, recent):
    character = (ROOT / "assets/character.md").read_text(encoding="utf-8")
    lo, hi = cfg["script"]["min_words"], cfg["script"]["max_words"]
    system = (
        "You are the head writer of a hit Hindi stand-up comedy channel. You write jokes that are specific, "
        "surprising and perform well out loud. Generic observations are failures. Output JSON only.\n\n"
        f"CHARACTER BIBLE:\n{character}"
    )
    avoid = "\n".join(f"- {r}" for r in recent) or "- (none yet)"
    draft = (
        f"Write ONE stand-up set for Raj.\n"
        f"TOPIC: {topic['topic']}  (kind: {topic['kind']}; if it is news, use it only as a light spark and pivot to "
        f"everyday life; never mention politics, religion, tragedy)\n"
        f"FORMAT FOR TODAY: {topic['format']}\n"
        f"LANGUAGE: spoken Hinglish. Hindi in Devanagari; English words in Latin script when Indians say them in English. "
        f"Write numbers as words (e.g. पाँच सौ रुपये), never digits. No emojis.\n"
        f"LENGTH: {lo} to {hi} words in total across all segments.\n"
        f"AVOID reusing these recent titles/openings:\n{avoid}\n\n{SCHEMA}"
    )
    return system, draft


def punch_up_prompt(cfg, draft_json):
    lo, hi = cfg["script"]["min_words"], cfg["script"]["max_words"]
    return (
        "Punch up this stand-up draft like a ruthless comedy script doctor.\n"
        "- Cut filler and any line that is not funny. Shorter sentences.\n"
        "- Put the surprising word at the very END of each punchline.\n"
        "- Use specifics (a number, a brand type, a named relative) instead of generic words.\n"
        "- Use rule of three with a twist, escalation, and at least one callback to the opening.\n"
        "- Add a quick tag joke (role aside or punch) after the two best punchlines.\n"
        "- The first line must hook within 5 seconds. The last line must be the biggest laugh.\n"
        f"- Keep it between {lo} and {hi} words. Keep the same JSON shape.\n"
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
