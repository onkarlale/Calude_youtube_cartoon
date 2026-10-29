#!/usr/bin/env python3
"""Upload build/final.mp4 to YouTube (resumable), set thumbnail, record the topic as used.

Env: YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN
Arg: --privacy private|unlisted|public   (default: config.json "privacy")
"""
import argparse
import json
import os
import sys
import time
from datetime import date

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import BUILD, ROOT, fail, load_config, log  # noqa: E402

DISCLOSURE = (
    "\n\nThis is an AI-generated comedy performance. The comedian, voice and audience are synthetic. "
    "Any resemblance to real people is coincidental."
)


def get_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    try:
        creds = Credentials(
            token=None,
            refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
            client_id=os.environ["YOUTUBE_CLIENT_ID"],
            client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
            token_uri="https://oauth2.googleapis.com/token",
        )
    except KeyError as e:
        fail(f"Missing env var {e}")
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def insert(yt, body, path):
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    media = MediaFileUpload(path, chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp, tries = None, 0
    while resp is None:
        try:
            status, resp = req.next_chunk()
            if status:
                log(f"[upload] {int(status.progress() * 100)}%")
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and tries < 5:
                tries += 1
                time.sleep(2 ** tries)
                continue
            raise
    return resp


def _hashtag(word_text):
    """'stand up comedy' -> '#StandUpComedy' (letters/digits/marks only, Hindi letters allowed)."""
    import unicodedata
    parts = []
    for w in str(word_text).replace("#", " ").split():
        w = "".join(ch for ch in w if unicodedata.category(ch)[0] in "LMN")
        if w:
            parts.append(w[:1].upper() + w[1:])
    tag = "".join(parts)
    return "#" + tag if 2 <= len(tag) <= 28 else ""


def build_hashtags(cfg, script, limit=12):
    """Channel hashtags first (YouTube shows the first 3 above the title), then topical ones from the script tags.
    YouTube ignores ALL hashtags if a video has more than 15, so we stay at 12 or fewer."""
    out, seen = [], set()
    candidates = [h for h in cfg.get("hashtags", ["#StandUpComedy", "#HindiComedy", "#IndianComedy", "#Comedy"])]
    candidates += [_hashtag(t) for t in script.get("tags", [])]
    for h in candidates:
        h = _hashtag(h) if h else ""
        if h and h.lower() not in seen:
            seen.add(h.lower())
            out.append(h)
        if len(out) >= limit:
            break
    return " ".join(out)


def main():
    from googleapiclient.errors import HttpError

    ap = argparse.ArgumentParser()
    ap.add_argument("--privacy", default=None)
    args = ap.parse_args()
    cfg = load_config()
    privacy = args.privacy or cfg["privacy"]

    script = json.loads((BUILD / "script.json").read_text(encoding="utf-8"))
    topic = json.loads((BUILD / "topic.json").read_text(encoding="utf-8"))
    final = BUILD / "final.mp4"
    if not final.exists():
        fail("build/final.mp4 not found")

    tags, total = [], 0
    for t in script.get("tags", []):
        t = str(t).replace("<", "").replace(">", "").strip()
        if t and total + len(t) < 450:
            tags.append(t)
            total += len(t) + 1
    title = (script.get("title") or topic["topic"])[:100].replace("<", "").replace(">", "")
    desc = (script.get("description") or "") + DISCLOSURE + "\n\n" + build_hashtags(cfg, script)

    yt_cfg = cfg["youtube"]
    body = {
        "snippet": {"title": title, "description": desc, "tags": tags, "categoryId": yt_cfg["category_id"],
                    "defaultLanguage": "hi", "defaultAudioLanguage": "hi"},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": yt_cfg["made_for_kids"],
                   "containsSyntheticMedia": yt_cfg["contains_synthetic_media"]},
    }

    yt = get_service()
    log(f"[upload] '{title}' as {privacy}")
    try:
        resp = insert(yt, body, str(final))
    except HttpError as e:
        if "containsSyntheticMedia" in str(e):
            log("[upload] API rejected containsSyntheticMedia; retrying without it. "
                "Set the 'altered content' disclosure manually in YouTube Studio.")
            body["status"].pop("containsSyntheticMedia")
            resp = insert(yt, body, str(final))
        else:
            raise
    vid = resp["id"]
    log(f"[upload] https://youtu.be/{vid}")
    actual = (resp.get("status") or {}).get("privacyStatus")
    log(f"[upload] requested privacy: {privacy} | YouTube set it to: {actual}")
    if actual and actual != privacy:
        log("::warning::YouTube did NOT apply the requested privacy. This happens when the Google Cloud project is unverified "
            "(YouTube locks API uploads to private until the project passes the API compliance audit). "
            "Open YouTube Studio -> Content and set the video to Public by hand, or apply for the audit: "
            "https://support.google.com/youtube/contact/yt_api_form")

    thumb = BUILD / "thumb.jpg"
    if thumb.exists():
        try:
            from googleapiclient.http import MediaFileUpload
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb))).execute()
            log("[upload] thumbnail set")
        except HttpError as e:
            log(f"[upload] thumbnail failed (is the channel phone-verified?): {str(e)[:200]}")

    if topic.get("kind") != "sample":
        path = ROOT / "used_topics.json"
        used = json.loads(path.read_text(encoding="utf-8"))
        used.append({"date": date.today().isoformat(), "topic": topic["topic"], "format": topic.get("format"),
                     "title": title, "opener": script["segments"][0]["text"][:80], "video_id": vid})
        path.write_text(json.dumps(used[-400:], ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
