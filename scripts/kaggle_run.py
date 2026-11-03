#!/usr/bin/env python3
"""Push the GPU render kernel to Kaggle, wait for it, download the result into build/render/.

Needs env KAGGLE_USERNAME and KAGGLE_KEY (GitHub secrets). Exit code != 0 means: use the fallback.
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import uuid

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import (BUILD, ROOT, base_size, comedian_pool, cover_crop, detect_face_center, episode_number, fail,  # noqa: E402
                    is_shorts, load_config, log, sh, shuffle_index)


EXPECTED_RENDER_VERSION = 9


def kaggle(*args):
    p = subprocess.run(["kaggle", *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return p.returncode, p.stdout.strip()


IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
VID_EXT = (".mp4", ".mov", ".webm", ".mkv", ".m4v")


def _image_jpeg(path, size, cfg):
    """A face picture cropped around the face to the base-video shape (vertical for Shorts), as a compact JPEG."""
    import io
    from PIL import Image
    vis = cfg.get("visuals", {})
    im = Image.open(path).convert("RGB")
    if cfg.get("shorts", {}).get("layout") == "scene":     # full-body picture: keep all of it (legs included)
        from common import fit_916
        out = fit_916(im, size[0], size[1])
    else:
        fx, fy = detect_face_center(im, (float(vis.get("face_x", 0.5)), float(vis.get("face_y", 0.42))))
        out = cover_crop(im, size[0], size[1], fx, fy)
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def _prep_video(path, size):
    """Shrink a base video (<= ~1.5 MB, <= 12 s, no audio) so it can travel inside the kernel script."""
    out = BUILD / "base_small.mp4"
    small = (int(size[0] * 0.75) // 2 * 2, int(size[1] * 0.75) // 2 * 2)
    for crf, dur, (w, h) in ((27, 12, size), (31, 10, size), (35, 8, size), (33, 8, small)):
        rc = sh(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-t", str(dur), "-an", "-vf",
                 f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps=25",
                 "-c:v", "libx264", "-crf", str(crf), "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out)], check=False)
        if out.exists() and out.stat().st_size <= 1_500_000:
            return out.read_bytes()
    return None


def pick_index(n, size, how):
    """Which pool item for episode n. 'random' never repeats the previous episode's pick and gives the SAME
    answer on a retry of the same episode (stateless, seeded)."""
    if size <= 1:
        return 0
    if how == "sequential":
        return n % size
    if how == "shuffle":      # every comedian once, in random order, then a new random order (never the same one twice in a row)
        return shuffle_index(n, size)
    import random
    rnd, prev = random.Random(20261029), -1
    for _ in range(n + 1):
        prev = rnd.choice([i for i in range(size) if i != prev])
    return prev


def _has_face(jpeg_bytes):
    """Best effort: False only if OpenCV works AND finds no face (MuseTalk cannot lip-sync a picture without one)."""
    try:
        import cv2
        import numpy as np
        img = cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
        from common import cascade_path
        cp = cascade_path()
        if not cp:
            return True
        det = cv2.CascadeClassifier(cp)
        if det.empty():
            return True
        return len(det.detectMultiScale(img, 1.1, 5, minSize=(60, 60))) > 0
    except Exception:  # noqa: BLE001
        return True


def base_pool(cfg=None):
    """Every picture in assets/ and assets/faces/ plus every clip in assets/base_videos/.
    Layout "scene": only the tall full-body pictures in assets/bodies/ (body_01.png first)."""
    if cfg is not None and cfg.get("shorts", {}).get("layout") == "scene":
        bodies = comedian_pool()          # comedian_*.png if present (any number of them), else every picture in the folder
        if not bodies:
            fail("Layout is 'scene' but assets/bodies/ has no pictures. The bootstrap step creates them automatically (check the 'Create face + audience images' step and your CLOUDFLARE_* secrets), "
                 "or put your own 9:16 full-body pictures in assets/bodies/.")
        return [("image", p) for p in bodies]
    imgs = sorted(p for p in (ROOT / "assets").glob("*") if p.suffix.lower() in IMG_EXT)
    imgs += sorted(p for p in (ROOT / "assets/faces").glob("*") if p.suffix.lower() in IMG_EXT)
    vids = sorted(p for p in (ROOT / "assets/base_videos").glob("*") if p.suffix.lower() in VID_EXT)
    return [("video", p) for p in vids] + [("image", p) for p in imgs]


def pick_base(cfg):
    """Choose today's base picture/video from the pool (random by default)."""
    vis = cfg.get("visuals", {})
    main = ROOT / "assets/comedian.png"
    pool = base_pool(cfg)
    today = ROOT / "build/today_body.png"
    if cfg.get("shorts", {}).get("layout") == "scene" and vis.get("comedian_mode", "new_daily") == "new_daily" and today.exists():
        pool = [("image", today)]          # a brand-new comedian for this video
    elif vis.get("base_mode", "rotate") == "single":
        if cfg.get("shorts", {}).get("layout") == "scene":
            pool = pool[:1]
        elif main.exists():
            pool = [("image", main)]
    if not pool:
        fail("No comedian picture found. Put at least one image in assets/ (for example assets/comedian.png).")
    n = episode_number()
    start = pick_index(n, len(pool), vis.get("base_pick", "random"))
    for off in range(len(pool)):
        idx = (start + off) % len(pool)
        kind, p = pool[idx]
        if kind == "video":
            data = _prep_video(p, base_size(cfg))
            if data is None:
                log(f"[kaggle] video {p.name} could not be shrunk under 1.5 MB (use a shorter, steadier clip of about 8 s); trying another")
                continue
            log(f"[kaggle] today's base: VIDEO {p.name} ({len(data) // 1024} KB) [{idx + 1}/{len(pool)}]")
            return "video", data, p.name
        try:
            data = _image_jpeg(p, base_size(cfg), cfg)
        except Exception as e:  # noqa: BLE001
            log(f"[kaggle] could not read {p.name} ({e}); trying another")
            continue
        if cfg.get("shorts", {}).get("layout") != "scene" and not _has_face(data):
            log(f"[kaggle] no clear face found in {p.name}; trying another picture")
            continue
        log(f"[kaggle] today's comedian: {p.relative_to(ROOT)} [{idx + 1}/{len(pool)}]")
        return "image", data, p.name
    fail("No usable base picture or video (every file was unreadable or had no clear face).")


