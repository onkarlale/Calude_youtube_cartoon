"""Cloudflare Workers AI FLUX helper (shared by the asset generators)."""
import base64
import io
import os
import sys
import time

import requests
from PIL import Image

MODEL = "@cf/black-forest-labs/flux-1-schnell"


def generate(prompt, seed=None, retries=3):
    acc, tok = os.environ.get("CLOUDFLARE_ACCOUNT_ID"), os.environ.get("CLOUDFLARE_API_TOKEN")
    if not acc or not tok:
        sys.exit("Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN.")
    url = f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/{MODEL}"
    body = {"prompt": prompt, "steps": 8}
    if seed is not None:
        body["seed"] = seed
    for i in range(retries):
        r = requests.post(url, headers={"Authorization": f"Bearer {tok}"}, json=body, timeout=120)
        if r.status_code == 200:
            data = r.json()
            b64 = (data.get("result") or {}).get("image")
            if b64:
                return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
        print(f"  cloudflare HTTP {r.status_code}: {r.text[:200]}", flush=True)
        time.sleep(3 * (i + 1))
    return None


def crop_169(im, w, h, y_frac=0.28):
    """Crop a 16:9 band out of a (usually square) image. y_frac = where the band starts (0 top .. 1 bottom)."""
    band_h = int(im.width * 9 / 16)
    top = int((im.height - band_h) * y_frac)
    return im.crop((0, top, im.width, top + band_h)).resize((w, h), Image.LANCZOS)
