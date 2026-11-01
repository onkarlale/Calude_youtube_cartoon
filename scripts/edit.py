#!/usr/bin/env python3
"""FFmpeg editor: talking head + audience cutaways + laugh track + captions + intro/outro + loudness.

  python scripts/edit.py --mode lipsync    # uses build/render/talking.mp4
  python scripts/edit.py --mode fallback   # uses assets/comedian.png (slow zoom), no lip sync

Needs: build/script.json, build/render/{voice.wav,timings.json}. Writes build/final.mp4 and build/thumb.jpg.
"""
import argparse
import math
import json
import random
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import BUILD, ROOT, canvas, cover_crop, fail, is_shorts, load_config, log, sh  # noqa: E402
from common import layout as get_layout  # noqa: E402
from common import detect_face_center as detect_face_pil  # noqa: E402

W, H, FPS = 1080, 1920, 25     # set from config.json in main(): Shorts are vertical 1080x1920
SHORTS = True
LAYOUT = "stage"           # scene | stage | full | closeup | landscape
PANEL_Y, PANEL_H, STRIP_Y, STRIP_H = 248, 1080, 1328, 592
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
MAX_CUTAWAYS = 10
CAPTION_MARGIN = 270


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
        mv = (H - STRIP_Y + (60 if LAYOUT == "full" else 30)) if LAYOUT in ("stage", "full") else int(H * 0.27)
        fs = 76
        if LAYOUT == "scene":      # low, over the audience area, so Raj's legs stay visible
            mv, fs = int(CAPTION_MARGIN), 68
        style = f"Style: Default,Noto Sans Devanagari,{fs},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,6,1,2,70,70,{mv},1\n\n"
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


def synth_crowd_laugh(path, dur, seed, big=True, sr=24000):
    """A crowd laughing, built from many separate 'voices'. Each voice is a pitched, breathy 'ha-ha-ha' pulse train
    (vowel formants, falling pitch, vibrato) that slows and fades; the voices join at slightly different moments.
    This is the fallback when assets/sfx has no real laugh recordings (those are always used when present)."""
    import wave
    import numpy as np
    rnd = np.random.default_rng(seed)
    n = int(dur * sr)
    mix = np.zeros(n)
    voices = int(rnd.integers(12, 18)) if big else int(rnd.integers(3, 6))
    for _ in range(voices):
        onset = float(rnd.uniform(0.0, min(0.7, dur * 0.3)))
        life = float(rnd.uniform(0.55, 0.95)) * (dur - onset)
        if life < 0.35:
            continue
        f0 = float(rnd.uniform(95, 150)) if rnd.random() < 0.5 else float(rnd.uniform(170, 290))
        rate = float(rnd.uniform(3.8, 6.2))
        tt = np.arange(int(life * sr)) / sr
        slow = 2 * np.pi * (rate * tt - 0.30 * rate * tt ** 2 / max(life, 0.6))      # the laugh slows down as it dies
        bursts = (0.5 + 0.5 * np.sin(slow - np.pi / 2)) ** 2.2
        env = bursts * np.clip(tt / 0.10, 0, 1) * np.exp(-tt / (life * 0.6))
        f = f0 * (1 + 0.22 * np.exp(-tt / 0.35)) * (1 + 0.012 * np.sin(2 * np.pi * 5.5 * tt + rnd.uniform(0, 6)))
        phase = 2 * np.pi * np.cumsum(f) / sr
        src = np.zeros_like(tt)
        for k in range(1, 16):
            fk = k * f0
            if fk > 5500:
                break
            g = (np.exp(-((fk - 750) / 320) ** 2) + 0.8 * np.exp(-((fk - 1250) / 420) ** 2)
                 + 0.35 * np.exp(-((fk - 2700) / 700) ** 2) + 0.04)
            src += g / k ** 0.6 * np.sin(k * phase)
        src /= max(np.abs(src).max(), 1e-6)
        breath = np.diff(rnd.standard_normal(len(tt)), prepend=0.0)     # high-passed hiss = breathiness
        breath /= max(np.abs(breath).max(), 1e-6)
        v = (0.85 * src + 0.22 * breath) * env * float(rnd.uniform(0.5, 1.0))
        a = int(onset * sr)
        mix[a:a + len(v)] += v[:max(n - a, 0)]
    if big:      # the room itself: a soft, swelling wash of many people
        bed = np.convolve(rnd.standard_normal(n), np.ones(5) / 5, mode="same")
        swell = np.clip(np.arange(n) / sr / 0.25, 0, 1) * np.exp(-np.arange(n) / sr / (dur * 0.7))
        mix += 0.10 * bed * swell * np.abs(mix).max()
    t = np.arange(n) / sr
    mix *= np.clip(t / 0.06, 0, 1) * np.clip((dur - t) / min(0.9, dur * 0.4), 0, 1)
    mix = mix / max(np.abs(mix).max(), 1e-6) * 0.9
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((mix * 32767).astype("<i2").tobytes())


