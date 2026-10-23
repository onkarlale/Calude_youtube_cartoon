import json, os, sys, datetime, random
import config, story, images, voice, video, thumbnail

HISTORY = "history.json"

def load_history():
    if os.path.exists(HISTORY):
        with open(HISTORY, encoding="utf-8") as f:
            return json.load(f)
    return []

def main():
    if not config.GROQ_API_KEY:
        sys.exit("GROQ_API_KEY is missing (check the GROQ_API_KEY_CLAUDE secret)")
    if not (config.CF_ACCOUNT_ID and config.CF_API_TOKEN):
        sys.exit("Cloudflare secrets missing: add CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN (see README).")
    if "hindi" in config.LANGUAGE.lower():
        import subprocess
        fonts = subprocess.run(["fc-list", ":lang=hi"], capture_output=True, text=True).stdout.strip()
        if not fonts:
            sys.exit("No Hindi (Devanagari) font installed. Add fonts-noto-core to the apt install step in daily.yml.")
    history = load_history()
    titles = [h["title"] for h in history]

    print("1/5 Writing story...")
    data = story.generate_story(titles)
    print("   Title:", data["title"])

    day = datetime.date.today().isoformat()
    outdir = os.path.join("out", day)
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "story.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    seed = random.randint(1, 10**6)
    scenes = []
    print("2/5 Drawing scenes + recording voice...")
    default_moves = ["zoom_in", "pan_right", "zoom_out", "pan_left"]
    for i, sc in enumerate(data["scenes"]):
        img = f"scene{i:02d}.jpg"
        aud = f"scene{i:02d}.mp3"
        prompt = f"{data['characters']}. {sc['image_prompt']}"
        images.make_image(prompt, os.path.join(outdir, img), seed)
        voice.synth(sc["narration"], os.path.join(outdir, aud), config.TTS_VOICE, config.TTS_RATE)
        dur = voice.duration(os.path.join(outdir, aud))
        motion = sc.get("motion") if sc.get("motion") in video.MOTIONS else default_moves[i % 4]
        sfx = sc.get("sfx") if sc.get("sfx") in video.SFX else "none"
        scenes.append({"image": img, "audio": aud, "dur": dur, "text": sc["narration"],
                       "motion": motion, "sfx": sfx})
        print(f"   scene {i+1}/{len(data['scenes'])} done ({dur:.1f}s, {motion}, sfx={sfx})")

    print("3/5 Rendering video...")
    final = video.build(scenes, outdir)

    print("4/5 Thumbnail...")
    # use the "punchiest" scene (a punch or shake moment) for the thumbnail if there is one
    pick = next((s for s in scenes if s["motion"] in ("punch", "shake")), scenes[0])
    thumb = thumbnail.make(os.path.join(outdir, pick["image"]), data["title"],
                           os.path.join(outdir, "thumb.jpg"))

    print("5/5 Uploading...")
    vid = None
    if config.YT_REFRESH_TOKEN and config.YT_CLIENT_ID and config.YT_CLIENT_SECRET:
        import upload
        desc = data["description"] + "\n\nThis story and its visuals were created with AI."
        vid = upload.upload(final, data["title"], desc, data["tags"], thumb)
    else:
        print("   YouTube secrets not set -> skipping upload (video saved in", outdir + ")")

    history.append({"date": day, "title": data["title"], "video_id": vid})
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print("Done.")

if __name__ == "__main__":
    main()
