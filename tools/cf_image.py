"""Cloudflare Workers AI FLUX helper (shared by the asset generators)."""
import base64
import io
import os
import sys
import time

import requests
from PIL import Image

MODEL = "@cf/black-forest-labs/flux-1-schnell"


_SIZE_OK = [True]    # flips to False the first time the API refuses width/height


def generate(prompt, seed=None, retries=3, size=None):
    """size=(w, h) asks for a tall picture. If the model refuses it (HTTP 400) we silently go back to the default square."""
    acc, tok = os.environ.get("CLOUDFLARE_ACCOUNT_ID"), os.environ.get("CLOUDFLARE_API_TOKEN")
    if not acc or not tok:
        sys.exit("Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN.")
    url = f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/{MODEL}"
    # flux-1-schnell on Workers AI rejects extra fields such as "seed" (HTTP 400), so only send prompt + steps.
    # Variety comes from the model's own randomness plus small prompt variations in the callers.
    body = {"prompt": prompt, "steps": 8}
    if size and _SIZE_OK[0]:
        body.update({"width": int(size[0]), "height": int(size[1])})
    for i in range(retries):
        r = requests.post(url, headers={"Authorization": f"Bearer {tok}"}, json=body, timeout=120)
        if r.status_code == 400 and "width" in body:
            print("  cloudflare model does not accept width/height; using its default square picture", flush=True)
            _SIZE_OK[0] = False
            body.pop("width", None)
            body.pop("height", None)
            continue
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


def crop_916(im, w, h, x_frac=0.5):
    """Tall 9:16 picture of size w x h. A square/landscape source is cropped (sides only, full height kept)."""
    target = w / h
    if im.width / im.height > target:
        cw = int(round(im.height * target))
        left = int((im.width - cw) * x_frac)
        im = im.crop((left, 0, left + cw, im.height))
    else:
        ch = int(round(im.width / target))
        im = im.crop((0, 0, im.width, ch))
    return im.resize((w, h), Image.LANCZOS)