def make_laugh(path, dur, seed, big=True):
    rnd = random.Random(seed)
    samples = real_samples("laugh")
    if samples:
        src = rnd.choice(samples)
        sh(["ffmpeg", "-y", "-i", str(src), "-t", f"{dur:.2f}", "-af",
            f"afade=t=in:d=0.1,afade=t=out:st={max(dur - 0.5, 0.1):.2f}:d=0.5", "-ar", "48000", "-ac", "1", str(path)])
        return
    synth_crowd_laugh(path, dur, seed, big)


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
    add(p, last["end"] + 0.35, 0.6)

    # the room laughs after every punchline: it starts a moment AFTER the line lands (people need a beat to get it),
    # is loud enough to feel like a real crowd, and its tail runs under the start of the next line
    segs = timings["segments"]
    for k, seg in enumerate(s_ for s_ in segs if s_["laugh"]):
        rnd = random.Random(k * 7 + 3)
        big = seg["pause"] >= 1.9
        dur = min(seg["pause"] + 0.9, 4.2)
        p = BUILD / f"sfx_laugh_{k}.wav"
        make_laugh(p, dur, seed=k + 11, big=big)
        add(p, seg["end"] + rnd.uniform(0.10, 0.28), round(rnd.uniform(0.62, 0.78) if big else 0.5, 2))
    for k, seg in enumerate(s_ for s_ in segs if s_.get("chuckle")):
        p = BUILD / f"sfx_chuckle_{k}.wav"          # the room murmurs / chuckles at a question or a small joke
        make_laugh(p, min(seg["pause"] + 0.4, 2.0), seed=k + 101, big=False)
        add(p, seg["end"] + 0.25, 0.38)

    # quiet room tone
    inputs.extend(["-f", "lavfi", "-i", f"anoisesrc=d={total:.2f}:c=brown:r=48000:a=0.3:s=3"])
    filters.append(f"[{idx}:a]lowpass=f=600,volume=0.07[a{idx}]")
    labels.append(f"[a{idx}]")

    filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=first,"
                   f"alimiter=limit=0.95,loudnorm=I=-14:TP=-1.5:LRA=11[mix]")
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
# ---------------------------------------------------------------- stage layout (comedian panel + live audience panel)
SHOTS_F = {"wide": (1.00, 0.0), "medium": (1.07, 0.0), "medium_l": (1.10, -0.04), "medium_r": (1.10, 0.04), "close": (1.22, 0.0)}
SHOTS_S = {"wide": (1.00, 0.0), "medium": (1.12, 0.0), "medium_l": (1.15, -0.04), "medium_r": (1.15, 0.04), "close": (1.35, 0.0)}


def _kb_clip(src_png, frames, out_mp4, variant, size, strong):
    """Slow zoom/pan on a still picture for `frames` frames (the audience panel is never frozen)."""
    zw, zh = size
    rate = 0.0022 if strong else 0.0011
    if variant == 0:
        z, x = f"min(1.0+{rate}*on,1.35)", "iw/2-(iw/zoom/2)"
    elif variant == 1:
        z, x = f"max(1.35-{rate}*on,1.0)", "iw/2-(iw/zoom/2)"
    elif variant == 2:
        z, x = "1.2", f"(iw-iw/zoom)*on/{max(frames, 2)}"
    else:
        z, x = "1.2", f"(iw-iw/zoom)*(1-on/{max(frames, 2)})"
    bright = "eq=brightness=0.04:saturation=1.1" if strong else "eq=brightness=-0.07:saturation=0.9"
    # laughing faces bounce (about 3 shakes a second); the ambient crowd sways slowly
    bounce = f"+11*sin(2*PI*on/{FPS}*3.1)" if strong else f"+4*sin(2*PI*on/{FPS}*0.45)"
    sway = "+5*sin(2*PI*on/25*2.3)" if strong else ""
    vf = (f"scale={int(zw * 1.8)}:-1,zoompan=z='{z}':x='{x}{sway}':y='ih/2-(ih/zoom/2){bounce}':d=1:s={zw}x{zh}:fps={FPS},"
          f"{bright},setsar=1,format=yuv420p")
    sh(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(FPS), "-i", str(src_png),
        "-frames:v", str(max(frames, 2)), "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-g", str(FPS), str(out_mp4)], cwd=str(BUILD))


