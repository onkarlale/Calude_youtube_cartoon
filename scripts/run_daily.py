#!/usr/bin/env python3
"""Orchestrates the whole daily pipeline with retry + fallback.

  python scripts/run_daily.py                  # normal daily run
  python scripts/run_daily.py --smoke          # sample script (no Groq), always uploads PRIVATE
  python scripts/run_daily.py --no-upload      # build the video only
  python scripts/run_daily.py --skip-lipsync   # force the fallback video (no Kaggle)
"""
import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import BUILD, ROOT, log  # noqa: E402

PY = sys.executable
S = ROOT / "scripts"


def step(*cmd):
    cmd = [str(c) for c in cmd]
    log(f"\n=== {' '.join(Path(c).name if c.endswith('.py') else c for c in cmd)} ===")
    return subprocess.run([PY, *cmd], cwd=ROOT).returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--skip-lipsync", action="store_true")
    ap.add_argument("--privacy", default=None)
    a = ap.parse_args()

    for f in ("final.mp4", "thumb.jpg", "script.json", "topic.json"):
        (BUILD / f).unlink(missing_ok=True)
    shutil.rmtree(BUILD / "render", ignore_errors=True)

    # 1. topic + script
    if a.smoke:
        if step(S / "write_script.py", "--sample"):
            sys.exit("sample script failed")
    else:
        if step(S / "topic.py") or step(S / "write_script.py"):
            sys.exit("topic/script stage failed (Groq down or rejected?). Nothing to publish today.")

    # 2. render: Kaggle lip-sync (retry once), else fallback voice+image video
    mode = "fallback"
    if not a.skip_lipsync:
        for attempt in (1, 2):
            if step(S / "kaggle_run.py") == 0:
                mode = "lipsync"
                break
            log(f"::warning::Kaggle render failed (attempt {attempt})")
            if attempt == 1:
                time.sleep(90)
    if mode == "fallback":
        log("::warning::Using the FALLBACK video (no lip-sync) today.")
        shutil.rmtree(BUILD / "render", ignore_errors=True)
        rc = step(S / "tts_lib.py", "--script", BUILD / "script.json", "--out", BUILD / "render",
                  "--config", ROOT / "config.json")
        if rc:
            sys.exit("Fallback TTS failed too. Failing the run so you get a GitHub email.")

    # 3. edit
    if step(S / "edit.py", "--mode", mode):
        sys.exit("edit stage failed")

    # 4. upload
    if a.no_upload:
        log("Skipping upload (--no-upload).")
        return
    privacy = "private" if a.smoke else a.privacy
    cmd = [S / "upload.py"] + (["--privacy", privacy] if privacy else [])
    if step(*cmd):
        sys.exit("upload failed")
    log(f"\nDONE (mode={mode})")


if __name__ == "__main__":
    main()