def dump_kernel_log(ref, lines=70):
    """On failure, download the kernel's own log and print its tail so the cause shows in GitHub."""
    d = BUILD / "kernel_log"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    rc, out = kaggle("kernels", "output", ref, "-p", str(d))
    logs = list(d.glob("*.log"))
    log(f"[kaggle] ---- kernel log tail ({'found' if logs else 'no log file; ' + out[-200:]}) ----")
    for f in logs:
        raw = f.read_text(encoding="utf-8", errors="replace")
        try:
            items = json.loads(raw)
            text = "".join(i.get("data", "") for i in items)
        except Exception:  # noqa: BLE001
            text = raw
        for ln in text.splitlines()[-lines:]:
            log("  | " + ln[:300])
    log("[kaggle] ---- end kernel log ----")


def setup_auth():
    """Accept both Kaggle credential styles, whichever secret name the token was saved under."""
    key = (os.environ.get("KAGGLE_KEY") or "").strip()
    tok = (os.environ.get("KAGGLE_API_TOKEN") or "").strip()
    if not tok and key.startswith("KGAT_"):      # new-style token pasted into KAGGLE_KEY
        tok = key
        os.environ.pop("KAGGLE_KEY", None)
    if tok:
        os.environ["KAGGLE_API_TOKEN"] = tok
        d = os.path.expanduser("~/.kaggle")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "access_token"), "w", encoding="utf-8") as f:
            f.write(tok)
        os.chmod(os.path.join(d, "access_token"), 0o600)
        log("[kaggle] using new-style API token")
    elif key:
        log("[kaggle] using legacy KAGGLE_USERNAME + KAGGLE_KEY")
    return bool(tok or key)


