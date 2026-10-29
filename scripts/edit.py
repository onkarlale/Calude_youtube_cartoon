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
from common import BUILD, ROOT, canvas, cover_crop, fail, is_shorts, load_config, log, sh  # noqa: E402
from common import detect_face_center as detect_face_pil  # noqa: E402

W, H, FPS = 1080, 1920, 25     # set from config.json in main(): Shorts are vertical 1080x1920
SHORTS = True
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
    if SHORTS:      # big captions in the lower third, above the Shorts buttons and title
        style = f"Style: Default,Noto Sans Devanagari,76,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,6,1,2,70,70,{int(H * 0.27)},1\n\n"
        maxc = 20
    else:
        style = "Style: Default,Noto Sans Devanagari,58,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,1,2,80,80,70,1\n\n"
        maxc = 34
    head = (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 2\n\n"
        "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
        "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,"
        "MarginL,MarginR,MarginV,Encoding\n"
        + style +
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )
    rows = []
    for seg in timings["segments"]:
        for a, b, txt in caption_events(seg["text"], seg["start"], seg["end"] + 0.15, maxc):
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
    if not SHORTS:
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
def _motion_clip(src_png, dur, out_mp4, variant):
    """Slow zoom / pan on a still audience picture so the cutaway feels like a camera shot, not a slide."""
    frames = max(int(dur * FPS), 2)
    if variant == 0:      # slow push in
        z, x = "min(1.0+0.0011*on,1.28)", "iw/2-(iw/zoom/2)"
    elif variant == 1:    # slow pull out
        z, x = "max(1.28-0.0011*on,1.0)", "iw/2-(iw/zoom/2)"
    elif variant == 2:    # pan left to right
        z, x = "1.18", f"(iw-iw/zoom)*on/{frames}"
    else:                 # pan right to left
        z, x = "1.18", f"(iw-iw/zoom)*(1-on/{frames})"
    vf = (f"scale={int(W * 1.8)}:-1,zoompan=z='{z}':x='{x}':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},"
          f"setsar=1,format=yuv420p")
    sh(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(FPS), "-i", str(src_png),
        "-t", f"{dur:.2f}", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(out_mp4)])


def prepare_cutaways(timings, seed):
    """Choose laugh windows that get an audience cutaway. Returns [(start, end, path, is_clip)].
    Faces (react_*.png) are preferred 2 times out of 3 over the plain crowd-from-behind pictures."""
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
    react = [p for p in files if p.name.startswith("react_")]
    other = [p for p in files if not p.name.startswith("react_")]
    rnd.shuffle(react)
    rnd.shuffle(other)
    order, ri, oi = [], 0, 0
    for k in range(len(wins)):
        use_react = react and (k % 3 != 2 or not other)
        if use_react:
            order.append(react[ri % len(react)])
            ri += 1
        else:
            order.append(other[oi % len(other)])
            oi += 1
    out = []
    for k, (a, b) in enumerate(wins):
        src = order[k]
        im = Image.open(src).convert("RGB")
        fx, fy = detect_face_pil(im, (0.5, 0.42)) if src.name.startswith("react_") else (0.5, 0.5)
        im = cover_crop(im, W, H, fx, fy)
        p = BUILD / f"cut_{k}.png"
        im.save(p)
        clip = BUILD / f"cut_{k}.mp4"
        try:
            _motion_clip(p, (b - a) + 0.3, clip, rnd.randint(0, 3))
            out.append((a, b, clip, True))
        except Exception as e:  # noqa: BLE001
            log(f"[edit] cutaway motion failed ({str(e)[:120]}); using a still picture")
            out.append((a, b, p, False))
    return out


