import os, shutil
import config
from effects import PAD, MOTIONS, SFX, motion, make_sfx, run, srt

FPS = 25

def build(scenes, outdir, music_dir="assets/music"):
    """scenes: list of dicts with image, audio (file names inside outdir), dur, text, motion, sfx"""
    W, H = config.WIDTH, config.HEIGHT
    clips = []
    for i, sc in enumerate(scenes):
        total = sc["dur"] + PAD
        frames = max(int(total * FPS), 2)
        z, x, y = motion(sc.get("motion", "zoom_in"), frames)
        vf = (f"[0:v]scale={W*2}:{H*2}:force_original_aspect_ratio=increase,crop={W*2}:{H*2},"
              f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={FPS},format=yuv420p[v]")
        cmd = ["ffmpeg", "-y", "-i", sc["image"], "-i", sc["audio"]]
        sfx = sc.get("sfx", "none")
        if sfx in SFX:
            cmd += ["-i", make_sfx(sfx, outdir)]
            af = (f"[1:a]apad=pad_dur={PAD}[a0];[2:a]volume=0.6[s];"
                  f"[a0][s]amix=inputs=2:duration=first:normalize=0[a]")
        else:
            af = f"[1:a]apad=pad_dur={PAD}[a]"
        clip = f"clip{i:02d}.mp4"
        cmd += ["-filter_complex", f"{vf};{af}", "-map", "[v]", "-map", "[a]",
                "-t", f"{total:.2f}", "-c:v", "libx264", "-preset", "veryfast",
                "-c:a", "aac", "-ar", "44100", "-ac", "2", clip]
        run(cmd, outdir)
        clips.append(clip)

    with open(os.path.join(outdir, "list.txt"), "w") as f:
        f.write("".join(f"file '{c}'\n" for c in clips))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "joined.mp4"], outdir)

    with open(os.path.join(outdir, "captions.srt"), "w", encoding="utf-8") as f:
        f.write(srt(scenes))
    size, margin = (14, 70) if config.IS_SHORT else (18, 30)
    style = (f"FontName=Noto Sans Devanagari,Fontsize={size},Bold=1,PrimaryColour=&H0000E6FF,"
             f"OutlineColour=&H00000000,Outline=3,Shadow=1,Alignment=2,MarginV={margin}")
    run(["ffmpeg", "-y", "-i", "joined.mp4", "-vf", f"subtitles=captions.srt:force_style='{style}'",
         "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "copy",
         "captioned.mp4"], outdir)

    tracks = [os.path.join(music_dir, f) for f in sorted(os.listdir(music_dir))
              if f.lower().endswith((".mp3", ".wav", ".m4a"))] if os.path.isdir(music_dir) else []
    final = os.path.join(outdir, "final.mp4")
    if tracks:
        track = os.path.abspath(tracks[0])
        run(["ffmpeg", "-y", "-i", "captioned.mp4", "-stream_loop", "-1", "-i", track,
             "-filter_complex", "[1:a]volume=0.07[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]",
             "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-shortest", "final.mp4"], outdir)
    else:
        shutil.copy(os.path.join(outdir, "captioned.mp4"), final)

    for c in clips:
        os.remove(os.path.join(outdir, c))
    return final
