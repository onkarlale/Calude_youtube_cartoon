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
from common import BUILD, ROOT, fail, load_config, log  # noqa: E402


def kaggle(*args):
    p = subprocess.run(["kaggle", *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return p.returncode, p.stdout.strip()


def _face_jpeg():
    """The comedian face as a compact JPEG (keeps the kernel source small)."""
    import io
    from PIL import Image
    im = Image.open(ROOT / "assets/comedian.png").convert("RGB").resize((1280, 720))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def main():
    cfg = load_config()
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
        "face_b64": base64.b64encode(_face_jpeg()).decode(),
    }
    b64 = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode()
    code = (ROOT / "kernel/render.py").read_text(encoding="utf-8").replace("__PAYLOAD_B64__", b64)
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