# ---------------------------------------------------------------- camera cuts
def detect_face_center(video, cfg):
    """Face centre (fx, fy as 0..1) for framing close-ups. Uses OpenCV if it works, else the config default."""
    vis = cfg.get("visuals", {})
    fx, fy = float(vis.get("face_x", 0.5)), float(vis.get("face_y", 0.42))
    try:
        import cv2
        frame = BUILD / "face_probe.png"
        sh(["ffmpeg", "-y", "-ss", "1.0", "-i", str(video), "-frames:v", "1", str(frame)])
        img = cv2.imread(str(frame))
        det = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = det.detectMultiScale(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), 1.1, 6, minSize=(80, 80))
        if len(faces) == 1:
            x, y, w, h = faces[0]
            H0, W0 = img.shape[:2]
            fx, fy = (x + w / 2) / W0, (y + h / 2) / H0
            log(f"[edit] face found at ({fx:.2f}, {fy:.2f})")
    except Exception as e:  # noqa: BLE001
        log(f"[edit] face detection unavailable ({type(e).__name__}); using config framing ({fx}, {fy})")
    return min(max(fx, 0.3), 0.7), min(max(fy, 0.3), 0.6)


# name -> (zoom, horizontal offset)  offset moves the framing a little left/right of the face
SHOTS = {"wide": (1.00, 0.0), "medium": (1.22, 0.0), "medium_l": (1.25, -0.05), "medium_r": (1.25, 0.05), "close": (1.50, 0.0)}
# vertical frames are already tight on the face, so the zooms are gentler
SHOTS_V = {"wide": (1.00, 0.0), "medium": (1.10, 0.0), "medium_l": (1.12, -0.03), "medium_r": (1.12, 0.03), "close": (1.26, 0.0)}


def plan_shots(timings, seed, min_len=3.6):
    """Cut points at segment starts. Punchlines get a close-up, set-ups alternate between wide and medium shots."""
    rnd = random.Random(seed)
    shots, last_cut, prev = [], -99.0, None
    setups = ["wide", "medium", "medium_l", "medium_r"]
    for k, seg in enumerate(timings["segments"]):
        t = 0.0 if k == 0 else seg["start"]
        if k and t - last_cut < min_len:
            continue
        if seg.get("laugh"):
            name = "close"
        else:
            name = rnd.choice([n for n in setups if n != prev] or setups)
        if name == prev:
            continue
        shots.append((t, name))
        prev, last_cut = name, t
    if not shots:
        shots = [(0.0, "wide")]
    shots[0] = (0.0, "wide")          # the title banner appears over the first seconds, so start wide
    merged = [shots[0]]
    for t, name in shots[1:]:
        if name != merged[-1][1]:     # drop a cut that would not change the picture
            merged.append((t, name))
    return merged