def build_audience_strip(timings, total, seed):
    """The live audience panel (W x STRIP_H): moving crowd shots; AI audience faces laughing during the laughs."""
    files = sorted(p for p in (ROOT / "assets/cutaways").glob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
    if not files:
        log("[edit] no assets/cutaways images: the audience panel will be empty")
        return None
    from PIL import Image
    rnd = random.Random(seed)
    react = [p for p in files if p.name.startswith("react_")]
    other = [p for p in files if not p.name.startswith("react_")]
    rnd.shuffle(react)
    rnd.shuffle(other)
    laugh = [(sg["end"] + 0.10, sg["end"] + sg["pause"] + 0.15) for sg in timings["segments"] if sg["laugh"] and sg["pause"] >= 0.7]

    def ambient(a, b):
        if b - a < 0.2:
            return []
        n = max(1, int(math.ceil((b - a) / 5.0)))
        step = (b - a) / n
        return [(a + i * step, a + (i + 1) * step, "ambient") for i in range(n)]

    pieces, t = [], 0.0
    for a, b in laugh:
        a = max(a, t)
        if b - a < 0.4:
            continue
        pieces += ambient(t, a)
        pieces.append((a, b, "react"))
        t = b
    pieces += ambient(t, total + 1.0)

    ri = oi = 0
    prepared, clips, last_end = {}, [], 0
    for k, (a, b, kind) in enumerate(pieces):
        pool = (react if (kind == "react" and react) else other) or react or other
        if pool is react and kind == "react":
            src, ri = pool[ri % len(pool)], ri + 1
        else:
            src, oi = pool[oi % len(pool)], oi + 1
        key = str(src)
        if key not in prepared:
            im = Image.open(src).convert("RGB")
            fx, fy = detect_face_pil(im, (0.5, 0.4)) if src.name.startswith("react_") else (0.5, 0.66 if LAYOUT == "full" else 0.5)
            png = BUILD / f"strip_src_{len(prepared)}.png"
            cover_crop(im, W, STRIP_H, fx, fy).save(png)
            prepared[key] = png
        end_f = int(round(b * FPS))
        frames = max(end_f - last_end, 2)
        last_end += frames
        clip = BUILD / f"strip_{k}.mp4"
        _kb_clip(prepared[key], frames, clip, rnd.randint(0, 3), (W, STRIP_H), kind == "react")
        clips.append(clip.name)
    (BUILD / "strip_list.txt").write_text("".join(f"file '{c}'\n" for c in clips), encoding="utf-8")
    sh(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "strip_list.txt", "-c", "copy", "strip.mp4"], cwd=str(BUILD))
    log(f"[edit] audience panel: {len(clips)} moving clips ({sum(1 for pc in pieces if pc[2] == 'react')} laughing-face moments)")
    return BUILD / "strip.mp4"


