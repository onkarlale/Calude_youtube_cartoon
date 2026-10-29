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
from common import BUILD, ROOT, fail, load_config, log, sh  # noqa: E402


EXPECTED_RENDER_VERSION = 7


def kaggle(*args):
    p = subprocess.run(["kaggle", *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return p.returncode, p.stdout.strip()


IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
VID_EXT = (".mp4", ".mov", ".webm", ".mkv", ".m4v")


def _image_jpeg(path):
    """A face image as a compact 1280x720 JPEG (keeps the kernel source small)."""
    import io
    from PIL import Image
    im = Image.open(path).convert("RGB")
    scale = max(1280 / im.width, 720 / im.height)
    im = im.resize((max(1280, int(im.width * scale)), max(720, int(im.height * scale))), Image.LANCZOS)
    left, top = (im.width - 1280) // 2, (im.height - 720) // 2
    im = im.crop((left, top, left + 1280, top + 720))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def _prep_video(path):
    """Shrink a base video (<= ~1.5 MB, <= 12 s, no audio) so it can travel inside the kernel script."""
    out = BUILD / "base_small.mp4"
    for crf, dur, w, h in ((27, 12, 1280, 720), (31, 10, 1280, 720), (35, 8, 1280, 720), (33, 8, 960, 540)):
        rc = sh(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-t", str(dur), "-an", "-vf",
                 f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps=25",
                 "-c:v", "libx264", "-crf", str(crf), "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out)], check=False)
        if out.exists() and out.stat().st_size <= 1_500_000:
            return out.read_bytes()
    return None


def episode_number():
    try:
        return len(json.loads((ROOT / "used_topics.json").read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        return 0


def pick_base(cfg):
    """Choose today's base: rotates through assets/base_videos/*, assets/faces/* and assets/comedian.png."""
    vis = cfg.get("visuals", {})
    main = ROOT / "assets/comedian.png"
    faces = ([main] if main.exists() else []) + sorted(
        p for p in (ROOT / "assets/faces").glob("*") if p.suffix.lower() in IMG_EXT)
    vids = sorted(p for p in (ROOT / "assets/base_videos").glob("*") if p.suffix.lower() in VID_EXT)
    if vis.get("base_mode", "rotate") == "single" or (not vids and len(faces) <= 1):
        pool = [("image", main)] if main.exists() else [("image", faces[0])] if faces else []
    else:
        pool = [("video", p) for p in vids] + [("image", p) for p in faces]
    if not pool:
        fail("No comedian image found: assets/comedian.png is missing.")
    n = episode_number()
    for off in range(len(pool)):
        kind, p = pool[(n + off) % len(pool)]
        if kind == "video":
            data = _prep_video(p)
            if data is None:
                log(f"[kaggle] video {p.name} could not be shrunk under 1.5 MB (use a shorter, steadier clip of about 8 s); trying the next base")
                continue
            log(f"[kaggle] today's base: VIDEO {p.name} ({len(data) // 1024} KB) [{(n + off) % len(pool) + 1}/{len(pool)}]")
            return "video", data
        log(f"[kaggle] today's base: IMAGE {p.name} [{(n + off) % len(pool) + 1}/{len(pool)}]")
        return "image", _image_jpeg(p)
    fail("No usable base image or video.")


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
    payload = {
        "script": script,
        "config": {"voice": cfg["voice"], "timing": cfg["timing"]},
        "tts_lib": (ROOT / "scripts/tts_lib.py").read_text(encoding="utf-8"),
        "run_id": run_id,
    }
    base_kind, base_bytes = pick_base(cfg)
    payload["base_kind"] = base_kind
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
