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


def layout(cfg):
    """'scene' (full-body vertical picture, audience is part of the picture) | 'landscape' | 'stage' | 'closeup'."""
    return cfg.get("shorts", {}).get("layout", "stage") if is_shorts(cfg) else "landscape"


def base_size(cfg):
    """Size of the lip-sync base video (upscaled/re-framed later in the edit)."""
    lay = layout(cfg)
    if lay == "scene":          # full-body vertical picture: a little larger so the (small) face keeps detail
        return (864, 1536)
    return (720, 1280) if lay == "closeup" else (1280, 720)


def cascade_path():
    """Path of OpenCV's frontal-face cascade, or None. (cv2.data is missing in some builds.)"""
    try:
        import os
        import cv2
        name = "haarcascade_frontalface_default.xml"
        try:
            return cv2.data.haarcascades + name
        except AttributeError:
            for base in (os.path.join(os.path.dirname(cv2.__file__), "data"),
                         "/usr/share/opencv4/haarcascades", "/usr/share/opencv/haarcascades"):
                if os.path.exists(os.path.join(base, name)):
                    return os.path.join(base, name)
    except Exception:  # noqa: BLE001
        pass
    return None


def detect_face_center(img, default=(0.5, 0.42)):
    """(fx, fy) of the one clear face in a PIL image, as 0..1 fractions. Falls back to `default` if OpenCV is unusable."""
    try:
        import cv2
        import numpy as np
        gray = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2GRAY)
        cp = cascade_path()
        if not cp:
            return default
        det = cv2.CascadeClassifier(cp)
        m = max(24, img.width // 40)
        faces = det.detectMultiScale(gray, 1.1, 5, minSize=(m, m))
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


def fit_916(im, w, h):
    """Make any picture a full 9:16 frame WITHOUT cutting the person off.
    Tall pictures are simply cropped to 9:16. Wide/square ones are shown whole on a blurred, darkened copy of
    themselves, so the legs and the sides are never lost."""
    from PIL import Image, ImageEnhance, ImageFilter
    im = im.convert("RGB")
    if im.height / im.width >= 1.6:
        return cover_crop(im, w, h, 0.5, 0.5)
    bg = cover_crop(im, w, h, 0.5, 0.5).filter(ImageFilter.GaussianBlur(28))
    bg = ImageEnhance.Brightness(bg).enhance(0.45)
    sc = w / im.width
    fg = im.resize((w, max(2, int(im.height * sc))), Image.LANCZOS)
    if fg.height > h:
        fg = fg.resize((int(fg.width * h / fg.height), h), Image.LANCZOS)
    bg.paste(fg, ((w - fg.width) // 2, (h - fg.height) // 2))
    return bg


# ---------------------------------------------------------------- comedian pictures (assets/bodies)
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")


def episode_number():
    """How many episodes were already published (= number of entries in used_topics.json)."""
    try:
        return len(json.loads((ROOT / "used_topics.json").read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        return 0


def comedian_pool(prefix="comedian_"):
    """All comedian pictures. If assets/bodies/ holds files starting with `prefix` (comedian_01.png ...), ONLY those are
    used (the generic body_XX.png pictures are ignored). Any number of pictures works: 12, 20, 50 ..."""
    allp = sorted(p for p in (ROOT / "assets/bodies").glob("*") if p.suffix.lower() in IMG_EXT)
    chosen = [p for p in allp if p.name.lower().startswith(prefix.lower())]
    return chosen or allp


def _bag_order(cycle, size, seed):
    """Order of the pictures in round number `cycle`. Every picture is used once per round, in a different random order
    each round, and a new round never starts with the picture that ended the previous one."""
    import random
    order, prev_last = [], None
    for c in range(cycle + 1):
        order = list(range(size))
        random.Random(seed * 1000 + c).shuffle(order)
        if prev_last is not None and size > 1 and order[0] == prev_last:
            order[0], order[1] = order[1], order[0]
        prev_last = order[-1]
    return order


def shuffle_index(n, size, seed=20261029):
    """Which picture for episode n. 'Shuffle bag': a different comedian every episode, no repeats until all `size`
    pictures were used, then a fresh random order. Stateless (nothing to commit) and the SAME answer when the same
    episode is retried."""
    if size <= 1:
        return 0
    return _bag_order(n // size, size, seed)[n % size]