def main():
    cfg = load_config()
    setup_auth()
    user = os.environ.get("KAGGLE_USERNAME")
    if not user or not (os.environ.get("KAGGLE_KEY") or os.environ.get("KAGGLE_API_TOKEN")):
        fail("Kaggle secrets missing: need KAGGLE_USERNAME and KAGGLE_KEY (or KAGGLE_API_TOKEN).")
    k = cfg["kaggle"]
    ref = f"{user}/{k['kernel_slug']}"
    script = json.loads((BUILD / "script.json").read_text(encoding="utf-8"))
    run_id = uuid.uuid4().hex

    # ---- build kernel folder
    kdir = BUILD / "kernel"
    shutil.rmtree(kdir, ignore_errors=True)
    kdir.mkdir(parents=True)
    base_kind, base_bytes, base_name = pick_base(cfg)
    voice_cfg = {k_: v_ for k_, v_ in cfg["voice"].items() if k_ != "by_image"}
    override = (cfg["voice"].get("by_image") or {}).get(base_name)
    if override:                      # e.g. a woman on stage must not talk with a man's voice
        voice_cfg["name"] = override
        log(f"[kaggle] voice for {base_name}: {override}")
    payload = {
        "script": script,
        "config": {"voice": voice_cfg, "timing": cfg["timing"], "video_size": list(base_size(cfg)),
                   "max_total": cfg.get("shorts", {}).get("max_seconds") if is_shorts(cfg) else None},
        "tts_lib": (ROOT / "scripts/tts_lib.py").read_text(encoding="utf-8"),
        "run_id": run_id,
    }
    payload["base_kind"] = base_kind
    (BUILD / "base_name.txt").write_text(base_name, encoding="utf-8")
    b64 = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode()
    template = (ROOT / "kernel/render.py").read_text(encoding="utf-8")
    if f"RENDER_VERSION = {EXPECTED_RENDER_VERSION}" not in template:
        fail(f"kernel/render.py in your repo is OUTDATED or the wrong file (expected RENDER_VERSION = {EXPECTED_RENDER_VERSION}). "
             "Upload kernel/render.py from the latest update zip, then run again.")
    if "__PAYLOAD_B64__" not in template or "MuseTalk" not in template:
        fail("kernel/render.py is the wrong file (it must be the Kaggle GPU script containing __PAYLOAD_B64__). "
             "Re-upload kernel/render.py from the v2 zip.")
    code = template.replace("__PAYLOAD_B64__", b64).replace("__BASE_B64__", base64.b64encode(base_bytes).decode())
    (kdir / "render.py").write_text(code, encoding="utf-8")

    meta = json.loads((ROOT / "kernel/kernel-metadata.template.json").read_text(encoding="utf-8"))
    meta["id"] = ref
    meta["title"] = k["kernel_slug"]
    meta["dataset_sources"] = []
    if k.get("weights_dataset"):
        meta["dataset_sources"].append(f"{user}/{k['weights_dataset']}")
    (kdir / "kernel-metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # ---- push
    log(f"[kaggle] pushing {ref} (run {run_id[:8]})")
    rc, out = kaggle("kernels", "push", "-p", str(kdir))
    log(out)
    if rc != 0 or "error" in out.lower() and "successfully" not in out.lower():
        fail("kaggle kernels push failed (quota, dataset name, or credentials?)")

    # ---- poll
    deadline = time.time() + k["timeout_minutes"] * 60
    started, seen_active, last = time.time(), False, ""
    while time.time() < deadline:
        time.sleep(30)
        rc, out = kaggle("kernels", "status", ref)
        low = out.lower()
        if out != last:
            log(f"[kaggle] {out}")
            last = out
        if "running" in low or "queued" in low:
            seen_active = True
        terminal = any(w in low for w in ("complete", "error", "cancel"))
        if terminal and (seen_active or time.time() - started > 240):
            if "complete" not in low:
                dump_kernel_log(ref)
                fail(f"Kaggle kernel ended with: {out}")
            break
    else:
        fail("Timed out waiting for the Kaggle kernel.")

    # ---- download and verify it is THIS run's output
    out_dir = BUILD / "render"
    for attempt in range(4):
        shutil.rmtree(out_dir, ignore_errors=True)
        out_dir.mkdir(parents=True)
        rc, out = kaggle("kernels", "output", ref, "-p", str(out_dir))
        rid = out_dir / "run_id.txt"
        if rid.exists() and rid.read_text().strip() == run_id and (out_dir / "talking.mp4").exists():
            log("[kaggle] output downloaded and verified")
            return
        log(f"[kaggle] output not ready/stale (attempt {attempt + 1}); retrying in 60s\n{out[-300:]}")
        time.sleep(60)
    fail("Could not download a valid output from Kaggle.")


if __name__ == "__main__":
    main()
