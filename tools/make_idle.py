#!/usr/bin/env python3
"""Make a seamless 14 s idle loop (gentle breathing/handheld sway) from assets/comedian.png.

Output: out/base_idle.mp4  -> upload it to your private Kaggle dataset "comedy-assets".
The mouth stays closed because it is just a still image with a tiny camera sway. MuseTalk animates the mouth.
"""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
src = root / "assets/comedian.png"
if not src.exists():
    sys.exit("assets/comedian.png not found. Commit your chosen face first.")
out = Path("out")
out.mkdir(exist_ok=True)
vf = ("scale=1408:792:flags=lanczos,"
      "crop=1280:720:x='64+14*sin(2*PI*t/7)':y='36+8*sin(2*PI*t/3.5)',"
      "format=yuv420p")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "25", "-i", str(src),
                "-vf", vf, "-t", "14", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", str(out / "base_idle.mp4")],
               check=True)
print("Wrote out/base_idle.mp4")