def stage_chain(shots, fx, fy, idx, wide=False):
    """Comedian panel (re-framed shots with a gentle camera drift), audience panel below.
    idx = input numbers: {"strip": n|None, "smask": n|None, "pmask": n|None}.
    full + tight : the picture fills the screen (audience fades in at the bottom).
    full + wide  : a soft-edged panel melts into a blurred copy of the same stage, so the screen is still full."""
    n = len(shots)
    full = LAYOUT == "full"
    need_bg = (not full) or wide
    parts = [f"[0:v]fps={FPS},setsar=1,tpad=stop_mode=clone:stop_duration=8,format=yuv420p,split={n + (1 if need_bg else 0)}"
             + ("[bgsrc]" if need_bg else "") + "".join(f"[b{i}]" for i in range(n))]
    if need_bg:
        bright = "-0.03:saturation=1.2" if full else "-0.12:saturation=1.15"
        parts.append(f"[bgsrc]crop=w='trunc(ih*{W}/{H}/2)*2':h=ih:x='(iw-ow)/2':y=0,scale={W}:{H},boxblur=22:3,"
                     f"eq=brightness={bright},format=yuv420p[bg]")
    tbl = SHOTS_F if full else SHOTS_S
    for i, (t0, name) in enumerate(shots):
        z, dx = tbl[name]
        end = f":end={shots[i + 1][0]:.3f}" if i + 1 < n else ""
        cx = min(max(fx + dx, 0.5 / z * 0.75), 1 - 0.5 / z * 0.75)
        cy = min(max(fy + 0.03, 0.5 / z), 1 - 0.5 / z)
        parts.append(
            f"[b{i}]trim=start={t0:.3f}{end},setpts=PTS-STARTPTS,"
            f"crop=w='trunc(ih/{z}*{W}/{PANEL_H}/2)*2':h='trunc(ih/{z}/2)*2':"
            f"x='clip(iw*{cx:.4f}-ow/2+14*sin(2*PI*t/5.3),0,iw-ow)':y='clip(ih*{cy:.4f}-oh/2+9*sin(2*PI*t/4.1),0,ih-oh)',"
            f"scale={W}:{PANEL_H}:flags=lanczos,setsar=1,format=yuv420p[c{i}]")
    parts.append("".join(f"[c{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[fgc]")
    # handheld camera: a slight over-scale, a tiny rolling tilt, then crop back (no black corners)
    parts.append(f"[fgc]scale={int(W * 1.05) // 2 * 2}:{int(PANEL_H * 1.05) // 2 * 2},"
                 f"rotate=a='0.010*sin(2*PI*t/3.9)+0.004*sin(2*PI*t/1.7)':ow=iw:oh=ih:c=black,"
                 f"crop={W}:{PANEL_H}[fg]")
    if need_bg:
        src = "fg"
        if idx.get("pmask"):
            parts.append(f"[{idx['pmask']}:v]format=gray,setsar=1[pm]")
            parts.append("[fg]format=yuv420p,setsar=1[fgv]")
            parts.append("[fgv][pm]alphamerge[fga]")
            src = "fga"
        parts.append(f"[bg][{src}]overlay=0:{PANEL_Y}:format=auto[comp1]")
    else:
        parts.append(f"[fg]pad={W}:{H}:0:0:color=black[comp1]")
    cur = "comp1"
    if idx.get("strip") and idx.get("smask"):       # audience at the bottom, fading softly into the picture above
        parts.append(f"[{idx['smask']}:v]format=gray,setsar=1[mask]")
        parts.append(f"[{idx['strip']}:v]format=yuv420p,setsar=1[sv]")
        parts.append("[sv][mask]alphamerge[stripa]")
        parts.append(f"[{cur}][stripa]overlay=0:{STRIP_Y}:format=auto:eof_action=repeat[comp2]")
        cur = "comp2"
    elif idx.get("strip"):
        parts.append(f"[{cur}][{idx['strip']}:v]overlay=0:{STRIP_Y}:eof_action=repeat[comp2]")
        cur = "comp2"
    lines = (f"drawbox=x=0:y={PANEL_Y - 4}:w={W}:h=8:color=0xFFC21A@1:t=fill,"
             f"drawbox=x=0:y={STRIP_Y - 4}:w={W}:h=8:color=0xFFC21A@1:t=fill,") if LAYOUT == "stage" else ""
    parts.append(f"[{cur}]{lines}vignette=PI/4.5,eq=brightness='0.012*sin(2*PI*t/2.7)':eval=frame[comp3]")
    return parts, "comp3"


def render_stage(cfg, args, script, timings, total, seed, rdir):
    global PANEL_Y, PANEL_H, STRIP_Y, STRIP_H
    wide = cfg.get("shorts", {}).get("framing", "wide") == "wide"
    if LAYOUT == "full":     # the picture fills the screen; the audience overlays the bottom and fades into it
        STRIP_H = 520
        STRIP_Y = H - STRIP_H
        if wide:             # Raj in a soft-edged panel that melts into a blurred extension of the same stage
            PANEL_H = 1100
            PANEL_Y = 250
        else:                # Raj's picture fills the whole screen (face large)
            PANEL_H = H - 360
            PANEL_Y = 0
    else:
        PANEL_H = 1000      # a wider-than-square comedian panel: face smaller, stage and shoulders visible
        PANEL_Y = int(H * 0.13) // 2 * 2
        STRIP_Y = PANEL_Y + PANEL_H
        STRIP_H = H - STRIP_Y
    write_ass(timings, BUILD / "captions.ass")
    build_audio(timings, rdir / "voice.wav", BUILD / "mix.wav", [])

    if args.mode == "lipsync":
        talking = rdir / "talking.mp4"
        if not talking.exists():
            fail("talking.mp4 missing (lip-sync render did not produce it)")
    else:
        face = ROOT / "assets/comedian.png"
        if not face.exists():
            fail("assets/comedian.png missing")
        from PIL import Image
        vis = cfg.get("visuals", {})
        im = Image.open(face).convert("RGB")
        fx0, fy0 = detect_face_pil(im, (float(vis.get("face_x", 0.5)), float(vis.get("face_y", 0.42))))
        cover_crop(im, 1280, 720, fx0, fy0).save(BUILD / "fallback_base.png")
        talking = BUILD / "fallback_main.mp4"
        sh(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(FPS), "-i", str(BUILD / "fallback_base.png"),
            "-vf", f"scale=1536:864,zoompan=z='min(1.0+0.00008*on,1.2)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1280x720:fps={FPS},format=yuv420p",
            "-t", f"{total + 8:.1f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(talking)])

    fx, fy = detect_face_center(talking, cfg)
    shots = plan_shots(timings, seed) if cfg.get("visuals", {}).get("camera_cuts", True) else [(0.0, "wide")]
    log(f"[edit] camera plan: {[(round(t, 1), n) for t, n in shots]}")
    strip = build_audience_strip(timings, total, seed)
    use_mask = LAYOUT == "full" and strip is not None
    inputs = ["-i", str(talking)]
    idx, n_in = {"strip": None, "smask": None, "pmask": None}, 1
    if strip is not None:
        inputs += ["-i", str(strip)]
        idx["strip"] = n_in
        n_in += 1
    from PIL import Image

    def vertical_ramp(height, top, bottom, path):
        """Grey mask: 0 -> 255 over `top` rows at the top, 255 -> 0 over `bottom` rows at the bottom (smoothstep)."""
        col = Image.new("L", (1, height))
        vals = []
        for y in range(height):
            a_ = min(1.0, y / top) if top else 1.0
            b_ = min(1.0, (height - 1 - y) / bottom) if bottom else 1.0
            v = min(a_, b_)
            vals.append(int(255 * v * v * (3 - 2 * v)))
        col.putdata(vals)
        col.resize((W, height)).save(path)

    if use_mask:
        vertical_ramp(STRIP_H, 190, 0, BUILD / "strip_mask.png")
        inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{total + 3:.1f}", "-i", str(BUILD / "strip_mask.png")]
        idx["smask"] = n_in
        n_in += 1
    if LAYOUT == "full" and wide:
        vertical_ramp(PANEL_H, 130, 130, BUILD / "panel_mask.png")
        inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{total + 3:.1f}", "-i", str(BUILD / "panel_mask.png")]
        idx["pmask"] = n_in
        n_in += 1
    chain, cur = stage_chain(shots, fx, fy, idx, wide=(LAYOUT == "full" and wide))
    audio_idx = n_in
    inputs += ["-i", str(BUILD / "mix.wav")]

    if Path(FONT_BOLD).exists():
        hook = (script.get("thumb_text") or script.get("title") or "WAIT FOR IT").upper()
        lines, cur_line = [], ""
        for w_ in hook.split():
            if cur_line and len(cur_line) + 1 + len(w_) > 12:
                lines.append(cur_line)
                cur_line = w_
            else:
                cur_line = (cur_line + " " + w_).strip()
        lines.append(cur_line)
        (BUILD / "intro.txt").write_text("\n".join(lines[:2]), encoding="utf-8")
        (BUILD / "channel.txt").write_text(cfg["channel_name"], encoding="utf-8")
        (BUILD / "outro.txt").write_text(cfg.get("shorts", {}).get("cta_text", "Follow for daily comedy"), encoding="utf-8")
        (BUILD / "live.txt").write_text("\u25cf LIVE", encoding="utf-8")
        full = LAYOUT == "full"
        box = ":box=1:boxcolor=black@0.38:boxborderw=14" if full else ""
        y_live = 150 if full else PANEL_Y + 24
        x_live = "36" if full else "w-text_w-36"
        y_hook, y_name = (200, 200) if full else (34, 80)
        y_cta = 200 if full else 84
        chain.append(
            f"[{cur}]drawtext=fontfile={FONT_BOLD}:textfile=live.txt:fontsize=44:fontcolor=0xFF3B30:borderw=4:"
            f"bordercolor=black@0.8:x={x_live}:y={y_live}:enable='lt(mod(t,1.6),1.1)'[tl]")
        cur = "tl"
        chain.append(
            f"[{cur}]drawtext=fontfile={FONT_BOLD}:textfile=intro.txt:fontsize=80:fontcolor=white:borderw=6:"
            f"bordercolor=black@0.85:line_spacing=8:x=(w-text_w)/2:y={y_hook}{box}:"
            f"alpha='if(lt(t,0.25),t/0.25,if(lt(t,3.2),1,max(0,(3.6-t)/0.4)))'[t1]")
        chain.append(
            f"[t1]drawtext=fontfile={FONT_BOLD}:textfile=channel.txt:fontsize=62:fontcolor=white:borderw=5:"
            f"bordercolor=black@0.85:x=(w-text_w)/2:y={y_name}{box}:enable='between(t,3.6,{max(total - 2.7, 4):.2f})'[t2]")
        chain.append(
            f"[t2]drawtext=fontfile={FONT_BOLD}:textfile=outro.txt:fontsize=58:fontcolor=0xFFC21A:borderw=5:"
            f"bordercolor=black@0.85:x=(w-text_w)/2:y={y_cta}{box}:enable='between(t,{max(total - 2.6, 4):.2f},{total - 0.1:.2f})'[t3]")
        cur = "t3"
    chain.append(f"[{cur}]subtitles=captions.ass:fontsdir=/usr/share/fonts[vout]")

    final = BUILD / "final.mp4"
    sh(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(chain), "-map", "[vout]", "-map", f"{audio_idx}:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-t", f"{total:.2f}", str(final)], cwd=str(BUILD))
    mb = final.stat().st_size / 1e6
    log(f"[edit] done: {final} ({mb:.1f} MB, {total:.0f}s, mode={args.mode}, layout={LAYOUT})")


# ---------------------------------------------------------------- scene layout (full-body picture, audience inside the picture)
# Gentle zooms only: Raj's legs and shoes must stay in the frame. (zoom, horizontal offset)
SHOTS_SCENE = {"wide": (1.00, 0.0), "medium": (1.05, 0.0), "medium_l": (1.07, -0.02), "medium_r": (1.07, 0.02), "close": (1.10, 0.0)}


def body_pool():
    exts = (".png", ".jpg", ".jpeg", ".webp")
    return sorted(p for p in (ROOT / "assets/bodies").glob("*") if p.suffix.lower() in exts)


def scene_chain(shots):
    """One full-screen picture. Re-framed per shot (gentle push-ins), slow handheld drift, no side panels."""
    n = len(shots)
    parts = [f"[0:v]fps={FPS},setsar=1,tpad=stop_mode=clone:stop_duration=8,format=yuv420p,split={n}"
             + "".join(f"[b{i}]" for i in range(n))]
    for i, (t0, name) in enumerate(shots):
        z, dx = SHOTS_SCENE[name]
        end = f":end={shots[i + 1][0]:.3f}" if i + 1 < n else ""
        cx = min(max(0.5 + dx, 0.5 / z), 1 - 0.5 / z)
        parts.append(
            f"[b{i}]trim=start={t0:.3f}{end},setpts=PTS-STARTPTS,"
            f"crop=w='trunc(iw/{z}/2)*2':h='trunc(ih/{z}/2)*2':"
            f"x='clip(iw*{cx:.4f}-ow/2+9*sin(2*PI*t/5.3),0,iw-ow)':y='clip(ih*0.5-oh/2+6*sin(2*PI*t/4.1),0,ih-oh)',"
            f"scale={W}:{H}:flags=lanczos,setsar=1,format=yuv420p[c{i}]")
    parts.append("".join(f"[c{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v0]")
    return parts


def scene_cutaways(timings, seed, cfg):
    """A few SHORT full-screen reaction shots of laughing audience members, right after the biggest punchlines.
    (start, end, clip). Set visuals.cutaways=false in config.json to turn them off."""
    vis = cfg.get("visuals", {})
    if not vis.get("cutaways", True):
        return []
    files = sorted(p for p in (ROOT / "assets/cutaways").glob("react_*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
    if not files:
        return []
    from PIL import Image
    length = float(vis.get("cutaway_seconds", 1.6))
    cands = [(sg["end"] + 0.55, sg["pause"]) for sg in timings["segments"] if sg["laugh"] and sg["pause"] >= 1.9]
    wins, last = [], -99.0
    for a, pause in cands:
        if a - last < 9.0:                       # keep them rare: the comedian is the show
            continue
        wins.append((a, a + min(length, max(pause - 0.5, 0.8))))
        last = a
    wins = wins[: int(vis.get("cutaway_max", 6))]
    rnd = random.Random(seed)
    rnd.shuffle(files)
    out = []
    for k, (a, b) in enumerate(wins):
        src = files[k % len(files)]
        im = Image.open(src).convert("RGB")
        fx, fy = detect_face_pil(im, (0.5, 0.4))
        p = BUILD / f"cut_{k}.png"
        cover_crop(im, W, H, fx, fy).save(p)
        clip = BUILD / f"cut_{k}.mp4"
        try:
            _motion_clip(p, (b - a) + 0.3, clip, rnd.randint(0, 3))
            out.append((a, b, clip))
        except Exception as e:  # noqa: BLE001
            log(f"[edit] cutaway motion failed ({str(e)[:120]}); skipping it")
    return out


def add_text_overlays(chain, cur, cfg, script, total):
    """Hook title (first seconds), red LIVE tag, channel name, and the follow call-to-action at the end."""
    if not Path(FONT_BOLD).exists():
        return cur
    hook = (script.get("thumb_text") or script.get("title") or "WAIT FOR IT").upper()
    lines, cur_line = [], ""
    for w_ in hook.split():
        if cur_line and len(cur_line) + 1 + len(w_) > 12:
            lines.append(cur_line)
            cur_line = w_
        else:
            cur_line = (cur_line + " " + w_).strip()
    lines.append(cur_line)
    (BUILD / "intro.txt").write_text("\n".join(lines[:2]), encoding="utf-8")
    (BUILD / "channel.txt").write_text(cfg["channel_name"], encoding="utf-8")
    (BUILD / "outro.txt").write_text(cfg.get("shorts", {}).get("cta_text", "Follow for daily comedy"), encoding="utf-8")
    (BUILD / "live.txt").write_text("\u25cf LIVE", encoding="utf-8")
    box = ":box=1:boxcolor=black@0.38:boxborderw=14"
    chain.append(
        f"[{cur}]drawtext=fontfile={FONT_BOLD}:textfile=live.txt:fontsize=44:fontcolor=0xFF3B30:borderw=4:"
        f"bordercolor=black@0.8:x=36:y=70:enable='lt(mod(t,1.6),1.1)'[tl]")
    chain.append(
        f"[tl]drawtext=fontfile={FONT_BOLD}:textfile=intro.txt:fontsize=80:fontcolor=white:borderw=6:"
        f"bordercolor=black@0.85:line_spacing=8:x=(w-text_w)/2:y=130{box}:"
        f"alpha='if(lt(t,0.25),t/0.25,if(lt(t,3.2),1,max(0,(3.6-t)/0.4)))'[t1]")
    chain.append(
        f"[t1]drawtext=fontfile={FONT_BOLD}:textfile=channel.txt:fontsize=56:fontcolor=white:borderw=5:"
        f"bordercolor=black@0.85:x=(w-text_w)/2:y=130{box}:enable='between(t,3.6,{max(total - 4.0, 4):.2f})'[t2]")
    chain.append(
        f"[t2]drawtext=fontfile={FONT_BOLD}:textfile=outro.txt:fontsize=58:fontcolor=0xFFC21A:borderw=5:"
        f"bordercolor=black@0.85:x=(w-text_w)/2:y=130{box}:enable='between(t,{max(total - 3.9, 4):.2f},{total - 0.1:.2f})'[t3]")
    return "t3"


def render_scene(cfg, args, script, timings, total, seed, rdir):
    write_ass(timings, BUILD / "captions.ass")
    build_audio(timings, rdir / "voice.wav", BUILD / "mix.wav", [])

    if args.mode == "lipsync":
        talking = rdir / "talking.mp4"
        if not talking.exists():
            fail("talking.mp4 missing (lip-sync render did not produce it)")
    else:      # no lip-sync: the full-body picture with a very slow push-in
        pool = body_pool()
        if not pool:
            fail("assets/bodies/ has no pictures (run the workflow once with 'new_face' ticked)")
        from PIL import Image
        first_only = cfg.get("visuals", {}).get("base_mode", "single") == "single"
        pic = pool[0] if first_only else pool[seed % len(pool)]
        cover_crop(Image.open(pic).convert("RGB"), W, H, 0.5, 0.5).save(BUILD / "fallback_base.png")
        talking = BUILD / "fallback_main.mp4"
        sh(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(FPS), "-i", str(BUILD / "fallback_base.png"),
            "-vf", f"scale={int(W * 1.1)}:{int(H * 1.1)},zoompan=z='min(1.0+0.00006*on,1.08)':x='iw/2-(iw/zoom/2)':"
                   f"y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},format=yuv420p",
            "-t", f"{total + 8:.1f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(talking)])

    shots = plan_shots(timings, seed, min_len=4.6) if cfg.get("visuals", {}).get("camera_cuts", True) else [(0.0, "wide")]
    log(f"[edit] camera plan: {[(round(t, 1), n) for t, n in shots]}")
    chain = scene_chain(shots)
    inputs = ["-i", str(talking)]
    cur = "v0"
    wins = scene_cutaways(timings, seed, cfg)
    for k, (a, b, clip) in enumerate(wins):
        inputs += ["-i", str(clip)]
        chain.append(f"[{k + 1}:v]setpts=PTS-STARTPTS+{a:.3f}/TB[cv{k}]")
        chain.append(f"[{cur}][cv{k}]overlay=0:0:eof_action=pass:enable='between(t,{a:.2f},{b:.2f})'[ov{k}]")
        cur = f"ov{k}"
    log(f"[edit] audience reaction cutaways: {len(wins)}")
    audio_idx = 1 + len(wins)
    inputs += ["-i", str(BUILD / "mix.wav")]
    chain.append(f"[{cur}]vignette=PI/5,eq=brightness='0.010*sin(2*PI*t/2.7)':eval=frame[vg]")
    cur = add_text_overlays(chain, "vg", cfg, script, total)
    chain.append(f"[{cur}]subtitles=captions.ass:fontsdir=/usr/share/fonts[vout]")

    final = BUILD / "final.mp4"
    sh(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(chain), "-map", "[vout]", "-map", f"{audio_idx}:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-t", f"{total:.2f}", str(final)], cwd=str(BUILD))
    log(f"[edit] done: {final} ({final.stat().st_size / 1e6:.1f} MB, {total:.0f}s, mode={args.mode}, layout=scene)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["lipsync", "fallback"], default="lipsync")
    ap.add_argument("--render-dir", default=str(BUILD / "render"))
    args = ap.parse_args()
    cfg = load_config()
    global W, H, SHORTS, LAYOUT
    W, H = canvas(cfg)
    SHORTS = is_shorts(cfg)
    LAYOUT = get_layout(cfg)
    log(f"[edit] canvas {W}x{H} (layout: {LAYOUT})")
    rdir = Path(args.render_dir)

    script = json.loads((BUILD / "script.json").read_text(encoding="utf-8"))
    timings = json.loads((rdir / "timings.json").read_text(encoding="utf-8"))
    voice = rdir / "voice.wav"
    total = timings["total"]
    if not voice.exists():
        fail("voice.wav missing")

    seed = date.today().toordinal()
    global CAPTION_MARGIN
    CAPTION_MARGIN = int(cfg.get("shorts", {}).get("caption_margin", 270))
    if LAYOUT == "scene":
        render_scene(cfg, args, script, timings, total, seed, rdir)
        return
    if LAYOUT in ("stage", "full"):
        render_stage(cfg, args, script, timings, total, seed, rdir)
        return
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
