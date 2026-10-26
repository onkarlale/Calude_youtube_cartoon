#!/usr/bin/env python3
"""FFmpeg editor: talking head + audience cutaways + laugh track + captions + intro/outro + loudness.

  python scripts/edit.py --mode lipsync    # uses build/render/talking.mp4
  python scripts/edit.py --mode fallback   # uses assets/comedian.png (slow zoom), no lip sync

Needs: build/script.json, build/render/{voice.wav,timings.json}. Writes build/final.mp4 and build/thumb.jpg.
"""
import argparse
import json
import random
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import BUILD, ROOT, fail, load_config, log, sh  # noqa: E402

W, H, FPS = 1920, 1080, 25
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
MAX_CUTAWAYS = 10


# ---------------------------------------------------------------- captions
def ass_time(t):
    cs = int(round(t * 100))
    return f"{cs // 360000}:{(cs // 6000) % 60:02d}:{(cs // 100) % 60:02d}.{cs % 100:02d}"


def caption_events(text, start, end, maxc=34):
    text = text.replace("{", "").replace("}", "")
    lines, cur = [], ""
    for w in text.split():
        if cur and len(cur) + 1 + len(w) > maxc:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    groups = [lines[i:i + 2] for i in range(0, len(lines), 2)]
    total = sum(len(" ".join(g)) for g in groups) or 1
    t, events = start, []
    for g in groups:
        d = (end - start) * len(" ".join(g)) / total
        events.append((t, t + d, "\\N".join(g)))
        t += d
    return events


def write_ass(timings, path):
    head = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\nWrapStyle: 2\n\n"
        "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
        "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,"
        "MarginL,MarginR,MarginV,Encoding\n"
        "Style: Default,Noto Sans Devanagari,58,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,1,2,80,80,70,1\n\n"
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )
    rows = []
    for seg in timings["segments"]:
        for a, b, txt in caption_events(seg["text"], seg["start"], seg["end"] + 0.15):
            rows.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Default,,0,0,0,,{txt}")
    Path(path).write_text(head + "\n".join(rows) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- sound effects
def real_samples(prefix):
    d = ROOT / "assets/sfx"
    return sorted(p for p in d.glob(f"{prefix}*") if p.suffix.lower() in (".mp3", ".wav", ".ogg", ".m4a"))


def make_laugh(path, dur, seed):
    rnd = random.Random(seed)
    samples = real_samples("laugh")
    if samples:
        src = rnd.choice(samples)
        sh(["ffmpeg", "-y", "-i", str(src), "-t", f"{dur:.2f}", "-af",
            f"afade=t=in:d=0.1,afade=t=out:st={max(dur - 0.5, 0.1):.2f}:d=0.5", "-ar", "48000", "-ac", "1", str(path)])
        return
    f = rnd.uniform(5.5, 8.5)
    lo, hi = rnd.randint(250, 450), rnd.randint(2800, 4200)
    af = (f"highpass=f={lo},lowpass=f={hi},tremolo=f={f:.1f}:d=0.75,"
          f"afade=t=in:st=0:d=0.25,afade=t=out:st={max(dur - 0.7, 0.1):.2f}:d=0.7,volume=1.6")
    sh(["ffmpeg", "-y", "-f", "lavfi", "-i", f"anoisesrc=d={dur:.2f}:c=pink:r=48000:a=0.5:s={seed}",
        "-af", af, "-ac", "1", str(path)])


def make_applause(path, dur):
    samples = real_samples("applause")
    if samples:
        sh(["ffmpeg", "-y", "-i", str(samples[0]), "-t", f"{dur:.2f}", "-af",
            f"afade=t=in:d=0.3,afade=t=out:st={max(dur - 1.0, 0.1):.2f}:d=1.0", "-ar", "48000", "-ac", "1", str(path)])
        return
    af = (f"highpass=f=1800,lowpass=f=7500,tremolo=f=16:d=0.9,afade=t=in:d=0.4,"
          f"afade=t=out:st={max(dur - 1.2, 0.1):.2f}:d=1.2,volume=1.2")
    sh(["ffmpeg", "-y", "-f", "lavfi", "-i", f"anoisesrc=d={dur:.2f}:c=white:r=48000:a=0.6:s=7",
        "-af", af, "-ac", "1", str(path)])


def build_audio(timings, voice, out_wav, windows):
    total = timings["total"]
    inputs = ["-i", str(voice)]
    filters = ["[0:a]aresample=48000,volume=1.0[a0]"]
    labels = ["[a0]"]
    idx = 1

    def add(path, start_s, vol):
        nonlocal idx
        inputs.extend(["-i", str(path)])
        ms = max(int(start_s * 1000), 0)
        filters.append(f"[{idx}:a]aresample=48000,adelay={ms}|{ms},volume={vol}[a{idx}]")
        labels.append(f"[a{idx}]")
        idx += 1

    # applause at the start and end
    p = BUILD / "sfx_applause_start.wav"
    make_applause(p, 2.2)
    add(p, 0.2, 0.45)
    p = BUILD / "sfx_applause_end.wav"
    make_applause(p, 3.4)
    last = timings["segments"][-1]
    add(p, last["end"] + 0.35, 0.55)

    # laugh after every punchline
    for k, seg in enumerate(s for s in timings["segments"] if s["laugh"]):
        dur = min(seg["pause"] + 0.5, 3.0)
        p = BUILD / f"sfx_laugh_{k}.wav"
        make_laugh(p, dur, seed=k + 11)
        add(p, seg["end"] + 0.12, round(random.Random(k).uniform(0.28, 0.42), 2))

    # quiet room tone
    inputs.extend(["-f", "lavfi", "-i", f"anoisesrc=d={total:.2f}:c=brown:r=48000:a=0.3:s=3"])
    filters.append(f"[{idx}:a]lowpass=f=600,volume=0.05[a{idx}]")
    labels.append(f"[a{idx}]")

    filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=first,"
                   f"loudnorm=I=-14:TP=-1.5:LRA=11[mix]")
    sh(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filters), "-map", "[mix]",
        "-t", f"{total:.2f}", "-ar", "48000", "-ac", "2", str(out_wav)])


