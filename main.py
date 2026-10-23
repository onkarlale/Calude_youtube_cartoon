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
    for i, sc in enumerate(data["scenes"]):
        img = f"scene{i:02d}.jpg"
        aud = f"scene{i:02d}.mp3"
        prompt = f"{data['characters']}. {sc['image_prompt']}"
        images.make_image(prompt, os.path.join(outdir, img), seed)
        voice.synth(sc["narration"], os.path.join(outdir, aud), config.TTS_VOICE)
        dur = voice.duration(os.path.join(outdir, aud))
        scenes.append({"image": img, "audio": aud, "dur": dur, "text": sc["narration"]})
        print(f"   scene {i+1}/{len(data['scenes'])} done ({dur:.1f}s)")

    print("3/5 Rendering video...")
    final = video.build(scenes, outdir)

    print("4/5 Thumbnail...")
    thumb = thumbnail.make(os.path.join(outdir, scenes[0]["image"]), data["title"],
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
