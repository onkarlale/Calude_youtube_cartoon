import os, re, subprocess, shutil
import config

FPS = 25
PAD = 0.6  # seconds of pause after each scene

def _run(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

def _ts(t):
    h, m = int(t // 3600), int(t % 3600 // 60)
    s = t % 60
    return f"{h:02d}:{m:02d}:{int(s):02d},{int((s - int(s)) * 1000):03d}"

def _srt(scenes):
    lines, idx, offset = [], 1, 0.0
    for sc in scenes:
        sentences = [x for x in re.split(r"(?<=[.!?।])\s+", sc["text"].strip()) if x]
        total = sum(len(x) for x in sentences) or 1
        t = offset
        for sen in sentences:
            d = sc["dur"] * len(sen) / total
            lines += [str(idx), f"{_ts(t)} --> {_ts(t + d)}", sen, ""]
            idx += 1
            t += d
        offset += sc["dur"] + PAD
    return "\n".join(lines)

def build(scenes, outdir, music_dir="assets/music"):
    """scenes: list of dicts with image, audio (file names inside outdir), dur, text"""
    W, H = config.WIDTH, config.HEIGHT
    clips = []
    for i, sc in enumerate(scenes):
        frames = int((sc["dur"] + PAD) * FPS)
        clip = f"clip{i:02d}.mp4"
        vf = (f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,crop={W*2}:{H*2},"
              f"zoompan=z='min(zoom+0.0005,1.18)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":d={frames}:s={W}x{H}:fps={FPS},format=yuv420p,"
              f"fade=t=in:st=0:d=0.35,fade=t=out:st={sc['dur'] + PAD - 0.35:.2f}:d=0.35")
        _run(["ffmpeg", "-y", "-i", sc["image"], "-i", sc["audio"],
              "-vf", vf, "-af", f"apad=pad_dur={PAD}",
              "-t", f"{sc['dur'] + PAD:.2f}",
              "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-ar", "44100", "-ac", "2",
              clip], outdir)
        clips.append(clip)

    with open(os.path.join(outdir, "list.txt"), "w") as f:
        f.write("".join(f"file '{c}'\n" for c in clips))
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "joined.mp4"], outdir)

    with open(os.path.join(outdir, "captions.srt"), "w", encoding="utf-8") as f:
        f.write(_srt(scenes))
    size = 16 if config.FORMAT == "long" else 11
    style = f"FontName=Noto Sans Devanagari,Fontsize={size},Bold=1,Outline=2,Shadow=1,Alignment=2,MarginV=28"
    _run(["ffmpeg", "-y", "-i", "joined.mp4", "-vf", f"subtitles=captions.srt:force_style='{style}'",
          "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "copy",
          "captioned.mp4"], outdir)

    tracks = [os.path.join(music_dir, f) for f in sorted(os.listdir(music_dir))
              if f.lower().endswith((".mp3", ".wav", ".m4a"))] if os.path.isdir(music_dir) else []
    final = os.path.join(outdir, "final.mp4")
    if tracks:
        track = os.path.abspath(tracks[0])
        _run(["ffmpeg", "-y", "-i", "captioned.mp4", "-stream_loop", "-1", "-i", track,
              "-filter_complex", "[1:a]volume=0.07[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]",
              "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-shortest", "final.mp4"], outdir)
    else:
        shutil.copy(os.path.join(outdir, "captioned.mp4"), final)

    for c in clips:
        os.remove(os.path.join(outdir, c))
    return final
