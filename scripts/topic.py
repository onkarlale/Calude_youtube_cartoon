#!/usr/bin/env python3
"""Pick today's topic + comedy format. Writes build/topic.json.

Uses mild news (tech / business / entertainment / sports / health RSS) as a spark about
half the time and evergreen relatable topics otherwise. Politics, religion, tragedy etc. are filtered.
"""
import difflib
import json
import random
import re
import sys
from datetime import date

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import BUILD, ROOT, log  # noqa: E402

FEEDS = [
    "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/headlines/section/topic/ENTERTAINMENT?hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/headlines/section/topic/HEALTH?hl=en-IN&gl=IN&ceid=IN:en",
]

FORMATS = [
    "live crowd work: talk to the front row, answer for them, then spiral",
    "act-out: re-enact one scene live with 2 or 3 voices (Mummy, Papa, Gupta sir) and react after each line",
    "rant that keeps interrupting itself and getting angrier",
    "audience poll: 'haath uthao agar...' then roast the situation (never the people)",
    "then vs now, performed to the room (childhood vs adult life)",
    "expectation vs reality in 4 rounds, said straight to the crowd",
    "if this thing were brutally honest, act out its voice and argue with it",
    "things I am too old for now, listed live while the room agrees",
]

BLOCK = re.compile(
    r"\b(modi|bjp|congress|aap|kejriwal|rahul|yogi|election|poll|minister|government|court|supreme|"
    r"police|arrest|murder|killed|dead|death|dies|died|rape|attack|terror|riot|war|army|border|"
    r"hindu|muslim|islam|christian|sikh|caste|dalit|temple|mosque|church|religion|communal|"
    r"suicide|accident|crash|blast|flood|earthquake|covid|cancer|virus)\b", re.I)


def norm(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def too_similar(topic, used):
    n = norm(topic)
    return any(difflib.SequenceMatcher(None, n, norm(u.get("topic", ""))).ratio() > 0.6 for u in used)


def news_candidates():
    try:
        import feedparser
    except ImportError:
        return []
    out = []
    for url in FEEDS:
        try:
            d = feedparser.parse(url)
            for e in d.entries[:25]:
                title = re.sub(r"\s+-\s+[^-]{2,40}$", "", e.title).strip()  # drop " - Publisher"
                if 20 <= len(title) <= 140 and not BLOCK.search(title):
                    out.append(title)
        except Exception as ex:  # noqa: BLE001
            log(f"[topic] feed failed: {url[:60]}... {ex}")
    return out


def main():
    used = json.loads((ROOT / "used_topics.json").read_text(encoding="utf-8"))
    evergreen = [l.strip() for l in (ROOT / "data/evergreen_topics.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    rnd = random.Random(date.today().toordinal())

    topic, kind = None, "evergreen"
    if rnd.random() < 0.5:
        cands = [c for c in news_candidates() if not too_similar(c, used)]
        if cands:
            topic, kind = rnd.choice(cands), "news"
    if topic is None:
        fresh = [t for t in evergreen if not too_similar(t, used)]
        if not fresh:  # everything used once: reuse the oldest-used topics
            order = {u["topic"]: i for i, u in enumerate(used)}
            fresh = sorted(evergreen, key=lambda t: order.get(t, -1))[:10]
        topic = rnd.choice(fresh)

    recent_formats = [u.get("format") for u in used[-3:]]
    fmt = rnd.choice([f for f in FORMATS if f not in recent_formats] or FORMATS)

    result = {"topic": topic, "kind": kind, "format": fmt, "date": date.today().isoformat()}
    (BUILD / "topic.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"[topic] {kind}: {topic}\n[topic] format: {fmt}")


if __name__ == "__main__":
    main()
