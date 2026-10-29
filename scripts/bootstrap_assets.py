#!/usr/bin/env python3
"""One-time, automatic asset creation. Runs at the start of every daily run but does nothing
if the assets already exist (the workflow commits them back to the repo, so Raj looks the same forever).

  assets/comedian.png      the comedian's face (picked automatically with OpenCV face detection)
  assets/cutaways/*.png    audience / stage images shown after punchlines

Env: CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN. Set FORCE_FACE=1 to make a new face.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import cf_image  # noqa: E402
import generate_cutaways as gc  # noqa: E402
import generate_face as gf  # noqa: E402

FACE = ROOT / "assets" / "comedian.png"
CUT = ROOT / "assets" / "cutaways"
MIN_CUTAWAYS = 8


def detector():
    """Return (cv2, face_detector) or (None, None) if OpenCV is unusable (then we pick without checking)."""
    try:
        import cv2
        print(f"[bootstrap] cv2 from {getattr(cv2, '__file__', '?')} version {getattr(cv2, '__version__', '?')}", flush=True)
        path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        det = cv2.CascadeClassifier(path)
        if det.empty():
            raise RuntimeError("cascade file empty")
        return cv2, det
    except Exception as e:  # noqa: BLE001
        print(f"[bootstrap] WARNING: OpenCV face check unavailable ({e}). Picking images without face check.", flush=True)
        return None, None


def face_score(im, cv2, det):
    """Higher is better. -1 = unusable (no face / several faces / tiny or huge / off-centre)."""
    import numpy as np
    g = cv2.cvtColor(np.array(im.convert("RGB")), cv2.COLOR_RGB2GRAY)
    faces = det.detectMultiScale(g, 1.1, 6, minSize=(60, 60))
    if len(faces) != 1:
        return -1
    x, y, w, h = faces[0]
    W, H = im.size
    rel_w, cx, cy = w / W, (x + w / 2) / W, (y + h / 2) / H
    if not (0.10 <= rel_w <= 0.32) or abs(cx - 0.5) > 0.18 or cy > 0.55:
        return -1
    return rel_w - abs(cx - 0.5)   # bigger and more central is better


def make_face(tries=24):
    cv2, det = detector()
    best, best_s = None, -1
    if cv2 is None:
        tries = 6
    for i in range(tries):
        print(f"[bootstrap] face candidate {i + 1}/{tries}", flush=True)
        im = cf_image.generate(gf.PROMPT)
        if im is None:
            continue
        im = cf_image.crop_169(im, 1280, 720, y_frac=0.12)
        if cv2 is None:
            best, best_s = im, 0
            break
        s = face_score(im, cv2, det)
        print(f"[bootstrap]   score {s:.3f}", flush=True)
        if s > best_s:
            best, best_s = im, s
        if best_s >= 0.17:      # good enough, stop early to save quota
            break
    if best is None or best_s < 0:
        sys.exit("Could not get a usable face from Cloudflare (check CLOUDFLARE_* secrets / quota).")
    FACE.parent.mkdir(parents=True, exist_ok=True)
    best.save(FACE)
    print(f"[bootstrap] saved {FACE} (score {best_s:.3f})", flush=True)


def make_cutaways(target=10):
    cv2, det = detector()
    import numpy as np
    CUT.mkdir(parents=True, exist_ok=True)
    have = len([p for p in CUT.glob("*.png")])
    attempts = 0
    while have < target and attempts < target * 3:
        scene = gc.SCENES[attempts % len(gc.SCENES)]
        attempts += 1
        im = cf_image.generate(f"{scene}, {gc.BASE}")
        if im is None:
            continue
        im = cf_image.crop_169(im, 1920, 1080, y_frac=0.5)
        big = []
        if cv2 is not None:
            g = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2GRAY)
            big = [f for f in det.detectMultiScale(g, 1.1, 6, minSize=(60, 60)) if f[2] > 0.06 * 1920]
        if big:
            print("[bootstrap] cutaway rejected (large visible face)", flush=True)
            continue
        im.save(CUT / f"cut_{have:02d}.png")
        have += 1
        print(f"[bootstrap] cutaway {have}/{target}", flush=True)
    if have < 3:
        print("[bootstrap] WARNING: fewer than 3 cutaways; video will use fewer cutaways.", flush=True)


LOOKS = [
    ("a navy blue casual blazer over a white t-shirt", "dark blue curtain backdrop with a warm spotlight"),
    ("a maroon hoodie", "red brick wall with warm string lights"),
    ("a grey checked shirt over a black t-shirt", "dark stage with a soft neon sign glow"),
    ("a black polo t-shirt", "warm wooden panelled wall of a comedy club"),
    ("an olive green overshirt over a white t-shirt", "teal wall with a bright stage spotlight"),
    ("a denim jacket over a plain t-shirt", "brick wall with a vintage microphone stand beside him"),
    ("a mustard yellow shirt", "dark purple curtain with a spotlight"),
]


def make_face_pool(target):
    """Extra faces (different outfits/backgrounds) so each episode can use a different base picture."""
    import json
    faces_dir = ROOT / "assets" / "faces"
    faces_dir.mkdir(parents=True, exist_ok=True)
    have = len(list(faces_dir.glob("*.png"))) + (1 if FACE.exists() else 0)
    need = target - have
    if need <= 0:
        print(f"[bootstrap] face pool ok ({have} faces)", flush=True)
        return
    cv2, det = detector()
    made, attempts = 0, 0
    idx = len(list(faces_dir.glob("*.png")))
    while made < need and attempts < need * 4:
        outfit, backdrop = LOOKS[(idx + attempts) % len(LOOKS)]
        attempts += 1
        prompt = gf.PROMPT.replace("checked flannel shirt over a plain t-shirt", outfit).replace(
            "red brick wall behind him", backdrop + " behind him")
        im = cf_image.generate(prompt)
        if im is None:
            continue
        im = cf_image.crop_169(im, 1280, 720, y_frac=0.12)
        if cv2 is not None and face_score(im, cv2, det) < 0:
            print("[bootstrap] face rejected (no clear single frontal face)", flush=True)
            continue
        im.save(faces_dir / f"face_{idx + made + 1:02d}.png")
        made += 1
        print(f"[bootstrap] extra face {made}/{need}", flush=True)


def main():
    if os.environ.get("FORCE_FACE") == "1" and FACE.exists():
        FACE.unlink()
    if not FACE.exists():
        make_face()
    else:
        print("[bootstrap] face exists, skipping", flush=True)
    try:
        import json
        vis = json.loads((ROOT / "config.json").read_text(encoding="utf-8")).get("visuals", {})
    except Exception:  # noqa: BLE001
        vis = {}
    if vis.get("base_mode", "rotate") == "rotate" and not list((ROOT / "assets" / "base_videos").glob("*.mp4")):
        make_face_pool(int(vis.get("face_pool", 6)))
    n = len(list(CUT.glob("*.png"))) if CUT.exists() else 0
    if n < MIN_CUTAWAYS:
        make_cutaways()
    else:
        print(f"[bootstrap] {n} cutaways exist, skipping", flush=True)


if __name__ == "__main__":
    main()