# ---------------------------------------------------------------- cutaways
def prepare_cutaways(timings, seed):
    """Choose laugh windows that get an audience cutaway. Returns [(start, end, png_path)]."""
    files = sorted(p for p in (ROOT / "assets/cutaways").glob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
    if not files:
        log("[edit] no assets/cutaways images: video will be talking head only")
        return []
    from PIL import Image
    wins = []
    for seg in timings["segments"]:
        if seg["laugh"] and seg["pause"] >= 0.7:
            wins.append((seg["end"] + 0.18, seg["end"] + seg["pause"] + 0.05))
    if len(wins) > MAX_CUTAWAYS:
        step = len(wins) / MAX_CUTAWAYS
        wins = [wins[int(i * step)] for i in range(MAX_CUTAWAYS)]
    rnd = random.Random(seed)
    order = files[:]
    rnd.shuffle(order)
    out = []
    for k, (a, b) in enumerate(wins):
        src = order[k % len(order)]
        im = Image.open(src).convert("RGB")
        scale = max(W / im.width, H / im.height)
        im = im.resize((int(im.width * scale) + 1, int(im.height * scale) + 1), Image.LANCZOS)
        left, top = (im.width - W) // 2, (im.height - H) // 2
        im = im.crop((left, top, left + W, top + H))
        p = BUILD / f"cut_{k}.png"
        im.save(p)
        out.append((a, b, p))
    return out


# ---------------------------------------------------------------- thumbnail
def make_thumbnail(final, script, out):
    from PIL import Image, ImageDraw, ImageFont
    frame = BUILD / "thumb_frame.png"
    sh(["ffmpeg", "-y", "-ss", "3.6", "-i", str(final), "-frames:v", "1", str(frame)])
    im = Image.open(frame).convert("RGB").resize((1280, 720), Image.LANCZOS)
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for y in range(300, 720):
        d.line([(0, y), (1280, y)], fill=(0, 0, 0, int(200 * (y - 300) / 420)))
    im = Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")
    d = ImageDraw.Draw(im)
    text = (script.get("thumb_text") or "NEW SET").upper()
    try:
        font = ImageFont.truetype(FONT_BOLD, 118)
    except OSError:
        font = ImageFont.load_default()
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and d.textlength(cur + " " + w, font=font) > 1150:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    lines.append(cur)
    y = 700 - len(lines) * 130
    for ln in lines[:3]:
        d.text((60, y), ln, font=font, fill=(255, 221, 0), stroke_width=7, stroke_fill=(0, 0, 0))
        y += 130
    im.save(out, quality=88)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["lipsync", "fallback"], default="lipsync")
    ap.add_argument("--render-dir", default=str(BUILD / "render"))
    args = ap.parse_args()
    cfg = load_config()
    rdir = Path(args.render_dir)

    script = json.loads((BUILD / "script.json").read_text(encoding="utf-8"))
    timings = json.loads((rdir / "timings.json").read_text(encoding="utf-8"))
    voice = rdir / "voice.wav"
    total = timings["total"]
    if not voice.exists():
        fail("voice.wav missing")

    seed = date.today().toordinal()
    write_ass(timings, BUILD / "captions.ass")
    windows = prepare_cutaways(timings, seed)
    build_audio(timings, voice, BUILD / "mix.wav", windows)

    # main layer
    if args.mode == "lipsync":
        talking = rdir / "talking.mp4"
        if not talking.exists():
            fail("talking.mp4 missing (lip-sync render did not produce it)")
        in_main = ["-i", str(talking)]
        chain = [f"[0:v]scale={W}:{H}:flags=lanczos,setsar=1,fps={FPS},"
                 f"tpad=stop_mode=clone:stop_duration=8,format=yuv420p[v0]"]
    else:
        face = ROOT / "assets/comedian.png"
        if not face.exists():
            fail("assets/comedian.png missing")
        in_main = ["-loop", "1", "-framerate", str(FPS), "-i", str(face)]
        chain = [f"[0:v]scale=2880:-1,zoompan=z='min(1.0+0.00008*on,1.25)':x='iw/2-(iw/zoom/2)':"
                 f"y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},setsar=1,format=yuv420p[v0]"]

    inputs = list(in_main)
    cur = "v0"
    for k, (a, b, png) in enumerate(windows):
        inputs += ["-loop", "1", "-framerate", str(FPS), "-i", str(png)]
        chain.append(f"[{cur}][{k + 1}:v]overlay=0:0:enable='between(t,{a:.2f},{b:.2f})'[ov{k}]")
        cur = f"ov{k}"
    audio_idx = 1 + len(windows)
    inputs += ["-i", str(BUILD / "mix.wav")]

    # intro / outro text
    if Path(FONT_BOLD).exists():
        (BUILD / "intro.txt").write_text(cfg["channel_name"], encoding="utf-8")
        (BUILD / "outro.txt").write_text("Like  |  Share  |  Subscribe", encoding="utf-8")
        chain.append(
            f"[{cur}]drawtext=fontfile={FONT_BOLD}:textfile=intro.txt:fontsize=104:fontcolor=white:borderw=5:"
            f"bordercolor=black@0.8:x=(w-text_w)/2:y=170:"
            f"alpha='if(lt(t,0.5),t/0.5,if(lt(t,2.3),1,max(0,(2.8-t)/0.5)))'[t1]")
        chain.append(
            f"[t1]drawtext=fontfile={FONT_BOLD}:textfile=outro.txt:fontsize=64:fontcolor=white:borderw=4:"
            f"bordercolor=black@0.8:x=(w-text_w)/2:y=90:"
            f"enable='between(t,{total - 3.2:.2f},{total - 0.2:.2f})'[t2]")
        cur = "t2"
    chain.append(f"[{cur}]subtitles=captions.ass:fontsdir=/usr/share/fonts[vout]")

    final = BUILD / "final.mp4"
    sh(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(chain), "-map", "[vout]", "-map", f"{audio_idx}:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-t", f"{total:.2f}", str(final)], cwd=str(BUILD))
    make_thumbnail(final, script, BUILD / "thumb.jpg")
    mb = final.stat().st_size / 1e6
    log(f"[edit] done: {final} ({mb:.1f} MB, {total:.0f}s, mode={args.mode}, cutaways={len(windows)})")


if __name__ == "__main__":
    main()