def camera_chain(shots, fx, fy):
    """filter_complex pieces: split the talking head and re-frame each shot (single resample, then concat)."""
    n = len(shots)
    parts = [f"[0:v]fps={FPS},setsar=1,tpad=stop_mode=clone:stop_duration=8,format=yuv420p,"
             f"split={n}" + "".join(f"[b{i}]" for i in range(n))]
    for i, (t0, name) in enumerate(shots):
        z, dx = (SHOTS_V if SHORTS else SHOTS)[name]
        end = f":end={shots[i + 1][0]:.3f}" if i + 1 < n else ""
        cx = min(max(fx + dx, 0.5 / z), 1 - 0.5 / z)
        cy = min(max(fy, 0.5 / z), 1 - 0.5 / z)
        parts.append(
            f"[b{i}]trim=start={t0:.3f}{end},setpts=PTS-STARTPTS,"
            f"crop=w='trunc(iw/{z}/2)*2':h='trunc(ih/{z}/2)*2':x='clip(iw*{cx:.4f}-ow/2,0,iw-ow)':y='clip(ih*{cy:.4f}-oh/2,0,ih-oh)',"
            f"scale={W}:{H}:flags=lanczos,setsar=1,format=yuv420p[c{i}]")
    parts.append("".join(f"[c{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v0]")
    return parts


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
    global W, H, SHORTS
    W, H = canvas(cfg)
    SHORTS = is_shorts(cfg)
    log(f"[edit] canvas {W}x{H} ({'Short' if SHORTS else 'landscape'})")
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
        if cfg.get("visuals", {}).get("camera_cuts", True):
            fx, fy = detect_face_center(talking, cfg)
            shots = plan_shots(timings, seed)
            log(f"[edit] camera plan: {[(round(t, 1), n) for t, n in shots]}")
            chain = camera_chain(shots, fx, fy)
        else:
            chain = [f"[0:v]scale={W}:{H}:flags=lanczos,setsar=1,fps={FPS},"
                     f"tpad=stop_mode=clone:stop_duration=8,format=yuv420p[v0]"]
    else:
        face = ROOT / "assets/comedian.png"
        if not face.exists():
            fail("assets/comedian.png missing")
        from PIL import Image
        vis = cfg.get("visuals", {})
        base_im = Image.open(face).convert("RGB")
        fx0, fy0 = detect_face_pil(base_im, (float(vis.get("face_x", 0.5)), float(vis.get("face_y", 0.42))))
        cover_crop(base_im, W, H, fx0, fy0).save(BUILD / "fallback_base.png")
        in_main = ["-loop", "1", "-framerate", str(FPS), "-i", str(BUILD / "fallback_base.png")]
        chain = [f"[0:v]scale={int(W * 1.5)}:-1,zoompan=z='min(1.0+0.00008*on,1.25)':x='iw/2-(iw/zoom/2)':"
                 f"y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},setsar=1,format=yuv420p[v0]"]

    inputs = list(in_main)
    cur = "v0"
    for k, (a, b, path, is_clip) in enumerate(windows):
        if is_clip:
            inputs += ["-i", str(path)]
            chain.append(f"[{k + 1}:v]setpts=PTS-STARTPTS+{a:.3f}/TB[cv{k}]")
            chain.append(f"[{cur}][cv{k}]overlay=0:0:eof_action=pass:enable='between(t,{a:.2f},{b:.2f})'[ov{k}]")
        else:
            inputs += ["-loop", "1", "-framerate", str(FPS), "-i", str(path)]
            chain.append(f"[{cur}][{k + 1}:v]overlay=0:0:enable='between(t,{a:.2f},{b:.2f})'[ov{k}]")
        cur = f"ov{k}"
    audio_idx = 1 + len(windows)
    inputs += ["-i", str(BUILD / "mix.wav")]

    # intro / outro text
    if Path(FONT_BOLD).exists():
        if SHORTS:
            hook = (script.get("thumb_text") or script.get("title") or "WAIT FOR IT").upper()
            lines, cur_line = [], ""
            for w_ in hook.split():
                if cur_line and len(cur_line) + 1 + len(w_) > 12:
                    lines.append(cur_line)
                    cur_line = w_
                else:
                    cur_line = (cur_line + " " + w_).strip()
            lines.append(cur_line)
            (BUILD / "intro.txt").write_text("\n".join(lines[:3]), encoding="utf-8")
            (BUILD / "outro.txt").write_text(cfg.get("shorts", {}).get("cta_text", "Follow for daily comedy"), encoding="utf-8")
            chain.append(
                f"[{cur}]drawtext=fontfile={FONT_BOLD}:textfile=intro.txt:fontsize=84:fontcolor=white:borderw=6:"
                f"bordercolor=black@0.85:line_spacing=10:x=(w-text_w)/2:y={int(H * 0.045)}:"
                f"alpha='if(lt(t,0.25),t/0.25,if(lt(t,3.2),1,max(0,(3.6-t)/0.4)))'[t1]")
            chain.append(
                f"[t1]drawtext=fontfile={FONT_BOLD}:textfile=outro.txt:fontsize=58:fontcolor=white:borderw=5:"
                f"bordercolor=black@0.85:x=(w-text_w)/2:y={int(H * 0.06)}:"
                f"enable='between(t,{max(total - 2.6, 4):.2f},{total - 0.1:.2f})'[t2]")
        else:
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
    if not SHORTS:
        make_thumbnail(final, script, BUILD / "thumb.jpg")
    mb = final.stat().st_size / 1e6
    log(f"[edit] done: {final} ({mb:.1f} MB, {total:.0f}s, mode={args.mode}, cutaways={len(windows)})")


if __name__ == "__main__":
    main()
