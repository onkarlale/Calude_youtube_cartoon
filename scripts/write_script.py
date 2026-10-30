#!/usr/bin/env python3
"""Comedy writer: Gemini writes a draft, a punch-up, then a tough-audience rewrite (Groq is only a backup).
Writes build/script.json.

  python scripts/write_script.py            # real run (needs build/topic.json + GEMINI_API_KEY)
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
from llm import gemini_available, gemini_chat, parse_json  # noqa: E402

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
    return os.environ.get("GROQ_API_KEY_CLAUDE") or os.environ.get("GROQ_API_KEY") or ""


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


_parse_json = parse_json


def groq_chat(model, system, user, temperature):
    if not groq_key():
        return None
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
    log("[writer] Groq backup failed too")
    return None


def chat(model, system, user, temperature):
    """Ask the configured AI writers in order (Gemini first, Groq as backup). Returns a dict."""
    scfg = load_config().get("script", {})
    level = scfg.get("thinking", "medium")
    for prov in scfg.get("providers", ["gemini", "groq"]):
        if prov == "gemini" and gemini_available():
            out = gemini_chat(system, user, temperature, thinking=level)
            if out is not None:
                return out
            log("[writer] Gemini did not work on any model in GEMINI_MODELS")
        elif prov == "groq" and groq_key():
            out = groq_chat(model, system, user, temperature)
            if out is not None:
                return out
    fail("No AI writer produced a script. Add the GEMINI_API_KEY secret (Google AI Studio key); GEMINI_MODELS is optional.")


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


FAMILY_BANNED = [
    "हरामी", "कमीना", "कमीने", "बकचोद", "चूतिया", "भोसड़ी", "गांड", "लौड़ा", "चोद", "सेक्स", "शराब", "दारू", "सिगरेट",
    "नशा", "हनीमून", "सुहागरात", "harami", "kamina", "kameena", "bakchod", "chutiya", "gaand", "bhosd", "sex", "porn",
    "condom", "drunk", "whisky", "vodka", "beer", "cigarette", "hangover", "suhaagraat", "honeymoon", "bedroom",
]


def family_hits(script):
    blob = " ".join(sg["text"] for sg in script.get("segments", [])).lower()
    return [w for w in FAMILY_BANNED if w.lower() in blob]


STYLE_REFERENCE = """STYLE REFERENCE. This is a DIFFERENT topic. It shows only the RHYTHM, the live feel and the joke
mechanics. Never reuse any of its jokes, its topic (the router) or its wording.
[
 {"text":"हाथ उठाओ, जिनके घर में कोई router को 'इंटरनेट का डिब्बा' बोलता है!","role":"aside"},
 {"text":"मेरे पापा के लिए वो डिब्बा है, और डिब्बे की एक ही दवाई है: प्लग निकालो.","role":"setup"},
 {"text":"फिर वो दस तक गिनते हैं, जैसे डिब्बे की नब्ज़ देख रहे हों.","role":"punch"},
 {"text":"नेट बंद हो तो पापा बोलते हैं, 'बेटा, डिब्बा देखना.' मैं बोलता हूँ, 'पापा, बिल भरा है?'","role":"setup"},
 {"text":"वो बोलते हैं, 'लाइट तो हरी जल रही है!' जैसे हरी लाइट मतलब ज़िंदगी सेट.","role":"punch"},
 {"text":"आप हँस रहे हो? सच बोलो, आपके पापा भी यही करते हैं ना?","role":"aside"},
 {"text":"फिर मैं कंपनी को फ़ोन करता हूँ. Customer care वाली मैडम बोलती हैं, 'सर, router restart करें.'","role":"setup"},
 {"text":"पापा तुरंत बोले, 'देखा? मैडम भी मेरी तरफ़ हैं!'","role":"punch"},
 {"text":"अब इस घर में नेट ठीक करने के तीन तरीके हैं: प्लग निकालना, प्लग लगाना, और मुझे बुलाना.","role":"setup"},
 {"text":"और तीसरे में सबसे ज़्यादा टाइम लगता है, क्योंकि मैं office में हूँ.","role":"punch"},
 {"text":"कल मैंने उन्हें समझाया, 'पापा, WiFi हवा में चलता है.'","role":"setup"},
 {"text":"बोले, 'हवा में चलता है तो पीछे तार क्यों लगा है?' मेरे पास जवाब नहीं था.","role":"punch"},
 {"text":"नहीं नहीं, रुको, यह तो कुछ नहीं. सुनो आगे.","role":"aside"},
 {"text":"आज सुबह पूछते हैं, 'डिब्बे का password क्या है?' मैंने कहा, 'पापा, आपने ही रखा था.'","role":"setup"},
 {"text":"बोले, 'हाँ, तभी तो भूल गया!' तो अगली बार कोई 'डिब्बा' बोले, समझ जाना, घर में एक पापा हैं.","role":"punch"}
]
Notice: it opens by talking to the room; every setup is 1 or 2 short sentences; the surprise word is last; Dad's
dialogue is acted out; there is a rule of three with a twist; the final line calls back to the first.
"""

CRAFT = (
    "COMEDY CRAFT TOOLBOX (use at least five of these): MISDIRECTION (lead the audience one way, land somewhere else); "
    "SPECIFICITY (a number, a name, an exact object beats a general word); RULE OF THREE with a twist on the third; "
    "ACT-OUT (let two or three voices argue); ESCALATION (each beat is bigger and weirder than the last); SELF-ROAST "
    "(Raj is the fool, not the audience); CALLBACK (return to an earlier line with a new meaning); TAG (a second punch on "
    "the same joke right after the laugh); REVERSAL (the confident person is wrong); EXAGGERATION to an absurd scale; "
    "UNDERSTATEMENT after a big claim.\n"
    "FIND THE FRESH ANGLE: the topic is only a seed. Do not make the first joke everyone makes. Look for the specific, "
    "slightly odd detail that makes an Indian family or office nod and say 'haan, yehi hota hai'.\n"
    "SELF-CHECK before you answer: read every line out loud. Does it sound SAID, not written? Is the surprise the LAST "
    "word of every punch line? Is there a joke, a reaction or a question in every group of 3 lines? Fix anything that fails.\n"
)


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


def estimate_seconds(script, cfg):
    """Rough length of the performance: ~2.6 spoken words per second + the pauses + lead/tail."""
    words = sum(len(sg["text"].split()) for sg in script["segments"])
    pauses = sum(int(sg.get("pause_after_ms", 300)) for sg in script["segments"]) / 1000
    t = cfg.get("timing", {})
    return words / 2.6 + pauses + (t.get("lead_ms", 500) + t.get("tail_ms", 1200)) / 1000


ADULT_RULES = (
    "ADULT (18+) COMEDY IS ALLOWED. The audience is adults who came for a late-night, no-filter show. You MAY use: "
    "dating, marriage and 'situationship' disasters, awkward intimacy and wedding-night nerves, flirting fails, "
    "drinking and hangovers, adult double meanings and innuendo, roasting Raj himself and his own life, and mild to "
    "moderate Hinglish swearing (saala, kameena, harami, bakchod, 'bakwaas'). The dirty part lives in the audience's "
    "head: IMPLY, never describe sexual acts, never use explicit anatomy words, never use mother/sister abuse words. "
    "HARD LIMITS (never): jokes that attack a religion, caste, region, gender, disability or sexuality; slurs; sexual "
    "content involving minors or without consent; real named people; politics, elections or tragedies; self-harm.\n"
)
TEEN_RULES = (
    "AUDIENCE: EVERYONE, 13 and older, parents and teenagers watching together. Make the whole family laugh. "
    "Warm, relatable, clever humour about family, relatives, school and college, office life, phones, food, traffic, "
    "money (EMI, salary), weddings, neighbours, WhatsApp groups, travel and everyday embarrassment. Roast situations and "
    "Raj himself, never people. NEVER: swearing or insults (not even mild words like saala, kameena, harami), sexual "
    "content or innuendo, dating-bedroom jokes, alcohol, drugs or smoking jokes, violence, anything cruel, scary or "
    "gross, or jokes that attack a religion, caste, region, gender, disability or sexuality. No politics, no real named people.\n"
)
CLEAN_RULES = TEEN_RULES

SHORTS_RULES = (
    "THIS IS A VERTICAL YOUTUBE SHORT told in 2 to 2.5 minutes of speech. Retention is everything:\n"
    "S1. The very first line must stop the scroll within 2 seconds: at most 10 words, a bold, cheeky or painfully "
    "relatable claim. No greeting, no introduction.\n"
    "S2. Something funny at least every 10 to 12 seconds (a punch line every 3 or 4 lines). A setup is at most two "
    "short sentences. Cut every slow moment.\n"
    "S3. The LAST line is the biggest laugh and calls back to the FIRST line so a replay feels seamless. NO sign-off, "
    "no 'thank you', no 'good night', no 'subscribe'.\n"
    "S4. Make people want to comment: include one line that provokes a fight or a confession ('Comment karo, kaun kaun...').\n"
)


def build_prompts(cfg, topic, recent):
    character = (ROOT / "assets/character.md").read_text(encoding="utf-8")
    lo, hi = cfg["script"]["min_words"], cfg["script"]["max_words"]
    shorts = cfg.get("format", "shorts") == "shorts"
    ADULT_RULES_USED = ADULT_RULES if cfg.get("audience", "teen") == "adult" else TEEN_RULES
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
        + ("End on the biggest laugh that calls back to the first line. No sign-off.\n" if shorts else
           "End on the biggest laugh, then one tiny sign-off aside (8 words max, for example \"Main Raj, aap sab ka shukriya, good night!\").\n") +
        "10. NEVER write stage directions, brackets, asterisks, emojis, hashtags or speaker labels. Only spoken words.\n"
        + CRAFT + ADULT_RULES_USED + (SHORTS_RULES if shorts else "") +
        "Output JSON only.\n\n"
        f"{STYLE_REFERENCE}\n"
        f"CHARACTER BIBLE:\n{character}"
    )
    avoid = "\n".join(f"- {r}" for r in recent) or "- (none yet)"
    draft = (
        f"Write ONE live stand-up set for Raj, performed to the room tonight.\n"
        f"TOPIC: {topic['topic']}  (kind: {topic['kind']}; if it is news, use it only as a light spark and pivot to "
        f"everyday life; never mention politics, religion, tragedy)\n"
        f"FORMAT FOR TONIGHT: {topic['format']}\n"
        + (f"SHAPE: scroll-stopping first line -> bit 1 (setup, punch, tag) -> crowd-work moment -> bit 2 (escalates, "
           f"act-out with two voices) -> bit 3 (the biggest, with a tag) -> final line that calls back to the FIRST line. "
           f"No sign-off.\n" if shorts else
           f"SHAPE: cold-open hook (2 lines) -> bit 1 (setup, punch, tag) -> crowd-work moment -> bit 2 (escalates, "
           f"act-out with two voices) -> callback to the hook -> bit 3 (the biggest, with a tag) -> closer that calls back "
           f"to bit 1 -> tiny sign-off.\n") +
        f"LENGTH: {lo} to {hi} words in total across all segments.\n"
        f"AVOID reusing these recent titles/openings:\n{avoid}\n\n{SCHEMA}"
    )
    return system, draft


def punch_up_prompt(cfg, draft_json):
    lo, hi = cfg["script"]["min_words"], cfg["script"]["max_words"]
    shorts = cfg.get("format", "shorts") == "shorts"
    return (
        "You are the script doctor. Rewrite this draft so it performs like a LIVE stand-up set, then punch it up.\n"
        + ("Keep it suitable for ages 13+ and the whole family: no swearing, no sexual or alcohol jokes, nothing cruel.\n"
           if cfg.get("audience", "teen") != "adult" else "") +
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
        + ("- The first line must stop the scroll within 2 seconds (max 10 words). The LAST line is the biggest laugh and "
           "calls back to the first line. Delete any sign-off. A laugh at least every 10 to 12 seconds.\n" if shorts else
           "- The first line must hook within 5 seconds. The last real line is the biggest laugh, then a tiny sign-off aside.\n") +
        f"- Keep it between {lo} and {hi} words. Keep 22 to 30 segments and the same JSON shape.\n"
        "- Also add: \"title\" (max 70 chars, Hinglish, curiosity-driven, no clickbait lies), "
        "\"description\" (2 short lines, Hinglish; the first line is a question to the viewer that makes them comment), "
        "\"tags\" (8 to 12 short strings), "
        "\"thumb_text\" (max 4 words, Latin script, ALL CAPS, punchy; it is also the on-screen hook banner in the first seconds).\n\n"
        f"DRAFT:\n{json.dumps(draft_json, ensure_ascii=False)}\n\n{SCHEMA}\n"
        "Plus the extra keys title, description, tags, thumb_text in the same JSON object."
    )


def crowd_test_prompt(cfg, segments_json):
    lo, hi = cfg["script"]["min_words"], cfg["script"]["max_words"]
    family = cfg.get("audience", "teen") != "adult"
    return (
        "You are a TOUGH comedy-club audience of 200 people AND a ruthless comedy editor. Below is the spoken set "
        "(Hinglish) that Raj will perform. Step 1: for every line, decide honestly whether it gets a BIG laugh, a smile, "
        "nothing, or confusion. Step 2: rewrite EVERY line that will not get at least a smile, every line that sounds "
        "written instead of spoken, every setup that is too slow, and every punch line whose last word is not the surprise. "
        "Keep the lines that already work word for word.\n"
        "RULES: keep the opening line's job (a scroll-stopping hook) and keep the final line calling back to the first. "
        "Keep the acted-out dialogue, the crowd-work questions and the same JSON shape. "
        f"Keep the total between {lo} and {hi} words and 22 to 30 segments. Punch lines stay at 14 words or fewer. "
        + ("Keep it family friendly (ages 13+): no swearing, no sexual, alcohol or cruel jokes. " if family else "")
        + "No story openers ('ek din'), no morals, no explanations of jokes, no stage directions.\n\n"
        f"SET:\n{json.dumps(segments_json, ensure_ascii=False)}\n\n{SCHEMA}"
    )


def crowd_test(cfg, system, final, model, before_problems):
    """Third pass: rewrite the lines a tough audience would not laugh at. Keeps the old script if the rewrite is worse."""
    log("[writer] tough-audience rewrite")
    try:
        out = chat(model, system, crowd_test_prompt(cfg, {"segments": final["segments"]}), 0.9)
    except SystemExit:
        log("[writer] tough-audience pass unavailable; keeping the punched-up script")
        return final
    cand = normalize({"segments": (out or {}).get("segments", [])}, cfg)
    segs = cand["segments"]
    lo, hi = cfg["script"]["min_words"], cfg["script"]["max_words"]
    candidate = dict(final)
    candidate["segments"] = segs
    words = count_words(candidate)
    cap = cfg.get("shorts", {}).get("max_seconds", 175) if cfg.get("format", "shorts") == "shorts" else None
    bad = []
    if not (18 <= len(segs) <= 34):
        bad.append(f"{len(segs)} segments")
    if words < lo - 40 or words > hi + 50:
        bad.append(f"{words} words")
    if banned_hit(candidate):
        bad.append("banned words")
    if cfg.get("audience", "teen") != "adult" and family_hits(candidate):
        bad.append("adult words")
    if cap and estimate_seconds(candidate, cfg) > cap * 1.12:
        bad.append("too long")
    if len(style_problems(candidate)) > len(before_problems):
        bad.append("sounds more like a story")
    if bad:
        log(f"[writer] rewrite rejected ({', '.join(bad)}); keeping the punched-up script")
        return final
    changed = sum(1 for a, b in zip(final["segments"], segs) if a["text"] != b["text"])
    log(f"[writer] tough-audience rewrite accepted ({changed} lines changed, {words} words)")
    return candidate


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
        if cfg.get("audience", "teen") != "adult":
            fam = family_hits(final)
            if fam:
                problems.append(f"remove adult/swearing words (the show is for ages 13+ and the whole family): {fam}")
        est = estimate_seconds(final, cfg)
        cap = cfg.get("shorts", {}).get("max_seconds", 175) if cfg.get("format", "shorts") == "shorts" else None
        if cap and est > cap * 1.12:
            problems.append(f"too long: about {est:.0f}s of speech, must be under {cap * 1.1:.0f}s. Cut about {int((est - cap) * 2.4)} words")
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

    if cfg.get("script", {}).get("crowd_test", True):
        final = crowd_test(cfg, system, final, model, style_problems(final))
        words = count_words(final)
    final["title"] = (final.get("title") or topic["topic"])[:95]
    final["description"] = final.get("description") or ""
    final["tags"] = [str(t)[:30] for t in (final.get("tags") or [])][:12]
    final["thumb_text"] = (final.get("thumb_text") or "NEW SET")[:28]
    final["_meta"] = {"topic": topic["topic"], "kind": topic["kind"], "format": topic["format"], "words": words}
    (BUILD / "script.json").write_text(json.dumps(final, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"[writer] title: {final['title']}")


if __name__ == "__main__":
    main()
