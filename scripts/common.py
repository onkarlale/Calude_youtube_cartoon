"""Shared helpers for the pipeline scripts."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
BUILD.mkdir(exist_ok=True)


def log(msg):
    print(msg, flush=True)


def load_config():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def sh(cmd, cwd=None, check=True):
    """Run a command (list), return stdout. Raise with stderr tail on failure."""
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and p.returncode != 0:
        tail = (p.stderr or "")[-2500:]
        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(map(str, cmd))}\n{tail}")
    return p.stdout


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def is_shorts(cfg):
    return cfg.get("format", "shorts") == "shorts"


def canvas(cfg):
    """Final video size. Shorts are vertical 1080x1920."""
    if is_shorts(cfg):
        sh_cfg = cfg.get("shorts", {})
        return int(sh_cfg.get("width", 1080)), int(sh_cfg.get("height", 1920))
    return 1920, 1080


def base_size(cfg):
    """Size of the lip-sync base video (smaller than the final video, upscaled in the edit)."""
    return (720, 1280) if is_shorts(cfg) else (1280, 720)


def detect_face_center(img, default=(0.5, 0.42)):
    """(fx, fy) of the one clear face in a PIL image, as 0..1 fractions. Falls back to `default` if OpenCV is unusable."""
    try:
        import cv2
        import numpy as np
        gray = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2GRAY)
        det = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = det.detectMultiScale(gray, 1.1, 5, minSize=(max(40, img.width // 20), max(40, img.width // 20)))
        if len(faces) >= 1:
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            return (x + w / 2) / img.width, (y + h / 2) / img.height
    except Exception:  # noqa: BLE001
        pass
    return default


def cover_crop(img, w, h, fx=0.5, fy=0.42):
    """Crop a PIL image to the w:h aspect around the point (fx, fy), then resize to exactly w x h."""
    from PIL import Image
    ar = w / h
    if img.width / img.height > ar:      # too wide: crop the sides
        cw, ch = int(round(img.height * ar)), img.height
    else:                                 # too tall: crop top/bottom
        cw, ch = img.width, int(round(img.width / ar))
    x0 = int(min(max(fx * img.width - cw / 2, 0), img.width - cw))
    y0 = int(min(max(fy * img.height - ch / 2, 0), img.height - ch))
    return img.crop((x0, y0, x0 + cw, y0 + ch)).resize((w, h), Image.LANCZOS)
