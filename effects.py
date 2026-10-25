import os, re, subprocess
import config

PAD = 0.25   # short pause after each scene = snappy cuts

CX = "iw/2-(iw/zoom/2)"
CY = "ih/2-(ih/zoom/2)"

# caption colour per speaker so viewers can tell who is talking (a = first star, b = second star)
COLORS = {"a": "#FFC400", "b": "#6CFF6C"}

MOTIONS = ["zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "shake", "punch"]

# Sound effects are synthesised with FFmpeg: nothing to download, no licence worries.
SFX = {
    "whoosh": "anoisesrc=d=0.5:c=pink:a=0.5,bandpass=f=1500:w=1200,afade=t=in:d=0.25,afade=t=out:st=0.25:d=0.25",
    "boing":  "aevalsrc=0.6*sin(2*PI*(350+300*sin(2*PI*9*t))*t)*exp(-4*t):d=0.6",
    "crash":  "anoisesrc=d=0.8:c=brown:a=0.9,lowpass=f=3500,afade=t=out:st=0.05:d=0.75",
    "pop":    "aevalsrc=0.7*sin(2*PI*700*t)*exp(-30*t):d=0.2",
}

def motion(name, n):
    """zoompan expressions (z, x, y) for each camera move. n = number of frames in the clip."""
    n = max(n - 1, 1)
    table = {
        "zoom_in":   ("min(1.0+0.0012*on,1.3)", CX, CY),
        "zoom_out":  ("max(1.3-0.0012*on,1.0)", CX, CY),
        "pan_left":  ("1.22", f"(iw-iw/zoom)*(1-on/{n})", CY),
        "pan_right": ("1.22", f"(iw-iw/zoom)*(on/{n})", CY),
        "pan_up":    ("1.22", CX, f"(ih-ih/zoom)*(1-on/{n})"),
        "pan_down":  ("1.22", CX, f"(ih-ih/zoom)*(on/{n})"),
        # camera shake that fades out over the first ~1.2 s (crash / explosion)
        "shake":     ("1.12+0.0005*on",
                      f"{CX}+sin(on*2.3)*22*max(0,1-on/30)",
                      f"{CY}+cos(on*2.9)*22*max(0,1-on/30)"),
        # sudden snap-zoom (surprise / punchline)
        "punch":     ("1.0+0.22*min(on/5,1)+0.0006*on", CX, CY),
    }
    return table[name]

def run(cmd, cwd):
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg failed:\n" + p.stderr[-1500:])

def make_sfx(name, outdir):
    path = f"sfx_{name}.wav"
    if not os.path.exists(os.path.join(outdir, path)):
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", SFX[name], "-ar", "44100", "-ac", "2", path], outdir)
    return path

def _ts(t):
    h, m = int(t // 3600), int(t % 3600 // 60)
    s = t % 60
    return f"{h:02d}:{m:02d}:{int(s):02d},{int((s - int(s)) * 1000):03d}"

def chunks(text, max_words=None):
    """Caption lines, split at sentence ends (long sentences are split in two)."""
    max_words = max_words or 12   # whole sentences: timing stays locked to the voice
    out = []
    for sen in re.split(r"(?<=[.!?।])\s+", text.strip()):
        words = sen.split()
        if not words:
            continue
        parts = -(-len(words) // max_words)
        size = -(-len(words) // parts)
        for i in range(0, len(words), size):
            out.append(" ".join(words[i:i + size]))
    return out

def srt(scenes):
    lines, idx, offset = [], 1, 0.0
    for sc in scenes:
        parts = chunks(sc["text"])
        total = sum(len(x) for x in parts) or 1
        color = COLORS.get(sc.get("speaker"))
        t = offset
        for ch in parts:
            d = sc["dur"] * len(ch) / total
            shown = f'<font color="{color}">{ch}</font>' if color else ch
            lines += [str(idx), f"{_ts(t)} --> {_ts(t + d)}", shown, ""]
            idx += 1
            t += d
        offset += sc["dur"] + PAD
    return "\n".join(lines)
